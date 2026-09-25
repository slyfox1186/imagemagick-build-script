"""The help screen and version string.

Deliberately plain: the launcher imports this module on whatever interpreter
the user happened to start, which on Ubuntu 22.04 is Python 3.10. `--help` and
`--version` are answered before any interpreter resolution, so this file must
parse on every interpreter the project can be launched from and must import
nothing that does not.

The layout is a contract. `README.md` reproduces it verbatim and the linter
diffs the two byte for byte.
"""

from __future__ import annotations

SCRIPT_VERSION = "3.0.0"
SCRIPT_NAME = "build-magick.py"

LABEL_WIDTH = 27

ACTIONS = (
    ("-b, --build", "Build and install ImageMagick"),
    ("-c, --cleanup", "Remove this project's build root and build leftovers"),
)
OPTIONS = (
    ("-h, --help", "Show this help without changing the filesystem"),
    ("-v, --version", "Show the script version"),
    ("    --config <path>", "Load build/package choices from TOML"),
    ("-j, --jobs <count>", "Set parallel build jobs (default: available CPUs)"),
    ("-g, --gcc-version <9-14>", "GCC major version (default: newest for this OS)"),
    ("-l, --latest", "Refresh upstream versions and rebuild outdated packages"),
    ("-d, --debug", "Stream command output while also logging it"),
)
ENVIRONMENT = (("BUILD_ROOT=/path", "Override the default ./build directory"),)

# Options that take a separate argument. Every walk over the command line skips
# that argument and stops at `--`, so an option's value is never mistaken for an
# option: `--config -h` means a file named '-h', not a request for help.
TAKES_VALUE = frozenset(["--config", "-j", "--jobs", "-g", "--gcc-version"])


def _row(label: str, description: str) -> str:
    return "  " + label.ljust(LABEL_WIDTH) + " " + description


def usage_text() -> str:
    lines = [
        "",
        "ImageMagick Build Script " + SCRIPT_VERSION,
        "Usage: " + SCRIPT_NAME + " [options]",
        "",
        "Actions:",
    ]
    lines += [_row(label, description) for label, description in ACTIONS]
    lines += ["", "Options:"]
    lines += [_row(label, description) for label, description in OPTIONS]
    lines += [
        "",
        "Long options also accept --option=value (for example: --jobs=8).",
        "",
        "Environment:",
    ]
    lines += [_row(label, description) for label, description in ENVIRONMENT]
    lines += [
        "",
        "Examples:",
        "  python3 " + SCRIPT_NAME + " --build",
        "  python3 " + SCRIPT_NAME + " --build --latest --jobs 8 --gcc-version 13",
        "  python3 " + SCRIPT_NAME + " --build --config ./custom.toml",
        "",
    ]
    return "\n".join(lines) + "\n"


def metadata_response(argv: list[str]) -> str | None:
    """Answer `--help`/`--version`, or return None when neither was requested.

    This walk runs before the interpreter is resolved, so on that path it is
    the only thing standing between `-- -h` and a help screen.
    """
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--":
            return None
        if argument in ("-h", "--help"):
            return usage_text()
        if argument in ("-v", "--version"):
            return SCRIPT_VERSION + "\n"
        if argument in TAKES_VALUE:
            index += 1
        index += 1
    return None
