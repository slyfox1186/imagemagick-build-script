"""Release detection, GCC selection, APT safety, and the build environment."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.errors import BuildError
from magick_builder.stages.core_tools import libtool_version
from magick_builder.stages.system_setup import (
    SystemSetup,
    configure_environment,
    detect_release,
    required_packages,
    select_gcc_version,
)


def os_release(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "os-release"
    path.write_text(text)
    return path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('ID=debian\nVERSION_ID="12"\nVERSION_CODENAME=bookworm\n', ("Debian", "12", "bookworm")),
        ('ID=debian\nVERSION_ID="13"\n', ("Debian", "13", "trixie")),
        ('ID=ubuntu\nVERSION_ID="22.04"\nVERSION_CODENAME=jammy\n', ("Ubuntu", "22.04", "jammy")),
        ('ID=ubuntu\nVERSION_ID="24.04"\n', ("Ubuntu", "24.04", "noble")),
    ],
)
def test_supported_releases_are_detected(
    tmp_path: Path, text: str, expected: tuple[str, str, str]
) -> None:
    assert detect_release(os_release(tmp_path, text)) == expected


@pytest.mark.parametrize(
    "text",
    [
        'ID=fedora\nVERSION_ID="41"\n',
        'ID=ubuntu\nVERSION_ID="20.04"\n',
        'ID=ubuntu\nVERSION_ID="26.04"\n',
        'ID=debian\nVERSION_ID="11"\n',
        "ID=debian\nVERSION_CODENAME=forky\n",
    ],
)
def test_unsupported_hosts_fail_before_any_package_work(tmp_path: Path, text: str) -> None:
    with pytest.raises(BuildError, match="Unsupported"):
        detect_release(os_release(tmp_path, text))


@pytest.mark.parametrize(
    ("distribution", "version", "default", "allowed", "refused"),
    [
        ("Debian", "12", 12, 11, 13),
        ("Debian", "13", 14, 12, 11),
        ("Ubuntu", "22.04", 12, 9, 13),
        ("Ubuntu", "24.04", 14, 9, 8),
    ],
)
def test_gcc_ranges_and_defaults(
    distribution: str, version: str, default: int, allowed: int, refused: int
) -> None:
    assert select_gcc_version(distribution, version, None) == default
    assert select_gcc_version(distribution, version, allowed) == allowed
    with pytest.raises(BuildError, match="Available versions"):
        select_gcc_version(distribution, version, refused)


def test_package_lists_follow_the_release() -> None:
    jammy = required_packages("Ubuntu", "22.04", 12)
    assert "libjxl-dev" not in jammy and jammy[-2:] == ["gcc-12", "g++-12"]
    assert {"libgegl-0.4-0t64", "libcamd3", "libjxl-dev"} <= set(
        required_packages("Debian", "13", 14)
    )
    assert libtool_version("Ubuntu", "22.04") == "2.4.6"
    assert libtool_version("Debian", "13") == "2.4.7"


class RecordingRunner:
    """Answers dpkg-query and apt show from tables; records everything else."""

    def __init__(self, installed: set[str], unavailable: set[str]) -> None:
        self.installed = installed
        self.unavailable = unavailable
        self.executed: list[list[str]] = []

    def capture(self, arguments: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        package = arguments[-1]
        status = "install ok installed" if package in self.installed else ""
        return subprocess.CompletedProcess(list(arguments), 0 if status else 1, status, "")

    def probe(self, arguments: Sequence[str], **_: object) -> bool:
        return arguments[-1] not in self.unavailable


def setup_with(context: BuildContext, runner: RecordingRunner) -> SystemSetup:
    setup = SystemSetup(context)
    setup.runner = runner  # type: ignore[assignment]
    context.execute = lambda arguments, **_: runner.executed.append(list(arguments))  # type: ignore[method-assign]
    return setup


def test_unavailable_package_aborts_before_any_install(context: BuildContext) -> None:
    runner = RecordingRunner(installed=set(), unavailable={"libheif-dev"})
    setup = setup_with(context, runner)
    with pytest.raises(BuildError, match="unavailable.*libheif-dev"):
        setup.install_packages(["git", "libheif-dev"])
    assert all("install" not in command for command in runner.executed)


def test_install_refuses_removals_and_only_drops_the_legacy_allowlist(
    context: BuildContext,
) -> None:
    runner = RecordingRunner(installed={"git", "libjpeg62-dev"}, unavailable=set())
    setup = setup_with(context, runner)
    setup.install_packages(["git", "cmake"])
    commands = [" ".join(command) for command in runner.executed]
    assert any(command.endswith("remove -y libjpeg62-dev") for command in commands)
    assert commands[-1].endswith("install -y --no-remove cmake")
    assert all("purge" not in command for command in commands)


def test_nothing_installed_when_everything_is_present(context: BuildContext) -> None:
    runner = RecordingRunner(installed={"git"}, unavailable=set())
    setup_with(context, runner).install_packages(["git"])
    assert runner.executed == []


def test_build_environment_isolates_upstream_git_discovery(context: BuildContext) -> None:
    configure_environment(context)
    env = context.env
    assert env["GIT_CEILING_DIRECTORIES"] == str(context.cwd)
    assert env["PATH"].startswith(f"/usr/lib/ccache:{context.workspace}/bin:")
    assert env["CFLAGS"] == "-O3 -fPIC -pipe -march=native -fstack-protector-strong"
    assert env["LDFLAGS"].startswith(f"-L{context.workspace}/lib64 -L{context.workspace}/lib ")
    assert env["PKG_CONFIG_PATH"].startswith(f"{context.workspace}/lib64/pkgconfig:")
    assert env["PKG_CONFIG_LIBDIR"].endswith(":/lib/pkgconfig")
