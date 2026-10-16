"""Failure types shared by every module.

`BuildError` replaces the Bash `fail()` helper. Raising rather than exiting is
what makes the recovery sites (a download that falls back to a mirror, a probe
whose failure is expected) expressible at all: Bash had to choose between
`fail`, which exits, and `warn` plus a return code, which callers could forget
to check.
"""

from __future__ import annotations

REPOSITORY_URL = "https://github.com/slyfox1186/imagemagick-build-script"
ISSUE_TRACKER_URL = f"{REPOSITORY_URL}/issues"


class SignalStop(BaseException):
    """A termination signal, carrying the exit status it should produce."""

    def __init__(self, name: str, exit_code: int) -> None:
        super().__init__(name)
        self.name = name
        self.exit_code = exit_code


class BuildError(Exception):
    """A fatal, reportable build failure."""


class UsageError(BuildError):
    """An invalid command line or configuration file.

    Separate from `BuildError` so the launcher can report it without the
    bug-report footer: a mistyped option is not a defect worth filing.
    """
