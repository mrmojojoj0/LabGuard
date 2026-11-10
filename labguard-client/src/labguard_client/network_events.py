"""Bounded, cursor based Windows Filtering Platform event reader."""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import queue
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("labguard_client.network_events")
NETWORK_EVENT_IDS = {5152, 5156, 5157}
SECURITY_LOG_CLEARED_EVENT_ID = 1102
MAX_PENDING_EVENTS = 5000
MAX_EVENTS_PER_POLL = 500
MAX_EVENTS_PER_BATCH = 25


@dataclass(frozen=True)
class WfpRecord:
    event_record_id: int
    event_id: int
    payload: dict | None


class EventSource(Protocol):
    def bounds(self) -> tuple[int, int]: ...
    def read_after(self, record_id: int, limit: int) -> list[WfpRecord]: ...


class WindowsSecurityEventSource:
    """Use pywin32 Event Log APIs; record-ID XPath queries avoid rescanning history."""

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows Security log is available only on Windows")
        import win32evtlog
        self.win32evtlog = win32evtlog

    def bounds(self) -> tuple[int, int]:
        win32evtlog = self.win32evtlog
        handle = win32evtlog.OpenEventLog(None, "Security")
        try:
            count = win32evtlog.GetNumberOfEventLogRecords(handle)
            oldest = win32evtlog.GetOldestEventLogRecord(handle) if count else 0
            return int(oldest), int(oldest + count - 1) if count else 0
        finally:
            win32evtlog.CloseEventLog(handle)

    def read_after(self, record_id: int, limit: int) -> list[WfpRecord]:
        win32evtlog = self.win32evtlog
        query = (
            "*[System[(EventID=5152 or EventID=5156 or EventID=5157 or EventID=1102) "
            f"and EventRecordID > {int(record_id)}]]"
        )
        flags = win32evtlog.EvtQueryChannelPath | getattr(win32evtlog, "EvtQueryForwardDirection", 0x100)
        handle = win32evtlog.EvtQuery("Security", flags, query)
        records: list[WfpRecord] = []
        while len(records) < limit:
            batch = win32evtlog.EvtNext(handle, min(128, limit - len(records)), 0, 0)
            if not batch:
                break
            for event in batch:
                # Pywin32 wraps EVT_HANDLE values in PyEVT_HANDLE objects and
                # calls EvtClose when each wrapper is released. This version
                # of win32evtlog does not expose an EvtClose function.
                xml_text = win32evtlog.EvtRender(event, win32evtlog.EvtRenderEventXml)
                record = parse_wfp_event(xml_text)
                if record is not None:
                    records.append(record)
        records.sort(key=lambda item: item.event_record_id)
        return records


def parse_wfp_event(xml_text: str) -> WfpRecord | None:
    """Normalize supported Security event XML without retaining raw XML or URLs."""
    root = ET.fromstring(xml_text)
    namespace = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    system = root.find("e:System", namespace)
    if system is None:
        return None
    event_id_node = system.find("e:EventID", namespace)
    record_id_node = system.find("e:EventRecordID", namespace)
    time_node = system.find("e:TimeCreated", namespace)
    if event_id_node is None or record_id_node is None:
        return None
    try:
        event_id = int(event_id_node.text or "0")
        record_id = int(record_id_node.text or "0")
    except ValueError:
        return None
    if event_id == SECURITY_LOG_CLEARED_EVENT_ID:
        return WfpRecord(record_id, event_id, None)
    if event_id not in NETWORK_EVENT_IDS or time_node is None or not time_node.get("SystemTime"):
        return None

    data = {
        item.get("Name", ""): (item.text or item.get("Value", ""))
        for item in root.findall("e:EventData/e:Data", namespace)
    }
    try:
        protocol_number = int(data["Protocol"], 0)
        source_ip = str(ipaddress.ip_address(data["SourceAddress"].split("%", 1)[0]))
        destination_ip = str(ipaddress.ip_address(data["DestAddress"].split("%", 1)[0]))
        event_time = datetime.fromisoformat(time_node.get("SystemTime", "").replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return None
    try:
        process_id = int(data.get("ProcessID", "0"), 0)
        if not 0 <= process_id <= 0xFFFFFFFF:
            process_id = 0
    except (ValueError, TypeError):
        process_id = 0

    direction_text = data.get("Direction", "").casefold()
    if "inbound" in direction_text or "14592" in direction_text:
        direction = "INCOMING"
    elif "outbound" in direction_text or "14593" in direction_text:
        direction = "OUTGOING"
    else:
        direction = "UNKNOWN"
    protocol = {1: "ICMP", 6: "TCP", 17: "UDP", 58: "ICMP"}.get(protocol_number, "OTHER")
    kind = {5152: "PACKET_BLOCKED", 5156: "CONNECTION_ALLOWED", 5157: "CONNECTION_BLOCKED"}[event_id]
    process_path = data.get("Application") or None
    if process_path in {"-", "N/A"}:
        process_path = None
    payload = {
        "event_record_id": record_id,
        "event_id": event_id,
        "event_time": event_time.isoformat(),
        "event_kind": kind,
        "direction": direction,
        "protocol": protocol,
        "protocol_number": protocol_number,
        "source_ip": source_ip,
        "source_port": _parse_port(data.get("SourcePort")),
        "destination_ip": destination_ip,
        "destination_port": _parse_port(data.get("DestPort")),
        "process_id": process_id or None,
        "process_path": process_path[:1024] if process_path else None,
    }
    return WfpRecord(record_id, event_id, payload)


def _parse_port(value: str | None) -> int | None:
    try:
        port = int(value or "")
        return port if 0 <= port <= 65535 else None
    except ValueError:
        return None


class WfpEventReader:
    """Poll by record ID, queue bounded batches, and persist cursor only after ACK."""

    def __init__(self, cursor_path: Path, source: EventSource | None = None):
        self.cursor_path = cursor_path
        self.source = source
        self.pending: queue.Queue[tuple[str, WfpRecord]] = queue.Queue(MAX_PENDING_EVENTS)
        self._lock = threading.RLock()
        self._queued_ids: set[tuple[str, int]] = set()
        self._read_record_id = 0
        self._acked_record_id = 0
        self._generation = str(uuid.uuid4())
        self._gap_reason: str | None = None
        self._status = "STARTING"
        self._error: str | None = None
        self._status_due = True
        self._last_status_sent_at = 0.0
        self._initialized = False
        self._load_cursor()

    @property
    def status(self) -> str:
        return self._status

    def _load_cursor(self) -> None:
        try:
            state = json.loads(self.cursor_path.read_text(encoding="utf-8"))
            self._acked_record_id = max(0, int(state["record_id"]))
            self._read_record_id = self._acked_record_id
            self._generation = str(uuid.UUID(state["generation"]))
            self._initialized = True
        except FileNotFoundError:
            self._initialized = False
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self._gap_reason = "CURSOR_INVALID"
            self._initialized = False

    def poll(self) -> None:
        with self._lock:
            try:
                source = self.source or WindowsSecurityEventSource()
                previous_status = self._status
                oldest, latest = source.bounds()
                if not self._initialized:
                    # Begin at the current end; do not upload unrelated historical audit data.
                    self._acked_record_id = latest
                    self._read_record_id = latest
                    self._initialized = True
                    self._persist_cursor(self._acked_record_id, self._generation)
                    self._status = "GAP" if self._gap_reason else "ACTIVE"
                    return
                if latest < self._read_record_id or (oldest and oldest > self._acked_record_id + 1):
                    reason = "SECURITY_LOG_CLEARED" if latest < self._read_record_id else "SECURITY_LOG_ROLLOVER"
                    self._generation = str(uuid.uuid4())
                    self._gap_reason = reason
                    self._clear_pending()
                    self._read_record_id = max(0, oldest - 1)
                records = source.read_after(self._read_record_id, MAX_EVENTS_PER_POLL)
                for record in records:
                    if record.event_id == SECURITY_LOG_CLEARED_EVENT_ID:
                        self._generation = str(uuid.uuid4())
                        self._gap_reason = "SECURITY_LOG_CLEARED"
                        self._clear_pending()
                        self._read_record_id = record.event_record_id
                        continue
                    if record.payload is None:
                        continue
                    key = (self._generation, record.event_record_id)
                    if key in self._queued_ids or self.pending.full():
                        break
                    self.pending.put_nowait((self._generation, record))
                    self._queued_ids.add(key)
                    self._read_record_id = record.event_record_id
                self._status = "GAP" if self._gap_reason else "ACTIVE"
                if previous_status != self._status:
                    self._status_due = True
                if time.monotonic() - self._last_status_sent_at >= 60:
                    self._status_due = True
                self._error = None
            except Exception as exc:
                previous_status = self._status
                self._status = "UNAVAILABLE"
                self._error = type(exc).__name__.upper()
                self._status_due = self._status_due or previous_status != self._status
                logger.warning("WFP event reader unavailable (%s)", self._error)

    def _clear_pending(self) -> None:
        while True:
            try:
                self.pending.get_nowait()
            except queue.Empty:
                break
        self._queued_ids.clear()

    def next_batch(self) -> dict | None:
        with self._lock:
            queued = list(self.pending.queue)[:MAX_EVENTS_PER_BATCH]
            if not queued and not self._gap_reason and self._status == "ACTIVE" and not self._status_due:
                return None
            generation = queued[0][0] if queued else self._generation
            same_generation = []
            for item_generation, record in queued:
                if item_generation != generation:
                    break
                same_generation.append(record.payload)
            cursor = same_generation[-1]["event_record_id"] if same_generation else self._read_record_id
            return {
                "log_generation": generation,
                "cursor_record_id": cursor,
                "status": self._status,
                "gap_reason": self._gap_reason,
                "error_code": self._error,
                "events": same_generation,
            }

    def acknowledge(self, batch: dict) -> None:
        with self._lock:
            generation = str(uuid.UUID(batch["log_generation"]))
            record_id = int(batch["cursor_record_id"])
            if generation != self._generation and self.pending.qsize():
                # Old-generation queued items must be acknowledged before cursor generation changes.
                if self.pending.queue[0][0] != generation:
                    raise ValueError("Cursor generation changed before queued events were acknowledged")
            self._persist_cursor(record_id, generation)
            self._acked_record_id = record_id
            while not self.pending.empty():
                item_generation, record = self.pending.queue[0]
                if item_generation != generation or record.event_record_id > record_id:
                    break
                self.pending.get_nowait()
                self._queued_ids.discard((item_generation, record.event_record_id))
            if self._gap_reason and generation == self._generation:
                self._gap_reason = None
                self._status = "ACTIVE"
                self._status_due = True
            elif not self._gap_reason:
                self._status_due = False
            self._last_status_sent_at = time.monotonic()

    def _persist_cursor(self, record_id: int, generation: str) -> None:
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"record_id": int(record_id), "generation": generation}, separators=(",", ":"))
        fd, temp_name = tempfile.mkstemp(prefix=".wfp-cursor-", dir=self.cursor_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp:
                temp.write(payload + "\n")
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, self.cursor_path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
