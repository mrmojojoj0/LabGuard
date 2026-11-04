from __future__ import annotations

import platform
import socket
import time
from datetime import UTC, datetime

import psutil


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
                             "hostname": socket.gethostname()[:255]},
        "boot_time": datetime.fromtimestamp(boot_time, UTC).isoformat(),
        "uptime_seconds": max(0.0, now - boot_time),
        "network_interfaces": interfaces,
    }
