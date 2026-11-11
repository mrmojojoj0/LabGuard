from __future__ import annotations

from dataclasses import dataclass
import ctypes
import base64
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable
from urllib.parse import urlsplit
from uuid import uuid4
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
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Chocolatey source must be a configured HTTP or HTTPS URL")
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


def _execute_user_scope_in_active_session(offer: SoftwareJobOffer, *, progress=None,
                                          cancellation_event=None) -> PackageResult:
    """Run only a typed USER-scope WinGet job as the active console user."""
    if os.name != "nt":
        raise UnsupportedExecutionContext("active_user_session_unavailable")
    if offer.action != "UNINSTALL" or offer.package_manager != "WINGET" or offer.installation_scope != "USER":
        raise UnsupportedExecutionContext("unsupported_active_user_operation")
    job_handle = process_handle = thread_handle = primary_token = user_token = None
    process_resumed = False
    result_path: Path | None = None
    try:
        import win32con
        import win32event
        import win32job
        import win32process
        import win32profile
        import win32security
        import win32ts

        get_console_session = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId
        get_console_session.restype = ctypes.c_ulong
        session_id = int(get_console_session())
        if session_id == 0xFFFFFFFF or session_id == 0:
            raise UnsupportedExecutionContext("active_user_session_unavailable")
        user_token = win32ts.WTSQueryUserToken(session_id)
        primary_token = win32security.DuplicateTokenEx(
            user_token, win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED,
            win32security.TokenPrimary, None)
        environment = win32profile.CreateEnvironmentBlock(primary_token, False)
        temp_dir = environment.get("TEMP") or environment.get("TMP")
        if not temp_dir:
            raise UnsupportedExecutionContext("active_user_temp_unavailable")
        result_path = Path(temp_dir) / f"LabGuard-Software-{uuid4().hex}.json"
        offer_arg = base64.urlsafe_b64encode(
            json.dumps({"job_id": offer.job_id, "action": offer.action,
                        "package_id": offer.package_id, "package_manager": offer.package_manager,
                        "version": offer.version, "installation_scope": offer.installation_scope,
                        "source": offer.source, "source_url": offer.source_url,
                        "expires_at": offer.expires_at, "timeout_seconds": offer.timeout_seconds},
                       separators=(",", ":")).encode("utf-8")).decode("ascii")
        command = subprocess.list2cmdline([
            sys.executable, "-m", "labguard_client.software_user_helper", offer_arg, str(result_path),
        ])
        startup = win32process.STARTUPINFO()
        startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE
        startup.lpDesktop = r"winsta0\default"
        flags = win32con.CREATE_NO_WINDOW | win32con.CREATE_SUSPENDED | getattr(win32con, "CREATE_UNICODE_ENVIRONMENT", 0)
        process_handle, thread_handle, _pid, _tid = win32process.CreateProcessAsUser(
            primary_token, sys.executable, command, None, None, False, flags,
            environment, temp_dir, startup)
        job_handle = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job_handle, win32job.JobObjectExtendedLimitInformation, info)
        win32job.AssignProcessToJobObject(job_handle, process_handle)
        win32process.ResumeThread(thread_handle)
        process_resumed = True
        if progress:
            progress("Running approved uninstall in active user session")
        # Allow up to two bounded inventory scans (WinGet and Chocolatey each
        # have their own finite query timeout) in addition to the job timeout.
        deadline = time.monotonic() + offer.timeout_seconds + 120
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                win32process.TerminateProcess(process_handle, 1)
                win32event.WaitForSingleObject(process_handle, 5000)
                return PackageResult(1, "", cancelled=True)
            wait = win32event.WaitForSingleObject(process_handle, 250)
            if wait == win32event.WAIT_OBJECT_0:
                break
            if time.monotonic() >= deadline:
                win32process.TerminateProcess(process_handle, 1)
                win32event.WaitForSingleObject(process_handle, 5000)
                return PackageResult(1, "", timed_out=True)
        helper_exit_code = int(win32process.GetExitCodeProcess(process_handle))
        if helper_exit_code != 0:
            raise PackageManagerUnavailable(f"active_user_helper_exit_{helper_exit_code}")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            result = PackageResult(int(payload["returncode"]), sanitize_output(str(payload.get("output", ""))),
                                   bool(payload.get("timed_out")), bool(payload.get("cancelled")))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise PackageManagerUnavailable("active_user_result_unavailable") from exc
        return result
    except (PackageManagerUnavailable, UnsupportedExecutionContext):
        raise
    except Exception as exc:
        raise UnsupportedExecutionContext("active_user_session_unavailable") from exc
    finally:
        if result_path is not None:
            result_path.unlink(missing_ok=True)
        if process_handle is not None and not process_resumed:
            try:
                import win32process
                win32process.TerminateProcess(process_handle, 1)
            except Exception:
                pass
        for handle in (job_handle, thread_handle, process_handle, primary_token, user_token):
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass


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
        if service_context and local_system and offer.action == "UNINSTALL" and offer.package_manager == "WINGET":
            return _execute_user_scope_in_active_session(offer, progress=progress,
                                                         cancellation_event=cancellation_event)
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
