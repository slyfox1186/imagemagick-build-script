"""Recipe helpers shared by the library stages.

Every workspace library follows the build's link mode: an archive by default,
so ImageMagick links it in (the linker would take a shared object over an
archive of the same name), or a shared object with `--shared`.
"""

from __future__ import annotations

from pathlib import Path

from ..runtime.context import BuildContext


def autotools_link_options(context: BuildContext, *, libtool: bool = True) -> list[str]:
    """`--with-pic` keeps a libtool archive's members PIC (a static-only libtool
    build compiles them non-PIC otherwise, and they end up in PIE executables);
    a hand-written configure such as jemalloc's does not know the option."""
    options = (
        ["--enable-shared", "--disable-static"]
        if context.shared
        else ["--disable-shared", "--enable-static"]
    )
    return [*options, "--with-pic"] if libtool else options


def cmake_link_options(context: BuildContext) -> list[str]:
    return [f"-DBUILD_SHARED_LIBS={'ON' if context.shared else 'OFF'}"]


def meson_link_options(context: BuildContext) -> list[str]:
    """meson never strips static archives, so --strip only matters for shared objects."""
    if context.shared:
        return ["--default-library=shared", "--strip"]
    return ["--default-library=static"]


def configure_make_install(
    context: BuildContext, source: Path, *options: str, library: bool = True, libtool: bool = True
) -> None:
    """`sh configure --prefix=<workspace> ...`, then make and make install.

    A library gets the link-mode options; a tool without libtool would only
    report them as unrecognized.
    """
    link = autotools_link_options(context, libtool=libtool) if library else []
    context.execute(
        ["sh", "configure", f"--prefix={context.workspace}", *link, *options], cwd=source
    )
    context.make(source)
    context.make(source, "install", jobs=False)


def ninja_install(context: BuildContext, source: Path, build_dir: str | None = "build") -> None:
    """Build and install with ninja, in `build_dir` or in the source tree."""
    directory = ["-C", build_dir] if build_dir else []
    context.execute(["ninja", f"-j{context.build_threads}", *directory], cwd=source)
    context.execute(["ninja", *directory, "install"], cwd=source)


def meson_install(context: BuildContext, source: Path, *options: str) -> None:
    """`b_ndebug=if-release` because meson's release buildtype keeps asserts on.

    `--libdir=lib` puts the archives where every other workspace library is:
    meson's Debian default, `lib/<multiarch>`, is a second directory that a
    system `-L` can precede on ImageMagick's link line.
    """
    context.execute(
        [
            "meson",
            "setup",
            "build",
            f"--prefix={context.workspace}",
            "--libdir=lib",
            "--buildtype=release",
            "-Db_ndebug=if-release",
            *meson_link_options(context),
            *options,
        ],
        cwd=source,
    )
    ninja_install(context, source)


def cmake_release_options(context: BuildContext) -> list[str]:
    """PIC is explicit: CMake applies it to shared targets only by default.

    The link mode is not here: libjpeg-turbo and OpenJPEG spell it their own
    way, the rest take `cmake_link_options`.
    """
    return [
        f"-DCMAKE_INSTALL_PREFIX={context.workspace}",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
    ]


def each_define(prefix: str, value: str, *names: str) -> list[str]:
    """`-D<name>=<value>` for each name, the Bash brace-expansion idiom."""
    return [f"{prefix}{name}={value}" for name in names]
