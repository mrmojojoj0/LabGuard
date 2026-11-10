from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import platform
import random
import re
import socket
import ssl
import threading
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import urlsplit
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from websockets.asyncio.client import ClientConnection, connect

from labguard_client.identity import DeviceIdentity
from labguard_client.instance import IdentityProcessLock
from labguard_client.telemetry import active_windows_username, collect_system_telemetry
from labguard_client.software_inventory import batch_entries, collect_software_inventory, inventory_digest
from labguard_client.software_management import (PackageManagerUnavailable, SoftwareJobOffer,
                                                 UnsupportedExecutionContext, execute_package_job)
from labguard_client.rdp_access import cleanup_expired_rdp_access, prepare_rdp_access
from labguard_client.process_control import MAX_PROCESSES, list_processes, terminate_process
from labguard_client.peripherals import collect_peripherals
from labguard_client.screenshot_capture import capture_screenshot
from labguard_client.network_events import WfpEventReader


class AgentClient:
    def __init__(self, server_url: str, identity: DeviceIdentity, *, agent_version: str = "0.1.0",
                 heartbeat_interval: float = 10.0, telemetry_interval_seconds: float = 30.0,
                 software_inventory_interval_seconds: float = 6 * 60 * 60,
                 timeout: float = 15.0, allow_insecure_dev: bool = False):
        parsed_server_url = urlsplit(server_url)
        if (parsed_server_url.scheme not in {"http", "https"} or not parsed_server_url.hostname
                or parsed_server_url.username or parsed_server_url.password
                or parsed_server_url.query or parsed_server_url.fragment):
            raise ValueError("Server URL must be a valid HTTP or HTTPS URL without credentials, query, or fragment")
        self.server_url = server_url.rstrip("/")
        self.identity = identity
        self.agent_version = agent_version
        self.heartbeat_interval = heartbeat_interval
        if not 10 <= telemetry_interval_seconds <= 3600:
            raise ValueError("Telemetry interval must be between 10 and 3600 seconds")
        self.telemetry_interval_seconds = telemetry_interval_seconds
        if not 300 <= software_inventory_interval_seconds <= 604800:
            raise ValueError("Software inventory interval must be between 300 and 604800 seconds")
        self.software_inventory_interval_seconds = software_inventory_interval_seconds
        self.timeout = timeout
        self.boot_id = str(uuid4())
        self.ssl_context = ssl.create_default_context()
        identity_state = getattr(identity, "state_file", None)
        self.wfp_reader = WfpEventReader(identity_state.parent / "wfp-event-cursor.json") if identity_state else None

    def _post(self, path: str, data: dict) -> dict:
        url = self.server_url + path
        request = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"}, method="POST")
        context = self.ssl_context if url.startswith("https://") else None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
                return json.loads(response.read(64 * 1024))
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", "replace")
            raise RuntimeError(f"Server rejected request ({exc.code}): {body}") from exc

    def enroll(self, enrollment_code: str, *, hostname: str | None = None) -> dict:
        return self._post("/api/v1/enrollment/request", {"enrollment_code": enrollment_code,
            "device_id": self.identity.device_id, "public_key": self.identity.public_key_pem(),
            "hostname": hostname or socket.gethostname(), "agent_version": self.agent_version})

    def _ticket(self) -> str:
        challenge = self._post("/api/v1/agent/challenge", {"device_id": self.identity.device_id})
        nonce_hash = hashlib.sha256(challenge["nonce"].encode("ascii")).hexdigest()
        message = f"labguard.device.auth.v1\n{self.identity.device_id}\n{challenge['challenge_id']}\n{nonce_hash}".encode("ascii")
        signature = self.identity.sign(message)
        encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        result = self._post("/api/v1/agent/ticket", {"device_id": self.identity.device_id,
            "challenge_id": challenge["challenge_id"], "signature": encoded})
        return result["ticket"]

    def _envelope(self, event_type: str, payload: dict) -> dict:
        return {"protocol": "labguard.agent", "schema_version": 1, "event_id": str(uuid4()),
                "device_id": self.identity.device_id, "sequence": self.identity.next_sequence(),
                "sent_at": datetime.now(UTC).isoformat(), "type": event_type, "payload": payload}

    async def connect_once(self) -> ClientConnection:
        ticket = await asyncio.to_thread(self._ticket)
        scheme = "wss" if self.server_url.startswith("https://") else "ws"
        parsed = urllib.parse.urlsplit(self.server_url)
        endpoint = scheme + "://" + parsed.netloc + "/api/v1/agent/session"
        ws = await connect(endpoint, additional_headers={"Authorization": f"Bearer {ticket}"},
                           open_timeout=self.timeout, close_timeout=3, max_size=64 * 1024,
                           ping_interval=20, ping_timeout=20, ssl=self.ssl_context if scheme == "wss" else None)
        await ws.send(json.dumps(self._envelope("client.hello", {"agent_version": self.agent_version,
                            "boot_id": self.boot_id, "protocol_versions": [1]}), separators=(",", ":")))
        welcome = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
        if welcome.get("type") != "server.welcome" or welcome.get("device_id") != self.identity.device_id:
            await ws.close()
            raise RuntimeError("Server did not return a valid welcome")
        self.heartbeat_interval = float(welcome["payload"]["heartbeat_interval_seconds"])
        # Consume hello acknowledgement before returning the established session.
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
        if ack.get("type") != "server.ack" or not ack.get("payload", {}).get("accepted"):
            await ws.close()
            raise RuntimeError("Server did not acknowledge hello")
        return ws

    async def heartbeat(self, ws: ClientConnection) -> dict:
        await ws.send(json.dumps(self._envelope("client.heartbeat", {"health": "ok"}), separators=(",", ":")))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.timeout))
        if ack.get("type") != "server.ack" or not ack.get("payload", {}).get("accepted"):
            raise RuntimeError("Heartbeat was not acknowledged")
        return ack

    async def _read_session_acks(self, ws: ClientConnection, pending: dict[str, asyncio.Future],
                                 inventory_requests: asyncio.Queue, job_offers: asyncio.Queue | None = None,
                                 rdp_requests: asyncio.Queue | None = None,
                                 process_requests: asyncio.Queue | None = None,
                                 screenshot_requests: asyncio.Queue | None = None,
                                 exam_browser_scans: asyncio.Queue | None = None):
        while True:
            message = json.loads(await ws.recv())
            if message.get("type") == "server.software_job.offer":
                if (message.get("protocol") != "labguard.agent"
                        or message.get("schema_version") != 1
                        or message.get("device_id") != self.identity.device_id
                        or job_offers is None):
                    logging.getLogger("labguard_client").warning("Rejected software job offer envelope")
                    continue
                try:
                    job_offers.put_nowait(message.get("payload"))
                except asyncio.QueueFull:
                    logging.getLogger("labguard_client").warning("Software job offer queue is full")
                continue
            if message.get("type") == "server.software_inventory.refresh":
                payload = message.get("payload", {})
                request_id = payload.get("request_id") if isinstance(payload, dict) else None
                inventory_requests.put_nowait(request_id if isinstance(request_id, str) else None)
                continue
            if message.get("type") == "server.rdp.access.request":
                if (message.get("protocol") != "labguard.agent"
                        or message.get("schema_version") != 1
                        or message.get("device_id") != self.identity.device_id
                        or rdp_requests is None):
                    logging.getLogger("labguard_client").warning("Rejected RDP request envelope")
                    continue
                try:
                    rdp_requests.put_nowait(message.get("payload"))
                except asyncio.QueueFull:
                    logging.getLogger("labguard_client").warning("RDP request queue is full")
                continue
            if message.get("type") == "server.process.request":
                if (message.get("protocol") != "labguard.agent"
                        or message.get("schema_version") != 1
                        or message.get("device_id") != self.identity.device_id
                        or process_requests is None):
                    logging.getLogger("labguard_client").warning("Rejected process request envelope")
                    continue
                try:
                    process_requests.put_nowait(message.get("payload"))
                except asyncio.QueueFull:
                    logging.getLogger("labguard_client").warning("Process request queue is full")
                continue
            if message.get("type") == "server.screenshot.request":
                if (message.get("protocol") != "labguard.agent"
                        or message.get("schema_version") != 1
                        or message.get("device_id") != self.identity.device_id
                        or screenshot_requests is None):
                    logging.getLogger("labguard_client").warning("Rejected screenshot request envelope")
                    continue
                try:
                    screenshot_requests.put_nowait(message.get("payload"))
                except asyncio.QueueFull:
                    logging.getLogger("labguard_client").warning("Screenshot request queue is full")
                continue
            if message.get("type") == "server.exam.browser_scan":
                if (message.get("protocol") != "labguard.agent"
                        or message.get("schema_version") != 1
                        or message.get("device_id") != self.identity.device_id
                        or exam_browser_scans is None):
                    logging.getLogger("labguard_client").warning("Rejected exam browser scan envelope")
                    continue
                try:
                    exam_browser_scans.put_nowait(message.get("payload"))
                except asyncio.QueueFull:
                    logging.getLogger("labguard_client").warning("Exam browser scan queue is full")
                continue
            if message.get("type") != "server.ack":
                continue
            event_id = message.get("payload", {}).get("event_id")
            future = pending.pop(event_id, None) if isinstance(event_id, str) else None
            if future is not None and not future.done():
                future.set_result(message.get("payload", {}))

    async def _send_session_event(self, ws: ClientConnection, event_type: str, payload: dict,
                                  pending: dict[str, asyncio.Future], send_lock: asyncio.Lock):
        event_id = None
        future = None
        try:
            async with send_lock:
                envelope = self._envelope(event_type, payload)
                encoded = json.dumps(envelope, separators=(",", ":"))
                if len(encoded.encode("utf-8")) > 60 * 1024:
                    raise ValueError("Telemetry/event frame exceeds the safe 60 KiB client limit")
                event_id = envelope["event_id"]
                future = asyncio.get_running_loop().create_future()
                pending[event_id] = future
                await ws.send(encoded)
            return await asyncio.wait_for(future, timeout=self.timeout)
        finally:
            if event_id is not None:
                pending.pop(event_id, None)
            if future is not None and not future.done():
                future.cancel()

    async def _run_connected_session(self, ws: ClientConnection, stop: asyncio.Event):
        logger = logging.getLogger("labguard_client")
        pending: dict[str, asyncio.Future] = {}
        send_lock = asyncio.Lock()
        inventory_requests: asyncio.Queue[str | None] = asyncio.Queue()
        job_offers: asyncio.Queue[dict] = asyncio.Queue(maxsize=8)
        rdp_requests: asyncio.Queue[dict] = asyncio.Queue(maxsize=4)
        process_requests: asyncio.Queue[dict] = asyncio.Queue(maxsize=4)
        screenshot_requests: asyncio.Queue[dict] = asyncio.Queue(maxsize=8)
        exam_browser_scans: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)

        async def heartbeat_loop():
            while not await self._wait_or_stop(stop, self.heartbeat_interval):
                ack = await self._send_session_event(ws, "client.heartbeat", {"health": "ok"}, pending, send_lock)
                if not ack.get("accepted"):
                    raise RuntimeError("Heartbeat was not acknowledged")

        async def telemetry_loop():
            while not stop.is_set():
                try:
                    snapshot = await asyncio.to_thread(collect_system_telemetry)
                    ack = await self._send_session_event(ws, "client.telemetry", snapshot, pending, send_lock)
                    if not ack.get("accepted"):
                        logger.warning("Telemetry was rejected by server (%s)", ack.get("reason", "unknown"))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # A collection or telemetry acknowledgement failure is isolated from heartbeats.
                    logger.warning("Telemetry collection/transmission failed (%s)", type(exc).__name__)
                if await self._wait_or_stop(stop, self.telemetry_interval_seconds):
                    break

        async def wfp_event_loop():
            if self.wfp_reader is None:
                logger.warning("WFP event collection unavailable (persistent device state path missing)")
                await stop.wait()
                return
            while not stop.is_set():
                try:
                    await asyncio.to_thread(self.wfp_reader.poll)
                    batch = self.wfp_reader.next_batch()
                    if batch is not None:
                        ack = await self._send_session_event(ws, "client.network.wfp", batch, pending, send_lock)
                        if ack.get("accepted"):
                            await asyncio.to_thread(self.wfp_reader.acknowledge, batch)
                        else:
                            logger.warning("WFP event batch rejected by server (%s)", ack.get("reason", "unknown"))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("WFP event collection/transmission failed (%s)", type(exc).__name__)
                delay = 0.01 if self.wfp_reader.pending.qsize() else 2
                if await self._wait_or_stop(stop, delay):
                    break

        async def software_inventory_loop():
            first_collection = True
            while not stop.is_set():
                if first_collection:
                    request_id, force = None, False
                    first_collection = False
                else:
                    try:
                        request_id = await asyncio.wait_for(inventory_requests.get(),
                                                            timeout=self.software_inventory_interval_seconds)
                        force = request_id is not None
                    except TimeoutError:
                        request_id, force = None, False
                try:
                    await self._collect_and_send_software_inventory(ws, pending, send_lock,
                        request_id=request_id, force=force)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Software inventory collection/transmission failed (%s)", type(exc).__name__)

        async def software_job_loop():
            while not stop.is_set():
                payload = await job_offers.get()
                try:
                    await self._run_software_job(payload, ws, pending, send_lock)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Software job processing failed (%s)", type(exc).__name__)

        async def rdp_access_loop():
            while not stop.is_set():
                payload = await rdp_requests.get()
                await self._run_rdp_access_request(payload, ws, pending, send_lock)

        async def process_request_loop():
            while not stop.is_set():
                payload = await process_requests.get()
                try:
                    await self._run_process_request(payload, ws, pending, send_lock)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Process request failed (%s)", type(exc).__name__)

        async def screenshot_request_loop():
            capture_limit = asyncio.Semaphore(4)
            active_captures: set[asyncio.Task] = set()

            async def run_capture(payload):
                try:
                    async with capture_limit:
                        await self._run_screenshot_request(payload, ws, pending, send_lock)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("Screenshot request processing failed (%s)", type(exc).__name__)

            try:
                while not stop.is_set():
                    payload = await screenshot_requests.get()
                    task = asyncio.create_task(run_capture(payload))
                    active_captures.add(task)
                    task.add_done_callback(active_captures.discard)
            finally:
                for task in active_captures:
                    task.cancel()
                if active_captures:
                    await asyncio.gather(*active_captures, return_exceptions=True)

        async def exam_browser_scan_loop():
            while not stop.is_set():
                payload = await exam_browser_scans.get()
                try:
                    if not isinstance(payload, dict) or set(payload) != {"scan_id", "browser_names"}:
                        continue
                    scan_id = str(UUID(payload["scan_id"]))
                    requested = payload["browser_names"]
                    supported = {"msedge.exe", "chrome.exe", "firefox.exe"}
                    if (not isinstance(requested, list) or len(requested) > 8
                            or any(not isinstance(name, str) for name in requested)):
                        continue
                    names = {name.casefold() for name in requested} & supported
                    processes = await asyncio.to_thread(list_processes, limit=MAX_PROCESSES)
                    counts = {}
                    for process in processes:
                        name = str(process.get("name") or "").casefold()
                        if name in names:
                            counts[name] = counts.get(name, 0) + 1
                    result = await self._send_session_event(ws, "client.exam.browser_scan", {
                        "scan_id": scan_id,
                        "browsers": [{"name": name, "count": count}
                                     for name, count in sorted(counts.items())]}, pending, send_lock)
                    if not result.get("accepted"):
                        logger.warning("Exam browser scan was rejected by server (%s)",
                                       result.get("reason", "unknown"))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Exam browser scan failed (%s)", type(exc).__name__)

        async def peripheral_snapshot_loop():
            last_signature = None
            last_sent_at = 0.0
            while not stop.is_set():
                try:
                    peripherals = await asyncio.to_thread(collect_peripherals)
                    if peripherals is not None:
                        signature = json.dumps(peripherals, sort_keys=True, separators=(",", ":"))
                        now = asyncio.get_running_loop().time()
                        if signature != last_signature or now - last_sent_at >= 30:
                            payload = {"collected_at": datetime.now(UTC).isoformat(),
                                       "peripherals": peripherals}
                            ack = await self._send_session_event(
                                ws, "client.peripheral.snapshot", payload, pending, send_lock)
                            if ack.get("accepted"):
                                last_signature = signature
                                last_sent_at = now
                            else:
                                logger.warning("Peripheral snapshot was rejected by server (%s)",
                                               ack.get("reason", "unknown"))
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("Peripheral monitoring failed (%s)", type(exc).__name__)
                if await self._wait_or_stop(stop, 5):
                    break

        tasks = [asyncio.create_task(self._read_session_acks(ws, pending, inventory_requests, job_offers, rdp_requests, process_requests, screenshot_requests, exam_browser_scans)),
                 asyncio.create_task(heartbeat_loop()), asyncio.create_task(telemetry_loop()),
                 asyncio.create_task(software_inventory_loop()),
                 asyncio.create_task(software_job_loop()), asyncio.create_task(rdp_access_loop()),
                 asyncio.create_task(process_request_loop()), asyncio.create_task(stop.wait()),
                 asyncio.create_task(peripheral_snapshot_loop()), asyncio.create_task(wfp_event_loop())]
        tasks.append(asyncio.create_task(screenshot_request_loop()))
        tasks.append(asyncio.create_task(exam_browser_scan_loop()))
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if tasks[7] in done:
                return
            for task in done:
                if task is tasks[0]:
                    await task
                    raise ConnectionError("Authenticated agent session ended")
                await task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def _inventory_digest_path(self):
        state_file = getattr(self.identity, "state_file", None)
        return state_file.parent / "software-inventory.sha256" if state_file else None

    def _read_inventory_digest(self) -> str | None:
        path = self._inventory_digest_path()
        if path is None:
            return None
        try:
            value = path.read_text(encoding="ascii").strip()
            return value if re.fullmatch(r"[0-9a-f]{64}", value) else None
        except OSError:
            return None

    def _save_inventory_digest(self, value: str) -> None:
        path = self._inventory_digest_path()
        if path is None:
            return
        try:
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(value + "\n", encoding="ascii")
            temp.replace(path)
        except OSError as exc:
            logging.getLogger("labguard_client").warning(
                "Could not persist software inventory fingerprint (%s)", type(exc).__name__)

    async def _send_inventory_event(self, ws: ClientConnection, payload: dict,
                                    pending: dict[str, asyncio.Future], send_lock: asyncio.Lock):
        ack = await self._send_session_event(ws, "client.software_inventory", payload, pending, send_lock)
        if ack.get("reason") != "inventory_rate_limited":
            return ack
        retry_after = ack.get("retry_after_seconds")
        if (not isinstance(retry_after, (int, float)) or isinstance(retry_after, bool)
                or not 1 <= retry_after <= 60):
            return ack
        # Inventory transfer is a background task; a short bounded retry must
        # not block heartbeats or interrupt the authenticated session.
        await asyncio.sleep(retry_after)
        return await self._send_session_event(ws, "client.software_inventory", payload, pending, send_lock)

    async def _collect_and_send_software_inventory(self, ws: ClientConnection, pending: dict,
                                                    send_lock: asyncio.Lock, *, request_id: str | None,
                                                    force: bool, collected=None, job_id: str | None = None) -> bool:
        logger = logging.getLogger("labguard_client")
        started_at = datetime.now(UTC).isoformat()
        collected = collected or await asyncio.to_thread(collect_software_inventory)
        digest = inventory_digest(collected.entries)
        common = {"collection_id": str(uuid4()), "request_id": request_id, "inventory_version": 1,
                  "started_at": started_at, "collection_status": "COMPLETE" if collected.complete else "PARTIAL",
                  "inventory_digest": digest, "errors": collected.errors, "job_id": job_id}
        if not force and collected.complete and digest == self._read_inventory_digest():
            payload = {**common, "batch_index": 0, "batch_count": 1, "unchanged": True, "entries": []}
            ack = await self._send_inventory_event(ws, payload, pending, send_lock)
            if ack.get("accepted"):
                self._save_inventory_digest(digest)
                return True
            if not ack.get("full_refresh_required"):
                logger.warning("Unchanged software inventory report was rejected (%s)", ack.get("reason", "unknown"))
                return False
            common["collection_id"] = str(uuid4())
        batches = batch_entries(collected.entries, common)
        for index, entries in enumerate(batches):
            payload = {**common, "batch_index": index, "batch_count": len(batches),
                       "unchanged": False, "entries": entries}
            ack = await self._send_inventory_event(ws, payload, pending, send_lock)
            if not ack.get("accepted"):
                logger.warning("Software inventory batch was rejected (%s)", ack.get("reason", "unknown"))
                return False
        if collected.complete:
            self._save_inventory_digest(digest)
        logger.info("Software inventory sent entries=%d batches=%d status=%s", len(collected.entries),
                    len(batches), common["collection_status"])
        return True

    def _job_journal_path(self):
        state_file = getattr(self.identity, "state_file", None)
        return state_file.parent / "software-jobs.json" if state_file else None

    def _load_job_journal(self) -> dict[str, dict]:
        path = self._job_journal_path()
        if path is None:
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            jobs = value.get("jobs", {}) if isinstance(value, dict) else {}
            return jobs if isinstance(jobs, dict) else {}
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            logging.getLogger("labguard_client").warning("Could not read software job journal")
            return {}

    def _save_job_journal(self, jobs: dict[str, dict]) -> None:
        path = self._job_journal_path()
        if path is None:
            raise OSError("Persistent identity state is required for software jobs")
        terminal = [(key, value) for key, value in jobs.items()
                    if value.get("status") in {"SUCCEEDED", "FAILED"}]
        active = [(key, value) for key, value in jobs.items()
                  if value.get("status") not in {"SUCCEEDED", "FAILED"}]
        bounded = dict((active + terminal[-200:])[-205:])
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps({"version": 1, "jobs": bounded}, separators=(",", ":")), encoding="utf-8")
        temp.replace(path)

    async def _send_job_terminal(self, job_id: str, state: dict, ws, pending, send_lock):
        success = state.get("status") == "SUCCEEDED"
        event_type = "client.job.completed" if success else "client.job.failed"
        payload = {"job_id": job_id, "result_code": state.get("result_code"),
                   "result_summary": state.get("result_summary"),
                   "error_message": state.get("error_message")}
        try:
            await self._send_session_event(ws, event_type, payload, pending, send_lock)
        except Exception as exc:
            logging.getLogger("labguard_client").warning(
                "Could not report software job result (%s)", type(exc).__name__)

    async def _run_software_job(self, payload: dict, ws, pending, send_lock):
        logger = logging.getLogger("labguard_client")
        try:
            offer = SoftwareJobOffer.parse(payload)
        except (TypeError, ValueError) as exc:
            logger.warning("Rejected invalid software job offer (%s)", type(exc).__name__)
            return
        jobs = self._load_job_journal()
        current = jobs.get(offer.job_id)
        expires = datetime.fromisoformat(offer.expires_at.replace("Z", "+00:00"))
        if current is None and expires.astimezone(UTC) <= datetime.now(UTC):
            logger.info("Ignored expired software job offer id=%s", offer.job_id)
            return
        if current and current.get("status") in {"SUCCEEDED", "FAILED"}:
            await self._send_job_terminal(offer.job_id, current, ws, pending, send_lock)
            return
        if current and current.get("status") == "RUNNING":
            interrupted = {"status": "FAILED", "result_code": "agent_restart_result_unknown",
                           "result_summary": "Agent restarted while package operation was active; it was not repeated.",
                           "error_message": "The previous operation may have completed; review inventory before retrying."}
            jobs[offer.job_id] = interrupted
            self._save_job_journal(jobs)
            await self._send_job_terminal(offer.job_id, interrupted, ws, pending, send_lock)
            return
        if current is None:
            current = {"status": "ACCEPTED"}
            jobs[offer.job_id] = current
            self._save_job_journal(jobs)
        accepted = await self._send_session_event(ws, "client.job.accepted", {"job_id": offer.job_id},
                                                  pending, send_lock)
        if not accepted.get("accepted"):
            if accepted.get("status") == "RUNNING":
                interrupted = {"status": "FAILED", "result_code": "agent_restart_result_unknown",
                    "result_summary": "Agent restarted while package operation was active; it was not repeated.",
                    "error_message": "Review inventory before retrying."}
                jobs[offer.job_id] = interrupted
                self._save_job_journal(jobs)
                await self._send_job_terminal(offer.job_id, interrupted, ws, pending, send_lock)
            return
        started = await self._send_session_event(ws, "client.job.started", {"job_id": offer.job_id},
                                                 pending, send_lock)
        if not started.get("accepted"):
            return
        jobs[offer.job_id] = {"status": "RUNNING"}
        self._save_job_journal(jobs)

        loop = asyncio.get_running_loop()
        progress_queue: asyncio.Queue[str] = asyncio.Queue()
        cancellation = threading.Event()
        def report_progress(message: str):
            loop.call_soon_threadsafe(progress_queue.put_nowait, message[:256])
        operation = asyncio.create_task(asyncio.to_thread(execute_package_job, offer,
            progress=report_progress, cancellation_event=cancellation))
        percent = 5
        try:
            while not operation.done():
                try:
                    message = await asyncio.wait_for(progress_queue.get(), timeout=2)
                except TimeoutError:
                    continue
                percent = min(90, percent + 10)
                try:
                    await self._send_session_event(ws, "client.job.progress", {
                        "job_id": offer.job_id, "progress_percent": percent,
                        "progress_message": message}, pending, send_lock)
                except Exception as exc:
                    logger.warning("Software job progress could not be sent (%s)", type(exc).__name__)
            result = await operation
        except asyncio.CancelledError:
            cancellation.set()
            try:
                result = await asyncio.wait_for(operation, timeout=7)
            except Exception:
                result = None
            if result is not None and result.cancelled:
                failed = {"status": "FAILED", "result_code": "operation_cancelled",
                          "result_summary": result.output, "error_message": "Agent stopped during package operation."}
                jobs[offer.job_id] = failed
                self._save_job_journal(jobs)
            raise
        except (PackageManagerUnavailable, UnsupportedExecutionContext, ValueError) as exc:
            code = str(exc)[:64].lower()
            if not re.fullmatch(r"[a-z0-9_:-]+", code):
                code = "unsupported_execution_context"
            failed = {"status": "FAILED", "result_code": code,
                      "result_summary": "Package operation was not started.", "error_message": code}
            jobs[offer.job_id] = failed
            self._save_job_journal(jobs)
            await self._send_job_terminal(offer.job_id, failed, ws, pending, send_lock)
            return
        except Exception as exc:
            logger.exception("Software package operation failed unexpectedly (%s)", type(exc).__name__)
            failed = {"status": "FAILED", "result_code": "package_operation_error",
                      "result_summary": "Package operation failed unexpectedly.",
                      "error_message": "The package manager operation could not be completed."}
            jobs[offer.job_id] = failed
            self._save_job_journal(jobs)
            await self._send_job_terminal(offer.job_id, failed, ws, pending, send_lock)
            return

        try:
            collected = await asyncio.to_thread(collect_software_inventory)
            report_ok = await self._collect_and_send_software_inventory(
                ws, pending, send_lock, request_id=None, force=True, collected=collected, job_id=offer.job_id)
        except Exception as exc:
            logger.exception("Post-operation software inventory failed (%s)", type(exc).__name__)
            collected = None
            report_ok = False
        expected_source = "WINGET" if offer.package_manager == "WINGET" else "CHOCO"
        found = bool(collected and any(item.get("package_id") and item["package_id"].casefold() == offer.package_id.casefold()
                    and item.get("source") == expected_source for item in collected.entries)
                    )
        if result.timed_out:
            result_code, error = "package_manager_timeout", "Package manager exceeded the configured operation timeout."
            state = "FAILED"
        elif result.cancelled:
            result_code, error = "operation_cancelled", "Package operation was cancelled."
            state = "FAILED"
        elif result.returncode != 0:
            result_code, error = f"package_manager_exit_{result.returncode}", "Package manager reported failure."
            state = "FAILED"
        elif not report_ok:
            result_code, error = "inventory_report_failed", "Operation completed but refreshed inventory was not accepted by the server."
            state = "FAILED"
        elif collected is None:
            result_code, error, state = "inventory_report_failed", "Could not collect post-operation inventory for verification.", "FAILED"
        elif (offer.action == "INSTALL" and found) or (
                offer.action == "UNINSTALL" and not found and collected.complete):
            result_code, error, state = "verified_success", None, "SUCCEEDED"
        else:
            result_code, error, state = "inventory_verification_failed", "Package manager exited successfully, but the refreshed inventory did not confirm the requested result.", "FAILED"
        final = {"status": state, "result_code": result_code,
                 "result_summary": result.output or "Package manager operation finished.",
                 "error_message": error}
        jobs[offer.job_id] = final
        self._save_job_journal(jobs)
        await self._send_job_terminal(offer.job_id, final, ws, pending, send_lock)

    async def _run_rdp_access_request(self, payload: dict, ws, pending, send_lock):
        logger = logging.getLogger("labguard_client")
        if not isinstance(payload, dict) or set(payload) != {"request_id", "expires_at", "access_expires_at"}:
            logger.warning("Rejected malformed RDP access request")
            return
        try:
            request_id = str(UUID(payload["request_id"]))
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            access_expires_at = datetime.fromisoformat(payload["access_expires_at"].replace("Z", "+00:00"))
            if expires.astimezone(UTC) <= datetime.now(UTC):
                result = {"status": "FAILED", "error_code": "rdp_request_expired"}
            else:
                result = await asyncio.to_thread(prepare_rdp_access, request_id,
                    access_expires_at.isoformat(), now=datetime.now(UTC))
        except (TypeError, ValueError, AttributeError):
            logger.warning("Rejected invalid RDP access request payload")
            return
        try:
            result_payload = {"request_id": request_id, "status": result["status"],
                              "error_code": result.get("error_code")}
            username = await asyncio.to_thread(active_windows_username)
            if username is not None and result["status"] == "READY":
                result_payload["username"] = username
            ack = await self._send_session_event(ws, "client.rdp.access.result",
                result_payload, pending, send_lock)
            if not ack.get("accepted"):
                logger.warning("RDP access result was rejected by server (%s)", ack.get("reason", "unknown"))
        except Exception as exc:
            logger.warning("Could not report RDP access result (%s)", type(exc).__name__)

    async def _run_process_request(self, payload: dict, ws, pending, send_lock):
        logger = logging.getLogger("labguard_client")
        expected = {"request_id", "operation", "target_pid", "target_created_at_us", "expires_at"}
        if not isinstance(payload, dict) or set(payload) != expected:
            logger.warning("Rejected malformed process request")
            return
        try:
            request_id = str(UUID(payload["request_id"]))
            operation = payload["operation"]
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            if operation not in {"LIST", "TERMINATE", "KILL"}:
                raise ValueError("unsupported operation")
            now = datetime.now(UTC)
            if expires.astimezone(UTC) > now + timedelta(minutes=2):
                raise ValueError("request expiry exceeds the supported window")
            if expires.astimezone(UTC) <= now:
                result_code = "request_expired"
                processes = []
                batch_count = 1
            elif operation == "LIST":
                if payload["target_pid"] is not None or payload["target_created_at_us"] is not None:
                    raise ValueError("list request has an unexpected target")
                result_code = None
                try:
                    processes = await asyncio.to_thread(list_processes, limit=MAX_PROCESSES + 1)
                except Exception:
                    processes = []
                    result_code = "process_list_failed"
                if result_code is None and len(processes) > MAX_PROCESSES:
                    result_code = "process_list_truncated"
                    processes = processes[:MAX_PROCESSES]
                batch_size = 8
                batches = [processes[index:index + batch_size]
                           for index in range(0, len(processes), batch_size)] or [[]]
                batch_count = len(batches)
            else:
                pid, created_at_us = payload["target_pid"], payload["target_created_at_us"]
                if (not isinstance(pid, int) or isinstance(pid, bool) or not 1 <= pid <= 2_147_483_647
                        or not isinstance(created_at_us, int) or isinstance(created_at_us, bool)
                        or created_at_us <= 0):
                    raise ValueError("invalid process identity")
                result_code = await asyncio.to_thread(terminate_process, pid, created_at_us,
                                                     force=operation == "KILL")
                processes = []
                batch_count = 1
        except (TypeError, ValueError, AttributeError, OverflowError):
            logger.warning("Rejected invalid process request payload")
            return

        try:
            for batch_index in range(batch_count):
                result_payload = {
                    "request_id": request_id,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                    "processes": batches[batch_index] if operation == "LIST"
                        and result_code not in {"process_list_failed", "request_expired"} else [],
                    "result_code": result_code,
                }
                ack = await self._send_session_event(ws, "client.process.result",
                                                     result_payload, pending, send_lock)
                if not ack.get("accepted"):
                    logger.warning("Process result was rejected by server (%s)", ack.get("reason", "unknown"))
                    break
        except Exception as exc:
            logger.warning("Could not report process result (%s)", type(exc).__name__)

    async def _run_screenshot_request(self, payload: dict, ws, pending, send_lock):
        logger = logging.getLogger("labguard_client")
        capture_id = None
        try:
            if not isinstance(payload, dict) or set(payload) != {"capture_id", "expires_at"}:
                raise ValueError("invalid_request")
            capture_id = UUID(payload["capture_id"])
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires.astimezone(UTC) <= datetime.now(UTC):
                raise ValueError("request_expired")
            if expires.astimezone(UTC) > datetime.now(UTC) + timedelta(minutes=3):
                raise ValueError("request_expiry_invalid")
            content = await asyncio.to_thread(capture_screenshot, capture_id)
            chunk_size = 32 * 1024
            chunks = [content[index:index + chunk_size] for index in range(0, len(content), chunk_size)]
            for index, chunk in enumerate(chunks):
                result = await self._send_session_event(ws, "client.screenshot.chunk", {
                    "capture_id": str(capture_id), "chunk_index": index,
                    "chunk_count": len(chunks), "data": base64.b64encode(chunk).decode("ascii")},
                    pending, send_lock)
                if not result.get("accepted"):
                    logger.warning("Screenshot chunk rejected (%s)", result.get("reason", "unknown"))
                    return
            logger.info("Screenshot capture %s uploaded", capture_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            candidate = str(exc)
            code = candidate if re.fullmatch(r"[a-z0-9_:-]{1,64}", candidate) else "capture_internal_error"
            # Keep the dashboard error code generic, while retaining a traceback in
            # the protected local service log so unexpected Windows API failures
            # can be diagnosed without exposing exception text to the UI.
            logger.exception("Screenshot capture failed (%s; exception=%s)", code, type(exc).__name__)
            if capture_id is not None:
                try:
                    await self._send_session_event(ws, "client.screenshot.failed",
                        {"capture_id": str(capture_id), "error_code": code}, pending, send_lock)
                except Exception:
                    pass

    async def _rdp_lease_cleanup_loop(self, stop: asyncio.Event):
        logger = logging.getLogger("labguard_client")
        while not stop.is_set():
            try:
                await asyncio.to_thread(cleanup_expired_rdp_access)
            except Exception as exc:
                logger.warning("Temporary RDP access cleanup failed (%s)", type(exc).__name__)
            if await self._wait_or_stop(stop, 30):
                break

    async def _wait_or_stop(self, stop: asyncio.Event, delay: float) -> bool:
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(0.0, delay))
            return True
        except TimeoutError:
            return stop.is_set()

    async def _operation_or_stop(self, operation, stop: asyncio.Event):
        task = asyncio.create_task(operation)
        stopped = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait((task, stopped), return_when=asyncio.FIRST_COMPLETED)
        if stopped in done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None
        stopped.cancel()
        await asyncio.gather(stopped, return_exceptions=True)
        return await task

    async def run_forever(self, stop: asyncio.Event | None = None):
        stop = stop or asyncio.Event()
        process_lock = IdentityProcessLock.for_state_file(self.identity.state_file)
        if process_lock:
            process_lock.acquire()
        logger = logging.getLogger("labguard_client")
        logger.info("Agent starting")
        attempt = 0
        rdp_cleanup_task = asyncio.create_task(self._rdp_lease_cleanup_loop(stop))
        try:
            while not stop.is_set():
                try:
                    ws = await self._operation_or_stop(self.connect_once(), stop)
                    if ws is None:
                        break
                    async with ws:
                        logger.info("Authenticated server connection established")
                        attempt = 0
                        await self._run_connected_session(ws, stop)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if stop.is_set():
                        break
                    category = "Authentication/connection failure" if isinstance(exc, RuntimeError) else "Unexpected agent exception"
                    logger.warning("%s (%s); reconnecting", category, type(exc).__name__)
                    cap = min(60.0, 1.0 * (2 ** min(attempt, 6)))
                    delay = random.uniform(0.0, cap)
                    logger.info("Reconnect attempt %d scheduled in %.1f seconds", attempt + 1, delay)
                    attempt += 1
                    if await self._wait_or_stop(stop, delay):
                        break
        finally:
            rdp_cleanup_task.cancel()
            await asyncio.gather(rdp_cleanup_task, return_exceptions=True)
            try:
                await asyncio.to_thread(cleanup_expired_rdp_access, force=True)
            except Exception as exc:
                logger.warning("Temporary RDP access shutdown cleanup failed (%s)", type(exc).__name__)
            if process_lock:
                process_lock.release()
            logger.info("Agent stopped")

