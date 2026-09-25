"""Build settings and package selection: reading and writing configuration.

The accepted format is a deliberately small TOML subset, parsed line by line
rather than with `tomllib`: it has to reject everything outside that subset (a
nested table, a string value, an array) instead of accepting and ignoring it,
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
_ENTRY = re.compile(r"^([A-Za-z0-9_-]+)[ \t]*=[ \t]*(true|false)$")
_SUPPORTED_TABLES = ("build", "packages")


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
    """Persistent `[build]` options."""

    def __init__(self, *, latest: bool = False) -> None:
        self.latest = latest


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

        entry = _ENTRY.match(line)
        if entry is None:
            raise UsageError(f"Unsupported config syntax at {location}: '{raw_line}'.")
        key, value = entry.group(1), entry.group(2) == "true"
        if not table:
            raise UsageError(
                f"Config entries must appear inside [build] or [packages] at {location}."
            )
        entry_id = f"{table}.{key}"
        if entry_id in seen_entries:
            raise UsageError(f"Duplicate config key '{entry_id}' at {location}.")
        seen_entries.add(entry_id)
        if table == "build":
            if key != "latest":
                raise UsageError(f"Unsupported '[build]' key '{key}' at {location}.")
            settings.latest = value
        else:
            if key not in registry.PACKAGES:
                raise UsageError(f"Unsupported '[packages]' key '{key}' at {location}.")
            explicit[key] = value

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
# Recheck upstream releases and rebuild components whose recorded versions
# differ. The --latest command-line flag overrides this key.
latest = {latest}

[packages]
"""


def render_config(settings: BuildSettings, states: dict[str, bool]) -> str:
    """Emit a configuration file from the registry.

    `example.toml` is exactly this output with every package enabled; the
    linter compares the two, so the template cannot drift from the registry.
    """
    parts = [_TEMPLATE_PREAMBLE.format(latest="true" if settings.latest else "false")]
    for group in registry.GROUPS:
        parts.append(f"\n# {group}\n")
        members = [package for package in registry.PACKAGE_LIST if package.group == group]
        for package in sorted(members, key=lambda item: item.key.lower()):
            value = "true" if states.get(package.key, True) else "false"
            parts.append(f"{package.key} = {value}  # {package.summary}\n")
    return "".join(parts)


def default_states() -> dict[str, bool]:
    return {key: True for key in registry.PACKAGE_NAMES}
