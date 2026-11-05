#!/usr/bin/env python3
"""Run static analysis and the repository's generated-contract checks."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from magick_builder import registry
from magick_builder.config import BuildSettings, default_states, render_config

REPO_ROOT = Path(__file__).resolve().parent
# Developer directories that .gitignore keeps out of the published repository.
# They are still checked whenever they exist in the checkout.
LOCAL_ONLY_DIRECTORIES = ("tests", "tools")
# What identifies the help screen among the README's text blocks.
HELP_MARKER = "Usage: python3 build-magick.py"


def checked_files(root: Path) -> set[bytes]:
    published = ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    local_only = ["git", "ls-files", "-z", "--others", "--ignored", "--exclude-standard"]
    names: set[bytes] = set()
    for command in (published, [*local_only, "--", *LOCAL_ONLY_DIRECTORIES]):
        listing = subprocess.run(command, cwd=root, capture_output=True, check=True)
        names.update(listing.stdout.split(b"\0"))
    return names - {b""}


def mypy_targets(root: Path) -> list[str]:
    with (root / "pyproject.toml").open("rb") as handle:
        configured: list[str] = tomllib.load(handle)["tool"]["mypy"]["files"]
    return [name for name in configured if (root / name).exists()]


def contract_errors(root: Path) -> list[str]:
    errors: list[str] = []
    template = (root / "example.toml").read_text(encoding="utf-8")
    keys = set(tomllib.loads(template)["packages"])
    declared = [package.key for package in registry.PACKAGE_LIST]
    registered = set(registry.PACKAGE_NAMES)
    if keys != registered or len(set(declared)) != len(declared):
        errors.append(
            f"Template/registry mismatch: template-only={sorted(keys - registered)}, "
            f"registry-only={sorted(registered - keys)}; duplicate registry keys are forbidden."
        )
    if template != render_config(BuildSettings(), default_states()):
        errors.append("example.toml differs from config.render_config(); regenerate it.")

    completed = subprocess.run(
        [sys.executable, "-B", str(root / "build-magick.py"), "--help"],
        cwd=root,
        # Color never reaches the README, whatever the caller's environment.
        env={**os.environ, "NO_COLOR": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    readme = (root / "README.md").read_text(encoding="utf-8")
    blocks = [
        block for block in re.findall(r"```text\n(.*?)\n```", readme, re.S) if HELP_MARKER in block
    ]
    if completed.returncode != 0 or blocks != [completed.stdout]:
        errors.append("README.md CLI block must match live --help byte for byte.")

    # Assembling the tokens keeps this checker from flagging its own source.
    forbidden = ("apt" + "-get", "apt" + "-cache", "auto" + "remove")
    for raw_name in sorted(checked_files(root)):
        path = root / raw_name.decode("utf-8", "surrogateescape")
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(content.splitlines(), 1):
            if line.rstrip(" \t") != line:
                errors.append(f"{path.relative_to(root)}:{number}: trailing whitespace")
            if path.suffix in (".py", ".sh", ".yml", ".yaml"):
                for token in forbidden:
                    if token in line:
                        errors.append(
                            f"{path.relative_to(root)}:{number}: forbidden APT usage '{token}'"
                        )
    return errors


def main() -> int:
    failed = False
    # tests/ and tools/ are local-only (gitignored); check them when present.
    # Ruff skips gitignored files under ".", so they are named explicitly.
    local = tuple(name for name in LOCAL_ONLY_DIRECTORIES if (REPO_ROOT / name).is_dir())
    mypy = ("mypy", *mypy_targets(REPO_ROOT))
    ruff = (("ruff", "check", ".", *local), ("ruff", "format", "--check", ".", *local))
    for command in (*ruff, mypy):
        result = subprocess.run([sys.executable, "-m", *command], cwd=REPO_ROOT, check=False)
        failed |= result.returncode != 0
    try:
        errors = contract_errors(REPO_ROOT)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        errors = [f"Unable to check repository contracts: {error}"]
    for diagnostic in errors:
        print(diagnostic, file=sys.stderr)
    if not errors:
        print(f"Repository contracts: OK ({len(registry.PACKAGE_NAMES)} packages)")
    return int(failed or bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
