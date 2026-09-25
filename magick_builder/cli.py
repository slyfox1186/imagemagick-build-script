"""Command-line parsing.

The help screen itself lives in `usage`, which the launcher can import on any
interpreter. `argparse` is not used: its formatter rewraps and re-indents, and
it cannot reproduce the layout `README.md` pins byte for byte.

Parsing runs in three passes: metadata options are answered first so `--help`
and `--version` stay free of side effects, the whole command line is validated
next, and only then is a configuration file opened. An invalid request must
never cause a TOML file to be read on its way to the error.
"""

from __future__ import annotations

import os
from pathlib import Path

from .runtime.errors import UsageError
from .runtime.settings import MAX_PROCESS_INTEGER, parse_integer
from .usage import SCRIPT_NAME, SCRIPT_VERSION, metadata_response, usage_text

__all__ = [
    "GCC_MAX_VERSION",
    "GCC_MIN_VERSION",
    "Arguments",
    "SCRIPT_NAME",
    "SCRIPT_VERSION",
    "parse_arguments",
    "requested_metadata",
    "resolve_config_path",
    "usage_text",
]

GCC_MIN_VERSION = 9
GCC_MAX_VERSION = 14


class Arguments:
    """The parsed command line."""

    def __init__(self) -> None:
        self.build = False
        self.cleanup = False
        self.jobs: int | None = None
        self.gcc_version: int | None = None
        self.latest = False
        self.debug = False
        self.config_path: str | None = None


def requested_metadata(argv: list[str]) -> str | None:
    """Answer `--help`/`--version` before any other work happens."""
    return metadata_response(argv)


def _value(argv: list[str], index: int, option: str) -> str:
    if index + 1 >= len(argv):
        raise UsageError(f"Missing value for '{option}'.")
    return argv[index + 1]


def parse_arguments(argv: list[str]) -> Arguments:
    arguments = Arguments()
    index = 0
    while index < len(argv):
        argument = argv[index]
        option, separator, inline = argument.partition("=")
        if not option.startswith("--"):
            option, separator, inline = argument, "", ""
        if argument in ("-b", "--build"):
            arguments.build = True
        elif argument in ("-c", "--cleanup"):
            arguments.cleanup = True
        elif argument in ("-l", "--latest"):
            arguments.latest = True
        elif argument in ("-d", "--debug"):
            arguments.debug = True
        elif option in ("-j", "--jobs"):
            value = inline if separator else _value(argv, index, option)
            index += 0 if separator else 1
            arguments.jobs = _parse_jobs(value)
        elif option in ("-g", "--gcc-version"):
            value = inline if separator else _value(argv, index, option)
            index += 0 if separator else 1
            arguments.gcc_version = _parse_gcc_version(value)
        elif option == "--config":
            value = inline if separator else _value(argv, index, option)
            index += 0 if separator else 1
            if arguments.config_path is not None:
                raise UsageError("'--config' may only be specified once.")
            arguments.config_path = value
        elif argument in ("-h", "--help", "-v", "--version"):
            # Already answered before the config is loaded, so these stay
            # side-effect free.
            pass
        elif argument == "--":
            remainder = argv[index + 1 :]
            if remainder:
                raise UsageError(f"Unexpected positional arguments: '{' '.join(remainder)}'.")
            break
        else:
            raise UsageError(f"Unknown option '{argument}'.")
        index += 1

    if arguments.build and arguments.cleanup:
        raise UsageError("'--build' and '--cleanup' are mutually exclusive.")
    return arguments


def _parse_jobs(value: str) -> int:
    parsed = parse_integer(value, maximum=MAX_PROCESS_INTEGER)
    if parsed is None:
        raise UsageError(f"Invalid jobs value '{value}'; expected a positive integer.")
    return parsed


def _parse_gcc_version(value: str) -> int:
    parsed = parse_integer(value, maximum=GCC_MAX_VERSION)
    if parsed is None or parsed < GCC_MIN_VERSION:
        raise UsageError(
            f"Invalid GCC version '{value}'; expected an integer from "
            f"{GCC_MIN_VERSION} through {GCC_MAX_VERSION}."
        )
    return parsed


def resolve_config_path(raw_path: str, invocation_dir: Path) -> Path:
    """Resolve `--config` against the invocation directory only.

    Retrying a missing relative path under the script's own directory would let
    a stale `custom.toml` beside the launcher supply a different selection,
    with nothing in the output naming the file that won.
    """
    if not raw_path or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in raw_path
    ):
        raise UsageError("Invalid value for '--config'.")
    candidate = Path(raw_path) if raw_path.startswith("/") else invocation_dir / raw_path
    return Path(os.path.realpath(candidate, strict=False))
