"""Recipe helpers shared by the library stages."""

from __future__ import annotations

from pathlib import Path

from ..runtime.context import BuildContext


def configure_make_install(context: BuildContext, source: Path, *options: str) -> None:
    """`sh configure --prefix=<workspace> ...`, then make and make install."""
    context.execute(["sh", "configure", f"--prefix={context.workspace}", *options], cwd=source)
    context.make(source)
    context.make(source, "install", jobs=False)


def ninja_install(context: BuildContext, source: Path, build_dir: str | None = "build") -> None:
    """Build and install with ninja, in `build_dir` or in the source tree."""
    directory = ["-C", build_dir] if build_dir else []
    context.execute(["ninja", f"-j{context.build_threads}", *directory], cwd=source)
    context.execute(["ninja", *directory, "install"], cwd=source)


def meson_static_install(context: BuildContext, source: Path, *options: str) -> None:
    context.execute(
        [
            "meson",
            "setup",
            "build",
            f"--prefix={context.workspace}",
            "--buildtype=release",
            "--default-library=static",
            "--strip",
            *options,
        ],
        cwd=source,
    )
    ninja_install(context, source)


def cmake_release_options(context: BuildContext, *, pic: str = "TRUE") -> list[str]:
    return [
        f"-DCMAKE_INSTALL_PREFIX={context.workspace}",
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_POSITION_INDEPENDENT_CODE={pic}",
    ]


def each_define(prefix: str, value: str, *names: str) -> list[str]:
    """`-D<name>=<value>` for each name, the Bash brace-expansion idiom."""
    return [f"{prefix}{name}={value}" for name in names]
