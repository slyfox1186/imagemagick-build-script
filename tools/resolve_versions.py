#!/usr/bin/env python3
"""Resolution gate: run every upstream resolver the build uses and report the result.

Network required. Uses `resolve_upstream`, the same dispatch the build stages
use, so a grammar that stops matching upstream fails here first.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from magick_builder import registry  # noqa: E402
from magick_builder.runtime.context import resolve_upstream  # noqa: E402
from magick_builder.runtime.exec import Runner, base_environment  # noqa: E402
from magick_builder.runtime.logging import Logger  # noqa: E402
from magick_builder.runtime.versions import VersionResolver  # noqa: E402


def main() -> int:
    logger = Logger()
    resolver = VersionResolver(Runner(logger, base_environment()), logger)
    failures = 0
    for package in registry.PACKAGE_LIST:
        if package.source is registry.Source.FIXED:
            continue
        resolved = resolve_upstream(resolver, package.key)
        if resolved is None:
            print(f"{package.key:<16} RESOLUTION FAILED")
            failures += 1
            continue
        print(
            f"{package.key:<16} tag={resolved.tag or '-':<14} version={resolved.version:<12} "
            f"commit={resolved.commit or '-'}"
        )
    if failures:
        print(f"{failures} resolver(s) FAILED", file=sys.stderr)
        return 1
    print("All resolvers returned valid results.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
