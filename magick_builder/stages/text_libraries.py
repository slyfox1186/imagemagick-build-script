"""The text rendering stack: FreeType, libxml2, fontconfig, FriBidi, HarfBuzz, raqm.

FreeType, libxml2 and fontconfig are cloned rather than downloaded: their
forges bot-gate generated archives (see `download.USER_AGENT`), and the clone is
verified against the resolved commit.
"""

from __future__ import annotations

from pathlib import Path

from ..runtime.context import BuildContext
from .helpers import cmake_release_options, each_define, meson_static_install, ninja_install


def ensure_harfbuzz_gobject_shim(context: BuildContext, version: str) -> None:
    """Keep a system harfbuzz-gobject resolvable while the workspace shadows harfbuzz.

    The workspace harfbuzz.pc shadows the system one, so any system `.pc` that
    exact-pins the system harfbuzz version cannot resolve. On Debian 13,
    librsvg's Requires chain reaches harfbuzz-gobject ("requires harfbuzz =
    10.2.0"), which silently killed ImageMagick's rsvg delegate probe. This
    companion forwards to the system library at our harfbuzz version, without
    adding Requires to harfbuzz.pc itself (doing that dragged the system -L
    directory into raqm's link resolution and broke it).
    """
    multiarch = context.multiarch
    if not Path(f"/usr/lib/{multiarch}/pkgconfig/harfbuzz-gobject.pc").is_file():
        return
    for directory in ("lib/pkgconfig", "lib64/pkgconfig", f"lib/{multiarch}/pkgconfig"):
        pc_directory = context.workspace / directory
        if not (pc_directory / "harfbuzz.pc").is_file():
            continue
        (pc_directory / "harfbuzz-gobject.pc").write_text(
            "Name: harfbuzz-gobject (workspace compatibility shim)\n"
            "Description: Forwards to the system harfbuzz-gobject while the workspace "
            "shadows harfbuzz\n"
            f"Version: {version}\n"
            "Requires: harfbuzz\n"
            f"Libs: -L/usr/lib/{multiarch} -lharfbuzz-gobject\n"
            "Cflags: -I/usr/include/harfbuzz\n",
            encoding="utf-8",
        )
        context.logger.info(f"Wrote the harfbuzz-gobject compatibility shim to {pc_directory}")
        return


def libiconv_cmake_options(context: BuildContext) -> list[str]:
    """Point CMake at a standalone GNU libiconv when one is installed."""
    for directory in (context.workspace / "lib", Path("/usr/local/lib"), Path("/usr/lib")):
        library = next(
            (
                directory / f"libiconv.{suffix}"
                for suffix in ("a", "so")
                if (directory / f"libiconv.{suffix}").is_file()
            ),
            None,
        )
        include = directory.parent / "include"
        if library is not None and (include / "iconv.h").is_file():
            return [f"-DIconv_INCLUDE_DIR={include}", f"-DIconv_LIBRARY={library}"]
    return []


def install_text_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Text Libraries")
    env = context.env

    resolved = context.resolve("freetype")
    if resolved and context.build("freetype", resolved.version):
        # autogen.sh copies sources from the pinned dlg submodule, which
        # generated archives omit.
        source = context.clone("freetype", resolved, recurse=True)
        context.execute(["sh", "autogen.sh"], cwd=source)
        meson_static_install(
            context,
            source,
            *each_define("-D", "disabled", "harfbuzz", "png", "bzip2", "brotli", "zlib", "tests"),
        )
        context.build_done("freetype", resolved.version, resolved.commit)

    resolved = context.resolve("libxml2")
    if resolved and context.build("libxml2", resolved.version):
        source = context.clone("libxml2", resolved)
        # A pure CMake build. ImageMagick needs no libxml2 Python bindings, and
        # probing python3.x-config is a hard failure on Ubuntu 22.04, so they
        # are pinned off regardless of upstream defaults.
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context),
                "-DBUILD_SHARED_LIBS=OFF",
                "-DLIBXML2_WITH_PYTHON=OFF",
                *libiconv_cmake_options(context),
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source)
        context.build_done("libxml2", resolved.version, resolved.commit)

    resolved = context.resolve("fontconfig")
    if resolved and context.build("fontconfig", resolved.version):
        source = context.clone("fontconfig", resolved)
        # The static libxml2 needs LIBXML_STATIC in every consumer's flags.
        template = source / "fontconfig.pc.in"
        template.write_text(
            template.read_text(encoding="utf-8").replace("Cflags:", "Cflags: -DLIBXML_STATIC"),
            encoding="utf-8",
        )
        context.execute(["sh", "autogen.sh", "--noconf"], cwd=source)
        multiarch = context.multiarch
        context.execute(
            [
                "sh",
                "configure",
                f"--prefix={context.workspace}",
                "--disable-docbook",
                "--disable-docs",
                "--disable-shared",
                "--disable-nls",
                "--enable-iconv",
                "--enable-libxml2",
                "--enable-static",
                "--with-arch=x86_64",
                "--with-libiconv-prefix=/usr",
                "--with-pic",
                f"CFLAGS={env['CFLAGS']} -I/usr/include -I/usr/include/libxml2",
                f"LDFLAGS={env['LDFLAGS']} -DLIBXML_STATIC -L/usr/lib/{multiarch} -lz -llzma",
            ],
            cwd=source,
        )
        context.make(source)
        context.make(source, "install", jobs=False)
        context.build_done("fontconfig", resolved.version, resolved.commit)

    resolved = context.resolve("fribidi")
    if resolved and context.build("fribidi", resolved.version):
        source = context.download(
            f"https://github.com/fribidi/fribidi/archive/refs/tags/{resolved.tag}.tar.gz",
            f"fribidi-{resolved.version}.tar.gz",
        )
        meson_static_install(context, source, *each_define("-D", "false", "docs", "tests"))
        context.build_done("fribidi", resolved.version, resolved.commit)

    resolved = context.resolve("harfbuzz")
    if resolved and context.build("harfbuzz", resolved.version):
        source = context.download(
            f"https://github.com/harfbuzz/harfbuzz/archive/refs/tags/{resolved.tag}.tar.gz",
            f"harfbuzz-{resolved.version}.tar.gz",
        )
        # glib/gobject must stay disabled: enabling them adds a glib Requires to
        # the workspace harfbuzz.pc, which drags the system -L directory into
        # consumers' link resolution, and raqm then resolved the older system
        # libharfbuzz.so instead of the workspace static library.
        meson_static_install(
            context,
            source,
            *each_define(
                "-D",
                "disabled",
                "benchmark",
                "cairo",
                "docs",
                "glib",
                "gobject",
                "icu",
                "introspection",
                "tests",
            ),
        )
        context.build_done("harfbuzz", resolved.version, resolved.commit)
    if resolved:
        ensure_harfbuzz_gobject_shim(context, resolved.version)

    resolved = context.resolve("raqm")
    if resolved and context.build("raqm", resolved.version):
        source = context.download(
            f"https://codeload.github.com/host-oman/libraqm/tar.gz/refs/tags/{resolved.tag}",
            f"raqm-{resolved.version}.tar.gz",
        )
        meson_static_install(
            context, source, f"--includedir={context.workspace}/include", "-Ddocs=false"
        )
        context.build_done("raqm", resolved.version, resolved.commit)
