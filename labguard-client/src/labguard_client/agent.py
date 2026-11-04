from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import platform
import random
import socket
import ssl
import logging
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from uuid import uuid4

from websockets.asyncio.client import ClientConnection, connect

from labguard_client.identity import DeviceIdentity
from labguard_client.instance import IdentityProcessLock
from labguard_client.telemetry import collect_system_telemetry


class AgentClient:
    def __init__(self, server_url: str, identity: DeviceIdentity, *, agent_version: str = "0.1.0",
                 heartbeat_interval: float = 10.0, telemetry_interval_seconds: float = 30.0,
                 timeout: float = 15.0, allow_insecure_dev: bool = False):
        if not server_url.startswith(("https://", "http://")):
            raise ValueError("Server URL must use HTTPS (HTTP is only for local development)")
        if server_url.startswith("http://") and not allow_insecure_dev:
            raise ValueError("Plain HTTP is disabled unless allow_insecure_dev is explicitly enabled")
        self.server_url = server_url.rstrip("/")
        self.identity = identity
        self.agent_version = agent_version
        self.heartbeat_interval = heartbeat_interval
        if not 10 <= telemetry_interval_seconds <= 3600:
            raise ValueError("Telemetry interval must be between 10 and 3600 seconds")
        self.telemetry_interval_seconds = telemetry_interval_seconds
        self.timeout = timeout
        self.boot_id = str(uuid4())
        self.ssl_context = ssl.create_default_context()

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

    async def _read_session_acks(self, ws: ClientConnection, pending: dict[str, asyncio.Future]):
        while True:
            message = json.loads(await ws.recv())
            if message.get("type") != "server.ack":
                continue
            event_id = message.get("payload", {}).get("event_id")
            future = pending.pop(event_id, None) if isinstance(event_id, str) else None
            if future is not None and not future.done():
                future.set_result(message.get("payload", {}))

    async def _send_session_event(self, ws: ClientConnection, event_type: str, payload: dict,
                                  pending: dict[str, asyncio.Future], send_lock: asyncio.Lock):
        envelope = self._envelope(event_type, payload)
        encoded = json.dumps(envelope, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 60 * 1024:
            raise ValueError("Telemetry/event frame exceeds the safe 60 KiB client limit")
        event_id = envelope["event_id"]
        future = asyncio.get_running_loop().create_future()
        pending[event_id] = future
        try:
            async with send_lock:
                await ws.send(encoded)
            return await asyncio.wait_for(future, timeout=self.timeout)
        finally:
            pending.pop(event_id, None)
            if not future.done():
                future.cancel()

    async def _run_connected_session(self, ws: ClientConnection, stop: asyncio.Event):
        logger = logging.getLogger("labguard_client")
        pending: dict[str, asyncio.Future] = {}
        send_lock = asyncio.Lock()

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

        tasks = [asyncio.create_task(self._read_session_acks(ws, pending)),
                 asyncio.create_task(heartbeat_loop()), asyncio.create_task(telemetry_loop()),
                 asyncio.create_task(stop.wait())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if tasks[3] in done:
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
            if process_lock:
                process_lock.release()
            logger.info("Agent stopped")

