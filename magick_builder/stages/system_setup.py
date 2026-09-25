"""Host validation, APT packages, compiler selection, and the build environment."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..runtime.context import BuildContext
from ..runtime.errors import BuildError

# The project standardizes on the high-level `apt` interface. Only its expected
# script-interface notice is suppressed; diagnostics and exit codes are intact.
APT_SCRIPT_OPTIONS = ("-o", "APT::Cmd::Disable-Script-Warning=1")

# Delegate-enabling packages, all verified available on every supported
# release by tools/check_apt_availability.py:
# - libdjvulibre/fftw3/lqr/openexr/pango/raw/wmf/zip dev packages light up the
#   djvu/fftw/lqr/openexr/pangocairo/raw/wmf/zip delegates.
# - libbz2/libjbig/liblzma/libzstd dev packages make the bzlib/jbig/lzma/zstd
#   delegates guaranteed instead of depending on transitive installs.
# - fonts-urw-base35 provides the exact directory --with-urw-base35-font-dir
#   points at.
# - ghostscript provides the runtime `gs` binary: delegates.xml shells out to it
#   for PDF/PS work, and the workspace-built gs is deleted with the build tree.
# - ffmpeg is the runtime video delegate (mpeg/mp4/webm coders).
# The legacy libjpeg62* packages are absent with evidence: nothing consumes
# them (jpeg comes from the workspace libjpeg-turbo), and on Ubuntu 24.04
# libjpeg62-dev conflicts with the libjpeg-turbo8-dev that libgraphviz-dev needs.
BASE_PACKAGES = (
    "autoconf",
    "autoconf-archive",
    "autopoint",
    "binutils",
    "bison",
    "build-essential",
    "bzip2",
    "cmake",
    "curl",
    "ffmpeg",
    "flex",
    "fontforge",
    "fonts-dejavu-core",
    "fonts-urw-base35",
    "ghostscript",
    "git",
    "gperf",
    "intltool",
    "jq",
    "libbz2-dev",
    "libc6",
    "libx11-dev",
    "libxext-dev",
    "libxt-dev",
    "libcpu-features-dev",
    "libdjvulibre-dev",
    "libfftw3-dev",
    "libfont-ttf-perl",
    "libgc-dev",
    "libgc1",
    "libgegl-common",
    "libgl2ps-dev",
    "libglib2.0-dev",
    "libgraphviz-dev",
    "libgs-dev",
    "libheif-dev",
    "libhwy-dev",
    "libjbig-dev",
    "liblqr-1-0-dev",
    "liblzma-dev",
    "libopenexr-dev",
    "libpango1.0-dev",
    "libraw-dev",
    "librsvg2-dev",
    "librust-jpeg-decoder-dev",
    "librust-malloc-buf-dev",
    "libsharp-dev",
    "libticonv-dev",
    "libtool",
    "libtool-bin",
    "libwmf-dev",
    "libyuv-dev",
    "libyuv-utils",
    "libyuv0",
    "libzip-dev",
    "libzstd-dev",
    "lsb-release",
    "m4",
    "meson",
    "nasm",
    "ninja-build",
    "pkg-config",
    "python3-dev",
    "xz-utils",
    "yasm",
    "zlib1g-dev",
)

# Installed by releases of this project before 2.0.0; their headers conflict
# with the libjpeg-turbo8-dev the libgraphviz-dev chain needs, and nothing in
# this build consumes them. Exactly these are removed; `--no-remove` still
# blocks every other solver-proposed removal.
LEGACY_CONFLICTING_PACKAGES = ("libjpeg62-dev", "libjpeg62-turbo-dev")

# (distribution, major release) -> (codename, release-specific packages, GCC
# versions in the standard archive). libjxl-dev is not packaged for Ubuntu
# 22.04, so builds there lack the optional JPEG-XL delegate.
RELEASES: dict[tuple[str, str], tuple[str, tuple[str, ...], tuple[int, ...]]] = {
    ("Debian", "12"): ("bookworm", ("libjxl-dev", "libgegl-0.4-0", "libcamd2"), (11, 12)),
    ("Debian", "13"): ("trixie", ("libjxl-dev", "libgegl-0.4-0t64", "libcamd3"), (12, 13, 14)),
    ("Ubuntu", "22"): ("jammy", (), (9, 10, 11, 12)),
    ("Ubuntu", "24"): ("noble", ("libjxl-dev",), (9, 10, 11, 12, 13, 14)),
}
SUPPORTED_RELEASES = (
    "Debian 12 (bookworm) through 13 (trixie), Ubuntu 22.04 (jammy) through 24.04 (noble)"
)

_OS_RELEASE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_os_release(path: Path) -> dict[str, str]:
    """Read os-release(5) as data, never as code.

    The file is shell syntax, and sourcing it would execute its contents in a
    process that goes on to run sudo-authorized steps.
    """
    fields: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, separator, value = raw_line.strip().partition("=")
        if not separator or not _OS_RELEASE_KEY.match(key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


def detect_release(path: Path) -> tuple[str, str, str]:
    """(distribution, version, codename), failing for anything unsupported."""
    if not path.is_file():
        raise BuildError(f"'{path}' is required for operating-system detection.")
    fields = read_os_release(path)
    distribution = {"debian": "Debian", "ubuntu": "Ubuntu"}.get(fields.get("ID", ""), "")
    version = fields.get("VERSION_ID", "")
    if not distribution:
        name = fields.get("NAME") or fields.get("ID") or "unknown"
        raise BuildError(f"Unsupported distribution '{name}'. Supported: {SUPPORTED_RELEASES}.")
    release = RELEASES.get((distribution, version.split(".", 1)[0]))
    if release is None or (distribution == "Ubuntu" and version not in ("22.04", "24.04")):
        raise BuildError(
            f"Unsupported {distribution} release '{version or 'unknown'}'. "
            f"Supported: {SUPPORTED_RELEASES}."
        )
    return distribution, version, fields.get("VERSION_CODENAME", "") or release[0]


def gcc_versions(distribution: str, version: str) -> tuple[int, ...]:
    return RELEASES[(distribution, version.split(".", 1)[0])][2]


def select_gcc_version(distribution: str, version: str, requested: int | None) -> int:
    available = gcc_versions(distribution, version)
    if requested is None:
        return available[-1]
    if requested not in available:
        listed = " ".join(str(item) for item in available)
        raise BuildError(
            f"GCC {requested} is unavailable on {distribution} {version}. "
            f"Available versions: {listed}."
        )
    return requested


def required_packages(distribution: str, version: str, gcc_version: int) -> list[str]:
    release_packages = RELEASES[(distribution, version.split(".", 1)[0])][1]
    return [*BASE_PACKAGES, *release_packages, f"gcc-{gcc_version}", f"g++-{gcc_version}"]


def workspace_pkg_config_dirs(workspace: Path, multiarch: str) -> str:
    return ":".join(
        [
            f"{workspace}/lib64/pkgconfig",
            f"{workspace}/lib/{multiarch}/pkgconfig",
            f"{workspace}/lib/pkgconfig",
            f"{workspace}/share/pkgconfig",
        ]
    )


def configure_environment(context: BuildContext) -> None:
    """The toolchain environment every build command inherits.

    The workspace -L paths are required so configure-time link probes (for
    example ImageMagick's FlashPIX `-lfpx` check) find workspace libraries that
    ship no pkg-config file. GIT_CEILING_DIRECTORIES stops every upstream build
    system from discovering an enclosing Git repository: ImageMagick's
    configure.ac, for one, bakes `git rev-parse` output into its version string
    and would otherwise report this project's commit as its own.
    """
    workspace = context.workspace
    context.env.update(
        {
            "PATH": ":".join(
                [
                    "/usr/lib/ccache",
                    f"{workspace}/bin",
                    "/usr/local/sbin",
                    "/usr/local/bin",
                    "/usr/sbin",
                    "/usr/bin",
                    "/sbin",
                    "/bin",
                ]
            ),
            "CC": "gcc",
            "CXX": "g++",
            "CFLAGS": "-O3 -fPIC -pipe -march=native -fstack-protector-strong",
            "CXXFLAGS": "-O3 -fPIC -pipe -march=native -fstack-protector-strong",
            "CPPFLAGS": f"-I{workspace}/include -I/usr/local/include -I/usr/include "
            "-D_FORTIFY_SOURCE=2",
            "LDFLAGS": f"-L{workspace}/lib64 -L{workspace}/lib -Wl,-O1 -Wl,--as-needed "
            "-Wl,-rpath,/usr/local/lib64:/usr/local/lib",
            "GIT_CEILING_DIRECTORIES": str(context.cwd),
        }
    )
    set_multiarch_paths(context)


def set_multiarch_paths(context: BuildContext) -> None:
    """Multiarch comes from the compiler, with a fallback before it is installed."""
    completed = context.runner.capture([context.env["CC"], "-print-multiarch"], timeout=10)
    context.multiarch = completed.stdout.strip() or f"{os.uname().machine}-linux-gnu"
    tuple_ = context.multiarch
    workspace_dirs = workspace_pkg_config_dirs(context.workspace, tuple_)
    system_dirs = ":".join(
        [
            f"/usr/lib/{tuple_}/pkgconfig",
            "/usr/share/pkgconfig",
            "/usr/lib/pkgconfig",
            f"/lib/{tuple_}/pkgconfig",
            "/lib/pkgconfig",
        ]
    )
    context.env["PKG_CONFIG_PATH"] = workspace_dirs
    context.env["PKG_CONFIG_LIBDIR"] = f"{workspace_dirs}:{system_dirs}"


class SystemSetup:
    def __init__(self, context: BuildContext) -> None:
        self.context = context
        self.logger = context.logger
        self.runner = context.runner

    def apt_package_installed(self, package: str) -> bool:
        completed = self.runner.capture(["dpkg-query", "-W", "-f=${Status}", package])
        return completed.returncode == 0 and "ok installed" in completed.stdout

    def apt_package_available(self, package: str) -> bool:
        return self.runner.probe(["apt", *APT_SCRIPT_OPTIONS, "show", package])

    def apt(self, *arguments: str) -> None:
        self.context.execute(
            [
                "sudo",
                "env",
                "DEBIAN_FRONTEND=noninteractive",
                "apt",
                *APT_SCRIPT_OPTIONS,
                *arguments,
            ]
        )

    def install_packages(self, packages: list[str]) -> None:
        """Install what is missing, failing closed before any mutation.

        A missing package means a silently degraded ImageMagick (failed
        configure probes), so every missing package must be installable before
        anything is installed. Nothing is ever removed as "no longer needed": that
        would be unrelated host mutation.
        """
        missing = [package for package in packages if not self.apt_package_installed(package)]
        if not missing:
            self.logger.info("All required APT packages are already installed.")
            return
        self.logger.info("Refreshing APT package metadata...")
        self.apt("update")
        unavailable = [package for package in missing if not self.apt_package_available(package)]
        if unavailable:
            context = self.context
            raise BuildError(
                f"Required APT packages are unavailable on {context.operating_system} "
                f"{context.release_version}: {' '.join(unavailable)}"
            )
        legacy = [
            package
            for package in LEGACY_CONFLICTING_PACKAGES
            if self.apt_package_installed(package)
        ]
        if legacy:
            self.logger.warn(
                "Removing legacy dev package(s) installed by older versions of this script: "
                + " ".join(legacy)
            )
            self.apt("remove", "-y", *legacy)
        self.logger.info(f"Installing {len(missing)} missing APT package(s): {' '.join(missing)}")
        self.apt("install", "-y", "--no-remove", *missing)

    def activate_compiler(self, version: int) -> None:
        context = self.context
        cc, cxx = f"gcc-{version}", f"g++-{version}"
        for compiler in (cc, cxx):
            if self.runner.which(compiler) is None:
                raise BuildError(f"The selected compiler '{compiler}' is not executable.")
            reported = self.runner.capture([compiler, "-dumpversion"]).stdout.strip()
            if reported.split(".", 1)[0] != str(version):
                raise BuildError(
                    f"'{compiler}' reports version '{reported}', not GCC major version {version}."
                )
        context.env["CC"], context.env["CXX"] = cc, cxx
        context.gcc_version = version
        set_multiarch_paths(context)
        self.logger.info(f"Using GNU compiler toolchain version {version}: {cc} and {cxx}.")

    def run(self) -> None:
        context = self.context
        self.logger.banner("Installing Required APT Packages")
        for tool in ("apt", "dpkg-query"):
            if self.runner.which(tool) is None:
                raise BuildError(f"Required command not found: '{tool}'.")
        os_release = Path(os.environ.get("OS_RELEASE_FILE", "/etc/os-release"))
        distribution, version, codename = detect_release(os_release)
        context.operating_system = distribution
        context.release_version = version
        context.release_codename = codename
        self.logger.info(f"Detected OS: {distribution} {version} ({codename})")
        gcc_version = select_gcc_version(distribution, version, context.requested_gcc_version)
        self.install_packages(required_packages(distribution, version, gcc_version))
        self.activate_compiler(gcc_version)
