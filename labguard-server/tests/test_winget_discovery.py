import subprocess

import pytest

from labguard_server import winget_discovery as discovery


SEARCH_OUTPUT = "\n".join([
    f"{'Name':<32}{'Id':<30}{'Version':<11}{'Match':<10}Source",
    "-" * 89,
    f"{'Mozilla Firefox':<32}{'Mozilla.Firefox':<30}{'132.0':<11}{'Moniker':<10}winget",
    f"{'Visual Studio Code':<32}{'Microsoft.VisualStudioCode':<30}{'1.95.3':<11}{'':<10}winget",
])


def test_parse_search_output_handles_aligned_columns_and_missing_match():
    packages = discovery.parse_search_output(SEARCH_OUTPUT)
    single_source_output = "\n".join([
        f"{'Name':<32}{'Id':<30}Version",
        "-" * 69,
        f"{'Firefox':<32}{'Mozilla.Firefox':<30}132.0",
    ])
    single_source = discovery.parse_search_output(single_source_output, "winget")
    assert len(single_source) == 1
    assert single_source[0].source == "winget"
    assert [package.as_dict() for package in packages] == [
        {"name": "Mozilla Firefox", "package_id": "Mozilla.Firefox", "version": "132.0", "source": "winget", "publisher": None},
        {"name": "Visual Studio Code", "package_id": "Microsoft.VisualStudioCode", "version": "1.95.3", "source": "winget", "publisher": None},
    ]


def test_parse_search_output_recognizes_empty_results_and_rejects_unknown_format():
    assert discovery.parse_search_output("No package found matching input criteria.") == []
    with pytest.raises(discovery.WingetDiscoveryError) as error:
        discovery.parse_search_output("unexpected output")
    assert error.value.code == "winget_unusable_output"


def test_parse_show_output_extracts_metadata():
    output = """Found Visual Studio Code [Microsoft.VisualStudioCode]
Version: 1.95.3
Publisher: Microsoft Corporation
Description:
  Code editing. Redefined.
  Build and debug modern web and cloud applications.
Homepage: https://code.visualstudio.com/
"""
    assert discovery.parse_show_output(output) == {
        "package_id": "Microsoft.VisualStudioCode", "version": "1.95.3",
        "display_name": "Visual Studio Code", "publisher": "Microsoft Corporation",
        "description": "Code editing. Redefined. Build and debug modern web and cloud applications.",
    }


def test_exact_show_validates_package_id_and_selected_version(monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, "locate_winget", lambda: "C:/fake/winget.exe")

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0,
            stdout="Found Example Editor [Vendor.Editor]\nVersion: 2.4.1\nPublisher: Vendor\n", stderr="")

    monkeypatch.setattr(discovery.subprocess, "run", run)
    metadata = discovery.get_winget_package_metadata("Vendor.Editor", "winget", "2.4.1")
    assert metadata["package_id"] == "Vendor.Editor"
    assert metadata["version"] == "2.4.1"
    assert calls[0][1:] == ["show", "--id", "Vendor.Editor", "--exact", "--source", "winget",
                             "--version", "2.4.1", "--accept-source-agreements", "--disable-interactivity"]

    def mismatched(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout="Found Other App [Other.App]\nVersion: 2.4.1\n", stderr="")

    monkeypatch.setattr(discovery.subprocess, "run", mismatched)
    with pytest.raises(discovery.WingetDiscoveryError, match="different package identity"):
        discovery.get_winget_package_metadata("Vendor.Editor")


def test_parse_source_output_returns_names_without_exposing_source_addresses():
    output = """Name    Argument                                      Explicit
---------------------------------------------------------------
winget  https://cdn.winget.microsoft.com/cache       false
msstore https://storeedgefd.dsx.mp.microsoft.com/v9.0 false
"""
    assert [source.as_dict() for source in discovery.parse_source_output(output)] == [
        {"name": "winget"}, {"name": "msstore"},
    ]


def test_search_passes_arguments_separately_and_returns_version(monkeypatch):
    calls = []
    monkeypatch.setattr(discovery, "locate_winget", lambda: "C:/fake/winget.exe")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="v1.9.0\n", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout=SEARCH_OUTPUT, stderr="")

    monkeypatch.setattr(discovery.subprocess, "run", run)
    version, packages = discovery.search_winget_packages('VLC" & whoami')
    assert version == "v1.9.0"
    assert len(packages) == 2
    assert calls[1][0][1:] == ["search", 'VLC" & whoami', "--source", "winget",
                               "--count", "100", "--accept-source-agreements", "--disable-interactivity"]
    assert calls[1][1]["shell"] is False


def test_search_reports_timeout_and_invalid_source(monkeypatch):
    monkeypatch.setattr(discovery, "locate_winget", lambda: "winget.exe")

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("winget", 60)

    monkeypatch.setattr(discovery.subprocess, "run", timeout)
    with pytest.raises(discovery.WingetDiscoveryError) as error:
        discovery.get_winget_version()
    assert error.value.code == "winget_timeout"
    with pytest.raises(discovery.WingetDiscoveryError) as error:
        discovery.search_winget_packages("editor", "bad source")
    assert error.value.code == "invalid_source"


def test_locate_winget_checks_windows_app_execution_alias(monkeypatch, tmp_path):
    alias = tmp_path / "Microsoft" / "WindowsApps" / "winget.exe"
    alias.parent.mkdir(parents=True)
    alias.touch()
    monkeypatch.setattr(discovery.shutil, "which", lambda _name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert discovery.locate_winget() == str(alias)
