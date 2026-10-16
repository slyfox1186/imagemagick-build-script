"""The text rendering stack: FreeType, libxml2, fontconfig, FriBidi, HarfBuzz, raqm.

FreeType, libxml2 and fontconfig are cloned rather than downloaded: their
forges bot-gate generated archives (see `download.USER_AGENT`), and the clone is
verified against the resolved commit.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..runtime.context import BuildContext
from ..runtime.paths import safe_remove_tree
from .helpers import (
    autotools_link_options,
    cmake_link_options,
    cmake_release_options,
    each_define,
    meson_install,
    ninja_install,
)

# libxml2 modules no consumer reaches: ImageMagick's svg and msl coders use
# the push parser with SAX1 callbacks, policy.c and profile.c xmlReadMemory,
# and fontconfig the same push parser. PUSH, SAX1, THREADS, ICONV, OUTPUT,
# VALID and CATALOG stay at their defaults.
LIBXML2_UNUSED_MODULES = (
    "DEBUG",
    "HTML",
    "MODULES",
    "PATTERN",
    "PROGRAMS",
    "PYTHON",
    "READER",
    "REGEXPS",
    "RELAXNG",
    "SCHEMAS",
    "TESTS",
    "WRITER",
    "XINCLUDE",
    "XPATH",
)
# Everything HarfBuzz can build beyond the shaping library raqm links: the
# subset, raster, vector and GPU libraries, the utilities, and the optional
# backends. glib and gobject must stay off: enabling them adds a glib Requires
# to the workspace harfbuzz.pc, which drags the system -L directory into
# consumers' link resolution, and raqm then resolved the older system
# libharfbuzz.so instead of the workspace library.
HARFBUZZ_DISABLED_FEATURES = (
    "benchmark",
    "cairo",
    "chafa",
    "docs",
    "fontations",
    "glib",
    "gobject",
    "gpu",
    "gpu_demo",
    "graphite2",
    "harfrust",
    "icu",
    "introspection",
    "kbts",
    "png",
    "raster",
    "subset",
    "tests",
    "utilities",
    "vector",
    "wasm",
    "zlib",
)


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


def install_under_workspace(context: BuildContext, source: Path) -> None:
    """`make install` through DESTDIR, keeping only what lands in the workspace.

    The /etc, /var and /usr/share files belong to the system's fontconfig
    packages; writing them would need root, and DESTDIR also skips fc-cache.
    """
    destination = context.packages / "fontconfig-destdir"
    if destination.exists():
        safe_remove_tree(destination, context.packages)
    context.make(source, "install", f"DESTDIR={destination}", jobs=False)
    shutil.copytree(
        destination / context.workspace.relative_to("/"),
        context.workspace,
        symlinks=True,
        dirs_exist_ok=True,
    )
    safe_remove_tree(destination, context.packages)


def install_text_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Text Libraries")
    env = context.env

    resolved = context.resolve("freetype")
    if resolved and context.build("freetype", resolved.version):
        # autogen.sh copies sources from the pinned dlg submodule, which
        # generated archives omit.
        source = context.clone("freetype", resolved, recurse=True)
        context.execute(["sh", "autogen.sh"], cwd=source)
        # zlib=internal keeps gzip-compressed fonts readable through the
        # bundled inflate; `disabled` would drop the support outright. png is
        # colour bitmap glyphs, which ImageMagick never requests
        # (annotate.c loads grayscale and mono bitmaps only); harfbuzz would
        # need the two-pass build or a run-time-loaded shared HarfBuzz.
        meson_install(
            context,
            source,
            "-Dzlib=internal",
            *each_define("-D", "disabled", "harfbuzz", "png", "bzip2", "brotli", "tests"),
        )
        context.build_done("freetype", resolved.version, resolved.commit)

    resolved = context.resolve("libxml2")
    if resolved and context.build("libxml2", resolved.version):
        source = context.clone("libxml2", resolved)
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context),
                *cmake_link_options(context),
                # The default XML catalog path is compiled into ImageMagick;
                # the workspace one is deleted with the build root.
                "-DCMAKE_INSTALL_SYSCONFDIR=/etc",
                *each_define("-DLIBXML2_WITH_", "OFF", *LIBXML2_UNUSED_MODULES),
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
        # autotools, not meson: fontconfig's meson build needs meson 1.6.1 and
        # Ubuntu 22.04 ships 0.61. No --with-arch: a forced architecture names
        # cache files `-x86_64.cache-N` while the system fc-cache writes
        # `-le64`, so the library could never read the caches the fonts stage
        # builds.
        context.execute(["sh", "autogen.sh", "--noconf"], cwd=source)
        context.execute(
            [
                "sh",
                "configure",
                f"--prefix={context.workspace}",
                *autotools_link_options(context),
                "--disable-docbook",
                "--disable-docs",
                "--disable-nls",
                "--enable-iconv",
                "--enable-libxml2",
                # Configuration, templates and cache locations are compiled into
                # ImageMagick: use the system's, which outlive the build root.
                "--sysconfdir=/etc",
                "--localstatedir=/var",
                "--with-templatedir=/usr/share/fontconfig/conf.avail",
                f"CFLAGS={env['CFLAGS']}",
                f"LDFLAGS={env['LDFLAGS']}",
            ],
            cwd=source,
        )
        context.make(source)
        install_under_workspace(context, source)
        context.build_done("fontconfig", resolved.version, resolved.commit)

    resolved = context.resolve("fribidi")
    if resolved and context.build("fribidi", resolved.version):
        source = context.download(
            f"https://github.com/fribidi/fribidi/archive/refs/tags/{resolved.tag}.tar.gz",
            f"fribidi-{resolved.version}.tar.gz",
        )
        meson_install(context, source, *each_define("-D", "false", "bin", "docs", "tests"))
        context.build_done("fribidi", resolved.version, resolved.commit)

    resolved = context.resolve("harfbuzz")
    if resolved and context.build("harfbuzz", resolved.version):
        source = context.download(
            f"https://github.com/harfbuzz/harfbuzz/archive/refs/tags/{resolved.tag}.tar.gz",
            f"harfbuzz-{resolved.version}.tar.gz",
        )
        # freetype is explicit so a missing workspace FreeType fails here
        # instead of silently building the shaper without its font functions.
        meson_install(
            context,
            source,
            "-Dfreetype=enabled",
            *each_define("-D", "disabled", *HARFBUZZ_DISABLED_FEATURES),
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
        meson_install(context, source, *each_define("-D", "false", "docs", "sheenbidi", "tests"))
        context.build_done("raqm", resolved.version, resolved.commit)
