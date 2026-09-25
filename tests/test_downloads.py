"""Transactional downloads and validated extraction, with a stub curl on the build PATH."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest

from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.download import (
    USER_AGENT,
    archive_checksum_matches,
    write_archive_checksum,
)
from magick_builder.runtime.errors import BuildError
from magick_builder.runtime.exec import BASE_PATH

Entry = tuple[str, bytes | str, bytes]


def archive_at(path: Path, entries: list[Entry]) -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, payload, kind in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                assert isinstance(payload, str)
                info.linkname = payload
                archive.addfile(info)
            else:
                assert isinstance(payload, bytes)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    return path


GOOD: list[Entry] = [("pkg-1.0/src/file.c", b"int x;\n", tarfile.REGTYPE)]


def test_benign_archive_round_trip_and_tamper_detection(context: BuildContext) -> None:
    archive = archive_at(context.packages / "pkg-1.0.tar.gz", GOOD)
    assert context.downloader.validate_tar_archive(archive)
    assert write_archive_checksum(archive)
    assert archive_checksum_matches(archive)
    assert context.downloader.extract_transactionally(archive, context.packages / "pkg-1.0")
    assert (context.packages / "pkg-1.0/src/file.c").read_bytes() == b"int x;\n"
    with archive.open("ab") as stream:
        stream.write(b"tamper")
    assert not archive_checksum_matches(archive)


@pytest.mark.parametrize(
    "entries",
    [
        [("pkg/../../outside", b"x", tarfile.REGTYPE)],
        [("/etc/passwd", b"x", tarfile.REGTYPE)],
        [("pkg/a", b"x", tarfile.REGTYPE), ("other/b", b"x", tarfile.REGTYPE)],
        [("pkg/a", b"x", tarfile.REGTYPE), ("pkg/fifo", b"", tarfile.FIFOTYPE)],
        [("pkg/a", b"x", tarfile.REGTYPE), ("pkg/link", "../../outside", tarfile.SYMTYPE)],
        [("pkg/a", b"x", tarfile.REGTYPE), ("pkg/link", "/etc/passwd", tarfile.SYMTYPE)],
        [("pkg/a", b"x", tarfile.REGTYPE), ("pkg/hard", "../outside", tarfile.LNKTYPE)],
        [("pkg/bad\x01name", b"x", tarfile.REGTYPE)],
    ],
)
def test_hostile_archives_are_rejected(context: BuildContext, entries: list[Entry]) -> None:
    archive = archive_at(context.packages / "bad.tar.gz", entries)
    assert not context.downloader.validate_tar_archive(archive)
    assert not context.downloader.extract_transactionally(archive, context.packages / "bad")
    assert not (context.packages / "bad").exists()


def test_failed_extraction_publishes_nothing(context: BuildContext) -> None:
    archive = context.packages / "broken.tar.gz"
    archive.write_bytes(b"not a tar archive")
    assert not context.downloader.extract_transactionally(archive, context.packages / "broken")
    assert not (context.packages / "broken").exists()
    assert not list(context.packages.glob(".extract.*"))


@pytest.fixture
def fake_curl(
    context: BuildContext, stub: Callable[[str, str], Path], tmp_path: Path
) -> Callable[[str], Path]:
    """Install a curl that serves `served.tar.gz` (or fails) and logs its argv."""

    def install(behavior: str) -> Path:
        calls = tmp_path / "curl-calls"
        stub(
            "curl",
            f"""
import shutil, sys
from pathlib import Path
with open({str(calls)!r}, "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
if {behavior!r} == "fail":
    Path(sys.argv[sys.argv.index("--output") + 1]).write_bytes(b"partial")
    sys.exit(22)
shutil.copy({str(tmp_path / "served.tar.gz")!r}, sys.argv[sys.argv.index("--output") + 1])
""",
        )
        archive_at(tmp_path / "served.tar.gz", GOOD)
        context.env["PATH"] = f"{tmp_path / 'bin'}:{BASE_PATH}"
        return calls

    return install


def test_download_publishes_only_after_success_and_sends_the_user_agent(
    context: BuildContext, fake_curl: Callable[[str], Path]
) -> None:
    calls = fake_curl("serve")
    source = context.download("https://example.test/pkg-1.0.tar.gz")
    assert source == context.packages / "pkg-1.0"
    assert (source / "src/file.c").is_file()
    assert archive_checksum_matches(context.packages / "pkg-1.0.tar.gz")
    assert f"--user-agent {USER_AGENT}" in calls.read_text()
    assert "--proto =https --proto-redir =https" in calls.read_text()


def test_failed_download_leaves_no_partial_file(
    context: BuildContext, fake_curl: Callable[[str], Path]
) -> None:
    fake_curl("fail")
    with pytest.raises(BuildError):
        context.download("https://example.test/pkg-1.0.tar.gz")
    assert not (context.packages / "pkg-1.0.tar.gz").exists()
    assert not list(context.packages.glob(".pkg-1.0.tar.gz.part.*"))


def test_valid_cache_skips_the_network(
    context: BuildContext, fake_curl: Callable[[str], Path]
) -> None:
    calls = fake_curl("fail")
    archive = archive_at(context.packages / "pkg-1.0.tar.gz", GOOD)
    assert write_archive_checksum(archive)
    context.download("https://example.test/pkg-1.0.tar.gz")
    assert not calls.exists()


def test_corrupt_cache_is_refetched(
    context: BuildContext, fake_curl: Callable[[str], Path]
) -> None:
    calls = fake_curl("serve")
    archive = archive_at(context.packages / "pkg-1.0.tar.gz", GOOD)
    assert write_archive_checksum(archive)
    archive.write_bytes(b"corrupted")
    context.download("https://example.test/pkg-1.0.tar.gz")
    assert calls.read_text().count("https://example.test/pkg-1.0.tar.gz") == 1
    assert archive_checksum_matches(archive)


def test_plain_http_is_refused(context: BuildContext) -> None:
    with pytest.raises(BuildError, match="HTTPS"):
        context.download("http://example.test/pkg-1.0.tar.gz")
