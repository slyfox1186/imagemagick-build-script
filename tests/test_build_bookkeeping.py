"""Marker-first resolution, build/skip decisions, completion markers, pinned clones."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from magick_builder.config import Selection
from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.errors import BuildError
from magick_builder.runtime.state import read_marker, write_marker
from magick_builder.runtime.versions import Resolved

from .conftest import COMMIT, make_context


def give_artifact(context: BuildContext, key: str) -> None:
    """Create what the registry's artifact contract for `key` checks."""
    paths = {
        "m4": "bin/m4",
        "libpng": "lib/pkgconfig/libpng16.pc",
        "libjpeg-turbo": "lib/libjpeg.a",
    }
    path = context.workspace / paths[key]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n")
    path.chmod(0o755)


def forbid_network(monkeypatch: pytest.MonkeyPatch, context: BuildContext) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the resolver must not be called")

    for name in ("latest_tag", "head", "listed_release"):
        monkeypatch.setattr(context.resolver, name, refuse)


def test_intact_marker_is_reused_without_network(
    context: BuildContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_marker(context.marker_path("libpng"), "1.6.58", COMMIT)
    give_artifact(context, "libpng")
    forbid_network(monkeypatch, context)
    resolved = context.resolve("libpng")
    assert resolved == Resolved("", "1.6.58", COMMIT)
    assert not context.build("libpng", resolved.version)
    assert context.packages_already_built == 1


def test_latest_forces_resolution_and_rebuilds_outdated(
    context: BuildContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_marker(context.marker_path("libpng"), "1.6.57", COMMIT)
    give_artifact(context, "libpng")
    context.latest = True
    monkeypatch.setattr(
        context.resolver, "latest_tag", lambda *_: Resolved("v1.6.58", "1.6.58", "b" * 40)
    )
    resolved = context.resolve("libpng")
    assert resolved == Resolved("v1.6.58", "1.6.58", "b" * 40)
    assert context.build("libpng", resolved.version)
    assert not context.marker_path("libpng").exists()


def test_disabled_package_skips_resolution_and_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_context(tmp_path / "build", Selection({"m4": True}, tmp_path / "c.toml"))
    forbid_network(monkeypatch, context)
    assert context.resolve("libpng") is None
    assert not context.build("libpng", None)
    assert context.packages_disabled == 1


def test_missing_artifacts_self_heal_and_malformed_markers_rebuild(context: BuildContext) -> None:
    write_marker(context.marker_path("libpng"), "1.6.58")
    assert context.build("libpng", "1.6.58")
    context.marker_path("m4").write_text("latest\nlegacy\n")
    assert context.build("m4", "1.4.21")
    assert not context.marker_path("m4").exists()


def test_build_done_requires_artifacts_and_records_the_commit(context: BuildContext) -> None:
    with pytest.raises(BuildError, match="artifacts are missing"):
        context.build_done("libpng", "1.6.58", COMMIT)
    give_artifact(context, "libpng")
    context.build_done("libpng", "1.6.58", COMMIT)
    assert read_marker(context.marker_path("libpng")) == ("1.6.58", COMMIT)


def test_library_rebuild_invalidates_imagemagick_but_tools_do_not(context: BuildContext) -> None:
    write_marker(context.marker_path("imagemagick"), "7.1.2-31")
    assert context.build("m4", "1.4.21")
    assert context.marker_path("imagemagick").exists()
    assert context.build("libjpeg-turbo", "3.1.2")
    assert not context.marker_path("imagemagick").exists()


def git(*arguments: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def upstream(tmp_path: Path, context: BuildContext) -> str:
    """A local repository served under an https:// URL through `insteadOf`."""
    repository = tmp_path / "upstream"
    repository.mkdir()
    git("init", "-q", "-b", "main", cwd=repository)
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "one",
        cwd=repository,
    )
    git("tag", "v1.0.0", cwd=repository)
    context.env.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": f"url.{repository.as_uri()}.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/pnggroup/libpng.git",
            "GIT_CONFIG_KEY_1": "protocol.file.allow",
            "GIT_CONFIG_VALUE_1": "always",
        }
    )
    return git("rev-parse", "HEAD", cwd=repository)


def test_clone_accepts_the_pinned_commit_and_rejects_a_moved_tag(
    context: BuildContext, upstream: str
) -> None:
    with pytest.raises(BuildError, match="reference may have moved"):
        context.clone("libpng", Resolved("v1.0.0", "1.0.0", "d" * 40))
    assert not (context.packages / "libpng").exists()
    checkout = context.clone("libpng", Resolved("v1.0.0", "1.0.0", upstream))
    assert git("rev-parse", "HEAD", cwd=checkout) == upstream
