"""Image format libraries: jpeg, tiff, FlashPix, Ghostscript, png, webp."""

from __future__ import annotations

from ..runtime.context import BuildContext
from .helpers import cmake_release_options, configure_make_install, each_define, ninja_install


def install_image_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Image Libraries")
    workspace = context.workspace

    # libjpeg-turbo builds first: libtiff's configure probes for jpeg, and with
    # no system jpeg dev package installed the workspace library provides it.
    resolved = context.resolve("libjpeg-turbo")
    if resolved and context.build("libjpeg-turbo", resolved.version):
        source = context.clone("libjpeg-turbo", resolved)
        context.execute(
            [
                "cmake",
                "-S",
                ".",
                *cmake_release_options(context),
                "-DENABLE_STATIC=ON",
                "-DENABLE_SHARED=OFF",
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source, build_dir=None)
        context.build_done("libjpeg-turbo", resolved.version, resolved.commit)

    resolved = context.resolve("libtiff")
    if resolved and context.build("libtiff", resolved.version):
        source = context.download(
            f"https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/{resolved.tag}",
            f"libtiff-{resolved.version}.tar.gz",
        )
        context.execute(["autoreconf", "-fi"], cwd=source)
        # webp is explicitly off: libwebp builds after libtiff, so a clean run
        # never has it, and leaving the probe on made the result depend on
        # leftover workspace state (libtiff's link line also does not carry
        # libwebp's private libsharpyuv dependency).
        configure_make_install(
            context, source, "--enable-cxx", "--disable-docs", "--disable-webp", "--with-pic"
        )
        context.build_done("libtiff", resolved.version, resolved.commit)

    resolved = context.resolve("libfpx")
    if resolved and context.build("libfpx", resolved.version):
        source = context.clone("libfpx", resolved)
        context.execute(["autoreconf", "-fi"], cwd=source)
        configure_make_install(context, source, "--with-pic")
        context.build_done("libfpx", resolved.version)

    resolved = context.resolve("ghostscript")
    if resolved and context.build("ghostscript", resolved.version):
        source = context.download(
            "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"
            f"{resolved.tag}/ghostscript-{resolved.version}.tar.xz",
            f"ghostscript-{resolved.version}.tar.xz",
        )
        context.execute(["sh", "autogen.sh"], cwd=source)
        configure_make_install(context, source, "--with-libiconv=native")
        context.build_done("ghostscript", resolved.version, resolved.commit)

    resolved = context.resolve("libpng")
    if resolved and context.build("libpng", resolved.version):
        source = context.download(
            f"https://github.com/pnggroup/libpng/archive/refs/tags/{resolved.tag}.tar.gz",
            f"libpng-{resolved.version}.tar.gz",
        )
        context.execute(["autoreconf", "-fi"], cwd=source)
        configure_make_install(context, source, "--enable-hardware-optimizations=yes", "--with-pic")
        context.build_done("libpng", resolved.version, resolved.commit)

    resolved = context.resolve("libwebp")
    if resolved and context.build("libwebp", resolved.version):
        source = context.clone("libwebp", resolved)
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context),
                "-DBUILD_SHARED_LIBS=OFF",
                f"-DZLIB_INCLUDE_DIR={workspace}/include",
                *each_define("-DWEBP_BUILD_", "ON", "CWEBP", "DWEBP"),
                *each_define("-DWEBP_BUILD_", "OFF", "ANIM_UTILS", "EXTRAS", "VWEBP"),
                "-DWEBP_ENABLE_SWAP_16BIT_CSP=OFF",
                "-DWEBP_LINK_STATIC=ON",
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source)
        context.build_done("libwebp", resolved.version, resolved.commit)
