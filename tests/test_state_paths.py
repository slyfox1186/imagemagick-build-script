"""Markers, build-context records, bounded deletion, locks, and build-root safety."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from magick_builder.main import Orchestrator
from magick_builder.runtime.errors import BuildError
from magick_builder.runtime.paths import DirectoryLock, safe_remove_tree
from magick_builder.runtime.state import (
    BUILD_ROOT_MARKER_NAME,
    assert_safe_build_root,
    build_context_changes,
    build_root_marker_matches,
    read_marker,
    render_build_context,
    write_build_root_marker,
    write_marker,
)

from .conftest import COMMIT, REPO


def test_markers_record_version_and_commit(tmp_path: Path) -> None:
    write_marker(tmp_path / "a.done", "1.6.58", COMMIT)
    write_marker(tmp_path / "b.done", "2.4.7")
    assert read_marker(tmp_path / "a.done") == ("1.6.58", COMMIT)
    assert read_marker(tmp_path / "b.done") == ("2.4.7", "")
    assert (tmp_path / "a.done").read_text() == f"1.6.58 {COMMIT}\n"


@pytest.mark.parametrize(
    "content", ["", "latest\nmore\n", "1.2 short\n", "-1.2\n", "1.2 " + "A" * 40]
)
def test_malformed_markers_are_absent(tmp_path: Path, content: str) -> None:
    (tmp_path / "x.done").write_text(content)
    assert read_marker(tmp_path / "x.done") is None


def test_marker_writes_reject_bad_values(tmp_path: Path) -> None:
    with pytest.raises(BuildError):
        write_marker(tmp_path / "x.done", "bad version")
    with pytest.raises(BuildError):
        write_marker(tmp_path / "x.done", "1.0", "abc")


def test_root_marker_is_path_bound_and_accepts_the_bash_format(tmp_path: Path) -> None:
    root, copy = tmp_path / "root", tmp_path / "copy"
    root.mkdir()
    write_build_root_marker(root)
    assert build_root_marker_matches(root / BUILD_ROOT_MARKER_NAME, root)
    shutil.copytree(root, copy)
    assert not build_root_marker_matches(copy / BUILD_ROOT_MARKER_NAME, copy)
    (copy / BUILD_ROOT_MARKER_NAME).write_text(f"magick-build-root {copy}\n")
    assert build_root_marker_matches(copy / BUILD_ROOT_MARKER_NAME, copy)


def context_record(**overrides: str) -> str:
    fields = {
        "os": "Ubuntu 24.04",
        "arch": "x86_64",
        "multiarch": "x86_64-linux-gnu",
        "cpu_model": "CPU",
        "compiler": "/usr/lib/ccache/gcc-14 gcc-14 (Ubuntu) 14.2.0",
        "cflags": "-O3",
        "cxxflags": "-O3",
        "cppflags": "-I/w/include",
        "ldflags": "-L/w/lib",
    }
    fields.update(overrides)
    return render_build_context(fields)


def test_unchanged_bash_context_record_is_adopted() -> None:
    bash_record = "schema=1\nscript_version=2.0.0\n" + context_record().split("\n", 1)[1]
    assert build_context_changes(bash_record, context_record()) == []


def test_changed_context_names_the_field() -> None:
    changes = build_context_changes(context_record(), context_record(cflags="-O2"))
    assert changes == ["cflags: '-O3' -> '-O2'"]
    assert build_context_changes("schema=9\n", context_record())
    selection = build_context_changes(context_record(), context_record(package_selection="m4"))
    assert selection == ["package_selection: '(not recorded)' -> 'm4'"]


def test_safe_remove_tree_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "packages"
    (root / "child/deep").mkdir(parents=True)
    sibling = tmp_path / "packages-evil"
    sibling.mkdir()
    safe_remove_tree(root / "child", root)
    assert not (root / "child").exists()
    with pytest.raises(BuildError, match="allowed root itself"):
        safe_remove_tree(root, root)
    with pytest.raises(BuildError, match="outside"):
        safe_remove_tree(sibling, root)
    (root / "link").symlink_to(sibling)
    with pytest.raises(BuildError, match="symlinked"):
        safe_remove_tree(root / "link", root)
    assert sibling.is_dir()


def test_directory_lock_is_exclusive(tmp_path: Path) -> None:
    first, second = DirectoryLock(tmp_path), DirectoryLock(tmp_path)
    assert first.acquire()
    assert not second.acquire()
    assert first.owner_pid() == os.getpid()
    first.release()
    assert second.acquire()
    second.release()


def test_second_build_on_one_root_names_the_running_pid(tmp_path: Path) -> None:
    orchestrator = Orchestrator(REPO, [])
    held = DirectoryLock(tmp_path)
    assert held.acquire()
    try:
        with pytest.raises(BuildError, match=f"PID {os.getpid()}"):
            orchestrator.acquire_lock(tmp_path)
    finally:
        held.release()


@pytest.mark.parametrize("candidate", ["/", "/usr/local", "/tmp"])
def test_unsafe_build_roots_are_refused(candidate: str) -> None:
    with pytest.raises(BuildError):
        assert_safe_build_root(Path(candidate), REPO)


def test_repository_and_its_ancestors_are_refused(tmp_path: Path) -> None:
    for candidate in (REPO, REPO.parent, tmp_path / "with space"):
        with pytest.raises(BuildError):
            assert_safe_build_root(candidate, REPO)
    assert_safe_build_root(REPO / "build", REPO)


def test_unmarked_populated_root_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = root
    with pytest.raises(BuildError, match="lacks a valid path-bound"):
        orchestrator.validate_build_root()


def test_initialize_refuses_a_symlinked_log(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    write_build_root_marker(root)
    (root / "build.log").symlink_to(tmp_path / "elsewhere.log")
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = root
    try:
        with pytest.raises(BuildError, match="symlink"):
            orchestrator.initialize_build_root()
    finally:
        orchestrator.teardown()
    assert not (tmp_path / "elsewhere.log").exists()


def test_noninteractive_cleanup_preserves_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    write_build_root_marker(root)
    (root / "packages").mkdir()
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = root
    orchestrator.cleanup()
    assert (root / "packages").is_dir()


def test_cleanup_refuses_an_unmarked_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "precious").mkdir(parents=True)
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = root
    with pytest.raises(BuildError, match="marker is missing"):
        orchestrator.cleanup()
    assert (root / "precious").is_dir()


def test_initialize_removes_the_bash_lock_file(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    write_build_root_marker(root)
    (root / ".magick-build-lock").write_text("646686\n")
    orchestrator = Orchestrator(REPO, [])
    orchestrator.build_root = root
    try:
        orchestrator.initialize_build_root()
    finally:
        orchestrator.teardown()
    assert not (root / ".magick-build-lock").exists()
    assert (root / "packages").is_dir()
