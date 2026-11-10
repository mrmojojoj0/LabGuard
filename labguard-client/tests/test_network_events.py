from __future__ import annotations

from datetime import UTC, datetime

from labguard_client.network_events import MAX_PENDING_EVENTS, WfpEventReader, WfpRecord, parse_wfp_event


class FakeEventSource:
    def __init__(self):
        self.oldest = 1
        self.latest = 10
        self.records: list[WfpRecord] = []

    def bounds(self):
        return self.oldest, self.latest

    def read_after(self, record_id, limit):
        return [record for record in self.records if record.event_record_id > record_id][:limit]


def connection_event(record_id=11, event_id=5156):
    kind = {5152: "PACKET_BLOCKED", 5156: "CONNECTION_ALLOWED", 5157: "CONNECTION_BLOCKED"}[event_id]
    return WfpRecord(record_id, event_id, {
        "event_record_id": record_id, "event_id": event_id,
        "event_time": datetime.now(UTC).isoformat(), "event_kind": kind,
        "direction": "OUTGOING", "protocol": "TCP", "protocol_number": 6,
        "source_ip": "192.168.1.20", "source_port": 52345,
        "destination_ip": "8.8.8.8", "destination_port": 443,
        "process_id": 1234, "process_path": r"C:\Windows\System32\curl.exe",
    })


def test_short_lived_event_is_queued_and_cursor_commits_only_after_ack(tmp_path):
    source = FakeEventSource()
    reader = WfpEventReader(tmp_path / "cursor.json", source)
    reader.poll()  # Establish the initial record ID, like service startup.
    initial = reader.next_batch()
    assert initial["events"] == []
    reader.acknowledge(initial)

    # Connection opens and closes completely between the periodic psutil snapshots.
    source.latest = 11
    source.records.append(connection_event())
    reader.poll()
    batch = reader.next_batch()
    assert batch["events"][0]["event_record_id"] == 11
    assert batch["events"][0]["process_id"] == 1234
    assert reader._acked_record_id == 10

    restarted = WfpEventReader(tmp_path / "cursor.json", source)
    assert restarted._acked_record_id == 10
    restarted.poll()
    assert restarted.next_batch()["events"][0]["event_record_id"] == 11
    restarted.acknowledge(batch)

    again = WfpEventReader(tmp_path / "cursor.json", source)
    assert again._acked_record_id == 11
    again.poll()
    status_batch = again.next_batch()
    assert status_batch["events"] == []
    again.acknowledge(status_batch)
    assert again.next_batch() is None


def test_security_log_rollover_changes_generation_and_reports_gap(tmp_path):
    source = FakeEventSource()
    reader = WfpEventReader(tmp_path / "cursor.json", source)
    reader.poll()
    reader.acknowledge(reader.next_batch())
    source.oldest = 30
    source.latest = 40
    source.records = [connection_event(35, 5157)]
    reader.poll()
    batch = reader.next_batch()
    assert batch["status"] == "GAP"
    assert batch["gap_reason"] == "SECURITY_LOG_ROLLOVER"
    assert batch["events"][0]["event_kind"] == "CONNECTION_BLOCKED"


def test_security_log_clearing_is_detected(tmp_path):
    source = FakeEventSource()
    reader = WfpEventReader(tmp_path / "cursor.json", source)
    reader.poll()
    reader.acknowledge(reader.next_batch())
    source.oldest = 1
    source.latest = 2
    reader._read_record_id = 10
    reader.poll()
    batch = reader.next_batch()
    assert batch["status"] == "GAP"
    assert batch["gap_reason"] == "SECURITY_LOG_CLEARED"


def test_high_volume_queue_stays_bounded_and_drains_in_acknowledged_batches(tmp_path):
    source = FakeEventSource()
    reader = WfpEventReader(tmp_path / "cursor.json", source)
    reader.poll()
    reader.acknowledge(reader.next_batch())
    source.latest = 6010
    source.records = [connection_event(record_id) for record_id in range(11, 6011)]
    for _ in range(10):
        reader.poll()
    assert reader.pending.qsize() == MAX_PENDING_EVENTS

    batches = 0
    while reader.pending.qsize() or reader._read_record_id < source.latest:
        reader.poll()
        batch = reader.next_batch()
        assert batch is not None and len(batch["events"]) <= 25
        reader.acknowledge(batch)
        batches += 1
    assert batches > 200
    assert reader.pending.empty()
    assert reader._acked_record_id == source.latest


def test_event_parser_preserves_ipv6_protocol_process_and_timestamp():
    xml = '''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System><Provider Name="Microsoft-Windows-Security-Auditing"/><EventID>5156</EventID>
      <TimeCreated SystemTime="2026-11-10T12:13:14.000Z"/><EventRecordID>42</EventRecordID></System>
      <EventData><Data Name="ProcessID">0x4d2</Data><Data Name="Application">\\device\\harddiskvolume1\\app.exe</Data>
      <Data Name="Direction">%%14593</Data><Data Name="SourceAddress">2001:4860:4860::8888</Data>
      <Data Name="SourcePort">50000</Data><Data Name="DestAddress">2001:db8::1</Data>
      <Data Name="DestPort">443</Data><Data Name="Protocol">6</Data></EventData></Event>'''
    record = parse_wfp_event(xml)
    assert record.payload["event_record_id"] == 42
    assert record.payload["source_ip"] == "2001:4860:4860::8888"
    assert record.payload["protocol"] == "TCP"
    assert record.payload["process_id"] == 1234
    assert record.payload["event_time"] == "2026-11-10T12:13:14+00:00"


def test_protocol_parser_identifies_udp_and_icmpv6():
    base = '''<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
      <System><EventID>5156</EventID><TimeCreated SystemTime="2026-11-10T12:13:14Z"/>
      <EventRecordID>43</EventRecordID></System><EventData>
      <Data Name="ProcessID">123</Data><Data Name="Direction">%%14593</Data>
      <Data Name="SourceAddress">2001:4860:4860::8888</Data><Data Name="SourcePort">-</Data>
      <Data Name="DestAddress">2001:db8::1</Data><Data Name="DestPort">-</Data>
      <Data Name="Protocol">{protocol}</Data></EventData></Event>'''
    udp = parse_wfp_event(base.format(protocol=17))
    icmpv6 = parse_wfp_event(base.format(protocol=58))
    assert udp.payload["protocol"] == "UDP"
    assert icmpv6.payload["protocol"] == "ICMP"
