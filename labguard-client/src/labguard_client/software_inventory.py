from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import getpass
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import getpass
from typing import Any
from labguard_client.winget_discovery import (
    WingetExecutableNotFound,
    discover_winget_executable,
)

REGISTRY_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
MAX_ENTRIES = 10_000
MAX_ERRORS = 20
MAX_BATCH_BYTES = 48 * 1024


@dataclass
class SoftwareInventory:
    entries: list[dict[str, str | None]]
    errors: list[str]
    detected_package_managers: list[str]

    @property
    def complete(self) -> bool:
        return not self.errors


def inventory_digest(entries: list[dict[str, Any]]) -> str:
    canonical = json.dumps(sorted(entries, key=lambda item: item["entry_key"]),
                           sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _execution_context() -> tuple[str, str]:
    try:
        account = getpass.getuser()[:128]
    except (OSError, KeyError):
        account = "unknown"
    session = "unknown"
    if os.name == "nt":
        try:
            import ctypes
            value = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(value))
            if ok:
                session = str(value.value)
        except (AttributeError, OSError):
            pass
    return account, session


def _clean(value: Any, limit: int) -> str | None:
    if not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text[:limit] or None


def _normalize_architecture(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    normalized = value.strip().casefold().replace("_", "-")
    if normalized in {"x86", "32", "32-bit", "win32", "i386", "i686"}:
        return "x86"
    if normalized in {"x64", "amd64", "64", "64-bit", "x86-64"}:
        return "x64"
    if normalized in {"arm64", "aarch64"}:
        return "ARM64"
    return value.strip()[:32] or "UNKNOWN"


def _make_entry(*, name: str, version: str | None, publisher: str | None,
                architecture: str | None, install_date: str | None,
                install_location: str | None, package_id: str | None,
                source: str, scope: str) -> dict[str, str | None]:
    name = name.strip()[:256]
    architecture = _normalize_architecture(architecture)
    normalized = "\x1f".join((source, scope, (package_id or name).casefold(),
                             (publisher or "").casefold(), (architecture or "UNKNOWN").casefold(),
                             (install_location or "").casefold()))
    return {
        "entry_key": hashlib.sha256(normalized.encode("utf-8", "replace")).hexdigest(),
        "name": name,
        "version": _clean(version, 128),
        "publisher": _clean(publisher, 256),
        "architecture": _clean(architecture, 32) or "UNKNOWN",
        "install_date": install_date,
        "install_location": _clean(install_location, 1024),
        "package_id": _clean(package_id, 256),
        "source": source,
        "installation_scope": scope,
    }


def _registry_entries(winreg, errors: list[str]) -> list[dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    is_64_bit = platform.machine().lower() in {"amd64", "x86_64", "arm64", "aarch64"}
    read = winreg.KEY_READ
    views = [getattr(winreg, "KEY_WOW64_64KEY", 0),
             getattr(winreg, "KEY_WOW64_32KEY", 0)] if is_64_bit else [0]
    roots: list[tuple[Any, str, str]] = [
        (winreg.HKEY_LOCAL_MACHINE, REGISTRY_PATH, "MACHINE"),
        (winreg.HKEY_CURRENT_USER, REGISTRY_PATH, "USER"),
    ]
    # LocalSystem's HKCU is its own profile. Include only loaded ordinary user hives.
    try:
        with winreg.OpenKey(winreg.HKEY_USERS, "") as users:
            index = 0
            while index < 4096:
                try:
                    sid = winreg.EnumKey(users, index)
                except OSError:
                    break
                index += 1
                if re.fullmatch(r"S-1-5-21-(?:\d+-){2,}\d+", sid):
                    roots.append((winreg.HKEY_USERS, sid + "\\" + REGISTRY_PATH, "USER"))
    except OSError as exc:
        if getattr(exc, "winerror", None) == 5:
            errors.append("registry_access_denied:loaded_user_hives")

    for root, path, scope in roots:
        for view in views:
            try:
                with winreg.OpenKey(root, path, 0, read | view) as uninstall:
                    index = 0
                    while index < MAX_ENTRIES:
                        try:
                            subkey = winreg.EnumKey(uninstall, index)
                        except OSError:
                            break
                        index += 1
                        try:
                            with winreg.OpenKey(uninstall, subkey, 0, read) as app:
                                def value(name: str):
                                    try:
                                        return winreg.QueryValueEx(app, name)[0]
                                    except OSError as exc:
                                        if getattr(exc, "winerror", None) == 5:
                                            errors.append("registry_value_access_denied")
                                        return None

                                display_name = _clean(value("DisplayName"), 256)
                                if not display_name or value("SystemComponent") == 1:
                                    continue
                                raw_date = _clean(value("InstallDate"), 16)
                                install_date = None
                                if raw_date and re.fullmatch(r"\d{8}", raw_date):
                                    try:
                                        install_date = datetime.strptime(raw_date, "%Y%m%d").date().isoformat()
                                    except ValueError:
                                        pass
                                item = _make_entry(
                                    name=display_name, version=_clean(value("DisplayVersion"), 128),
                                    publisher=_clean(value("Publisher"), 256),
                                    architecture=_normalize_architecture(_clean(value("Architecture"), 32)),
                                    install_date=install_date, install_location=_clean(value("InstallLocation"), 1024),
                                    package_id=_clean(value("PackageId") or value("ProductId"), 256),
                                    source="WINDOWS_REGISTRY", scope=scope,
                                )
                                result[item["entry_key"]] = item
                        except OSError as exc:
                            if getattr(exc, "winerror", None) == 5:
                                errors.append("registry_entry_access_denied")
            except OSError as exc:
                if getattr(exc, "winerror", None) == 5:
                    errors.append("registry_access_denied:uninstall_key")
    return list(result.values())


def _run_fixed_command(command: list[str], timeout: float = 20.0) -> str:
    kwargs: dict[str, Any] = {"capture_output": True, "text": True, "timeout": timeout,
                              "check": False, "shell": False, "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    completed = subprocess.run(command, **kwargs)
    if completed.returncode != 0:
        diagnostic = f"{completed.stdout or ''}\n{completed.stderr or ''}".casefold()
        if "access is denied" in diagnostic or "0x80070005" in diagnostic:
            reason = "access_denied"
        elif any(marker in diagnostic for marker in ("app installer", "package registration", "0x80073d")):
            reason = "package_registration"
        else:
            reason = "command_failed"
        raise RuntimeError(f"{reason}:{completed.returncode}")
    return completed.stdout[:2_000_000]


def _winget_entries(which, run, errors, environ=None):
    env = os.environ if environ is None else environ
    try:
        executable = discover_winget_executable(which=which, environ=env)
    except WingetExecutableNotFound:
        logger = logging.getLogger("labguard_client")
        account, session = _execution_context()
        logger.warning("WinGet inventory discovery failed reason=executable_not_found account=%s session=%s local_app_data_present=%s path_entries=%d",
                       account, session, bool(env.get("LOCALAPPDATA")), len(env.get("PATH", "").split(os.pathsep)))
        errors.append("winget_executable_not_found")
        return [], False
    try:
        # WinGet currently permits list --count values only up to 1000.
        output = run([executable, "list", "--disable-interactivity", "--accept-source-agreements", "--count", "1000"])
        lines = output.splitlines()
        header_index = next((i for i, line in enumerate(lines) if re.search(r"\bID\b", line, re.I)
                             and re.search(r"\bVersion\b", line, re.I)), None)
        if header_index is None:
            raise ValueError("winget_table_unavailable")
        header = lines[header_index]
        id_start = re.search(r"\bID\b", header, re.I).start()
        version_match = re.search(r"\bVersion\b", header, re.I)
        later = [match.start() for label in ("Available", "Source")
                 if (match := re.search(rf"\b{label}\b", header, re.I)) and match.start() > version_match.start()]
        version_end = min(later) if later else len(header)
        entries = []
        for line in lines[header_index + 1:]:
            if not line.strip() or set(line.strip()) == {"-"}:
                continue
            package_id = line[id_start:version_match.start()].strip().split()[0:1]
            version = line[version_match.start():version_end].strip().split()[0:1]
            name = line[:id_start].strip()
            if not name or not package_id:
                continue
            entries.append(_make_entry(name=name, version=version[0] if version else None, publisher=None,
                architecture="UNKNOWN", install_date=None, install_location=None, package_id=package_id[0],
                source="WINGET", scope="UNKNOWN"))
        return entries[:2000], True
    except subprocess.TimeoutExpired:
        category = "timeout"
    except subprocess.SubprocessError as exc:
        category = f"process_error:{type(exc).__name__}"
    except PermissionError as exc:
        category = f"access_denied:{getattr(exc, 'winerror', None) or 'unknown'}"
    except FileNotFoundError:
        category = "executable_not_found"
    except RuntimeError as exc:
        category = str(exc).split(":", 1)[0]
    except ValueError as exc:
        category = str(exc)
    except OSError as exc:
        category = f"process_error:{getattr(exc, 'winerror', None) or type(exc).__name__}"
    else:
        return entries[:2000], True
    account, session = _execution_context()
    logging.getLogger("labguard_client").warning(
        "WinGet inventory query failed reason=%s account=%s session=%s executable_found=true local_app_data_present=%s",
        category[:64], account, session, bool(os.environ.get("LOCALAPPDATA")))
    if category.startswith("access_denied"):
        errors.append("winget_access_denied")
    elif category == "timeout":
        errors.append("winget_timeout")
    elif category == "package_registration":
        errors.append("winget_package_registration_unavailable")
    elif category == "executable_not_found":
        errors.append("winget_executable_not_found")
    elif category.startswith("command_failed"):
        errors.append("winget_command_failed")
    elif category.startswith("process_error"):
        errors.append("winget_process_error")
    else:
        errors.append("winget_query_unavailable")
    return [], True


def _chocolatey_entries(which, run, errors):
    executable = which("choco")
    if not executable:
        return [], False
    try:
        # Chocolatey v2 lists local packages; --local-only keeps v1 from querying sources.
        output = run([executable, "list", "--limit-output", "--local-only", "--no-progress"])
        entries = []
        for line in output.splitlines():
            if "|" not in line:
                continue
            package_id, version = line.split("|", 1)
            package_id, version = package_id.strip(), version.strip()
            if not package_id or not version or len(package_id) > 256 or len(version) > 128:
                continue
            entries.append(_make_entry(name=package_id, version=version, publisher=None, architecture="UNKNOWN",
                install_date=None, install_location=None, package_id=package_id, source="CHOCO", scope="MACHINE"))
        return entries[:2000], True
    except subprocess.TimeoutExpired:
        errors.append("chocolatey_timeout")
        logging.getLogger("labguard_client").warning("Chocolatey inventory query failed reason=timeout")
        return [], True
    except subprocess.SubprocessError as exc:
        errors.append("chocolatey_command_failed")
        logging.getLogger("labguard_client").warning("Chocolatey inventory query failed reason=%s", type(exc).__name__)
        return [], True
    except PermissionError as exc:
        errors.append("chocolatey_access_denied")
        logging.getLogger("labguard_client").warning("Chocolatey inventory query failed reason=access_denied winerror=%s", getattr(exc, "winerror", None))
        return [], True
    except (OSError, RuntimeError) as exc:
        errors.append("chocolatey_command_failed")
        logging.getLogger("labguard_client").warning("Chocolatey inventory query failed reason=%s", type(exc).__name__)
        return [], True


def collect_software_inventory(*, winreg_module=None, which=shutil.which, run=_run_fixed_command,
                               windows: bool | None = None) -> SoftwareInventory:
    """Read Windows uninstall metadata and optional local package-manager listings only."""
    errors: list[str] = []
    detected: list[str] = []
    if windows is None:
        windows = platform.system() == "Windows"
    entries: list[dict[str, str | None]] = []
    if windows:
        if winreg_module is None:
            try:
                import winreg as winreg_module
            except ImportError:
                errors.append("registry_unavailable")
        if winreg_module is not None:
            entries.extend(_registry_entries(winreg_module, errors))
        winget, has_winget = _winget_entries(which, run, errors)
        choco, has_choco = _chocolatey_entries(which, run, errors)
        if has_winget:
            detected.append("WINGET")
        if has_choco:
            detected.append("CHOCO")
        entries.extend(winget)
        entries.extend(choco)
    else:
        errors.append("windows_software_inventory_unavailable")
    unique = {item["entry_key"]: item for item in entries}
    if len(unique) > MAX_ENTRIES:
        errors.append("inventory_entry_limit_exceeded")
    bounded = list(unique.values())[:MAX_ENTRIES]
    if len(errors) > MAX_ERRORS:
        errors = errors[:MAX_ERRORS]
    logging.getLogger("labguard_client").info(
        "Software inventory collected entries=%d errors=%d managers=%s",
        len(bounded), len(errors), ",".join(detected) or "none")
    return SoftwareInventory(bounded, errors, detected)


def batch_entries(entries: list[dict[str, str | None]], payload_base: dict[str, Any],
                  max_bytes: int = MAX_BATCH_BYTES) -> list[list[dict[str, str | None]]]:
    """Partition inventory into protocol-safe batches, including payload metadata overhead."""
    batches: list[list[dict[str, str | None]]] = []
    current: list[dict[str, str | None]] = []
    for entry in entries:
        candidate = current + [entry]
        payload = {**payload_base, "batch_index": 255, "batch_count": 256, "entries": candidate}
        if current and (len(candidate) > 100 or len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > max_bytes):
            batches.append(current)
            current = [entry]
        else:
            current = candidate
        if len(json.dumps({**payload_base, "batch_index": 255, "batch_count": 256,
                           "entries": current}, separators=(",", ":")).encode("utf-8")) > max_bytes:
            raise ValueError("A software inventory entry exceeds the safe batch size")
    if current or not batches:
        batches.append(current)
    if len(batches) > 256:
        raise ValueError("Software inventory exceeds the supported batch count")
    return batches
