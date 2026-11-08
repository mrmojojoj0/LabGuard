"""Bounded process inventory and identity-checked termination operations."""
from __future__ import annotations

import os
import math
import time

import psutil

MAX_PROCESSES = 1000
_PROTECTED_PIDS = {0, 4}
_PROTECTED_NAMES = {"system", "registry", "smss.exe", "csrss.exe", "wininit.exe",
                    "winlogon.exe", "services.exe", "lsass.exe"}


def _created_at_us(created_at: float) -> int:
    return int(round(created_at * 1_000_000))


def list_processes(*, limit: int = MAX_PROCESSES) -> list[dict]:
    """Return bounded process details; inaccessible optional fields are null."""
    limit = max(1, min(int(limit), MAX_PROCESSES + 1))
    processes = []
    handles = []
    for process in psutil.process_iter(
            attrs=["pid", "name", "username", "exe", "create_time", "memory_info"],
            ad_value=None):
        try:
            with process.oneshot():
                info = process.info
                created_at = info.get("create_time")
                memory = info.get("memory_info")
                try:
                    process.cpu_percent(interval=None)
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
                processes.append({
                    "pid": int(info["pid"]),
                    "name": str(info.get("name") or "(unknown)")[:256],
                    "username": str(info["username"])[:256] if info.get("username") else None,
                    "executable_path": str(info["exe"])[:1024] if info.get("exe") else None,
                    "cpu_percent": None,
                    "memory_bytes": int(memory.rss) if memory is not None else None,
                    "created_at_us": _created_at_us(float(created_at)) if created_at is not None else None,
                })
                handles.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError, ValueError):
            continue
        if len(processes) >= limit:
            break
    time.sleep(0.1)
    for process, item in zip(handles, processes):
        try:
            cpu_percent = float(process.cpu_percent(interval=None))
            if math.isfinite(cpu_percent):
                item["cpu_percent"] = max(0.0, min(cpu_percent, 10000.0))
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess, OSError, ValueError):
            continue
    return sorted(processes, key=lambda item: (item["pid"], item["created_at_us"] or 0))


def terminate_process(pid: int, created_at_us: int, *, force: bool = False,
                      wait_seconds: float = 2.0) -> str:
    """Terminate only the process instance identified by PID and creation time."""
    if (not isinstance(pid, int) or isinstance(pid, bool) or pid in _PROTECTED_PIDS
            or pid == os.getpid() or not isinstance(created_at_us, int)
            or isinstance(created_at_us, bool) or created_at_us <= 0):
        return "invalid_process_identity"
    try:
        process = psutil.Process(pid)
        actual_created_at = _created_at_us(process.create_time())
        if actual_created_at != created_at_us:
            return "pid_reused"
        if process.name().casefold() in _PROTECTED_NAMES:
            return "protected_process"
        if not process.is_running():
            return "process_not_found"
        # psutil checks its cached creation time before signaling, protecting against PID reuse.
        if force:
            process.kill()
            process.wait(timeout=wait_seconds)
            return "killed"
        process.terminate()
        try:
            process.wait(timeout=wait_seconds)
        except psutil.TimeoutExpired:
            return "terminate_timeout"
        return "terminated"
    except psutil.NoSuchProcess:
        return "process_not_found"
    except psutil.AccessDenied:
        return "access_denied"
    except psutil.TimeoutExpired:
        return "terminate_timeout" if not force else "kill_timeout"
    except (OSError, ValueError):
        return "operation_failed"
