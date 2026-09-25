#!/usr/bin/env python3
"""Availability gate: every required APT package for this host's release exists.

Read-only; run `sudo apt update` first so the package index is current. Checks
the compiler pair of every GCC version the release offers, not just the default.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magick_builder.stages.system_setup import (  # noqa: E402
    APT_SCRIPT_OPTIONS,
    detect_release,
    gcc_versions,
    required_packages,
)


def main() -> int:
    distribution, version, _codename = detect_release(Path("/etc/os-release"))
    packages: list[str] = []
    for gcc in gcc_versions(distribution, version):
        for name in required_packages(distribution, version, gcc):
            if name not in packages:
                packages.append(name)
    unavailable = [
        name
        for name in packages
        if subprocess.run(
            ["apt", *APT_SCRIPT_OPTIONS, "show", name], capture_output=True, check=False
        ).returncode
        != 0
    ]
    if unavailable:
        print(
            f"UNAVAILABLE on {distribution} {version} ({len(unavailable)} of {len(packages)}): "
            + " ".join(unavailable),
            file=sys.stderr,
        )
        return 1
    print(f"All {len(packages)} required packages are available on {distribution} {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
