from __future__ import annotations

import os
from pathlib import Path


class InstanceAlreadyRunning(RuntimeError):
    """Raised when another LabGuard process owns this device identity."""


class IdentityProcessLock:
    """Cross-session process lock stored beside the protected identity."""

    def __init__(self, path: Path):
        self.path = path
        self._handle = None

    @classmethod
    def for_state_file(cls, state_file: Path | None):
        return cls(state_file.with_name("agent.lock")) if state_file else None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._handle.seek(0)
                if self.path.stat().st_size == 0:
                    self._handle.write(b"0")
                    self._handle.flush()
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self._handle.close()
            self._handle = None
            raise InstanceAlreadyRunning("Another LabGuard agent process is already using this device identity") from exc

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_args) -> None:
        self.release()
