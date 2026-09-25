"""m4, libtool and pkg-config: the tools every later configure run uses."""

from __future__ import annotations

from pathlib import Path

from ..registry import GNU_FALLBACK_MIRROR, GNU_PRIMARY_MIRROR
from ..runtime.context import BuildContext
from ..runtime.errors import BuildError
from .helpers import configure_make_install
from .system_setup import workspace_pkg_config_dirs


def libtool_version(distribution: str, version: str) -> str:
    """libtool is pinned per release to the version its autotools expect."""
    if (distribution, version) == ("Ubuntu", "22.04"):
        return "2.4.6"
    if (distribution, version) in (("Ubuntu", "24.04"), ("Debian", "12"), ("Debian", "13")):
        return "2.4.7"
    raise BuildError(f"Unsupported OS version for libtool: {distribution} {version}.")


def gnu_download(context: BuildContext, path: str) -> Path:
    return context.download_with_fallback(
        f"{GNU_PRIMARY_MIRROR}/{path}", f"{GNU_FALLBACK_MIRROR}/{path}"
    )


def install_core_tools(context: BuildContext) -> None:
    context.logger.banner("Building Core Tools")
    workspace = context.workspace

    resolved = context.resolve("m4")
    if resolved and context.build("m4", resolved.version):
        source = gnu_download(context, f"m4/m4-{resolved.version}.tar.xz")
        configure_make_install(context, source, "--enable-c++", "--enable-threads=posix")
        context.build_done("m4", resolved.version)

    version = libtool_version(context.operating_system, context.release_version)
    if context.build("libtool", version):
        source = gnu_download(context, f"libtool/libtool-{version}.tar.xz")
        # The workspace m4 when it was built, otherwise the APT copy.
        m4 = workspace / "bin/m4" if context.package_enabled("m4") else "m4"
        configure_make_install(context, source, "--with-pic", f"M4={m4}")
        context.build_done("libtool", version)

    resolved = context.resolve("pkg-config")
    if resolved and context.build("pkg-config", resolved.version):
        source = context.download(
            f"https://pkgconfig.freedesktop.org/releases/pkg-config-{resolved.version}.tar.gz"
        )
        context.execute(["autoconf"], cwd=source)
        cppflags = context.env["CPPFLAGS"]
        ldflags = context.env["LDFLAGS"]
        iconv_options: list[str] = []
        # A GNU libiconv in /usr/local must supply headers and library together,
        # so the bundled GLib never mixes them with glibc's iconv detection.
        local = Path("/usr/local")
        if (local / "include/iconv.h").is_file() and any(
            (local / directory / f"libiconv.{suffix}").is_file()
            for directory in ("lib", "lib64")
            for suffix in ("a", "so")
        ):
            cppflags = (
                f"-I{workspace}/include -I/usr/local/include -I/usr/include -D_FORTIFY_SOURCE=2"
            )
            ldflags += " -L/usr/local/lib64 -L/usr/local/lib"
            iconv_options.append("--with-libiconv=gnu")
        configure_make_install(
            context,
            source,
            "--with-internal-glib",
            *iconv_options,
            f"--with-pc-path={workspace_pkg_config_dirs(workspace, context.multiarch)}",
            f"CFLAGS={context.env['CFLAGS']}",
            f"CPPFLAGS={cppflags}",
            f"LDFLAGS={ldflags}",
        )
        context.build_done("pkg-config", resolved.version)
