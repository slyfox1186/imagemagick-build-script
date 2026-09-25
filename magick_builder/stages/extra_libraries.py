"""jemalloc, the OpenCL SDK, OpenJPEG and Little CMS."""

from __future__ import annotations

from ..runtime.context import BuildContext
from .helpers import cmake_release_options, configure_make_install, each_define, ninja_install


def install_extra_libraries(context: BuildContext) -> None:
    context.logger.banner("Building Extra Libraries")
    env = context.env

    resolved = context.resolve("jemalloc")
    if resolved and context.build("jemalloc", resolved.version):
        source = context.download(
            f"https://github.com/jemalloc/jemalloc/archive/refs/tags/{resolved.tag}.tar.gz",
            f"jemalloc-{resolved.version}.tar.gz",
        )
        context.execute(["sh", "autogen.sh"], cwd=source)
        configure_make_install(
            context,
            source,
            *(
                f"--disable-{feature}"
                for feature in ("debug", "doc", "fill", "log", "prof", "stats")
            ),
            "--enable-autogen",
            "--enable-static",
            "--enable-xmalloc",
            f"CFLAGS={env['CFLAGS']}",
        )
        context.build_done("jemalloc", resolved.version, resolved.commit)

    resolved = context.resolve("opencl-sdk")
    if resolved and context.build("opencl-sdk", resolved.version):
        source = context.clone("opencl-sdk", resolved, recurse=True)
        context.execute(
            [
                "cmake",
                "-S",
                ".",
                "-B",
                "build",
                *cmake_release_options(context, pic="true"),
                "-DBUILD_SHARED_LIBS=OFF",
                *each_define("-DBUILD_", "OFF", "DOCS", "EXAMPLES", "TESTING"),
                *each_define("-DOPENCL_SDK_", "OFF", "BUILD_SAMPLES", "TEST_SAMPLES"),
                f"-DCMAKE_C_FLAGS={env['CFLAGS']}",
                f"-DCMAKE_CXX_FLAGS={env['CXXFLAGS']}",
                "-DOPENCL_HEADERS_BUILD_CXX_TESTS=OFF",
                "-DOPENCL_ICD_LOADER_BUILD_SHARED_LIBS=OFF",
                "-DOPENCL_SDK_BUILD_OPENGL_SAMPLES=OFF",
                "-DTHREADS_PREFER_PTHREAD_FLAG=ON",
                "-G",
                "Ninja",
                "-Wno-dev",
            ],
            cwd=source,
        )
        ninja_install(context, source)
        context.build_done("opencl-sdk", resolved.version, resolved.commit)

    resolved = context.resolve("openjpeg")
    if resolved and context.build("openjpeg", resolved.version):
        source = context.download(
            f"https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/{resolved.tag}",
            f"openjpeg-{resolved.version}.tar.gz",
        )
        context.execute(
            [
                "cmake",
                "-B",
                "build",
                *cmake_release_options(context, pic="true"),
                "-DBUILD_CODEC=OFF",
                *each_define("-DBUILD_", "OFF", "SHARED_LIBS", "TESTING", "THIRDPARTY"),
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
        context.execute(["sh", "autogen.sh"], cwd=source)
        configure_make_install(context, source, "--with-pic", "--with-threaded")
        context.build_done("lcms2", resolved.version, resolved.commit)
