"""Image format libraries: jpeg, webp, tiff, FlashPix, png.

Ghostscript is not here: ImageMagick's gslib delegate is the APT libgs and the
`gs` binary it runs comes from the APT ghostscript package (see system_setup).
"""

from __future__ import annotations

from ..runtime.context import BuildContext
from .helpers import (
    cmake_link_options,
    cmake_release_options,
    configure_make_install,
    each_define,
    ninja_install,
)


def install_image_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Image Libraries")
    shared, static = ("ON", "OFF") if context.shared else ("OFF", "ON")

    # libjpeg-turbo and libwebp build before libtiff: its configure enables the
    # jpeg and webp codecs only when their libraries are already present.
    resolved = context.resolve("libjpeg-turbo")
    if resolved and context.build("libjpeg-turbo", resolved.version):
        source = context.clone("libjpeg-turbo", resolved)
        # ImageMagick links -ljpeg only, never the TurboJPEG API.
        context.execute(
            [
                "cmake",
                "-S",
                ".",
                *cmake_release_options(context),
                f"-DENABLE_SHARED={shared}",
                f"-DENABLE_STATIC={static}",
                "-DWITH_TURBOJPEG=OFF",
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source, build_dir=None)
        context.build_done("libjpeg-turbo", resolved.version, resolved.commit)

    resolved = context.resolve("libwebp")
    if resolved and context.build("libwebp", resolved.version):
        source = context.clone("libwebp", resolved)
        # Only the libraries: ImageMagick needs libwebp, libwebpmux and
        # libwebpdemux, and the command-line tools are what drag in the
        # png/jpeg/tiff probes.
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context),
                *cmake_link_options(context),
                "-DWEBP_BUILD_LIBWEBPMUX=ON",
                *each_define(
                    "-DWEBP_BUILD_",
                    "OFF",
                    "ANIM_UTILS",
                    "CWEBP",
                    "DWEBP",
                    "EXTRAS",
                    "GIF2WEBP",
                    "IMG2WEBP",
                    "VWEBP",
                    "WEBPINFO",
                    "WEBPMUX",
                ),
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source)
        context.build_done("libwebp", resolved.version, resolved.commit)

    resolved = context.resolve("libtiff")
    if resolved and context.build("libtiff", resolved.version):
        source = context.download(
            f"https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/{resolved.tag}",
            f"libtiff-{resolved.version}.tar.gz",
        )
        context.execute(["autoreconf", "-fi"], cwd=source)
        # ImageMagick uses the C API; the codecs (jpeg, webp, zlib, zstd, lzma,
        # jbig) are auto-detected from the workspace and the APT baseline.
        configure_make_install(
            context,
            source,
            *(f"--disable-{feature}" for feature in ("contrib", "cxx", "docs", "tests", "tools")),
        )
        context.build_done("libtiff", resolved.version, resolved.commit)

    resolved = context.resolve("libfpx")
    if resolved and context.build("libfpx", resolved.version):
        source = context.clone("libfpx", resolved)
        context.execute(["autoreconf", "-fi"], cwd=source)
        configure_make_install(context, source)
        context.build_done("libfpx", resolved.version)

    resolved = context.resolve("libpng")
    if resolved and context.build("libpng", resolved.version):
        source = context.download(
            f"https://github.com/pnggroup/libpng/archive/refs/tags/{resolved.tag}.tar.gz",
            f"libpng-{resolved.version}.tar.gz",
        )
        context.execute(["autoreconf", "-fi"], cwd=source)
        # libpng keeps its SSE filter code off unless asked.
        configure_make_install(
            context,
            source,
            "--enable-hardware-optimizations=yes",
            "--disable-tests",
            "--disable-tools",
        )
        context.build_done("libpng", resolved.version, resolved.commit)
