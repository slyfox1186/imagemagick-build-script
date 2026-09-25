"""Interrupts stop the build, kill its commands, and release the build-root lock."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest

from magick_builder import main as main_module
from magick_builder.main import Orchestrator, _install_signal_handlers
from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.errors import SignalStop
from magick_builder.runtime.paths import DirectoryLock


def test_interrupt_exits_130_and_releases_the_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def interrupted(self: Orchestrator) -> int:
        self._lock = DirectoryLock(tmp_path)
        assert self._lock.acquire()
        raise SignalStop("INT", 130)

    monkeypatch.setattr(Orchestrator, "run", interrupted)
    assert main_module.main(["--build"]) == 130
    probe = DirectoryLock(tmp_path)
    assert probe.acquire()
    probe.release()


def test_interrupt_kills_the_running_command_group(context: BuildContext) -> None:
    marker = "61.5"
    previous = {
        name: signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    }
    _install_signal_handlers()
    timer = threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGINT))
    try:
        timer.start()
        with pytest.raises(SignalStop):
            context.runner.run_logged(["sh", "-c", f"sleep {marker} & sleep {marker}; wait"])
    finally:
        timer.cancel()
        for number, handler in previous.items():
            signal.signal(number, handler)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        survivors = subprocess.run(
            ["pgrep", "-f", f"sleep {marker}"], capture_output=True, text=True, check=False
        ).stdout.split()
        if not survivors:
            break
        time.sleep(0.1)
    assert not survivors
