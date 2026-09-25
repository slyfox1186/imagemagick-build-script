"""The command line and the TOML selection: pure, strict, and side-effect free."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from magick_builder import registry
from magick_builder.cli import parse_arguments
from magick_builder.config import (
    BuildSettings,
    Selection,
    default_states,
    load_config,
    render_config,
)
from magick_builder.main import Orchestrator, validate_request
from magick_builder.runtime.errors import UsageError
from magick_builder.runtime.logging import Logger
from magick_builder.usage import SCRIPT_VERSION, usage_text

from .conftest import REPO, invoke


def snapshot(directory: Path) -> set[Path]:
    return set(directory.rglob("*"))


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_is_pure(tmp_path: Path, flag: str) -> None:
    before = snapshot(tmp_path)
    completed = invoke(flag, "--config", "missing.toml", cwd=tmp_path)
    assert completed.returncode == 0
    assert completed.stdout == usage_text()
    assert snapshot(tmp_path) == before


def test_version_prints_exactly_the_version(tmp_path: Path) -> None:
    completed = invoke("--version", cwd=tmp_path)
    assert (completed.returncode, completed.stdout) == (0, f"{SCRIPT_VERSION}\n")
    assert not any(tmp_path.iterdir())


def test_no_action_prints_help_and_creates_nothing(tmp_path: Path) -> None:
    completed = invoke(cwd=tmp_path, environment={"BUILD_ROOT": str(tmp_path / "root")})
    assert completed.returncode == 0
    assert "Usage: build-magick.py" in completed.stdout
    assert not (tmp_path / "root").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--bogus"],
        ["--jobs"],
        ["--jobs", "0"],
        ["--jobs=-1"],
        ["--jobs="],
        ["-j", "abc"],
        ["--gcc-version", "8"],
        ["--gcc-version=15"],
        ["-g", "twelve"],
        ["--gcc-version"],
        ["--build", "--cleanup"],
        ["--config", "a.toml", "--config", "b.toml"],
        ["--", "stray"],
    ],
)
def test_invalid_command_lines_fail_without_side_effects(tmp_path: Path, argv: list[str]) -> None:
    completed = invoke(*argv, cwd=tmp_path, environment={"BUILD_ROOT": str(tmp_path / "root")})
    assert completed.returncode == 1, completed.stdout
    assert "[ERROR]" in completed.stdout
    assert not (tmp_path / "root").exists()


def test_valid_values_parse() -> None:
    arguments = parse_arguments(["-b", "--jobs=8", "-g", "13", "--latest", "-d"])
    assert (arguments.build, arguments.jobs, arguments.gcc_version) == (True, 8, 13)
    assert arguments.latest and arguments.debug


def test_missing_config_fails_before_any_work(tmp_path: Path) -> None:
    root = tmp_path / "root"
    completed = invoke(
        "--build", "--config", "nope.toml", cwd=tmp_path, environment={"BUILD_ROOT": str(root)}
    )
    assert completed.returncode == 1
    assert "Config file not found" in completed.stdout
    assert not root.exists()


def test_root_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("os.geteuid", lambda: 0)
    assert Orchestrator(REPO, ["--build"]).run() == 1


def test_example_config_matches_the_registry_and_enables_everything() -> None:
    text = (REPO / "example.toml").read_text(encoding="utf-8")
    assert text == render_config(BuildSettings(), default_states())
    assert set(tomllib.loads(text)["packages"]) == set(registry.PACKAGE_NAMES)
    loaded = load_config(REPO / "example.toml", Logger())
    assert loaded.selection.enabled_names() == list(registry.PACKAGE_NAMES)
    assert loaded.settings.latest is False


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "custom.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[bogus]\n", "Unsupported TOML table '[bogus]'"),
        ("[packages]\nnot-a-package = true\n", "Unsupported '[packages]' key"),
        ("[build]\ncompiler = true\n", "Unsupported '[build]' key"),
        ("[packages]\nlibpng = yes\n", "Unsupported config syntax"),
        ("[packages]\nlibpng = true\nlibpng = false\n", "Duplicate config key 'packages.libpng'"),
        ("[packages]\n[packages]\n", "Duplicate TOML table"),
        ("libpng = true\n", "must appear inside [build] or [packages]"),
        ("[packages]\nlibpng = [true]\n", "Unsupported config syntax"),
    ],
)
def test_config_rejects_invalid_input_with_its_location(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(UsageError) as raised:
        load_config(write(tmp_path, text), Logger())
    assert message in str(raised.value)
    assert "custom.toml:" in str(raised.value)


def test_config_is_an_allowlist(tmp_path: Path) -> None:
    loaded = load_config(
        write(tmp_path, "[build]\nlatest = true\n[packages]\nm4 = true\n"), Logger()
    )
    assert loaded.selection.enabled_names() == ["m4"]
    assert loaded.settings.latest
    assert Selection().enabled_names() == list(registry.PACKAGE_NAMES)


def test_impossible_selection_fails_up_front() -> None:
    selection = Selection({"raqm": True, "fribidi": True, "harfbuzz": True}, Path("x.toml"))
    with pytest.raises(UsageError) as raised:
        validate_request(selection)
    assert "'raqm = true' requires 'freetype = true'" in str(raised.value)
    assert "'harfbuzz = true' requires 'freetype = true'" in str(raised.value)


def test_invalid_download_setting_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOWNLOAD_MAX_TIME", "soon")
    with pytest.raises(UsageError, match="DOWNLOAD_MAX_TIME"):
        validate_request(Selection())
