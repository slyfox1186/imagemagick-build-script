"""Build-root markers, package markers, and the build-context record.

Nothing in this project is deleted without a path-bound marker match, and no
package is considered current without both a version marker and the artifact
that marker claims. These are the files that make those two statements true.

Workspaces created by the Bash implementation (2.x) are read as well: their
package markers already use the format below, their root marker is recognized
and upgraded, and their build-context record is adopted when every recorded
input is unchanged, so an existing tree is not rebuilt merely because the
builder changed language.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from .errors import BuildError
from .paths import UNSAFE_BUILD_ROOTS, canonicalize, is_exclusive_regular_file, path_is_within

BUILD_ROOT_MARKER_NAME = ".magick-build-root"
BUILD_ROOT_MARKER_HEADER = "magick-build-root:v2"
LEGACY_BUILD_ROOT_MARKER_PREFIX = "magick-build-root "
BUILD_CONTEXT_NAME = ".magick-build-context"
# The flock file of the Bash releases; the directory lock replaced it.
LEGACY_LOCK_NAME = ".magick-build-lock"
BUILD_CONTEXT_SCHEMA = "2"
CONFIGURE_FINGERPRINT_SUFFIX = ".configure.sha256"

# "VERSION" or "VERSION COMMIT" (a full 40-character commit). Anything else is
# treated as absent, so a truncated or foreign marker causes a clean rebuild
# instead of a wrong-version reuse.
_MARKER = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._+-]*)(?: ([0-9a-f]{40}))?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def is_valid_version(version: str) -> bool:
    return bool(_VERSION.fullmatch(version))


def publish_atomically(target: Path, content: str, *, mode: int = 0o644) -> None:
    """Write through a temporary in the same directory, then rename.

    An interrupted write must never leave a marker that claims more than the
    filesystem actually holds.
    """
    handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError as cleanup_error:
            error.add_note(f"Unable to remove temporary file '{temporary}': {cleanup_error}")
        if isinstance(error, OSError):
            raise BuildError(f"Unable to publish '{target}': {error}") from error
        raise


# --------------------------------------------------------------------------
# Package markers
# --------------------------------------------------------------------------


def read_marker(marker_file: Path) -> tuple[str, str] | None:
    """(version, commit) from a `.done` marker, or None when unusable."""
    if not is_exclusive_regular_file(marker_file):
        return None
    try:
        lines = marker_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    if len(lines) != 1:
        return None
    match = _MARKER.fullmatch(lines[0])
    if match is None:
        return None
    return match.group(1), match.group(2) or ""


def write_marker(marker_file: Path, version: str, commit: str = "") -> None:
    if not is_valid_version(version):
        raise BuildError(f"Refusing to record the invalid version '{version}'.")
    if commit and not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise BuildError(f"Refusing to record the invalid commit '{commit}'.")
    publish_atomically(marker_file, f"{version} {commit}\n" if commit else f"{version}\n")


# --------------------------------------------------------------------------
# Build-root marker and safety
# --------------------------------------------------------------------------


def build_root_marker_matches(marker_file: Path, expected_root: Path) -> bool:
    """True when the marker names this exact build root.

    Binding the marker to its path is what stops a copied marker from
    authorizing deletion of an unrelated directory. The one-line marker the
    Bash implementation wrote carries the same binding and is accepted.
    """
    if not is_exclusive_regular_file(marker_file):
        return False
    try:
        lines = marker_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return False
    root = str(canonicalize(expected_root))
    if lines == [BUILD_ROOT_MARKER_HEADER, f"root={root}"]:
        return True
    return lines == [f"{LEGACY_BUILD_ROOT_MARKER_PREFIX}{root}"]


def write_build_root_marker(root: Path) -> None:
    resolved = canonicalize(root)
    if str(resolved) == "/" or not resolved.is_dir():
        raise BuildError(f"Refusing to write a marker for unsafe build root '{resolved}'.")
    marker_file = resolved / BUILD_ROOT_MARKER_NAME
    if marker_file.is_symlink():
        raise BuildError(f"Refusing symlink build-root marker '{marker_file}'.")
    publish_atomically(marker_file, f"{BUILD_ROOT_MARKER_HEADER}\nroot={resolved}\n", mode=0o600)


def build_root_is_adoptable(root: Path) -> bool:
    """True for a root holding nothing but this project's empty scaffolding.

    A run interrupted before its marker was written otherwise leaves a
    populated unmarked directory that neither `--build` nor `--cleanup` will
    touch again.
    """
    try:
        entries = list(root.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.name not in ("packages", "workspace") or entry.is_symlink() or not entry.is_dir():
            return False
        try:
            if any(entry.iterdir()):
                return False
        except OSError:
            return False
    return True


def assert_safe_build_root(candidate: Path, repository_root: Path) -> None:
    """One refusal list shared by the build and cleanup paths.

    The repository is compared by containment rather than equality: a build
    root that is an ancestor of the repository must be refused too, or a later
    cleanup takes the repository with it.
    """
    resolved = canonicalize(candidate)
    repository = canonicalize(repository_root)
    home = os.environ.get("HOME", "")
    if not home.startswith("/"):
        raise BuildError("'HOME' must name an absolute user home directory.")
    if any(character.isspace() for character in str(resolved)):
        raise BuildError(
            "The build root may not contain whitespace because several upstream build "
            f"systems cannot represent it safely: '{resolved}'."
        )
    if str(resolved) in UNSAFE_BUILD_ROOTS or resolved == canonicalize(home):
        raise BuildError(f"Refusing unsafe build root '{resolved}'.")
    if resolved == repository:
        raise BuildError(f"Refusing to use the repository root as a build root: '{resolved}'.")
    if path_is_within(repository, resolved):
        raise BuildError(f"Refusing a build root that contains this repository: '{resolved}'.")


# --------------------------------------------------------------------------
# Build context
# --------------------------------------------------------------------------

# Every input that changes what -march=native and the selected compiler
# produce. `package_selection` is recorded only while a config file is active,
# so a full build keeps the record it always had.
CONTEXT_FIELDS = (
    "os",
    "arch",
    "multiarch",
    "cpu_model",
    "compiler",
    "cflags",
    "cxxflags",
    "cppflags",
    "ldflags",
    "package_selection",
)


def render_build_context(fields: dict[str, str]) -> str:
    lines = [f"schema={BUILD_CONTEXT_SCHEMA}"]
    for name in CONTEXT_FIELDS:
        if name in fields:
            lines.append(f"{name}={fields[name]}")
    return "\n".join(lines) + "\n"


def parse_build_context(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    return fields


def build_context_changes(previous_text: str, current_text: str) -> list[str]:
    """The inputs that differ, ignoring bookkeeping.

    A schema-1 record (the Bash implementation) also carried the script
    version, which never affected an artifact; it is not compared.
    """
    previous = parse_build_context(previous_text)
    current = parse_build_context(current_text)
    if previous.get("schema") not in ("1", BUILD_CONTEXT_SCHEMA):
        return ["the build-context record uses an unknown format"]
    changes: list[str] = []
    for name in CONTEXT_FIELDS:
        if previous.get(name) != current.get(name):
            before = previous.get(name, "(not recorded)")
            after = current.get(name, "(not recorded)")
            changes.append(f"{name}: '{before}' -> '{after}'")
    return changes
