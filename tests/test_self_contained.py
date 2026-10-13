"""The staged install stops depending on the build root before publication."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from magick_builder.runtime.context import BuildContext
from magick_builder.runtime.errors import BuildError
from magick_builder.stages.self_contained import (
    BUNDLED_LIBRARY_DIRECTORY,
    SelfContainedInstall,
    audit_published_install,
    parse_ldd,
)
from magick_builder.stages.system_setup import configure_environment

pytestmark = pytest.mark.skipif(
    not (shutil.which("gcc") and shutil.which("patchelf")), reason="needs gcc and patchelf"
)


def compile_library(directory: Path, soname: str, source: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "x.c").write_text(source)
    target = directory / soname
    subprocess.run(
        ["gcc", "-shared", "-fPIC", f"-Wl,-soname,{soname}", "-o", str(target), "x.c"],
        cwd=directory,
        check=True,
    )
    return target


def staged_tree(context: BuildContext) -> tuple[Path, Path]:
    """A workspace libdep.so.1 and a staged libuser.so linked to it like libtool does."""
    workspace_lib = context.workspace / "lib"
    compile_library(workspace_lib, "libdep.so.1", "int dep(void) { return 7; }\n")
    staging = context.packages / "imagemagick-staging"
    staged_lib = staging / "usr/local/lib"
    staged_lib.mkdir(parents=True)
    (staged_lib / "u.c").write_text("int dep(void);\nint user(void) { return dep(); }\n")
    subprocess.run(
        [
            "gcc",
            "-shared",
            "-fPIC",
            "-o",
            str(staged_lib / "libuser.so"),
            "u.c",
            f"-L{workspace_lib}",
            "-l:libdep.so.1",
            f"-Wl,-rpath,{workspace_lib}:/usr/local/lib",
            "-Wl,--enable-new-dtags",
        ],
        cwd=staged_lib,
        check=True,
    )
    (staged_lib / "u.c").unlink()
    return staging, staged_lib / "libuser.so"


def test_parse_ldd_reads_resolved_and_missing_libraries() -> None:
    output = (
        "\tlinux-vdso.so.1 (0x00007ffd)\n"
        "\tlibjemalloc.so.2 => not found\n"
        "\tlibc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f00)\n"
        "\t/lib64/ld-linux-x86-64.so.2 (0x00007f01)\n"
    )
    assert parse_ldd(output) == {
        "libjemalloc.so.2": None,
        "libc.so.6": "/lib/x86_64-linux-gnu/libc.so.6",
    }


def test_workspace_libraries_are_bundled_and_the_build_root_leaves_the_run_path(
    context: BuildContext,
) -> None:
    configure_environment(context)
    staging, library = staged_tree(context)
    installer = SelfContainedInstall(context, staging)
    installer.apply()

    bundled = staging / BUNDLED_LIBRARY_DIRECTORY.relative_to("/") / "libdep.so.1"
    assert bundled.is_file()
    # A host compiler may add run path entries of its own; those stay.
    entries = installer.run_path(library)
    assert entries[0] == str(BUNDLED_LIBRARY_DIRECTORY) and "/usr/local/lib" in entries
    assert not any(entry.startswith(str(context.cwd)) for entry in entries)
    # Deleting the build root's workspace no longer matters to the staged tree.
    shutil.rmtree(context.workspace)
    library_path = f"{staging}/usr/local/lib:{bundled.parent}"
    assert installer.dependencies(library, library_path)["libdep.so.1"] == str(bundled)


def test_publication_audit_rejects_a_library_loaded_from_the_build_root(
    context: BuildContext,
) -> None:
    configure_environment(context)
    _staging, library = staged_tree(context)
    with pytest.raises(BuildError, match="libdep.so.1 loads from the build root"):
        audit_published_install(context, [library])
    shutil.rmtree(context.workspace)
    with pytest.raises(BuildError, match="libdep.so.1 not found"):
        audit_published_install(context, [library])


def test_metadata_stops_naming_the_build_root(context: BuildContext) -> None:
    configure_environment(context)
    staging = context.packages / "imagemagick-staging"
    root, workspace = context.cwd, context.workspace
    files = {
        "usr/local/lib/libMagickCore-7.Q16HDRI.la": (
            f"dependency_libs=' -L{workspace}/lib {workspace}/lib/liblcms2.la -lm'\n"
            "libdir='/usr/local/lib'\n"
        ),
        "usr/local/lib/pkgconfig/MagickCore.pc": (
            f"Libs.private: -L${{libdir}} -lMagickCore  -L{workspace}/lib -llcms2 -lm\n"
        ),
        "usr/local/bin/MagickCore-config": f"{workspace}/bin/pkg-config --cflags MagickCore\n",
        "usr/local/lib/perl/auto/Image/Magick/.packlist": (
            f"{staging}/usr/local/lib/perl/Image/Magick.pm\n"
        ),
        "usr/local/lib/ImageMagick-7/config/configure.xml": f'<configure value="{root}"/>\n',
    }
    for name, text in files.items():
        (staging / name).parent.mkdir(parents=True, exist_ok=True)
        (staging / name).write_text(text)
    SelfContainedInstall(context, staging).apply()

    def read(name: str) -> str:
        return (staging / name).read_text()

    assert read("usr/local/lib/libMagickCore-7.Q16HDRI.la") == (
        "dependency_libs=''\nlibdir='/usr/local/lib'\n"
    )
    assert read("usr/local/lib/pkgconfig/MagickCore.pc") == (
        "Libs.private: -L${libdir} -lMagickCore -llcms2 -lm\n"
    )
    assert read("usr/local/bin/MagickCore-config") == "pkg-config --cflags MagickCore\n"
    assert read("usr/local/lib/perl/auto/Image/Magick/.packlist") == (
        "/usr/local/lib/perl/Image/Magick.pm\n"
    )
    # The configure record keeps naming the workspace by design.
    assert str(root) in read("usr/local/lib/ImageMagick-7/config/configure.xml")


def test_the_audit_names_files_that_still_need_the_build_root(context: BuildContext) -> None:
    configure_environment(context)
    staging = context.packages / "imagemagick-staging"
    compile_library(
        staging / "usr/local/lib",
        "libfc.so.1",
        f'const char *conf = "{context.workspace}/etc/fonts/fonts.conf";\n',
    )
    stray = staging / "usr/local/share/doc/notes.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text(f"built in {context.cwd}\n")
    (staging / "usr/local/lib/x.c").unlink()
    with pytest.raises(BuildError) as raised:
        SelfContainedInstall(context, staging).apply()
    message = str(raised.value)
    assert f"usr/local/lib/libfc.so.1 reads files under {context.workspace}/etc/" in message
    assert "usr/local/share/doc/notes.txt names the build root" in message
