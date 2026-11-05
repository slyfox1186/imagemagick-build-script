"""Host validation, APT packages, compiler selection, and the build environment."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from ..runtime.context import BuildContext
from ..runtime.errors import BuildError
from ..runtime.host import compiler_cpu_target, march
from ..runtime.paths import safe_remove_tree

# Every package has a consumer in this build; all are available on every
# supported release:
# - The toolchain and build systems the recipes run: build-essential, the
#   autotools (autoconf, autoconf-archive, automake via libtool, autopoint for
#   fontconfig's gettext macros, m4), cmake, meson, ninja, gperf (fontconfig),
#   nasm (libjpeg-turbo's SIMD), git, curl, tar's bzip2 and xz decompressors,
#   patchelf (stages/self_contained.py rewrites the install's run paths). No
#   recipe's configure, CMake or meson files probe for bison, flex or intltool.
# - libdjvulibre/fftw3/lqr/openexr/pango/raw/wmf/zip dev packages light up the
#   djvu/fftw/lqr/openexr/pangocairo/raw/wmf/zip delegates; libglib2.0-dev,
#   libgraphviz-dev, libheif-dev, librsvg2-dev and the X11 dev packages the
#   gvc/heic/rsvg/x delegates.
# - libbz2/libjbig/liblzma/libzstd/zlib1g dev packages make the
#   bzlib/jbig/lzma/zstd/zlib delegates guaranteed instead of depending on
#   transitive installs.
# - fonts-urw-base35 and fonts-dejavu-core provide the exact directories the
#   font-dir configure options point at.
# - libgs-dev is the gslib delegate (PostScript and PDF rendered in-process)
#   and ghostscript the `gs` binary delegates.xml runs for PS/PDF/EPS
#   conversions. Ghostscript has no supported static library and prefers its
#   bundled copies of the image libraries, so it is never built from source.
# - ocl-icd-opencl-dev provides CL/cl.h for configure and the libOpenCL.so
#   that ImageMagick dlopens at run time to reach the vendor ICDs (it never
#   calls the library it links); libltdl-dev backs that dlopen and the coder
#   modules when the workspace libtool is disabled.
# - ffmpeg is the runtime video delegate (mpeg/mp4/webm coders).
# - fontconfig-config provides /etc/fonts, which the workspace fontconfig is
#   compiled to read.
# - The APT libtool, pkg-config and m4 are the fallbacks for a selection that
#   disables the workspace builds of them.
# The legacy libjpeg62* packages are absent with evidence: nothing consumes
# them (jpeg comes from the workspace libjpeg-turbo), and on Ubuntu 24.04
# libjpeg62-dev conflicts with the libjpeg-turbo8-dev that libgraphviz-dev needs.
BASE_PACKAGES = (
    "autoconf",
    "autoconf-archive",
    "autopoint",
    "build-essential",
    "bzip2",
    "cmake",
    "curl",
    "ffmpeg",
    "fonts-dejavu-core",
    "fontconfig-config",
    "fonts-urw-base35",
    "ghostscript",
    "git",
    "gperf",
    "libbz2-dev",
    "libx11-dev",
    "libxext-dev",
    "libxt-dev",
    "libdjvulibre-dev",
    "libfftw3-dev",
    "libglib2.0-dev",
    "libgraphviz-dev",
    "libgs-dev",
    "libheif-dev",
    "libjbig-dev",
    "liblqr-1-0-dev",
    "libltdl-dev",
    "liblzma-dev",
    "libopenexr-dev",
    "libpango1.0-dev",
    "libraw-dev",
    "librsvg2-dev",
    "libtool",
    "libtool-bin",
    "libwmf-dev",
    "libzip-dev",
    "libzstd-dev",
    "m4",
    "meson",
    "nasm",
    "ninja-build",
    "ocl-icd-opencl-dev",
    "patchelf",
    "pkg-config",
    "xz-utils",
    "zlib1g-dev",
)

# Installed by releases of this project before 2.0.0; their headers conflict
# with the libjpeg-turbo8-dev the libgraphviz-dev chain needs, and nothing in
# this build consumes them.
LEGACY_CONFLICTING_PACKAGES = ("libjpeg62-dev", "libjpeg62-turbo-dev")


class Release(NamedTuple):
    codename: str
    packages: tuple[str, ...]
    """Release-specific APT packages."""
    gcc_versions: tuple[int, ...]
    """The gcc-N/g++-N pairs in the standard archive."""
    default_gcc: int
    libtool: str
    """The workspace libtool, pinned to the version the release's autotools expect."""


# Keyed by (distribution, major release); Ubuntu releases are the LTS `.04`
# ones. libjxl-dev (the jxl delegate) is not packaged for Ubuntu 22.04, so
# builds there lack the optional JPEG-XL delegate. Ubuntu 26.04 dropped
# gcc-9/gcc-10, and its gcc-16 is a pre-release snapshot (16-20260322), so it
# is selectable but the default stays the archive's own gcc-15.
RELEASES: dict[tuple[str, str], Release] = {
    ("Debian", "12"): Release("bookworm", ("libjxl-dev",), (11, 12), 12, "2.4.7"),
    ("Debian", "13"): Release("trixie", ("libjxl-dev",), (12, 13, 14), 14, "2.4.7"),
    ("Ubuntu", "22"): Release("jammy", (), (9, 10, 11, 12), 12, "2.4.6"),
    ("Ubuntu", "24"): Release("noble", ("libjxl-dev",), (9, 10, 11, 12, 13, 14), 14, "2.4.7"),
    ("Ubuntu", "26"): Release("resolute", ("libjxl-dev",), (11, 12, 13, 14, 15, 16), 15, "2.5.4"),
}
SUPPORTED_RELEASES = (
    "Debian 12 (bookworm) and 13 (trixie), Ubuntu 22.04 (jammy), 24.04 (noble) and 26.04 "
    "(resolute), and Ubuntu derivatives built on those Ubuntu releases"
)
# Ubuntu derivatives (Linux Mint, Zorin OS, Pop!_OS, ...) declare ID_LIKE=ubuntu
# and name the Ubuntu release whose archive they use in UBUNTU_CODENAME.
UBUNTU_BASES = {"jammy": "22.04", "noble": "24.04", "resolute": "26.04"}
# The packages the Clang toolchain adds; both are in every supported release's
# archive (Ubuntu: universe). Clang's OpenMP runtime is LLVM's libomp, not GCC's
# libgomp, and ImageMagick builds with OpenMP.
CLANG_PACKAGES = ("clang", "libomp-dev")
# Commands every recipe runs that APT is expected to provide.
REQUIRED_HOST_TOOLS = (
    "autoreconf",
    "cmake",
    "curl",
    "git",
    "make",
    "meson",
    "nasm",
    "ninja",
    "patchelf",
    "pkg-config",
    "tar",
)
# A C++ translation unit using libstdc++ and OpenMP: what MagickCore and the
# C++ dependencies need from the toolchain, checked before any package builds.
_TOOLCHAIN_PROBE = """\
#include <omp.h>
#include <string>
int main() {
    std::string text("probe");
    int threads = 0;
#pragma omp parallel reduction(+ : threads)
    threads += 1;
    return threads > 0 && text.size() == 5 ? 0 : 1;
}
"""

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
    """(distribution, version, codename), failing for anything unsupported.

    An Ubuntu derivative is treated as the Ubuntu release it is built on, since
    its APT sources are that release's archive.
    """
    if not path.is_file():
        raise BuildError(f"'{path}' is required for operating-system detection.")
    fields = read_os_release(path)
    distribution = {"debian": "Debian", "ubuntu": "Ubuntu"}.get(fields.get("ID", ""), "")
    version = fields.get("VERSION_ID", "")
    if not distribution and "ubuntu" in fields.get("ID_LIKE", "").split():
        base = fields.get("UBUNTU_CODENAME", "")
        if base not in UBUNTU_BASES:
            raise BuildError(
                f"Unsupported Ubuntu derivative base '{base or 'unknown'}' "
                f"({fields.get('NAME') or fields.get('ID')}). Supported: {SUPPORTED_RELEASES}."
            )
        return "Ubuntu", UBUNTU_BASES[base], base
    if not distribution:
        name = fields.get("NAME") or fields.get("ID") or "unknown"
        raise BuildError(f"Unsupported distribution '{name}'. Supported: {SUPPORTED_RELEASES}.")
    major = version.split(".", 1)[0]
    release = RELEASES.get((distribution, major))
    if release is None or (distribution == "Ubuntu" and version != f"{major}.04"):
        raise BuildError(
            f"Unsupported {distribution} release '{version or 'unknown'}'. "
            f"Supported: {SUPPORTED_RELEASES}."
        )
    return distribution, version, fields.get("VERSION_CODENAME", "") or release.codename


def release_info(distribution: str, version: str) -> Release:
    """The table entry for a release `detect_release` accepted."""
    return RELEASES[(distribution, version.split(".", 1)[0])]


def gcc_versions(distribution: str, version: str) -> tuple[int, ...]:
    return release_info(distribution, version).gcc_versions


def select_gcc_version(distribution: str, version: str, requested: int | None) -> int:
    available = gcc_versions(distribution, version)
    if requested is None:
        return release_info(distribution, version).default_gcc
    if requested not in available:
        listed = " ".join(str(item) for item in available)
        raise BuildError(
            f"GCC {requested} is unavailable on {distribution} {version}. "
            f"Available versions: {listed}."
        )
    return requested


def required_packages(distribution: str, version: str, gcc_version: int | None) -> list[str]:
    """The APT packages for this release and the selected GCC, or Clang for None.

    A Clang build still has a GCC: build-essential brings the release's default
    gcc/g++, whose crt files, libgcc and libstdc++ Clang uses.
    """
    release_packages = release_info(distribution, version).packages
    if gcc_version is None:
        return [*BASE_PACKAGES, *release_packages, *CLANG_PACKAGES]
    return [*BASE_PACKAGES, *release_packages, f"gcc-{gcc_version}", f"g++-{gcc_version}"]


def read_kernel_release(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def check_wsl(kernel_release: str) -> bool:
    """True on WSL2; WSL1, which has no Linux kernel to build against, fails."""
    lowered = kernel_release.lower()
    if "microsoft" not in lowered:
        return False
    # Microsoft's WSL2 kernels end their release with '-microsoft-standard'
    # (4.19) or '-microsoft-standard-WSL2' (5.10 and later); WSL1 has no Linux
    # kernel and reports a plain '-Microsoft' suffix.
    if "microsoft-standard" not in lowered and "wsl2" not in lowered:
        raise BuildError(
            f"WSL1 detected ('{kernel_release}'); convert the distribution with "
            "'wsl.exe --set-version <distro> 2' and update WSL with 'wsl.exe --update'."
        )
    return True


def describe_operating_system(context: BuildContext) -> str:
    """The distribution as it names itself, then what the build treats it as."""
    base = f"{context.operating_system} {context.release_version}"
    name = context.os_pretty_name or base
    details = [f"'{context.release_codename}'"]
    if not name.startswith(context.operating_system):
        details.insert(0, f"{base} base")
    if context.kernel_release:
        details.append(f"kernel '{context.kernel_release}'")
    if context.wsl2:
        details.append("WSL2")
    return f"'{name}' ({', '.join(details)})"


def compiler_behind_ccache(executable: str, command: str, path: str) -> str | None:
    """The compiler a ccache shim dispatches to, found the way ccache finds it.

    ccache invoked through a compiler-named symlink walks PATH for that name
    and skips every candidate that is ccache itself. None when `executable` is
    not a ccache shim or nothing else on PATH answers to the name.
    """
    if Path(executable).resolve().name != "ccache":
        return None
    for entry in path.split(":"):
        if not entry:
            continue
        candidate = shutil.which(command, path=entry)
        if candidate is not None and Path(candidate).resolve().name != "ccache":
            return candidate
    return None


def compiler_flags(cpu_target: str) -> str:
    """CFLAGS and CXXFLAGS for a CPU target; the native string predates the targets."""
    return f"-O3 -fPIC -pipe -march={march(cpu_target)} -fstack-protector-strong"


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
    # ccache's compiler-named shims go first when ccache is installed; the
    # administrator's /usr/local stays ahead of the distribution's /usr.
    ccache = [directory for directory in ("/usr/lib/ccache",) if Path(directory).is_dir()]
    flags = compiler_flags(context.cpu_target)
    cc, cxx = ("clang", "clang++") if context.compiler == "clang" else ("gcc", "g++")
    context.env.update(
        {
            "PATH": ":".join(
                [
                    *ccache,
                    f"{workspace}/bin",
                    "/usr/local/sbin",
                    "/usr/local/bin",
                    "/usr/sbin",
                    "/usr/bin",
                    "/sbin",
                    "/bin",
                ]
            ),
            "CC": cc,
            "CXX": cxx,
            "CFLAGS": flags,
            "CXXFLAGS": flags,
            # Fortification level 3 needs GCC 12 and glibc 2.34, which every
            # supported release has; -U first because Ubuntu's gcc predefines
            # the level. --as-needed stays a separate -Wl argument: libtool
            # reorders combined ones.
            "CPPFLAGS": f"-I{workspace}/include -I/usr/local/include -I/usr/include "
            "-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3",
            "LDFLAGS": f"-L{workspace}/lib64 -L{workspace}/lib -Wl,-O1 -Wl,--as-needed "
            "-Wl,-z,relro -Wl,-z,now -Wl,-rpath,/usr/local/lib64:/usr/local/lib",
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

    def installed_packages(self, packages: Sequence[str]) -> set[str]:
        """The members of `packages` that dpkg reports installed, in one query.

        dpkg-query exits non-zero when any name is unknown yet still lists the
        known ones, so its status is not consulted. A query that fails outright
        leaves every package treated as missing, which costs only a redundant
        `apt install`.
        """
        completed = self.runner.capture(
            ["dpkg-query", "-W", "-f=${Package}\t${Status}\n", *packages]
        )
        installed: set[str] = set()
        for line in completed.stdout.splitlines():
            name, _, status = line.partition("\t")
            if "ok installed" in status:
                installed.add(name)
        return installed

    def apt_package_available(self, package: str) -> bool:
        return self.runner.probe(["apt", "show", package])

    def apt(self, *arguments: str) -> None:
        self.context.execute(["sudo", "apt", *arguments])

    def install_packages(self, packages: list[str]) -> None:
        """Install what is missing, failing closed before any mutation.

        A missing package means a silently degraded ImageMagick (failed
        configure probes), so every missing package must be installable before
        anything is installed. Nothing is ever removed as "no longer needed": that
        would be unrelated host mutation.
        """
        installed = self.installed_packages([*packages, *LEGACY_CONFLICTING_PACKAGES])
        missing = [package for package in packages if package not in installed]
        if not missing:
            self.logger.info("All required APT packages are already installed.")
            return
        self.logger.info("Refreshing APT package metadata...")
        self.apt("update")
        unavailable = [package for package in missing if not self.apt_package_available(package)]
        if unavailable:
            context = self.context
            message = (
                f"Required APT packages are unavailable on {context.operating_system} "
                f"{context.release_version}: {' '.join(unavailable)}"
            )
            if context.operating_system == "Ubuntu":
                # Minimal Ubuntu images can lack the universe component, which
                # carries several delegates' dev packages, Clang and libomp.
                message += (
                    ". Many of them come from Ubuntu's 'universe' component; enable it with "
                    "'sudo add-apt-repository universe' and run the build again."
                )
            raise BuildError(message)
        legacy = [package for package in LEGACY_CONFLICTING_PACKAGES if package in installed]
        if legacy:
            self.logger.warn(
                "Removing legacy dev package(s) installed by older versions of this script: "
                + " ".join(legacy)
            )
            self.apt("remove", "-y", *legacy)
        self.logger.info(f"Installing {len(missing)} missing APT package(s): {' '.join(missing)}")
        self.apt("install", "-y", *missing)

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

    def activate_clang(self) -> None:
        """Use the release's default Clang with the libstdc++ it selected.

        Clang compiles C++ against the newest GCC installation it finds under
        /usr/lib/gcc, which can be a GCC whose libstdc++ headers were never
        installed; that libstdc++-N-dev is installed here instead of failing
        the first C++ dependency.
        """
        context = self.context
        for compiler in ("clang", "clang++"):
            if self.runner.which(compiler) is None:
                raise BuildError(f"The selected compiler '{compiler}' is not executable.")
        context.env["CC"], context.env["CXX"] = "clang", "clang++"
        context.gcc_version = 0
        selected = self.runner.capture(["clang++", "-v", "-E", "-x", "c++", "/dev/null"])
        match = re.search(
            r"^Selected GCC installation: (/\S*/gcc/[^/\s]+/([0-9]+))$",
            selected.stderr,
            re.MULTILINE,
        )
        if match is not None:
            libstdcxx = f"libstdc++-{match.group(2)}-dev"
            if libstdcxx not in self.installed_packages([libstdcxx]):
                self.logger.info(
                    f"Clang uses the GCC {match.group(2)} installation at '{match.group(1)}'; "
                    f"installing its C++ library headers ({libstdcxx})."
                )
                self.install_packages([libstdcxx])
        set_multiarch_paths(context)
        version = self.runner.capture(["clang", "-dumpversion"]).stdout.strip() or "unknown"
        self.logger.info(
            f"Using the Clang compiler toolchain version {version}: clang and clang++."
        )

    def verify_toolchain(self) -> None:
        """Compile, link and run a C++ OpenMP program with the selected compilers.

        A toolchain that cannot would otherwise fail or silently lose OpenMP
        deep inside a dependency's or ImageMagick's configure.
        """
        context = self.context
        compiler = context.env["CXX"]
        directory = Path(tempfile.mkdtemp(prefix=".toolchain.", dir=context.cwd))
        context.register_temporary_path(directory)
        try:
            program = directory / "probe"
            completed = self.runner.capture(
                [
                    compiler,
                    *context.env["CXXFLAGS"].split(),
                    "-fopenmp",
                    "-x",
                    "c++",
                    "-",
                    "-o",
                    str(program),
                ],
                stdin_text=_TOOLCHAIN_PROBE,
                timeout=120,
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip().splitlines()[-3:]
                raise BuildError(
                    f"'{compiler}' cannot compile a C++ OpenMP program with this build's flags"
                    + (": " + " ".join(detail) if detail else ".")
                    + (
                        " Check that the C++ library headers of the GCC that "
                        "'clang++ -v' reports as selected are installed."
                        if context.compiler == "clang"
                        else ""
                    )
                )
            if self.runner.capture([str(program)], timeout=30).returncode != 0:
                raise BuildError(
                    f"A C++ OpenMP program built by '{compiler}' does not run on this machine."
                )
        finally:
            safe_remove_tree(directory, context.cwd)
            context.unregister_temporary_path(directory)

    def verify_required_host_tools(self) -> None:
        missing = [tool for tool in REQUIRED_HOST_TOOLS if self.runner.which(tool) is None]
        if missing:
            listed = ", ".join(f"'{tool}'" for tool in missing)
            raise BuildError(f"Required command(s) not found after installing packages: {listed}.")

    def report_compiler_versions(self) -> None:
        """Report the selected C/C++ commands through the actual build PATH."""
        for variable, label in (("CC", "C compiler"), ("CXX", "C++ compiler")):
            command = self.context.env[variable]
            executable = self.runner.which(command)
            if executable is None:
                self.logger.warn(f"{label}: '{command}' was not found on the build PATH.")
                continue
            # Keep the invocation name: resolving a ccache/clang symlink to
            # ccache itself would report ccache's version instead of Clang's.
            result = self.runner.capture([executable, "--version"], timeout=10)
            lines = result.stdout.strip().splitlines()
            if result.returncode != 0 or not lines:
                self.logger.warn(f"{label}: unable to read the version from '{executable}'.")
                continue
            location = f"'{executable}'"
            compiler = compiler_behind_ccache(executable, command, self.context.env["PATH"])
            if compiler is not None:
                location += f", ccache for '{compiler}'"
            self.logger.compiler(label, lines[0], location)

    def report_compiler_cpu_target(self) -> None:
        """Name the CPU the selected compiler actually generates code for."""
        context = self.context
        if context.cpu_target != "native":
            self.logger.info(f"Compiler CPU target: '{march(context.cpu_target)}'.")
            return
        resolved = compiler_cpu_target(self.runner, context.compiler, context.env["CC"])
        if resolved is None:
            self.logger.warn(
                "Compiler CPU target: unable to resolve '-march=native' with "
                f"'{context.env['CC']}'."
            )
            return
        self.logger.info(f"Compiler CPU target: '{resolved}' (-march=native).")

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
        context.os_pretty_name = read_os_release(os_release).get("PRETTY_NAME", "")
        context.kernel_release = read_kernel_release(
            Path(os.environ.get("KERNEL_RELEASE_FILE", "/proc/sys/kernel/osrelease"))
        )
        context.wsl2 = check_wsl(context.kernel_release)
        self.logger.info(f"Detected OS: {describe_operating_system(context)}")
        if context.compiler == "clang":
            self.install_packages(required_packages(distribution, version, None))
            self.verify_required_host_tools()
            self.activate_clang()
        else:
            gcc_version = select_gcc_version(distribution, version, context.requested_gcc_version)
            self.install_packages(required_packages(distribution, version, gcc_version))
            self.verify_required_host_tools()
            self.activate_compiler(gcc_version)
        self.report_compiler_versions()
        self.report_compiler_cpu_target()
        self.verify_toolchain()
