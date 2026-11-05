"""The build context every stage receives.

Passing one object instead of process globals is what makes a stage testable in
isolation: a test builds a context over a temporary build root and exercises a
recipe without touching the host.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from .. import registry
from ..config import Selection
from .download import Downloader, DownloadSettings
from .errors import BuildError
from .exec import Runner
from .git import GitCloner
from .host import HostCpu, HostMemory
from .logging import Logger, format_duration
from .paths import path_is_within, safe_remove_tree
from .state import is_valid_version, read_marker, write_marker
from .versions import Resolved, VersionResolver

FONT_ROOT = Path("/usr/share/fonts/truetype")
MAGICK_BINARY = Path("/usr/local/bin/magick")


# Packages whose tags separate version components differently from the
# recorded version: freetype tags VER-2-14-3 for the recorded 2.14.3.
_TAG_SEPARATORS = {"freetype": "-"}


def _recorded_form(key: str, resolved: Resolved) -> Resolved:
    separator = _TAG_SEPARATORS.get(key)
    if separator is None:
        return resolved
    return Resolved(resolved.tag, resolved.version.replace(separator, "."), resolved.commit)


def resolve_upstream(resolver: VersionResolver, key: str) -> Resolved | None:
    """The newest upstream release of one package, by its registry source."""
    package = registry.PACKAGES[key]
    if package.source is registry.Source.GIT_HEAD:
        return resolver.head(package.repository)
    if package.source is registry.Source.LISTING:
        return resolver.listed_release(package.listings)
    if package.source is not registry.Source.GIT_TAG:
        raise BuildError(f"'{key}' has a recipe-selected version and cannot be resolved.")
    resolved = resolver.latest_tag(
        package.repository, package.accept, package.exclude, package.prefix
    )
    return None if resolved is None else _recorded_form(key, resolved)


def resolve_recorded(resolver: VersionResolver, key: str, version: str, commit: str) -> Resolved:
    """The source of a recorded release, for repairing it without an upgrade.

    A pinned Git release must still be where it was recorded: a moved tag or
    HEAD stops the build with the two ways forward instead of quietly building
    something else.
    """
    package = registry.PACKAGES[key]
    refresh = f"rerun with '--latest' to build {key}'s newest release instead"
    if package.source is registry.Source.LISTING:
        return Resolved("", version)
    if package.source is registry.Source.GIT_HEAD:
        head = resolver.head(package.repository)
        if head is None:
            raise BuildError(f"Unable to reach {key}'s repository to repair commit {version}.")
        if head.commit != version:
            raise BuildError(
                f"{key} needs repair, but its recorded commit {version} is no longer the "
                f"upstream HEAD ({head.commit}); {refresh}."
            )
        return head
    if package.source is not registry.Source.GIT_TAG:
        raise BuildError(f"'{key}' has a recipe-selected version and cannot be resolved.")
    separator = _TAG_SEPARATORS.get(key)
    found = resolver.tag_for_version(
        package.repository,
        version.replace(".", separator) if separator else version,
        package.accept,
        package.exclude,
        package.prefix,
    )
    if found is None:
        raise BuildError(
            f"{key} needs repair, but its recorded release {version} has no stable tag "
            f"upstream any more (or the repository is unreachable); {refresh}."
        )
    resolved = _recorded_form(key, found)
    if commit and resolved.commit != commit:
        raise BuildError(
            f"{key} needs repair, but the tag of its recorded release {version} moved from "
            f"commit {commit} to {resolved.commit}; {refresh}."
        )
    return resolved


def link_mode(context: BuildContext) -> str:
    """The word the logs, the context record and the closing report use."""
    return "shared" if context.shared else "static"


class BuildContext:
    """Shared state and services for one build."""

    def __init__(
        self,
        *,
        repo_root: Path,
        build_root: Path,
        logger: Logger,
        runner: Runner,
        selection: Selection,
        build_threads: int,
        latest: bool,
        shared: bool = False,
        gcc_version: int | None = None,
        compiler: str = "gcc",
        cpu_target: str = "native",
        host_cpu: HostCpu | None = None,
        host_memory: HostMemory | None = None,
        jobs_reason: str = "",
    ) -> None:
        self.repo_root = repo_root
        self.cwd = build_root
        self.packages = build_root / "packages"
        self.workspace = build_root / "workspace"
        self.log_file = build_root / "build.log"
        self.logger = logger
        self.runner = runner
        self.selection = selection
        self.build_threads = build_threads
        self.latest = latest
        # Static by default: every workspace library is an archive linked into
        # magick. `--shared` builds shared libraries and coder modules instead.
        self.shared = shared
        self.requested_gcc_version = gcc_version
        self.compiler = compiler
        # The single source of CPU tuning: CFLAGS/CXXFLAGS `-march`. Recipes add
        # no native switches of their own; runtime-dispatched SIMD stays on.
        self.cpu_target = cpu_target
        self.host_cpu = host_cpu
        self.host_memory = host_memory
        self.jobs_reason = jobs_reason

        # Filled in by the system setup stage.
        self.operating_system = ""
        self.release_version = ""
        self.release_codename = ""
        self.os_pretty_name = ""
        self.kernel_release = ""
        self.wsl2 = False
        self.gcc_version = 0
        self.multiarch = "x86_64-linux-gnu"

        self.packages_built = 0
        self.packages_already_built = 0
        self._package_started = 0
        self._package_in_progress = ""
        self._package_version = ""
        self._resolved: dict[str, Resolved] = {}
        self._temporary_paths: list[Path] = []

        self.download_settings = DownloadSettings(dict(os.environ))
        self.resolver = VersionResolver(
            runner, logger, git_timeout=int(os.environ.get("GIT_OPERATION_TIMEOUT") or "120")
        )
        self.downloader = Downloader(
            runner=runner,
            logger=logger,
            packages=self.packages,
            settings=self.download_settings,
            register_temporary=self.register_temporary_path,
            unregister_temporary=self.unregister_temporary_path,
            build_root_locked=True,
        )
        self.cloner = GitCloner(
            clone_timeout=int(os.environ.get("GIT_CLONE_TIMEOUT") or "1800"),
            operation_timeout=self.resolver.git_timeout,
            runner=runner,
            logger=logger,
            packages=self.packages,
            register_temporary=self.register_temporary_path,
            unregister_temporary=self.unregister_temporary_path,
        )

    # -- environment -----------------------------------------------------

    @property
    def env(self) -> dict[str, str]:
        return self.runner.environment

    # -- temporary paths -------------------------------------------------

    def register_temporary_path(self, path: Path) -> None:
        """Track a path so an abort cannot strand it."""
        self._temporary_paths.append(Path(path))

    def unregister_temporary_path(self, path: Path) -> None:
        target = Path(path)
        self._temporary_paths = [entry for entry in self._temporary_paths if entry != target]

    def remove_registered_temporary_paths(self) -> None:
        """Runs on the way out, so it never raises; containment is still enforced."""
        for entry in self._temporary_paths:
            if not entry.exists() and not entry.is_symlink():
                continue
            if path_is_within(entry, self.packages) or path_is_within(entry, self.workspace):
                try:
                    safe_remove_tree(entry, entry.parent)
                except (BuildError, OSError):
                    pass
        self._temporary_paths = []

    # -- selection -------------------------------------------------------

    def package_enabled(self, key: str) -> bool:
        return self.selection.enabled(key)

    @property
    def packages_disabled(self) -> int:
        """Derived from the selection: stages skip a disabled package before `build()`."""
        return len(registry.PACKAGE_NAMES) - len(self.selection.enabled_names())

    # -- artifacts -------------------------------------------------------

    def workspace_pc_exists(self, module: str) -> bool:
        return any(
            (self.workspace / directory / f"{module}.pc").is_file()
            for directory in (
                "lib/pkgconfig",
                "lib64/pkgconfig",
                f"lib/{self.multiarch}/pkgconfig",
                "share/pkgconfig",
            )
        )

    def workspace_lib_exists(self, basename: str) -> bool:
        return any(
            (self.workspace / directory / f"{basename}.{suffix}").exists()
            for directory in ("lib", "lib64", f"lib/{self.multiarch}")
            for suffix in ("a", "so")
        )

    def artifacts_present(self, key: str) -> bool:
        """True when what this package produced still exists.

        A completion marker without usable output is a lie, so `build_done`
        refuses to write one and `build` rebuilds when the artifacts vanish.
        """
        kind, *detail = registry.PACKAGES[key].artifact
        if kind == "bin":
            return os.access(self.workspace / "bin" / detail[0], os.X_OK)
        if kind == "pc":
            return self.workspace_pc_exists(detail[0])
        if kind == "lib":
            return self.workspace_lib_exists(detail[0])
        if kind == "font":
            directory = FONT_ROOT / key
            try:
                return directory.is_dir() and any(directory.iterdir())
            except OSError:
                return False
        if kind == "magick":
            return os.access(MAGICK_BINARY, os.X_OK)
        raise BuildError(f"No artifact contract is defined for package '{key}'.")

    # -- versions --------------------------------------------------------

    def marker_path(self, key: str) -> Path:
        return self.packages / f"{key}.done"

    def pin_path(self, key: str) -> Path:
        """The release a package is being rebuilt at, kept until it completes.

        Rebuilding is not upgrading: an invalidated or interrupted package is
        rebuilt at this release unless `--latest` asks for the newest.
        """
        return self.packages / f"{key}.pin"

    def invalidate(self, key: str) -> None:
        """Make `key` rebuild at the release its completion marker records."""
        marker = self.marker_path(key)
        if read_marker(marker) is not None:
            os.replace(marker, self.pin_path(key))
        else:
            marker.unlink(missing_ok=True)

    def resolve(self, key: str) -> Resolved | None:
        """The version to build, or None for a disabled package.

        A completion marker whose artifacts are intact is reused with no network
        traffic unless `--latest` asks for a refresh; build() then skips it. A
        marker whose artifacts are gone, or a pin left by an invalidated or
        interrupted rebuild, is rebuilt at the recorded release: a repair is
        not an implicit upgrade.
        """
        if not self.package_enabled(key):
            return None
        resolved: Resolved | None = None
        if not self.latest:
            recorded = read_marker(self.marker_path(key))
            if recorded is not None and self.artifacts_present(key):
                resolved = Resolved("", recorded[0], recorded[1])
            else:
                pinned = recorded or read_marker(self.pin_path(key))
                if pinned is not None:
                    resolved = resolve_recorded(self.resolver, key, *pinned)
        if resolved is None:
            resolved = resolve_upstream(self.resolver, key)
        if resolved is None:
            raise BuildError(f"Failed to resolve the latest {key} version.")
        self._resolved[key] = resolved
        return resolved

    # -- build bookkeeping -----------------------------------------------

    @property
    def package_in_progress(self) -> str:
        """The package whose recipe is running, or empty between packages."""
        return self._package_in_progress

    @property
    def package_version(self) -> str:
        return self._package_version

    def build(self, key: str, version: str | None) -> bool:
        """Decide whether this package's recipe should run."""
        if key not in registry.PACKAGES:
            raise BuildError(f"build() received unsupported package '{key}'.")
        if not self.package_enabled(key):
            self.logger.debug(f"{key} is disabled by the package selection config.")
            return False
        if version is None or not is_valid_version(version):
            raise BuildError(f"build() called for '{key}' with an invalid version '{version}'.")

        marker = self.marker_path(key)
        recorded = read_marker(marker)
        if recorded is None:
            if marker.exists() or marker.is_symlink():
                self.logger.warn(
                    f"The completion marker for {key} is unreadable or in an unknown format; "
                    "rebuilding."
                )
        elif recorded[0] == version:
            if self.artifacts_present(key):
                self.packages_already_built += 1
                self.logger.package_reused(key, version)
                # Shown on its own line so it can be copied whole; deleting the
                # marker rebuilds the package on the next run.
                self.logger.hint(str(marker))
                return False
            self.logger.warn(
                f"{key} has a completion marker but its artifacts are missing; rebuilding."
            )
        self._start_package_build(key, version, recorded[0] if recorded else "")
        return True

    def _start_package_build(self, key: str, version: str, prior_version: str) -> None:
        # Recipes install in place, so the markers go before any write: this
        # package's, every package built against it, and ImageMagick's when a
        # library it links changes. Each keeps its release as a pin, so an
        # interrupted run resumes the same releases instead of upgrading.
        resolved = self._resolved.get(key)
        commit = resolved.commit if resolved is not None and resolved.version == version else ""
        self.packages.mkdir(parents=True, exist_ok=True)
        write_marker(self.pin_path(key), version, commit)
        self.marker_path(key).unlink(missing_ok=True)
        for consumer in registry.consumers_of(key):
            self.invalidate(consumer)
        if registry.PACKAGES[key].kind is registry.Kind.LIBRARY:
            self.invalidate("imagemagick")
        self.packages_built += 1
        self._package_started = self.logger.elapsed_seconds
        self._package_in_progress = key
        self._package_version = version
        replacing = prior_version if prior_version and prior_version != version else ""
        self.logger.package_start(key, version, replacing)

    def build_done(self, key: str, version: str, commit: str = "") -> None:
        """Publish the marker, but only once the artifact is actually there."""
        if not self.artifacts_present(key):
            raise BuildError(
                f"Refusing to record completion for '{key}': its expected artifacts are missing."
            )
        self.packages.mkdir(parents=True, exist_ok=True)
        write_marker(self.marker_path(key), version, commit)
        self.pin_path(key).unlink(missing_ok=True)
        if self._package_in_progress == key:
            duration = format_duration(self.logger.elapsed_seconds - self._package_started)
            self.logger.package_done(key, version, duration)
            self._package_in_progress = ""
        else:
            self.logger.package_done(key, version)

    # -- sources ---------------------------------------------------------

    def clone(self, key: str, resolved: Resolved, *, recurse: bool = False) -> Path:
        """Clone the resolved commit and verify it; returns the checkout."""
        commit = self.cloner.clone(
            registry.PACKAGES[key].repository,
            key,
            "recurse" if recurse else "shallow",
            reference=resolved.tag or None,
            expected_commit=resolved.commit or None,
        )
        if commit is None:
            raise BuildError(
                f"Unable to obtain '{key}' at the resolved commit {resolved.commit or 'HEAD'} "
                "(the reference may have moved upstream; rerun the build)."
            )
        return self.packages / key

    def download(self, url: str, filename: str | None = None) -> Path:
        return self.downloader.download(url, filename)

    def download_with_fallback(self, primary_url: str, fallback_url: str) -> Path:
        return self.downloader.download_with_fallback(primary_url, fallback_url)

    # -- commands --------------------------------------------------------

    def execute(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        env_overrides: Mapping[str, str] | None = None,
        display: str | None = None,
    ) -> None:
        self.runner.execute(arguments, cwd=cwd, env_overrides=env_overrides, display=display)

    def make(self, cwd: Path, *targets: str, jobs: bool = True) -> None:
        arguments = ["make"]
        if jobs:
            arguments.append(f"-j{self.build_threads}")
        arguments.extend(targets)
        self.execute(arguments, cwd=cwd)

    def sudo(self, *arguments: str, display: str | None = None) -> None:
        self.execute(["sudo", *arguments], display=display)
