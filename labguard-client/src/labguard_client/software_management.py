from __future__ import annotations

from dataclasses import dataclass
import ctypes
from datetime import UTC, datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit
from labguard_client.winget_discovery import (
    WingetExecutableNotFound,
    discover_winget_executable,
)

PACKAGE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
PACKAGE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


class PackageManagerUnavailable(RuntimeError):
    pass


class UnsupportedExecutionContext(RuntimeError):
    pass


@dataclass(frozen=True)
class SoftwareJobOffer:
    job_id: str
    action: str
    package_id: str
    package_manager: str
    version: str | None
    installation_scope: str
    source: str
    source_url: str | None
    expires_at: str
    timeout_seconds: int

    @classmethod
    def parse(cls, payload: dict) -> "SoftwareJobOffer":
        required = {"job_id", "action", "package_id", "package_manager", "version",
                    "installation_scope", "source", "source_url", "expires_at", "timeout_seconds"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise ValueError("Invalid software job fields")
        try:
            from uuid import UUID
            UUID(payload["job_id"])
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid software job identifier") from exc
        if payload["action"] not in {"INSTALL", "UNINSTALL"}:
            raise ValueError("Unsupported software job action")
        if not isinstance(payload["package_id"], str) or not PACKAGE_ID.fullmatch(payload["package_id"]):
            raise ValueError("Invalid package identifier")
        manager = payload["package_manager"]
        source = payload["source"]
        source_url = payload["source_url"]
        if manager == "WINGET":
            if source != "WINGET_COMMUNITY" or source_url is not None:
                raise ValueError("Invalid WinGet source")
        elif manager == "CHOCO":
            if source != "CHOCO_CONFIGURED" or not isinstance(source_url, str):
                raise ValueError("Invalid Chocolatey source")
            parsed = urlsplit(source_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Chocolatey source must be a configured HTTPS URL")
        else:
            raise ValueError("Unsupported package manager")
        scope = payload["installation_scope"]
        if scope not in {"MACHINE", "USER"} or (manager == "CHOCO" and scope != "MACHINE"):
            raise ValueError("Unsupported installation scope")
        version = payload["version"]
        if version is not None and (not isinstance(version, str) or not PACKAGE_VERSION.fullmatch(version)):
            raise ValueError("Invalid package version")
        timeout = payload["timeout_seconds"]
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 60 <= timeout <= 7200:
            raise ValueError("Invalid software job timeout")
        if not isinstance(payload["expires_at"], str) or len(payload["expires_at"]) > 40:
            raise ValueError("Invalid software job expiration")
        try:
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Invalid software job expiration") from exc
        if expires.tzinfo is None:
            raise ValueError("Software job expiration must include a timezone")
        return cls(payload["job_id"], payload["action"], payload["package_id"], manager,
                   version, scope, source, source_url, payload["expires_at"], timeout)


@dataclass(frozen=True)
class PackageResult:
    returncode: int
    output: str
    timed_out: bool = False
    cancelled: bool = False


def running_as_local_system() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32api
        import win32con
        import win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        current_sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        system_sid = win32security.CreateWellKnownSid(win32security.WinLocalSystemSid, None)
        return (win32security.ConvertSidToStringSid(current_sid).casefold()
                == win32security.ConvertSidToStringSid(system_sid).casefold())
    except (ImportError, OSError, AttributeError):
        return False


def is_administrator() -> bool:
    if os.name != "nt":
        return False
    try:
        import win32api
        import win32con
        import win32security
        token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
        elevation = win32security.GetTokenInformation(token, win32security.TokenElevation)
        return bool(elevation)
    except (ImportError, OSError, AttributeError):
        # Fail closed when Windows cannot determine whether the current token is elevated.
        return False


def running_in_service_session() -> bool:
    """Session 0 has no interactive user's package registrations or profile."""
    if os.name != "nt":
        return False
    try:
        session_id = ctypes.c_ulong()
        kernel32 = ctypes.windll.kernel32
        if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session_id)):
            return True  # fail closed if Windows cannot determine the session
        return session_id.value == 0
    except (AttributeError, OSError):
        return True


def _discover(name: str, known_paths: list[Path], which: Callable[[str], str | None]) -> str:
    for path in known_paths:
        if path.is_file():
            return str(path)
    found = which(name)
    if found:
        resolved = Path(found).resolve(strict=False)
        if any(resolved == path.resolve(strict=False) for path in known_paths):
            return str(resolved)
    for path in known_paths:
        if path.is_file():
            return str(path)
    raise PackageManagerUnavailable(f"{name}_not_found")


def discover_winget(which: Callable[[str], str | None] = shutil.which,
                    environ: dict[str, str] | None = None) -> str:
    try:
        return discover_winget_executable(which=which, environ=environ)
    except WingetExecutableNotFound as exc:
        raise PackageManagerUnavailable("winget_not_found") from exc


def discover_chocolatey(which: Callable[[str], str | None] = shutil.which,
                        environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    program_data = env.get("ProgramData", r"C:\ProgramData")
    expected = Path(program_data) / "chocolatey" / "bin" / "choco.exe"
    candidates = [expected]
    return _discover("choco", candidates, which)


def build_command(offer: SoftwareJobOffer, executable: str) -> list[str]:
    if not PACKAGE_ID.fullmatch(offer.package_id):
        raise ValueError("Invalid package identifier")
    if offer.package_manager == "WINGET":
        command = [executable, "install" if offer.action == "INSTALL" else "uninstall",
                   "--id", offer.package_id, "--exact", "--source", "winget",
                   "--disable-interactivity", "--silent"]
        if offer.action == "INSTALL":
            command.extend(["--accept-source-agreements", "--accept-package-agreements"])
            command.extend(["--scope", "machine" if offer.installation_scope == "MACHINE" else "user"])
            if offer.version:
                command.extend(["--version", offer.version])
        else:
            command.extend(["--scope", "machine" if offer.installation_scope == "MACHINE" else "user"])
        return command
    if offer.package_manager == "CHOCO":
        if offer.installation_scope != "MACHINE" or offer.source_url is None:
            raise UnsupportedExecutionContext("Chocolatey supports machine scope only")
        if offer.action == "INSTALL":
            command = [executable, "install", offer.package_id, "--yes", "--no-progress",
                       "--limit-output", "--source", offer.source_url]
            if offer.version:
                command.extend(["--version", offer.version])
            return command
        return [executable, "uninstall", offer.package_id, "--yes", "--no-progress", "--limit-output"]
    raise ValueError("Unsupported package manager")


class WingetAdapter:
    discover = staticmethod(discover_winget)
    build_command = staticmethod(lambda offer, executable: build_command(offer, executable))


class ChocolateyAdapter:
    discover = staticmethod(discover_chocolatey)
    build_command = staticmethod(lambda offer, executable: build_command(offer, executable))


def sanitize_output(value: str, limit: int = 1000) -> str:
    value = re.sub(r"(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", value)
    value = re.sub(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@", r"\1[redacted]@", value)
    value = "".join(char for char in value if char in "\n\t" or 32 <= ord(char) < 127)
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return " | ".join(lines[-5:])[:limit]


def execute_package_job(offer: SoftwareJobOffer, *, which: Callable[[str], str | None] = shutil.which,
                        environ: dict[str, str] | None = None,
                        local_system: bool | None = None, administrator: bool | None = None,
                        service_context: bool | None = None,
                        popen=subprocess.Popen, progress: Callable[[str], None] | None = None,
                        cancellation_event=None) -> PackageResult:
    local_system = running_as_local_system() if local_system is None else local_system
    administrator = is_administrator() if administrator is None else administrator
    service_context = running_in_service_session() if service_context is None else service_context
    if offer.installation_scope == "USER" and (local_system or service_context):
        raise UnsupportedExecutionContext("user_scope_unavailable_in_service_session")
    if offer.installation_scope == "MACHINE":
        if not service_context:
            raise UnsupportedExecutionContext("privileged_service_unavailable")
        if not local_system:
            if not administrator:
                raise UnsupportedExecutionContext("machine_scope_requires_administrator")
            raise UnsupportedExecutionContext("privileged_service_unavailable")
    if offer.package_manager == "WINGET":
        env = os.environ if environ is None else environ
        executable = discover_winget(which=which, environ=env)
    elif offer.package_manager == "CHOCO":
        env = os.environ if environ is None else environ
        paths = [Path(env.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / "choco.exe"]
        executable = _discover("choco", paths, which)
    else:
        raise PackageManagerUnavailable("unsupported_package_manager")
    command = build_command(offer, executable)
    if progress:
        progress("Starting approved package manager")
    with tempfile.TemporaryFile() as output:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            proc = popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                         shell=False, creationflags=flags)
        except PermissionError as exc:
            code = "machine_scope_permission_denied" if offer.installation_scope == "MACHINE" else "user_scope_permission_denied"
            raise UnsupportedExecutionContext(code) from exc
        start = time.monotonic()
        last_progress = 0
        timed_out = False
        cancelled = False
        while proc.poll() is None:
            if cancellation_event is not None and cancellation_event.is_set():
                cancelled = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                break
            elapsed = time.monotonic() - start
            if elapsed >= offer.timeout_seconds:
                timed_out = True
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                break
            step = min(90, 10 + int(elapsed / max(1, offer.timeout_seconds) * 75))
            if progress and step > last_progress and elapsed >= 2:
                progress(f"Package manager running ({step}%)")
                last_progress = step
            time.sleep(0.25)
        returncode = proc.wait()
        output.seek(0, os.SEEK_END)
        size = output.tell()
        output.seek(max(0, size - 16 * 1024))
        text = output.read().decode("utf-8", "replace")
    return PackageResult(returncode, sanitize_output(text), timed_out, cancelled)
