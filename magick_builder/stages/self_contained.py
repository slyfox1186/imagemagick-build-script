"""Make the staged ImageMagick install independent of the build root.

libtool writes the workspace library directory into the run path of every
object it links, and a `--shared` build links the workspace libraries as
shared objects (jemalloc, libfpx, libpng, ...). An install built that way
works only while the build root exists: `--cleanup` deleted it and left magick
unable to start (libjemalloc.so.2 not found) and silently loading older system
copies of the rest. Before publication, every workspace library the install
loads is copied into BUNDLED_LIBRARY_DIRECTORY, a private directory that only
these objects' run paths name, so the system's own copies are never shadowed;
every build-root run path entry is removed; and the libtool, pkg-config,
*-config and Perl metadata stop naming build-root paths. The static default
links the workspace archives in, so it bundles nothing, and `assert_static`
refuses a tree that still carries shared objects.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path

from ..runtime.context import BuildContext
from ..runtime.errors import BuildError
from ..runtime.paths import path_is_within

BUNDLED_LIBRARY_DIRECTORY = Path("/usr/local/lib/imagemagick-build-script")
ELF_MAGIC = b"\x7fELF"
AR_MAGIC = b"!<arch>\n"
# `magick -list configure` reports the configure arguments verbatim, so this
# record keeps naming the workspace by design; nothing reads a path from it.
BUILD_RECORD_NAMES = frozenset({"configure.xml"})
_LDD_LINE = re.compile(r"^\s*(\S+) => (not found|(\S+) \(0x[0-9a-f]+\))\s*$")


def _regular_files(root: Path) -> Iterator[Path]:
    for directory, _subdirectories, names in os.walk(root):
        for name in sorted(names):
            path = Path(directory, name)
            if path.is_file() and not path.is_symlink():
                yield path


def _starts_with(path: Path, magic: bytes) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(magic)) == magic


def elf_files(root: Path) -> list[Path]:
    return sorted(path for path in _regular_files(root) if _starts_with(path, ELF_MAGIC))


def parse_ldd(output: str) -> dict[str, str | None]:
    """Each needed soname and the file it resolved to, None when it was not found.

    The vDSO and the dynamic loader appear without `=>` and are not dependencies.
    """
    resolved: dict[str, str | None] = {}
    for line in output.splitlines():
        match = _LDD_LINE.match(line)
        if match:
            resolved[match.group(1)] = match.group(3)
    return resolved


class SelfContainedInstall:
    def __init__(self, context: BuildContext, staging: Path) -> None:
        self.context = context
        self.staging = staging
        self.root = context.cwd
        self.bundle_directory = staging / BUNDLED_LIBRARY_DIRECTORY.relative_to("/")

    # -- probes ----------------------------------------------------------

    def inside_build_root(self, path: str) -> bool:
        return Path(path).is_absolute() and path_is_within(path, self.root)

    def _staged_library_path(self) -> str:
        """Where ldd resolves a staged object's libraries: the staged tree, the
        bundle, then the workspace, whose libraries the objects were linked
        against even when their run path does not say so (meson installs
        libraqm without one, and the system has a libharfbuzz.so.0 too)."""
        workspace = self.context.workspace
        directories = [
            self.staging / "usr/local/lib",
            self.staging / "usr/local/lib64",
            self.bundle_directory,
            workspace / "lib",
            workspace / "lib64",
            workspace / "lib" / self.context.multiarch,
        ]
        return ":".join(str(directory) for directory in directories)

    def dependencies(self, path: Path, library_path: str | None) -> dict[str, str | None]:
        overrides = {"LD_LIBRARY_PATH": library_path} if library_path else None
        completed = self.context.runner.capture(["ldd", str(path)], env_overrides=overrides)
        if completed.returncode != 0:
            # A static executable has no dynamic dependencies to resolve.
            if "not a dynamic executable" in completed.stdout + completed.stderr:
                return {}
            raise BuildError(f"ldd failed for {path}: {completed.stderr.strip()}")
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and self.inside_build_root(fields[0]):
                raise BuildError(
                    f"{path} loads an absolute build-root dependency ({fields[0]}); "
                    "relink it with a soname before publication."
                )
        return parse_ldd(completed.stdout)

    def _patchelf(self, *arguments: str) -> str:
        completed = self.context.runner.capture(["patchelf", *arguments])
        if completed.returncode != 0:
            raise BuildError(f"patchelf {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    def run_path(self, path: Path) -> list[str]:
        return [entry for entry in self._patchelf("--print-rpath", str(path)).split(":") if entry]

    # -- the transformation ----------------------------------------------

    def apply(self) -> dict[str, Path]:
        bundled = self.bundle_workspace_libraries()
        self.rewrite_run_paths(set(bundled))
        self.clean_metadata()
        self.audit(bundled)
        if bundled:
            self.context.logger.info(
                f"Bundled {len(bundled)} workspace libraries into {BUNDLED_LIBRARY_DIRECTORY}: "
                + " ".join(sorted(bundled))
            )
        return bundled

    def assert_static(self, bundled: dict[str, Path]) -> None:
        """A static build bundles nothing, ships no libMagick objects or modules."""
        problems = [f"workspace library {soname} was bundled" for soname in sorted(bundled)]
        library = self.staging / "usr/local/lib"
        problems += [
            f"{path.relative_to(self.staging)} is a shared library"
            for path in sorted(library.glob("libMagick*.so*"))
        ]
        problems += [
            f"{path.relative_to(self.staging)} holds coder modules"
            for path in sorted(library.glob("ImageMagick-*/modules-*"))
            if any(path.rglob("*"))
        ]
        for path in elf_files(self.staging / "usr"):
            needed = [
                soname
                for soname in self._patchelf("--print-needed", str(path)).split()
                if soname.startswith("libMagick")
            ]
            if needed:
                problems.append(f"{path.relative_to(self.staging)} needs {' '.join(needed)}")
        if problems:
            raise BuildError(
                "The static build produced a shared install:\n" + "\n".join(problems[:40])
            )

    def bundle_workspace_libraries(self) -> dict[str, Path]:
        """Copy every library the staged objects load from the build root, named by soname."""
        library_path = self._staged_library_path()
        sources: dict[str, Path] = {}
        for path in elf_files(self.staging / "usr"):
            for soname, resolved in self.dependencies(path, library_path).items():
                if resolved is None:
                    raise BuildError(
                        f"{path.relative_to(self.staging)} needs {soname}, which is not found."
                    )
                if not self.inside_build_root(resolved) or path_is_within(resolved, self.staging):
                    continue
                source = Path(os.path.realpath(resolved))
                if sources.setdefault(soname, source) != source:
                    raise BuildError(f"{soname} resolves to both {sources[soname]} and {source}.")
        if sources:
            self.bundle_directory.mkdir(parents=True, exist_ok=True)
        for soname, source in sources.items():
            target = self.bundle_directory / soname
            shutil.copyfile(source, target)
            target.chmod(0o644)
        return sources

    def rewrite_run_paths(self, bundled: set[str]) -> None:
        """Drop build-root entries; objects that load a bundled library search it first."""
        for path in elf_files(self.staging / "usr"):
            entries = self.run_path(path)
            kept = [entry for entry in entries if not self.inside_build_root(entry)]
            needed = set(self._patchelf("--print-needed", str(path)).split())
            if needed & bundled and str(BUNDLED_LIBRARY_DIRECTORY) not in kept:
                kept.insert(0, str(BUNDLED_LIBRARY_DIRECTORY))
            if kept == entries:
                continue
            # ExtUtils::Install leaves Perl's modules read-only.
            mode = path.stat().st_mode
            path.chmod(mode | 0o200)
            try:
                if kept:
                    self._patchelf("--set-rpath", ":".join(kept), str(path))
                else:
                    self._patchelf("--remove-rpath", str(path))
            finally:
                path.chmod(mode)

    def clean_metadata(self) -> None:
        """libtool, pkg-config, *-config and Perl records that name the build root.

        A kept .la file loses its dependency_libs, as Debian ships them: the
        dynamic loader resolves the dependencies, and the workspace libraries
        they list are deleted with the build root.
        """
        root = re.escape(str(self.root))
        build_flag = re.compile(rf"\s+-[LI]{root}/\S*")
        # The workspace pkg-config or the static build's wrapper around it.
        workspace_pkg_config = re.compile(
            re.escape(str(self.context.workspace / "bin")) + r"/(magick-)?pkg-config"
        )
        for path in _regular_files(self.staging / "usr"):
            if _starts_with(path, ELF_MAGIC) or _starts_with(path, AR_MAGIC):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if str(self.root) not in text:
                continue
            if path.suffix == ".la":
                cleaned = re.sub(r"(?m)^dependency_libs=.*$", "dependency_libs=''", text)
            elif path.suffix == ".pc":
                cleaned = build_flag.sub("", text)
            elif path.name == ".packlist":
                cleaned = "".join(
                    line.removeprefix(str(self.staging)) for line in text.splitlines(True)
                )
            elif path.name.endswith("-config"):
                cleaned = build_flag.sub("", workspace_pkg_config.sub("pkg-config", text))
            else:
                continue
            path.write_text(cleaned, encoding="utf-8")

    def audit(self, bundled: dict[str, Path]) -> None:
        """No staged object or file may still depend on the build root."""
        problems: list[str] = []
        workspace_data = [
            f"{self.context.workspace}/{directory}/".encode()
            for directory in ("etc", "var", "share")
        ]
        for path in elf_files(self.staging / "usr"):
            name = path.relative_to(self.staging)
            leaked = [entry for entry in self.run_path(path) if self.inside_build_root(entry)]
            if leaked:
                problems.append(f"{name} searches {':'.join(leaked)}")
            data = path.read_bytes()
            problems += [
                f"{name} reads files under {location.decode()}"
                for location in workspace_data
                if location in data
            ]
        for path in _regular_files(self.staging / "usr"):
            if path.name in BUILD_RECORD_NAMES or _starts_with(path, ELF_MAGIC):
                continue
            if _starts_with(path, AR_MAGIC):
                continue
            if str(self.root).encode() in path.read_bytes():
                problems.append(f"{path.relative_to(self.staging)} names the build root")
        if problems:
            raise BuildError(
                "The staged install still depends on the build root, which --cleanup deletes:\n"
                + "\n".join(problems[:40])
            )


def audit_published_install(context: BuildContext, files: list[Path]) -> None:
    """Every published object resolves every library without the build root.

    Run with the build root still present, so the check rests on the run paths
    and resolved locations, never on what happens to exist at the moment.
    """
    checker = SelfContainedInstall(context, context.packages / "imagemagick-staging")
    problems: list[str] = []
    for path in files:
        if path.is_symlink() or not path.is_file() or not _starts_with(path, ELF_MAGIC):
            continue
        for soname, resolved in checker.dependencies(path, None).items():
            if resolved is None:
                problems.append(f"{path}: {soname} not found")
            elif checker.inside_build_root(resolved):
                problems.append(f"{path}: {soname} loads from the build root ({resolved})")
    if problems:
        raise BuildError(
            "The installed ImageMagick cannot load its libraries without the build root:\n"
            + "\n".join(problems[:40])
        )
