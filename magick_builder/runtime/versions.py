"""Upstream release discovery.

Every resolver returns a `Resolved` triplet or None. None means "upstream could
not be reached or published nothing usable"; enabled packages then fail
explicitly, because a fixed fallback version would masquerade as the latest.

Git sources are pinned at resolution time: the commit a tag points to is
recorded here and the clone is later verified against it, so a tag that moves
upstream fails the build instead of silently building different content.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .download import USER_AGENT
from .exec import Runner
from .logging import Logger
from .versioncmp import version_compare

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
# Pre-release tags are excluded whatever each package's grammar accepts.
_PRERELEASE = re.compile(r"(rc|alpha|beta|pre|dev|preview)[._-]?[0-9]*$")
# `<name>-X.Y[.Z].tar.*` in a release-directory listing. Rolling aliases such as
# `m4-latest.tar.xz` never match, so markers always record a real version.
_LISTED_RELEASE = re.compile(r"[A-Za-z0-9_-]+-([0-9]+(?:\.[0-9]+)+)(?=\.tar)")


def _sort_v_order(left: str, right: str) -> int:
    """`sort -V` order: version comparison, then byte order to break ties."""
    return version_compare(left, right) or (left > right) - (left < right)


def newest(values: Iterable[str]) -> str | None:
    """The last value `sort -V` would emit, in one linear pass."""
    return max(values, key=functools.cmp_to_key(_sort_v_order), default=None)


@dataclass(frozen=True)
class Resolved:
    """What one package resolved to: the upstream tag, the recorded version,
    and the pinned commit. Tag and commit are empty for tarball-only sources."""

    tag: str
    version: str
    commit: str = ""


def select_latest_stable_tag(
    listing: str, accept: str, exclude: str = "", prefix: str = ""
) -> Resolved | None:
    """Pick the highest stable tag from `git ls-remote --tags` output.

    Every upstream needs its own grammar: libjpeg-turbo alone carries x.y.9z
    development tags plus inherited jpeg-9e/jpeg-10 tags that a generic version
    sort would happily select. The peeled (`^{}`) line carries the commit an
    annotated tag actually points to, so it wins over the tag object itself.
    """
    accept_pattern = re.compile(accept)
    exclude_pattern = re.compile(exclude) if exclude else None
    references: dict[str, str] = {}
    by_version: dict[str, str] = {}
    for line in listing.splitlines():
        sha, _, reference = line.partition("\t")
        if not reference.startswith("refs/tags/"):
            continue
        references[reference] = sha
        tag = reference[len("refs/tags/") :]
        if tag.endswith("^{}") or not accept_pattern.search(tag):
            continue
        if exclude_pattern is not None and exclude_pattern.search(tag):
            continue
        if _PRERELEASE.search(tag.lower()):
            continue
        version = tag[len(prefix) :] if prefix and tag.startswith(prefix) else tag
        by_version[version] = tag
    selected = newest(by_version)
    if selected is None:
        return None
    tag = by_version[selected]
    commit = references.get(f"refs/tags/{tag}^{{}}") or references.get(f"refs/tags/{tag}", "")
    if not _COMMIT.match(commit):
        return None
    return Resolved(tag, selected, commit)


def select_listed_release(listing: str) -> str | None:
    """The highest plain numeric release named in a directory listing."""
    return newest(_LISTED_RELEASE.findall(listing))


def ghostscript_version(tag: str) -> str | None:
    """`gs10071` means 10.07.1; the zero padding is part of the tarball name.

    The grammar is pinned to exactly five digits: a future six-digit tag would
    sort wrongly against five-digit ones, so it fails closed for a deliberate
    update instead.
    """
    match = re.fullmatch(r"gs([0-9]{2})([0-9]{2})([0-9])", tag)
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}" if match else None


class VersionResolver:
    """Queries upstream tag lists and release indexes."""

    def __init__(self, runner: Runner, logger: Logger, *, git_timeout: int = 120) -> None:
        self.runner = runner
        self.logger = logger
        self.git_timeout = git_timeout

    def _git(self, *arguments: str) -> str | None:
        completed = self.runner.capture(
            [
                "git",
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.https.allow=always",
                *arguments,
            ],
            env_overrides={"GIT_TERMINAL_PROMPT": "0"},
            timeout=self.git_timeout,
        )
        if completed.returncode != 0:
            self.logger.warn(
                f"'git {' '.join(arguments)}' failed (exit {completed.returncode}): "
                f"{completed.stderr.strip() or 'no diagnostic output'}"
            )
            return None
        return completed.stdout

    def latest_tag(
        self, repository_url: str, accept: str, exclude: str = "", prefix: str = ""
    ) -> Resolved | None:
        listing = self._git("ls-remote", "--tags", repository_url)
        if listing is None:
            return None
        resolved = select_latest_stable_tag(listing, accept, exclude, prefix)
        if resolved is None:
            self.logger.warn(f"No stable release tag matched in '{repository_url}'.")
        return resolved

    def head(self, repository_url: str) -> Resolved | None:
        """Pin HEAD itself, for repositories whose tags do not track content."""
        listing = self._git("ls-remote", repository_url, "HEAD")
        if listing is None:
            return None
        sha = listing.split("\t", 1)[0].strip()
        if not _COMMIT.match(sha):
            self.logger.warn(f"'{repository_url}' reported no usable HEAD commit.")
            return None
        return Resolved("", sha, sha)

    def fetch_text(self, url: str, *, max_time: int = 120) -> str | None:
        """Fetch a release index with the same HTTPS policy as downloads.

        A version index that could be redirected to plain HTTP decides which
        bytes get compiled, so the scheme stays pinned across redirects.
        """
        completed = self.runner.capture(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--tlsv1.2",
                "--user-agent",
                USER_AGENT,
                "--connect-timeout",
                "15",
                "--max-time",
                str(max_time),
                "--retry",
                "3",
                "--retry-delay",
                "5",
                "--retry-all-errors",
                url,
            ],
            timeout=max_time * 4 + 30,
        )
        if completed.returncode != 0:
            self.logger.warn(
                f"Unable to read '{url}': {completed.stderr.strip() or 'no diagnostic output'}"
            )
            return None
        return completed.stdout

    def listed_release(self, urls: Sequence[str]) -> Resolved | None:
        """The newest release in the first listing that yields one."""
        for url in urls:
            listing = self.fetch_text(url)
            if listing is None:
                continue
            version = select_listed_release(listing)
            if version is not None:
                return Resolved("", version)
            self.logger.warn(f"No release archive is listed at '{url}'.")
        return None
