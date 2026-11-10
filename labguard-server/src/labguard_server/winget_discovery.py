"""Read-only discovery of packages from the server's configured WinGet sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess


PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")
SOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_TIMEOUT_SECONDS = 60


class WingetDiscoveryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class WingetPackage:
    name: str
    package_id: str
    version: str | None
    source: str
    publisher: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WingetSource:
    name: str

    def as_dict(self) -> dict:
        return asdict(self)


def validate_source(source: str) -> str:
    value = source.strip()
    if not SOURCE_RE.fullmatch(value):
        raise WingetDiscoveryError("invalid_source", "WinGet source name is invalid")
    return value


def locate_winget() -> str | None:
    """Resolve the current server identity's WinGet alias or PATH executable."""
    found = shutil.which("winget.exe") or shutil.which("winget")
    if found:
        return found
    roots = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        roots.append(Path(local_app_data) / "Microsoft" / "WindowsApps" / "winget.exe")
    for program_files in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if program_files:
            packages = Path(program_files) / "WindowsApps"
            try:
                roots.extend(packages.glob("Microsoft.DesktopAppInstaller_*/winget.exe"))
            except OSError:
                continue
    for candidate in roots:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def _run(executable: str, args: list[str], *, allow_no_matches: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            [executable, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=_TIMEOUT_SECONDS, shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WingetDiscoveryError("winget_timeout", "WinGet did not respond before the discovery timeout") from exc
    except (OSError, PermissionError) as exc:
        raise WingetDiscoveryError("winget_execution_failed", "WinGet could not be started by the server process") from exc
    if result.returncode != 0:
        combined_output = f"{result.stdout}\n{result.stderr}"
        if allow_no_matches and re.search(r"\bno\s+(?:package|results?|matches)\b", combined_output, re.IGNORECASE):
            return subprocess.CompletedProcess(result.args, 0, stdout="No package found matching input criteria.", stderr="")
        raise WingetDiscoveryError("winget_command_failed", "WinGet reported a discovery command failure")
    return result


def get_winget_version() -> str:
    executable = locate_winget()
    if executable is None:
        raise WingetDiscoveryError("winget_unavailable", "WinGet is not available to the LabGuard server process")
    output = _run(executable, ["--version"]).stdout.strip()
    if not output or len(output) > 64:
        raise WingetDiscoveryError("winget_unusable_output", "WinGet returned an unusable version response")
    return output


def _table_columns(header: str, required: set[str] | None = None) -> list[tuple[str, int]] | None:
    matches = list(re.finditer(r"\S+", header))
    names = [match.group().casefold() for match in matches]
    required = required or {"name", "id", "version", "source"}
    if not required.issubset(names):
        return None
    if any(name not in {"name", "id", "version", "publisher", "match", "source", "argument", "explicit"} for name in names):
        return None
    return [(match.group(), match.start()) for match in matches]


def parse_search_output(output: str, source: str = "winget") -> list[WingetPackage]:
    """Parse WinGet's aligned text table; single-source searches omit the Source column."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        columns = _table_columns(line, {"name", "id", "version"})
        if columns is None or index + 1 >= len(lines):
            continue
        if not re.fullmatch(r"\s*-{3,}(?:\s+-{3,})*\s*", lines[index + 1]):
            continue
        starts = [position for _, position in columns]
        fields = [name.casefold() for name, _ in columns]
        packages = []
        for row in lines[index + 2:]:
            if not row.strip() or set(row.strip()) <= {"-", " "}:
                continue
            values = [row[start:starts[pos + 1] if pos + 1 < len(starts) else None].strip()
                      for pos, start in enumerate(starts)]
            value_by_field = dict(zip(fields, values))
            package_id = value_by_field.get("id", "")
            if not PACKAGE_ID_RE.fullmatch(package_id):
                continue
            name = value_by_field.get("name", "")
            package_source = value_by_field.get("source") or source
            if not name or not package_source:
                continue
            packages.append(WingetPackage(name=name, package_id=package_id,
                                          version=value_by_field.get("version") or None, source=package_source,
                                          publisher=value_by_field.get("publisher") or None))
        return packages
    if re.search(r"\bno\s+(?:package|installed package|results?|matches)\b", output, re.IGNORECASE):
        return []
    raise WingetDiscoveryError("winget_unusable_output", "WinGet search output did not contain a recognized package table")


def parse_source_output(output: str) -> list[WingetSource]:
    lines = output.splitlines()
    for index, header in enumerate(lines):
        columns = _table_columns(header, {"name", "argument"})
        if columns is None or "argument" not in [name.casefold() for name, _ in columns] or index + 1 >= len(lines):
            continue
        if not re.fullmatch(r"\s*-{3,}(?:\s+-{3,})*\s*", lines[index + 1]):
            continue
        starts = [position for _, position in columns]
        fields = [name.casefold() for name, _ in columns]
        sources = []
        for row in lines[index + 2:]:
            if not row.strip():
                continue
            values = [row[start:starts[pos + 1] if pos + 1 < len(starts) else None].strip()
                      for pos, start in enumerate(starts)]
            source_name = dict(zip(fields, values)).get("name", "")
            if SOURCE_RE.fullmatch(source_name):
                sources.append(WingetSource(source_name))
        return sources
    raise WingetDiscoveryError("winget_unusable_output", "WinGet source output did not contain a recognized source table")


def list_winget_sources() -> tuple[str, list[WingetSource]]:
    executable = locate_winget()
    if executable is None:
        raise WingetDiscoveryError("winget_unavailable", "WinGet is not available to the LabGuard server process")
    version_output = _run(executable, ["--version"]).stdout.strip()
    if not version_output or len(version_output) > 64:
        raise WingetDiscoveryError("winget_unusable_output", "WinGet returned an unusable version response")
    output = _run(executable, ["source", "list"]).stdout
    return version_output, parse_source_output(output)


def search_winget_packages(query: str, source: str = "winget") -> tuple[str, list[WingetPackage]]:
    normalized_source = validate_source(source)
    clean_query = query.strip()
    if not clean_query or len(clean_query) > 128:
        raise WingetDiscoveryError("invalid_query", "Search text must contain 1 to 128 characters")
    version = get_winget_version()
    executable = locate_winget()
    words = clean_query.split()
    candidates = [clean_query]
    if len(words) > 1:
        # Try common package-name spellings for every multiword query.
        for separator in ("::", "", ":", "-", "_"):
            candidate = separator.join(words)
            if candidate not in candidates and len(candidate) <= 128:
                candidates.append(candidate)

    first_search_error: WingetDiscoveryError | None = None
    successful_search = False
    matched: dict[str, WingetPackage] = {}
    for candidate in candidates:
        # Each query remains a single subprocess argument; input never becomes command text.
        try:
            output = _run(executable, ["search", candidate, "--source", normalized_source,
                                      "--count", "100", "--accept-source-agreements",
                                      "--disable-interactivity"], allow_no_matches=True).stdout
        except WingetDiscoveryError as exc:
            first_search_error = first_search_error or exc
            continue
        try:
            packages = parse_search_output(output, normalized_source)
        except WingetDiscoveryError as exc:
            first_search_error = first_search_error or exc
            continue
        successful_search = True
        for package in packages:
            matched.setdefault(package.package_id.casefold(), package)
            if len(matched) >= 100:
                break
        if len(matched) >= 100:
            break
    if (first_search_error is not None and not successful_search and not matched
            and first_search_error.code != "winget_command_failed"):
        raise first_search_error
    return version, list(matched.values())


def parse_show_output(output: str) -> dict[str, str | None]:
    """Extract the metadata fields WinGet prints as `Label: value` lines."""
    metadata: dict[str, str | None] = {"display_name": None, "package_id": None, "version": None,
                                       "publisher": None, "description": None}
    lines = output.splitlines()
    for index, line in enumerate(lines):
        name_match = re.match(r"^\s*Found\s+(.+?)\s+\[[^\]]+\]\s*$", line, re.IGNORECASE)
        if name_match and metadata["display_name"] is None:
            metadata["display_name"] = name_match.group(1).strip()
            metadata["package_id"] = re.search(r"\[([^\]]+)\]", line).group(1)
        match = re.match(r"^\s*(Version|Publisher|Description):\s*(.*)\s*$", line, re.IGNORECASE)
        if not match:
            continue
        field = match.group(1).casefold()
        value = match.group(2).strip()
        if field == "version" and value:
            metadata["version"] = value[:128]
        elif field == "description" and not value:
            description_lines = []
            for detail in lines[index + 1:]:
                if not detail.strip() or re.match(r"^\s*[A-Za-z][A-Za-z ]{1,30}:\s*", detail):
                    break
                description_lines.append(detail.strip())
            value = " ".join(description_lines)
        if value:
            metadata["publisher" if field == "publisher" else "description"] = value[:1000 if field == "description" else 256]
    return metadata


def get_winget_package_metadata(package_id: str, source: str = "winget",
                                version: str | None = None) -> dict[str, str | None]:
    if not PACKAGE_ID_RE.fullmatch(package_id):
        raise WingetDiscoveryError("invalid_package_id", "WinGet package identifier is invalid")
    normalized_source = validate_source(source)
    executable = locate_winget()
    if executable is None:
        raise WingetDiscoveryError("winget_unavailable", "WinGet is not available to the LabGuard server process")
    args = ["show", "--id", package_id, "--exact", "--source", normalized_source]
    if version is not None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version):
            raise WingetDiscoveryError("invalid_version", "WinGet package version is invalid")
        args.extend(["--version", version])
    args.extend(["--accept-source-agreements", "--disable-interactivity"])
    output = _run(executable, args).stdout
    metadata = parse_show_output(output)
    if metadata["display_name"] is None or metadata["package_id"] is None:
        raise WingetDiscoveryError("winget_unusable_output", "WinGet package details did not include a package name")
    if metadata["package_id"].casefold() != package_id.casefold():
        raise WingetDiscoveryError("package_identity_mismatch", "WinGet returned a different package identity")
    if version is not None and metadata["version"] is not None and metadata["version"] != version:
        raise WingetDiscoveryError("version_not_found", "WinGet returned a different package version")
    return metadata
