"""ImageMagick configure arguments, staged and live validation, and the recipe."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from magick_builder.config import Selection
from magick_builder.registry import PACKAGE_NAMES
from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.errors import BuildError
from magick_builder.runtime.state import write_marker
from magick_builder.runtime.versions import Resolved
from magick_builder.stages import imagemagick
from magick_builder.stages.imagemagick import (
    ImageMagickStage,
    configure_arguments,
    configure_fingerprint,
    required_delegates,
    toggle_arguments,
)
from magick_builder.stages.system_setup import configure_environment

from .conftest import make_context

FULL_DELEGATES = (
    "bzlib fontconfig freetype fpx gslib gvc heic jbig jng jp2 jpeg lcms lzma png raqm rsvg "
    "tiff webp xml zlib zstd"
)


def fake_magick(stub: Callable[[str, str], Path], version: str, delegates: str) -> Path:
    return stub(
        "magick",
        f"""
import sys
from pathlib import Path
if sys.argv[1:] == ["-version"]:
    print("Version: ImageMagick {version} Q16-HDRI x86_64 test:20260101 https://imagemagick.org")
    print("Copyright: (C) 1999 ImageMagick Studio LLC")
    print("Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5) ")
    print("Delegates (built-in): {delegates}")
elif sys.argv[1] == "identify":
    print("Path: /usr/local/etc/ImageMagick-7/policy.xml")
else:
    Path(sys.argv[-1]).write_bytes(b"image")
""",
    )


@pytest.fixture
def stage(context: BuildContext) -> ImageMagickStage:
    configure_environment(context)
    pkg_config = context.workspace / "bin/pkg-config"
    pkg_config.parent.mkdir(parents=True)
    pkg_config.write_text("#!/bin/sh\necho 7.9.9\n")
    pkg_config.chmod(0o755)
    return ImageMagickStage(context)


def test_validation_accepts_a_good_install_and_tags_the_report(
    stage: ImageMagickStage,
    stub: Callable[[str, str], Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    magick = fake_magick(stub, "7.9.9-99", FULL_DELEGATES)
    # Pytest swaps sys.stdout after fixtures run, and a real run always has
    # earlier output, so the report opens with its separating blank line.
    stage.logger._out = sys.stdout
    stage.logger._after_blank = False
    stage.validate_installation("7.9.9-99", magick)
    assert stage.context.magick_validated
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "",
        "[MAGICK] Version: ImageMagick 7.9.9-99 Q16-HDRI x86_64 test:20260101 https://imagemagick.org",
        "[MAGICK] Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5)",
        f"[MAGICK] Delegates (built-in): {FULL_DELEGATES}",
        "",
        "[INFO] Security policy: /usr/local/etc/ImageMagick-7/policy.xml "
        "(details: magick identify -list policy)",
        "[INFO] Functional smoke test passed (logo: -> PNG -> WebP).",
    ]


def test_validation_names_a_missing_delegate(
    stage: ImageMagickStage, stub: Callable[[str, str], Path]
) -> None:
    magick = fake_magick(stub, "7.9.9-99", FULL_DELEGATES.replace(" gvc", ""))
    with pytest.raises(BuildError, match="missing expected delegates: gvc"):
        stage.validate_installation("7.9.9-99", magick)


def test_validation_rejects_a_version_mismatch(
    stage: ImageMagickStage, stub: Callable[[str, str], Path]
) -> None:
    magick = fake_magick(stub, "7.9.9-98", FULL_DELEGATES)
    with pytest.raises(BuildError, match="different version"):
        stage.validate_installation("7.9.9-99", magick)


def test_staged_install_must_stay_inside_usr(
    stage: ImageMagickStage, stub: Callable[[str, str], Path], tmp_path: Path
) -> None:
    staging = tmp_path / "staging"
    binary = staging / "usr/local/bin/magick"
    binary.parent.mkdir(parents=True)
    binary.write_text(fake_magick(stub, "7.9.9-99", "").read_text())
    binary.chmod(0o755)
    stage.validate_staged_install(staging, "7.9.9-99")
    (staging / "etc").mkdir()
    with pytest.raises(BuildError, match="outside /usr: etc"):
        stage.validate_staged_install(staging, "7.9.9-99")


def test_disabled_providers_become_without_flags_and_leave_the_required_set(
    tmp_path: Path,
) -> None:
    enabled = {key: True for key in PACKAGE_NAMES}
    enabled.update({"libpng": False, "jemalloc": False})
    context = make_context(tmp_path / "build", Selection(enabled, tmp_path / "c.toml"))
    assert "--without-png" in toggle_arguments(context)
    assert "--without-jemalloc" in toggle_arguments(context)
    assert "--with-jpeg" in toggle_arguments(context)
    required = required_delegates(context)
    assert "png" not in required and "jng" not in required and "jpeg" in required


def test_fingerprint_change_invalidates_the_marker(stage: ImageMagickStage) -> None:
    context = stage.context
    marker = context.marker_path("imagemagick")
    fingerprint = configure_fingerprint(configure_arguments(context))
    write_marker(marker, "7.1.2-31")
    stage.fingerprint_file.write_text(f"{fingerprint}\n")
    stage.invalidate_stale_marker(fingerprint)
    assert marker.exists()
    stage.invalidate_stale_marker(configure_fingerprint(["--different"]))
    assert not marker.exists()


def test_recipe_keeps_the_shipped_configure(
    stage: ImageMagickStage, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """autoreconf inside this checkout baked this repository's commit into
    ImageMagick's version string; the shipped configure carries upstream's."""
    context = stage.context
    source = tmp_path / "imagemagick-7.1.2-31"
    source.mkdir()
    (source / "configure").write_text("#!/bin/sh\n")
    commands: list[tuple[list[str], Path | None]] = []

    def record(arguments: Sequence[str], *, cwd: Path | None = None, **_: object) -> None:
        commands.append((list(arguments), cwd))

    monkeypatch.setattr(context, "resolve", lambda _key: Resolved("7.1.2-31", "7.1.2-31", "e" * 40))
    monkeypatch.setattr(context, "build", lambda _key, _version: True)
    monkeypatch.setattr(context, "download", lambda _url, _name=None: source)
    monkeypatch.setattr(context, "execute", record)
    for name in ("validate_staged_install", "publish", "validate_installation"):
        monkeypatch.setattr(stage, name, lambda *_args: None)
    monkeypatch.setattr(context, "build_done", lambda *_args: None)
    monkeypatch.setattr(imagemagick, "publish_atomically", lambda *_args: None)
    stage.run()
    assert not any(arguments[0] == "autoreconf" for arguments, _ in commands)
    assert commands[0][0][:2] == ["sh", "../configure"]
    assert commands[0][1] == source / "build"
