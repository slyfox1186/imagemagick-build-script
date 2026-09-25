#!/usr/bin/env python3
"""Run static analysis and the repository's generated-contract checks."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

from magick_builder import registry
from magick_builder.config import BuildSettings, default_states, render_config

REPO_ROOT = Path(__file__).resolve().parent


def contract_errors(root: Path) -> list[str]:
    errors: list[str] = []
    template = (root / "example.toml").read_text(encoding="utf-8")
    if set(tomllib.loads(template)["packages"]) != set(registry.PACKAGE_NAMES):
        errors.append("example.toml and the registry list different packages.")
    if template != render_config(BuildSettings(), default_states()):
        errors.append("example.toml differs from config.render_config(); regenerate it.")

    completed = subprocess.run(
        [sys.executable, "-B", str(root / "build-magick.py"), "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    readme = (root / "README.md").read_text(encoding="utf-8")
    blocks = [
        block
        for block in re.findall(r"```text\n(.*?)\n```", readme, re.S)
        if "Usage: build-magick.py" in block
    ]
    if completed.returncode != 0 or blocks != [completed.stdout]:
        errors.append("README.md CLI block must match live --help byte for byte.")

    files = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    # Assembling the tokens keeps this checker from flagging its own source.
    forbidden = ("apt" + "-get", "apt" + "-cache", "auto" + "remove")
    for raw_name in sorted(set(files.stdout.split(b"\0")) - {b""}):
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
            if path.suffix in (".py", ".yml", ".yaml"):
                for token in forbidden:
                    if token in line:
                        errors.append(
                            f"{path.relative_to(root)}:{number}: forbidden APT usage '{token}'"
                        )
    return errors


def main() -> int:
    failed = False
    for command in (("ruff", "check", "."), ("ruff", "format", "--check", "."), ("mypy",)):
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
