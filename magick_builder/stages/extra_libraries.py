"""jemalloc, OpenJPEG and Little CMS.

OpenCL is not here: ImageMagick dlopens the system libOpenCL.so at run time
whatever it was linked against, so the APT ocl-icd-opencl-dev package provides
both the headers configure probes and the library that is actually loaded.
"""

from __future__ import annotations

from ..runtime.context import BuildContext
from .helpers import (
    cmake_release_options,
    configure_make_install,
    each_define,
    ninja_install,
)


def install_extra_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Extra Libraries")
    env = context.env

    resolved = context.resolve("jemalloc")
    if resolved and context.build("jemalloc", resolved.version):
        source = context.download(
            f"https://github.com/jemalloc/jemalloc/archive/refs/tags/{resolved.tag}.tar.gz",
            f"jemalloc-{resolved.version}.tar.gz",
        )
        # The GitHub archive ships no configure. Statistics, debugging and
        # fill support are run-time-off features that still cost code; the
        # malloc_stats_print probe ImageMagick runs survives --disable-stats.
        # A shared libjemalloc is dlopened through PerlMagick's module, which
        # its default initial-exec TLS model cannot survive ("cannot allocate
        # memory in static TLS block"); the static default links it in.
        context.execute(["sh", "autogen.sh"], cwd=source)
        configure_make_install(
            context,
            source,
            *(f"--disable-{feature}" for feature in ("debug", "doc", "fill", "stats")),
            *(["--disable-initial-exec-tls"] if context.shared else []),
            f"CFLAGS={env['CFLAGS']}",
            libtool=False,
        )
        context.build_done("jemalloc", resolved.version, resolved.commit)

    resolved = context.resolve("openjpeg")
    if resolved and context.build("openjpeg", resolved.version):
        source = context.download(
            f"https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/{resolved.tag}",
            f"openjpeg-{resolved.version}.tar.gz",
        )
        shared, static = ("ON", "OFF") if context.shared else ("OFF", "ON")
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context),
                f"-DBUILD_SHARED_LIBS={shared}",
                f"-DBUILD_STATIC_LIBS={static}",
                *each_define("-DBUILD_", "OFF", "CODEC", "DOC", "TESTING"),
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source)
        context.build_done("openjpeg", resolved.version, resolved.commit)

    resolved = context.resolve("lcms2")
    if resolved and context.build("lcms2", resolved.version):
        source = context.download(
            f"https://github.com/mm2/Little-CMS/archive/refs/tags/{resolved.tag}.tar.gz",
            f"lcms2-{resolved.version}.tar.gz",
        )
        # No plugins: the threaded and fast-float plugins are GPL-3 and
        # lcms2.pc would put them on the public link line while ImageMagick
        # never activates a plugin. jpeg and tiff only feed the lcms utilities.
        context.execute(["sh", "autogen.sh"], cwd=source)
        configure_make_install(context, source, "--without-jpeg", "--without-tiff")
        context.build_done("lcms2", resolved.version, resolved.commit)
