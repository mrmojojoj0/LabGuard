import pytest

from labguard_client import process_control


class FakeProcess:
    def __init__(self, *, created_at=123.456789, name="worker.exe", running=True):
        self.created_at = created_at
        self.process_name = name
        self.running = running
        self.terminated = False
        self.killed = False

    def create_time(self):
        return self.created_at

    def name(self):
        return self.process_name

    def is_running(self):
        return self.running

    def terminate(self):
        self.terminated = True
        self.running = False

    def kill(self):
        self.killed = True
        self.running = False

    def wait(self, timeout=None):
        assert timeout == 2.0
        return 0


def test_termination_refuses_reused_pid_before_signaling(monkeypatch):
    process = FakeProcess(created_at=123.456790)
    monkeypatch.setattr(process_control.psutil, "Process", lambda _pid: process)

    result = process_control.terminate_process(
        4321, process_control._created_at_us(123.456789))

    assert result == "pid_reused"
    assert process.terminated is False
    assert process.killed is False


@pytest.mark.parametrize(("force", "expected", "attribute"), [
    (False, "terminated", "terminated"),
    (True, "killed", "killed"),
])
def test_termination_uses_exact_process_identity_and_requested_action(
        monkeypatch, force, expected, attribute):
    process = FakeProcess()
    monkeypatch.setattr(process_control.psutil, "Process", lambda _pid: process)

    result = process_control.terminate_process(
        4321, process_control._created_at_us(process.created_at), force=force)

    assert result == expected
    assert getattr(process, attribute) is True
    assert process.terminated is (not force)
    assert process.killed is force


def test_termination_refuses_protected_process_names(monkeypatch):
    process = FakeProcess(name="LSASS.EXE")
    monkeypatch.setattr(process_control.psutil, "Process", lambda _pid: process)

    result = process_control.terminate_process(
        4321, process_control._created_at_us(process.created_at))

    assert result == "protected_process"
    assert process.terminated is False
    assert process.killed is False
