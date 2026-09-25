"""Font families from their upstream repositories, pinned to the HEAD commit.

DejaVu is deliberately absent: its source repository ships no built fonts at
HEAD, and the fonts-dejavu-core APT package provides the exact directory
ImageMagick's --with-dejavu-font-dir points at. The font repositories' newest
tags are years older than their content, so a tag pin would regress them.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import FONT_PACKAGES
from ..runtime.context import FONT_ROOT, BuildContext
from ..runtime.errors import BuildError


def font_files(checkout: Path) -> list[Path]:
    """Only real font files, never the repository's history, sources or scripts."""
    return sorted(
        path
        for path in checkout.rglob("*")
        if path.suffix.lower() in (".ttf", ".otf")
        and path.is_file()
        and not path.is_symlink()
        and ".git" not in path.relative_to(checkout).parts
    )


def install_font_files(context: BuildContext, key: str, checkout: Path) -> None:
    files = font_files(checkout)
    if not files:
        raise BuildError(
            f"No .ttf/.otf files found in the {key} repository; refusing to record it as installed."
        )
    destination = FONT_ROOT / key
    # -D creates the destination; the terminal shows a count, the log every file.
    command = ["sudo", "install", "-D", "-m", "644", "-t", str(destination)]
    context.execute(
        [*command, *(str(path.relative_to(checkout)) for path in files)],
        cwd=checkout,
        display=f"{' '.join(command)} <{len(files)} font files>",
    )


def install_fonts(context: BuildContext) -> None:
    if not any(context.package_enabled(key) for key in FONT_PACKAGES):
        context.packages_disabled += len(FONT_PACKAGES)
        return
    context.logger.banner("Installing Fonts")
    for key in FONT_PACKAGES:
        resolved = context.resolve(key)
        if resolved and context.build(key, resolved.version):
            checkout = context.clone(key, resolved)
            install_font_files(context, key, checkout)
            context.build_done(key, resolved.version)
    # The fontconfig cache refresh is the stage's only other privileged step.
    context.sudo("fc-cache", "-f")
