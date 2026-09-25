"""Font installation and the terminal/log presentation."""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.logging import Logger
from magick_builder.stages.fonts import font_files, install_font_files

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_only_real_font_files_are_installed(tmp_path: Path) -> None:
    checkout = tmp_path / "fam"
    for relative in ("TTF/A.ttf", "OTF/B.OTF", ".git/C.ttf", "README.md", "src/D.glyphs"):
        (checkout / relative).parent.mkdir(parents=True, exist_ok=True)
        (checkout / relative).write_text("x")
    (checkout / "TTF/link.ttf").symlink_to(checkout / "TTF/A.ttf")
    assert [path.relative_to(checkout).as_posix() for path in font_files(checkout)] == [
        "OTF/B.OTF",
        "TTF/A.ttf",
    ]


def test_font_install_prints_a_count_and_logs_every_file(
    context: BuildContext, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    checkout = tmp_path / "fam"
    for name in ("a.ttf", "b.ttf", "c.otf"):
        (checkout / name).parent.mkdir(parents=True, exist_ok=True)
        (checkout / name).write_text("x")
    calls: list[tuple[list[str], str | None]] = []

    def record(arguments: Sequence[str], *, display: str | None = None, **_: object) -> None:
        calls.append((list(arguments), display))

    monkeypatch.setattr(context, "execute", record)
    install_font_files(context, "fam", checkout)
    (arguments, display) = calls[0]
    assert display == "sudo install -D -m 644 -t /usr/share/fonts/truetype/fam <3 font files>"
    assert arguments[-3:] == ["a.ttf", "b.ttf", "c.otf"]


def test_long_command_shows_a_label_but_logs_every_argument(
    context: BuildContext, capsys: pytest.CaptureFixture[str]
) -> None:
    context.logger._out = sys.stdout
    context.runner.execute(
        ["echo", *(f"file{index}" for index in range(50))], display="echo <50 files>"
    )
    assert "$ echo <50 files>" in capsys.readouterr().out
    log = context.log_file.read_text()
    assert "file49" in log


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def terminal_logger(monkeypatch: pytest.MonkeyPatch, stream: Terminal) -> Logger:
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr(sys, "stdout", stream)
    return Logger()


def test_terminal_layout_matches_the_sibling_ffmpeg_builder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = Terminal()
    logger = terminal_logger(monkeypatch, stream)
    logger.banner("Building Image Libraries")
    logger.package_reused("libpng", "1.6.58")
    logger.package_start("libtiff", "4.7.2")
    logger.package_done("libtiff", "4.7.2", "12s")
    logger.magick("Features: Cipher DPC HDRI ")
    raw = stream.getvalue()
    assert "\x1b[1m\x1b[36mBuilding Image Libraries" in raw
    assert "\x1b[36m[SKIP]\x1b[0m \x1b[1m\x1b[33mlibpng\x1b[0m" in raw
    assert ANSI.sub("", raw).splitlines() == [
        "┌────────────────────────────┐",
        "│  Building Image Libraries  │",
        "└────────────────────────────┘",
        "",
        "[SKIP] libpng 1.6.58 is already built.",
        "",
        "Building libtiff - version 4.7.2",
        "================================",
        "[DONE] libtiff 4.7.2 built in 12s",
        "",
        "[MAGICK] Features: Cipher DPC HDRI",
    ]


def test_no_color_outside_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.delenv("NO_COLOR", raising=False)
    Logger().info("plain")
    assert stream.getvalue() == "[INFO] plain\n"
