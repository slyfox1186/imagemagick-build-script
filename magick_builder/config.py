"""Build settings and package selection: reading and writing configuration.

The accepted format is a deliberately small TOML subset, parsed line by line
rather than with `tomllib`: it has to reject everything outside that subset (a
nested table, an arbitrary string, an array) instead of accepting and ignoring it,
and every diagnostic names the exact line that caused it. `tomllib` still has a
job: the linter parses the generated template with it, so the subset this
writes stays real TOML.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import registry
from .runtime.errors import UsageError
from .runtime.logging import Logger

_TABLE = re.compile(r"^\[([A-Za-z0-9._-]+)\]$")
_ASSIGNMENT = re.compile(r"^([A-Za-z0-9_-]+)[ \t]*=[ \t]*(.*)$")
_QUOTED = re.compile(r"""^(?:"([^"]*)"|'([^']*)')$""")
_INTEGER = re.compile(r"^[0-9]{1,2}$")
_SUPPORTED_TABLES = ("build", "packages")
COMPILERS = ("gcc", "clang")
# `native` tunes for the building CPU and runs only on CPUs like it; the others
# are portable: `generic` runs on any x86-64 CPU, and each psABI level on any CPU
# that implements it.
CPU_TARGETS = ("native", "generic", "x86-64-v2", "x86-64-v3", "x86-64-v4")
CPU_TARGET_CHOICES = "'native', 'generic', 'x86-64-v2', 'x86-64-v3' or 'x86-64-v4'"
GCC_MIN_VERSION = 9
GCC_MAX_VERSION = 16


class Selection:
    """Which packages are on.

    Without a configuration file every package is enabled. With one, the file
    is an allowlist: an omitted key is disabled. Those are opposite defaults, so
    whether a file was supplied is part of the state.
    """

    def __init__(self, explicit: dict[str, bool] | None = None, config_file: Path | None = None):
        self.explicit: dict[str, bool] = dict(explicit or {})
        self.config_file = config_file

    @property
    def has_config(self) -> bool:
        return self.config_file is not None

    def enabled(self, key: str) -> bool:
        if key not in registry.PACKAGES:
            raise UsageError(f"Unsupported package '{key}'.")
        if key in self.explicit:
            return self.explicit[key]
        return not self.has_config

    def enabled_names(self) -> list[str]:
        return [key for key in registry.PACKAGE_NAMES if self.enabled(key)]

    def problems(self) -> list[str]:
        """Selections this project's recipes cannot build, in registry order."""
        return [
            rule.message()
            for rule in registry.REQUIREMENTS
            if self.enabled(rule.package) and not self.enabled(rule.needs)
        ]


class BuildSettings:
    """Persistent `[build]` options; an omitted key keeps its default.

    `gcc_version` None means the newest stable GCC of the detected release.
    """

    def __init__(
        self,
        *,
        compiler: str = "gcc",
        cpu_target: str = "native",
        gcc_version: int | None = None,
        shared: bool = False,
        latest: bool = False,
    ) -> None:
        self.compiler = compiler
        self.cpu_target = cpu_target
        self.gcc_version = gcc_version
        self.shared = shared
        self.latest = latest

    def validate(self) -> None:
        if self.compiler not in COMPILERS:
            raise UsageError("Compiler must be 'gcc' or 'clang'.")
        if self.cpu_target not in CPU_TARGETS:
            raise UsageError(f"CPU target must be {CPU_TARGET_CHOICES}.")
        if self.gcc_version is not None and not (
            GCC_MIN_VERSION <= self.gcc_version <= GCC_MAX_VERSION
        ):
            raise UsageError(
                f"GCC version must be an integer from {GCC_MIN_VERSION} through {GCC_MAX_VERSION}."
            )
        if self.compiler == "clang" and self.gcc_version is not None:
            raise UsageError("'gcc_version' applies only to GCC builds, not compiler 'clang'.")


def _quoted(value_text: str) -> str | None:
    match = _QUOTED.fullmatch(value_text)
    if match is None:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _build_value(settings: BuildSettings, key: str, value_text: str, location: str) -> None:
    """Apply one `[build]` assignment, naming the expected value on a mismatch."""
    if key == "compiler":
        compiler = _quoted(value_text)
        if compiler not in COMPILERS:
            raise UsageError(f"Invalid compiler at {location}; expected a quoted 'gcc' or 'clang'.")
        settings.compiler = compiler
    elif key == "cpu_target":
        target = _quoted(value_text)
        if target not in CPU_TARGETS:
            raise UsageError(
                f"Invalid cpu_target at {location}; expected a quoted {CPU_TARGET_CHOICES}."
            )
        settings.cpu_target = target
    elif key == "gcc_version":
        version = int(value_text) if _INTEGER.fullmatch(value_text) else 0
        if not GCC_MIN_VERSION <= version <= GCC_MAX_VERSION:
            raise UsageError(
                f"Invalid gcc_version at {location}; expected an integer from "
                f"{GCC_MIN_VERSION} through {GCC_MAX_VERSION}."
            )
        settings.gcc_version = version
    elif key in ("shared", "latest"):
        if value_text not in ("true", "false"):
            raise UsageError(f"Invalid {key} at {location}; expected true or false.")
        setattr(settings, key, value_text == "true")
    else:
        raise UsageError(f"Unsupported '[build]' key '{key}' at {location}.")


class LoadedConfig:
    def __init__(self, settings: BuildSettings, selection: Selection) -> None:
        self.settings = settings
        self.selection = selection


def load_config(config_file: Path, logger: Logger) -> LoadedConfig:
    """Parse a selection file, rejecting anything outside the accepted subset."""
    if not config_file.is_file():
        raise UsageError(f"Config file not found: '{config_file}'.")
    try:
        text = config_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise UsageError(f"Config file is not readable: '{config_file}'. {error}") from error

    settings = BuildSettings()
    explicit: dict[str, bool] = {}
    seen_tables: set[str] = set()
    seen_entries: set[str] = set()
    table = ""
    gcc_version_line = 0

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        location = f"'{config_file}:{line_number}'"

        table_match = _TABLE.match(line)
        if table_match:
            table = table_match.group(1)
            if table not in _SUPPORTED_TABLES:
                raise UsageError(f"Unsupported TOML table '[{table}]' at {location}.")
            if table in seen_tables:
                raise UsageError(f"Duplicate TOML table '[{table}]' at {location}.")
            seen_tables.add(table)
            continue

        entry = _ASSIGNMENT.match(line)
        if entry is None:
            raise UsageError(f"Unsupported config syntax at {location}: '{raw_line}'.")
        key, value_text = entry.group(1), entry.group(2).strip()
        if not table:
            raise UsageError(
                f"Config entries must appear inside [build] or [packages] at {location}."
            )
        entry_id = f"{table}.{key}"
        if entry_id in seen_entries:
            raise UsageError(f"Duplicate config key '{entry_id}' at {location}.")
        seen_entries.add(entry_id)
        if table == "build":
            _build_value(settings, key, value_text, location)
            if key == "gcc_version":
                gcc_version_line = line_number
        else:
            if value_text not in ("true", "false"):
                raise UsageError(f"Unsupported config syntax at {location}: '{raw_line}'.")
            if key in registry.REMOVED_PACKAGES:
                raise UsageError(
                    f"'[packages]' key '{key}' at {location} is no longer built from source: "
                    f"{registry.REMOVED_PACKAGES[key]}. Remove the line."
                )
            if key not in registry.PACKAGES:
                raise UsageError(f"Unsupported '[packages]' key '{key}' at {location}.")
            explicit[key] = value_text == "true"

    if settings.compiler == "clang" and settings.gcc_version is not None:
        raise UsageError(
            f"'gcc_version' at '{config_file}:{gcc_version_line}' applies only to GCC builds, "
            "not compiler 'clang'."
        )
    logger.info(f"Loaded package selection from '{config_file}' (omitted packages are disabled).")
    return LoadedConfig(settings, Selection(explicit, config_file))


_TEMPLATE_PREAMBLE = """\
# Copy this template to custom.toml, edit it, and then run:
# python3 build-magick.py --build --config ./custom.toml
#
# This project accepts a deliberately small TOML subset:
#   [build]
#   [packages]
#   key = true|false
#   compiler = "gcc"|"clang", cpu_target = "<target>" and gcc_version = <N>
#   (only in [build])
#
# Package entries are an explicit allowlist: an omitted key is DISABLED.
# This file lists every supported key set to true, which reproduces the
# default full build. Every key names a component this script builds from
# source; a true value builds it into the workspace and (where the
# component provides an ImageMagick delegate) requires that delegate in
# the final validated install. A false value skips the build and passes an
# explicit --without flag to ImageMagick's configure, so a stray system
# dev package cannot silently re-enable it.
#
# The APT baseline is not configurable here: the system packages that
# provide the bzlib/gvc/heic/jbig/lzma/rsvg/zlib/zstd delegates (plus the
# djvu/fftw/lqr/openexr/pango/raw/wmf/zip extras and the gs/ffmpeg runtime
# delegates) are always installed.
#
# The groups below are for readability, with package keys alphabetized
# inside each group. They do not control build order; the builder fixes the
# build order itself. Some selections are impossible and fail up front: the
# raqm text stack needs freetype, fribidi, and harfbuzz; fontconfig needs
# freetype and libxml2; libtiff needs libjpeg-turbo.
#
# The active selection is recorded in the build context. Changing it
# invalidates the completion markers and the workspace automatically on
# the next run - no manual cleanup is needed.

[build]
# C/C++ compiler family. --compiler (or --gcc/--clang) overrides this value.
compiler = "{compiler}"

# GCC major version for GCC builds; omitted means the newest stable GCC of
# this OS release. --gcc-version overrides it. Not used with clang.
{gcc_version}

# CPU the build is optimized for. "native" tunes for this machine's CPU and
# the result may not run on others; "generic" runs on any x86-64 CPU; an
# x86-64-vN level runs on any CPU that implements it. --cpu-target (or
# --generic) overrides this value.
cpu_target = "{cpu_target}"

# Build shared libraries and coder modules instead of the static default.
# The --shared command-line flag turns this on for one run.
shared = {shared}

# Recheck upstream releases and rebuild components whose recorded versions
# differ. The --latest command-line flag turns this on for one run.
latest = {latest}

[packages]
"""


def render_config(settings: BuildSettings, states: dict[str, bool]) -> str:
    """Emit a configuration file from the registry.

    `example.toml` is exactly this output with every package enabled; the
    linter compares the two, so the template cannot drift from the registry.
    """
    settings.validate()
    gcc_version = (
        f"gcc_version = {settings.gcc_version}"
        if settings.gcc_version is not None
        else "# gcc_version = 14"
    )
    parts = [
        _TEMPLATE_PREAMBLE.format(
            compiler=settings.compiler,
            gcc_version=gcc_version,
            cpu_target=settings.cpu_target,
            shared="true" if settings.shared else "false",
            latest="true" if settings.latest else "false",
        )
    ]
    for group in registry.GROUPS:
        parts.append(f"\n# {group}\n")
        members = [package for package in registry.PACKAGE_LIST if package.group == group]
        for package in sorted(members, key=lambda item: item.key.lower()):
            value = "true" if states.get(package.key, True) else "false"
            parts.append(f"{package.key} = {value}  # {package.summary}\n")
    return "".join(parts)


def default_states() -> dict[str, bool]:
    return {key: True for key in registry.PACKAGE_NAMES}
