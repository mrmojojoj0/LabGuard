from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Callable


class WingetExecutableNotFound(FileNotFoundError):
    pass


def winget_executable_candidates(environ: dict[str, str] | None = None) -> list[Path]:
    """Return the current account alias and machine App Installer locations."""
    env = os.environ if environ is None else environ
    candidates: list[Path] = []

    local_app_data = env.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe")

    program_roots = []
    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        value = env.get(key)
        if value and value not in program_roots:
            program_roots.append(value)
    for program_root in program_roots:
        windows_apps = Path(program_root) / "WindowsApps"
        try:
            candidates.extend(windows_apps.glob(
                "Microsoft.DesktopAppInstaller_*_8wekyb3d8bbwe/winget.exe"
            ))
        except OSError:
            # An inaccessible architecture-specific package directory should not
            # prevent checking the other configured WindowsApps roots.
            continue

    unique: dict[str, Path] = {}
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(candidate))
        unique.setdefault(key, candidate)
    return list(unique.values())


def discover_winget_executable(
    which: Callable[[str], str | None] = shutil.which,
    environ: dict[str, str] | None = None,
) -> str:
    """Find WinGet from known App Installer locations, independent of user PATH."""
    candidates = winget_executable_candidates(environ)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve(strict=False))

    # PATH can help locate an alias only when it resolves to one of the known
    # account or machine App Installer paths. Arbitrary executables are rejected.
    found = which("winget")
    if found:
        resolved = Path(found).resolve(strict=False)
        if any(resolved == candidate.resolve(strict=False) for candidate in candidates):
            return str(resolved)
    raise WingetExecutableNotFound("winget_not_found")
