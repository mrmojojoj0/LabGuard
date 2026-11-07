"""Prepare a bounded, private-network-only Windows RDP access lease."""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from datetime import UTC, datetime, timedelta
from uuid import UUID

_TERMINAL_SERVICES = r"SYSTEM\CurrentControlSet\Control\Terminal Server"
_POLICY_TERMINAL_SERVICES = r"SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services"
_RDP_STATE_VALUE = "LabGuardTemporaryRdpState"
_F_DENY = "fDenyTSConnections"
_RULE_PREFIX = "LabGuard-RDP-"
_LEASE_MINUTES = 60
_CODE_RE = re.compile(r"^[a-z0-9_:-]{1,64}$")


class RdpAccessError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _netsh(system_root: str, args: list[str], run_process=subprocess.run) -> None:
    executable = os.path.join(system_root, "System32", "netsh.exe")
    try:
        result = run_process([executable, "advfirewall", "firewall", *args],
                             capture_output=True, text=True, timeout=15, shell=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RdpAccessError("rdp_firewall_unavailable") from exc
    if result.returncode != 0:
        raise RdpAccessError("rdp_firewall_configuration_failed")


def _read_value(registry, root, path, name):
    try:
        with registry.OpenKey(root, path, 0, registry.KEY_READ) as key:
            value, value_type = registry.QueryValueEx(key, name)
            return value, value_type
    except FileNotFoundError:
        return None, None


def _write_value(registry, root, path, name, value, value_type):
    with registry.CreateKeyEx(root, path, 0, registry.KEY_SET_VALUE) as key:
        registry.SetValueEx(key, name, 0, value_type, value)


def _delete_value(registry, root, path, name):
    try:
        with registry.OpenKey(root, path, 0, registry.KEY_SET_VALUE) as key:
            registry.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _load_winreg():
    try:
        import winreg
    except ImportError as exc:
        raise RdpAccessError("rdp_windows_only") from exc
    return winreg


def _read_marker(registry, winreg):
    value, _ = _read_value(winreg, winreg.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES, _RDP_STATE_VALUE)
    if value is None:
        return None
    try:
        marker = json.loads(value)
        if not isinstance(marker, dict) or marker.get("version") != 1:
            return None
        rules = marker.get("firewall_rules")
        if (not isinstance(rules, list) or len(rules) != 2
                or not all(isinstance(name, str) and re.fullmatch(
                    rf"{re.escape(_RULE_PREFIX)}[0-9a-f-]{{36}}-(Domain|Private)", name) for name in rules)
                or {name.rsplit("-", 1)[-1] for name in rules} != {"Domain", "Private"}):
            return None
        datetime.fromisoformat(marker["access_expires_at"].replace("Z", "+00:00"))
        return marker
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _remove_firewall_rules(marker, system_root, run_process):
    for name in marker.get("firewall_rules", []):
        if not isinstance(name, str) or not name.startswith(_RULE_PREFIX):
            continue
        _netsh(system_root, ["delete", "rule", f"name={name}"], run_process)


def cleanup_expired_rdp_access(*, registry_module=None, run_process=subprocess.run,
                               windows: bool | None = None, system_root: str | None = None,
                               now: datetime | None = None) -> bool:
    """Restore the machine setting and remove LabGuard's firewall rules at lease expiry."""
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return False
    registry = registry_module or _load_winreg()
    system_root = system_root or os.environ.get("SystemRoot", r"C:\Windows")
    marker = _read_marker(registry, registry)
    if marker is None:
        return False
    expires = datetime.fromisoformat(marker["access_expires_at"].replace("Z", "+00:00"))
    now = now or datetime.now(UTC)
    if expires > now.astimezone(UTC):
        return False
    original = marker.get("original_f_deny")
    if original is None:
        _delete_value(registry, registry.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES, _F_DENY)
    else:
        _write_value(registry, registry.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES,
                     _F_DENY, original["value"], original["type"])
    try:
        _remove_firewall_rules(marker, system_root, run_process)
    except RdpAccessError:
        # Keep the marker so the next service loop retries cleanup.
        return False
    _delete_value(registry, registry.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES, _RDP_STATE_VALUE)
    return True


def prepare_rdp_access(request_id: str, access_expires_at: str, *, registry_module=None,
                       run_process=subprocess.run, windows: bool | None = None,
                       system_root: str | None = None, now: datetime | None = None) -> dict:
    """Enable RDP for one bounded lease without changing NLA or public firewall profiles."""
    try:
        request_uuid = str(UUID(request_id))
        expiry = datetime.fromisoformat(access_expires_at.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, AttributeError):
        return {"status": "FAILED", "error_code": "invalid_rdp_request"}
    now = now or datetime.now(UTC)
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return {"status": "FAILED", "error_code": "rdp_windows_only"}
    if expiry <= now.astimezone(UTC) or expiry > now.astimezone(UTC) + timedelta(minutes=_LEASE_MINUTES + 2):
        return {"status": "FAILED", "error_code": "invalid_rdp_lease"}
    registry = registry_module or _load_winreg()
    system_root = system_root or os.environ.get("SystemRoot", r"C:\Windows")
    try:
        edition, _ = _read_value(registry, registry.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "EditionID")
        if isinstance(edition, str) and edition.casefold().startswith("core"):
            return {"status": "FAILED", "error_code": "rdp_host_unsupported_edition"}
        policy, _ = _read_value(registry, registry.HKEY_LOCAL_MACHINE,
                                _POLICY_TERMINAL_SERVICES, _F_DENY)
        if policy == 1:
            return {"status": "FAILED", "error_code": "rdp_disabled_by_policy"}

        marker = _read_marker(registry, registry)
        if marker is not None:
            old_expiry = datetime.fromisoformat(marker["access_expires_at"].replace("Z", "+00:00"))
            if old_expiry <= now.astimezone(UTC):
                cleanup_expired_rdp_access(registry_module=registry, run_process=run_process,
                                           windows=True, system_root=system_root, now=now)
                marker = None
        existing_lease = marker is not None
        if marker is None:
            current, current_type = _read_value(registry, registry.HKEY_LOCAL_MACHINE,
                                                _TERMINAL_SERVICES, _F_DENY)
            rules = [f"{_RULE_PREFIX}{request_uuid}-Domain", f"{_RULE_PREFIX}{request_uuid}-Private"]
            marker = {"version": 1, "request_id": request_uuid,
                      "access_expires_at": expiry.isoformat().replace("+00:00", "Z"),
                      "original_f_deny": None if current is None else {"value": current, "type": current_type},
                      "firewall_rules": rules}
        else:
            marker["request_id"] = request_uuid
            marker["access_expires_at"] = expiry.isoformat().replace("+00:00", "Z")
            rules = marker["firewall_rules"]

        # Save recovery information before the first machine-wide side effect.
        _write_value(registry, registry.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES,
                     _RDP_STATE_VALUE, json.dumps(marker, separators=(",", ":")), registry.REG_SZ)
        if not existing_lease and (marker["original_f_deny"] is None or marker["original_f_deny"]["value"] != 0):
            _write_value(registry, registry.HKEY_LOCAL_MACHINE, _TERMINAL_SERVICES,
                         _F_DENY, 0, registry.REG_DWORD)
        if not existing_lease:
            for name, profile in zip(rules, ("domain", "private")):
                _netsh(system_root, ["add", "rule", f"name={name}", "dir=in", "action=allow",
                                     "protocol=TCP", "localport=3389", f"profile={profile}",
                                     "remoteip=localsubnet"], run_process)
        return {"status": "READY", "error_code": None}
    except RdpAccessError as exc:
        return {"status": "FAILED", "error_code": exc.code if _CODE_RE.fullmatch(exc.code) else "rdp_prepare_failed"}
    except (OSError, ValueError, TypeError):
        return {"status": "FAILED", "error_code": "rdp_prepare_failed"}
