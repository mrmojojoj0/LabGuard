from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import ctypes
from pathlib import Path
from uuid import UUID

MAX_IMAGE_BYTES = 4 * 1024 * 1024


def _python_executable() -> str:
    candidate = Path(sys.prefix) / "Scripts" / "python.exe" if os.name == "nt" else Path(sys.executable)
    return str(candidate if candidate.is_file() else Path(sys.executable))


def _capture_in_current_session(capture_id: UUID, timeout: int) -> bytes:
    output = Path(tempfile.gettempdir()) / f"LabGuard-{capture_id}.jpg"
    created = False
    try:
        try:
            result = subprocess.run([_python_executable(), "-m", "labguard_client.screenshot_helper", str(capture_id)],
                timeout=timeout, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("capture_timeout") from exc
        if result.returncode != 0:
            raise RuntimeError(_helper_error(result.returncode))
        created = True
        try:
            content = output.read_bytes()
        except OSError as exc:
            raise RuntimeError("screenshot_output_unavailable") from exc
        _validate_image(content)
        return content
    finally:
        if created:
            output.unlink(missing_ok=True)


def _validate_image(content: bytes) -> None:
    if len(content) < 4 or len(content) > MAX_IMAGE_BYTES:
        raise RuntimeError("image_size_invalid")
    if not content.startswith(b"\xff\xd8\xff") or not content.endswith(b"\xff\xd9"):
        raise RuntimeError("image_invalid")


def _helper_error(exit_code: int) -> str:
    return {10: "screenshot_dependency_missing", 11: "desktop_capture_failed",
            12: "screenshot_temp_conflict", 13: "screenshot_temp_unavailable"}.get(
                exit_code, f"screenshot_helper_error_{exit_code}")


def _win_error(exc: BaseException) -> str:
    code = getattr(exc, "winerror", None)
    if code == 1314:
        return "required_windows_privilege_missing"
    if code == 5:
        return "desktop_access_denied"
    if code in {2, 3}:
        return "python_runtime_unavailable"
    if isinstance(code, int) and 0 <= code <= 65535:
        return f"windows_error_{code}"
    return "windows_capture_setup_failed"


def _current_process_session_id() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_id_to_session_id = kernel32.ProcessIdToSessionId
    process_id_to_session_id.argtypes = (ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong))
    process_id_to_session_id.restype = ctypes.c_int
    session_id = ctypes.c_ulong()
    if not process_id_to_session_id(os.getpid(), ctypes.byref(session_id)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(session_id.value)


def capture_screenshot(capture_id: UUID, timeout: int = 20) -> bytes:
    if os.name != "nt":
        raise RuntimeError("unsupported_platform")
    try:
        import win32api
        import win32con
        import win32process
        import win32profile
        import win32security
    except ImportError as exc:
        raise RuntimeError("windows_capture_dependencies_missing") from exc

    current_session = _current_process_session_id()
    if current_session != 0:
        return _capture_in_current_session(capture_id, timeout)

    get_console_session = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId
    get_console_session.restype = ctypes.c_ulong
    session_id = get_console_session()
    if session_id == 0xFFFFFFFF:
        raise RuntimeError("no_active_session")
    system_token = None
    primary_token = None
    process_handle = thread_handle = None
    output = None
    output_created = False
    try:
        try:
            system_token = win32security.OpenProcessToken(win32api.GetCurrentProcess(),
                win32security.TOKEN_ALL_ACCESS)
            # pywin32 orders these as (token, impersonation level, desired
            # access, token type, token attributes), unlike the Win32 C API.
            primary_token = win32security.DuplicateTokenEx(system_token,
                win32security.SecurityImpersonation, win32con.MAXIMUM_ALLOWED,
                win32security.TokenPrimary, None)
            win32security.SetTokenInformation(primary_token, win32security.TokenSessionId, session_id)
            environment = win32profile.CreateEnvironmentBlock(primary_token, False)
        except Exception as exc:
            raise RuntimeError(_win_error(exc)) from exc
        temp_dir = environment.get("TEMP") or environment.get("TMP")
        if not temp_dir:
            raise RuntimeError("system_temp_unavailable")
        output = Path(temp_dir) / f"LabGuard-{capture_id}.jpg"
        python_executable = _python_executable()
        command = subprocess.list2cmdline([python_executable, "-m", "labguard_client.screenshot_helper", str(capture_id)])
        startup = win32process.STARTUPINFO()
        startup.dwFlags |= win32con.STARTF_USESHOWWINDOW
        startup.wShowWindow = win32con.SW_HIDE
        desktop = r"winsta0\default"
        startup.lpDesktop = desktop
        flags = win32con.CREATE_NO_WINDOW | getattr(win32con, "CREATE_UNICODE_ENVIRONMENT", 0)
        try:
            process_handle, thread_handle, _pid, _tid = win32process.CreateProcessAsUser(
                primary_token, python_executable, command, None, None, False, flags,
                environment, None, startup)
        except Exception as exc:
            raise RuntimeError(_win_error(exc)) from exc
        wait_result = win32event_wait(process_handle, int(timeout * 1000))
        if not wait_result:
            win32process.TerminateProcess(process_handle, 1)
            raise RuntimeError("capture_timeout")
        exit_code = win32process.GetExitCodeProcess(process_handle)
        if exit_code != 0:
            raise RuntimeError(_helper_error(exit_code))
        output_created = True
        try:
            content = output.read_bytes()
        except OSError as exc:
            raise RuntimeError("screenshot_output_unavailable") from exc
        _validate_image(content)
        return content
    finally:
        if output_created and output is not None:
            output.unlink(missing_ok=True)
        for handle in (thread_handle, process_handle, primary_token, system_token):
            if handle is not None:
                try:
                    handle.Close()
                except Exception:
                    pass


def win32event_wait(handle, timeout_ms: int) -> bool:
    import win32event
    return win32event.WaitForSingleObject(handle, timeout_ms) == win32event.WAIT_OBJECT_0
