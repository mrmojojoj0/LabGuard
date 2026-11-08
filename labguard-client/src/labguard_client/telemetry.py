from __future__ import annotations

import platform
import socket
import subprocess
import time
from datetime import UTC, datetime

import psutil


def agent_account_name() -> str | None:
    """Return the account running the endpoint agent using the fixed whoami command."""
    if platform.system() != "Windows":
        return None
    try:
        result = subprocess.run(
            ["whoami"], capture_output=True, text=True, timeout=5,
            check=True, shell=False,
        )
        value = result.stdout.strip()
        if not value or len(value) > 256 or any(ord(char) < 32 or ord(char) == 127 for char in value):
            return None
        return value
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def _windows_edition() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            return str(winreg.QueryValueEx(key, "ProductName")[0])[:128]
    except (OSError, ImportError):
        return None


def _processor_name() -> str | None:
    name = platform.processor().strip()
    if name:
        return name[:256]
    if platform.system() == "Windows":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()[:256] or None
        except (OSError, ImportError):
            return None
    return None


def active_windows_username() -> str | None:
    """Return the active console account as DOMAIN\\user, including in Session 0."""
    if platform.system() != "Windows":
        return None
    try:
        import ctypes

        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WTSGetActiveConsoleSessionId.restype = ctypes.c_ulong
        session_id = int(kernel32.WTSGetActiveConsoleSessionId())
        if session_id == 0xFFFFFFFF:
            return None
        values: dict[int, str] = {}
        for info_class in (5, 7):  # WTSUserName, WTSDomainName
            buffer = ctypes.c_void_p()
            byte_count = ctypes.c_ulong()
            if not wts.WTSQuerySessionInformationW(
                    None, session_id, info_class, ctypes.byref(buffer), ctypes.byref(byte_count)):
                return None
            try:
                values[info_class] = ctypes.wstring_at(buffer.value) if buffer.value else ""
            finally:
                wts.WTSFreeMemory(buffer)
        username = values.get(5, "").strip()
        domain = values.get(7, "").strip()
        if (not username or len(username) > 128 or len(domain) > 128
                or any(ord(char) < 32 or ord(char) == 127 for char in username + domain)):
            return None
        if not domain or domain == ".":
            domain = socket.gethostname()
        qualified = f"{domain}\\{username}"
        return qualified[:256] if len(qualified) <= 256 else None
    except (AttributeError, OSError, ValueError, TypeError):
        return None


def collect_system_telemetry() -> dict:
    """Collect bounded host metrics and metadata; does not inspect user files."""
    cpu_percent = float(psutil.cpu_percent(interval=0.1))
    memory = psutil.virtual_memory()
    boot_time = float(psutil.boot_time())

    partitions = []
    try:
        for part in psutil.disk_partitions(all=False)[:64]:
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except (OSError, psutil.Error):
                continue
            partitions.append({
                "device": part.device[:256], "mountpoint": part.mountpoint[:1024],
                "filesystem": (part.fstype or "")[:64] or None, "total_bytes": int(usage.total),
                "used_bytes": int(usage.used), "free_bytes": int(usage.free),
                "utilization_percent": float(usage.percent),
            })
    except (OSError, psutil.Error):
        pass

    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except (OSError, psutil.Error):
        addresses, stats = {}, {}
    interfaces = []
    link_family = getattr(psutil, "AF_LINK", getattr(socket, "AF_PACKET", -1))
    for name, entries in list(addresses.items())[:64]:
        state = stats.get(name)
        ipv4, ipv6, mac = [], [], None
        for address in entries:
            if address.family == socket.AF_INET and len(ipv4) < 32:
                ipv4.append(address.address.split("%", 1)[0])
            elif address.family == socket.AF_INET6 and len(ipv6) < 32:
                ipv6.append(address.address.split("%", 1)[0])
            elif address.family == link_family and address.address:
                mac = address.address[:32]
        interfaces.append({
            "name": str(name)[:128], "status": "UP" if state and state.isup else "DOWN" if state else "UNKNOWN",
            "mac_address": mac, "ipv4_addresses": ipv4, "ipv6_addresses": ipv6,
            "speed_mbps": float(state.speed) if state and state.speed > 0 else None,
        })

    try:
        windows = platform.win32_ver()
        windows_version = windows[1] or platform.version()
        build = str(__import__("sys").getwindowsversion().build) if platform.system() == "Windows" else platform.version()
    except (AttributeError, OSError):
        windows_version, build = platform.version(), None
    logical = psutil.cpu_count(logical=True) or 1
    physical = psutil.cpu_count(logical=False)
    now = time.time()
    return {
        "collected_at": datetime.now(UTC).isoformat(),
        "cpu": {"processor_name": _processor_name(), "logical_processors": int(logical),
                "physical_cores": int(physical) if physical else None, "utilization_percent": cpu_percent},
        "memory": {"total_bytes": int(memory.total), "used_bytes": int(memory.used),
                   "available_bytes": int(memory.available), "utilization_percent": float(memory.percent)},
        "storage_partitions": partitions,
        "operating_system": {"edition": _windows_edition(), "version": windows_version or None,
                             "build_number": build or None, "architecture": platform.machine() or "unknown",
                             "hostname": socket.gethostname()[:255],
                             "username": active_windows_username(),
                             "agent_account": agent_account_name()},
        "boot_time": datetime.fromtimestamp(boot_time, UTC).isoformat(),
        "uptime_seconds": max(0.0, now - boot_time),
        "network_interfaces": interfaces,
    }
