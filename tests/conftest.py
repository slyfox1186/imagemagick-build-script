"""Isolated build roots; fixtures never install software, use sudo, or reach the network."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from magick_builder.cli import Arguments
from magick_builder.config import BuildSettings, Selection
from magick_builder.main import Orchestrator
from magick_builder.runtime.context import BuildContext

REPO = Path(__file__).resolve().parents[1]
COMMIT = "a" * 40


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in tuple(os.environ):
        if name.startswith(("DOWNLOAD_", "GIT_")) or name in (
            "BUILD_ROOT",
            "HOST_MUTATION_LOCK_TIMEOUT",
            "FORCE_COLOR",
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("MAGICK_BUILD_INTERPRETER_RESOLVED", "1")


def make_context(build_root: Path, selection: Selection | None = None) -> BuildContext:
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = build_root
    context = orchestrator.build_context(Arguments(), BuildSettings(), selection or Selection())
    context.packages.mkdir(parents=True, exist_ok=True)
    context.workspace.mkdir(exist_ok=True)
    context.log_file.touch()
    orchestrator.logger.log_file = context.log_file
    orchestrator.runner.log_file = context.log_file
    return context


@pytest.fixture
def context(tmp_path: Path) -> BuildContext:
    return make_context(tmp_path / "build")


@pytest.fixture
def stub(tmp_path: Path) -> Callable[[str, str], Path]:
    """Create an executable Python script in tmp/bin, bound to the test interpreter."""

    def create(name: str, source: str) -> Path:
        target = tmp_path / "bin" / name
        target.parent.mkdir(exist_ok=True)
        target.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
        target.chmod(0o755)
        return target

    return create


def invoke(
    *argv: str, cwd: Path | None = None, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the real launcher, never the build: tests pass no action or a failing one."""
    return subprocess.run(
        [sys.executable, "-B", str(REPO / "build-magick.py"), *argv],
        env={**os.environ, **(environment or {})},
        cwd=cwd or REPO,
        input="",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
