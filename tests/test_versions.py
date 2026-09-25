"""Upstream version selection: per-repository grammars, pinned commits, listings."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Sequence

import pytest

from magick_builder import registry
from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.versions import (
    Resolved,
    VersionResolver,
    ghostscript_version,
    select_latest_stable_tag,
    select_listed_release,
)


def listing(*tags: str, peeled: dict[str, str] | None = None) -> str:
    lines = [f"{index:040x}\trefs/tags/{tag}" for index, tag in enumerate(tags, 1)]
    for tag, commit in (peeled or {}).items():
        lines.append(f"{commit}\trefs/tags/{tag}^{{}}")
    return "\n".join(lines) + "\n"


def grammar(key: str) -> tuple[str, str, str]:
    package = registry.PACKAGES[key]
    return package.accept, package.exclude, package.prefix


def test_libjpeg_turbo_grammar_skips_development_and_jpeg_tags() -> None:
    text = listing("2.1.5", "2.1.91", "3.0.4", "3.0.90", "jpeg-9e", "jpeg-10", "3.1.2")
    assert select_latest_stable_tag(text, *grammar("libjpeg-turbo")) == Resolved(
        "3.1.2", "3.1.2", f"{7:040x}"
    )


def test_annotated_tag_resolves_to_its_peeled_commit() -> None:
    text = listing("v1.6.57", "v1.6.58", peeled={"v1.6.58": "b" * 40})
    assert select_latest_stable_tag(text, *grammar("libpng")) == Resolved(
        "v1.6.58", "1.6.58", "b" * 40
    )


def test_prereleases_are_excluded() -> None:
    text = listing("v2.16.0-rc1", "v2.16.0beta", "v2.15.4", "v2.16.0alpha2")
    resolved = select_latest_stable_tag(text, r"^v[0-9]+\.[0-9]+\.[0-9]+.*$", "", "v")
    assert resolved is not None and resolved.version == "2.15.4"


def test_ghostscript_and_freetype_grammars() -> None:
    gs = select_latest_stable_tag(
        listing("gs10060", "gs10071", "gs9561", "ghostpdl-10.07.1"), *grammar("ghostscript")
    )
    assert gs is not None and gs.tag == "gs10071"
    assert ghostscript_version(gs.tag) == "10.07.1"
    assert ghostscript_version("gs100710") is None
    freetype = select_latest_stable_tag(
        listing("VER-2-13-3", "VER-2-14-3", "VER-2-9"), *grammar("freetype")
    )
    assert freetype is not None and freetype.version == "2-14-3"


@pytest.mark.parametrize("text", ["", "\n", f"{'1' * 40}\trefs/heads/main\n"])
def test_empty_or_tagless_input_fails_closed(text: str) -> None:
    assert select_latest_stable_tag(text, *grammar("libpng")) is None


def test_large_listing_selects_quickly() -> None:
    text = listing(*(f"v1.{minor}.{patch}" for minor in range(300) for patch in range(1000)))
    started = time.monotonic()
    resolved = select_latest_stable_tag(text, *grammar("libpng"))
    assert resolved is not None and resolved.version == "1.299.999"
    assert time.monotonic() - started < 30


def test_listed_release_ignores_rolling_aliases() -> None:
    page = '<a href="m4-latest.tar.xz">x</a> m4-1.4.9.tar.gz m4-1.4.21.tar.xz m4-1.4.21.tar.xz.sig'
    assert select_listed_release(page) == "1.4.21"
    assert select_listed_release("nothing here") is None


class ScriptedRunner:
    """Answers `capture` calls from a URL -> (status, stdout) table."""

    def __init__(self, answers: dict[str, tuple[int, str]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def capture(self, arguments: Sequence[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(arguments))
        status, stdout = self.answers[arguments[-1]]
        return subprocess.CompletedProcess(
            list(arguments), status, stdout, "boom" if status else ""
        )


def test_listing_falls_back_to_the_next_mirror(context: BuildContext) -> None:
    runner = ScriptedRunner(
        {"https://a.test/m4/": (22, ""), "https://b.test/m4/": (0, "m4-1.4.21.tar.xz")}
    )
    resolver = VersionResolver(runner, context.logger)  # type: ignore[arg-type]
    assert resolver.listed_release(["https://a.test/m4/", "https://b.test/m4/"]) == Resolved(
        "", "1.4.21"
    )
    # Listings use the same browser user agent as archive downloads.
    assert all("--user-agent" in call for call in runner.calls)


def test_head_pin_requires_a_full_commit(context: BuildContext) -> None:
    good = ScriptedRunner({"HEAD": (0, f"{'c' * 40}\tHEAD\n")})
    assert VersionResolver(good, context.logger).head("https://x.test/r.git") == Resolved(  # type: ignore[arg-type]
        "", "c" * 40, "c" * 40
    )
    bad = ScriptedRunner({"HEAD": (0, "")})
    assert VersionResolver(bad, context.logger).head("https://x.test/r.git") is None  # type: ignore[arg-type]
