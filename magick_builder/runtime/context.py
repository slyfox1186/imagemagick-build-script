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
from . import shellquote
from .download import Downloader, DownloadSettings
from .errors import BuildError
from .exec import Runner
from .git import GitCloner
from .logging import Logger, format_duration
from .paths import path_is_within, safe_remove_tree
from .state import is_valid_version, read_marker, write_marker
from .versions import Resolved, VersionResolver, ghostscript_version

FONT_ROOT = Path("/usr/share/fonts/truetype")
MAGICK_BINARY = Path("/usr/local/bin/magick")


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
    if resolved is None:
        return None
    if key == "ghostscript":
        version = ghostscript_version(resolved.tag)
        return None if version is None else Resolved(resolved.tag, version, resolved.commit)
    if key == "freetype":
        # Tags use dashes (VER-2-14-3); the recorded version is dotted.
        return Resolved(resolved.tag, resolved.version.replace("-", "."), resolved.commit)
    return resolved


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
        gcc_version: int | None = None,
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
        self.requested_gcc_version = gcc_version

        # Filled in by the system setup stage.
        self.operating_system = ""
        self.release_version = ""
        self.release_codename = ""
        self.gcc_version = 0
        self.multiarch = "x86_64-linux-gnu"
        # Set once the ImageMagick stage has validated and displayed the
        # installed binary, so the closing report does not repeat it.
        self.magick_validated = False

        self.packages_built = 0
        self.packages_already_built = 0
        self.packages_disabled = 0
        self._package_started = 0
        self._package_in_progress = ""
        self._package_version = ""
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

    def resolve(self, key: str) -> Resolved | None:
        """The version to build, or None for a disabled package.

        A completion marker whose artifacts are intact is reused with no network
        traffic unless `--latest` asks for a refresh; build() then skips it.
        """
        if not self.package_enabled(key):
            return None
        if not self.latest:
            recorded = read_marker(self.marker_path(key))
            if recorded is not None and self.artifacts_present(key):
                return Resolved("", recorded[0], recorded[1])

        resolved = resolve_upstream(self.resolver, key)
        if resolved is None:
            raise BuildError(f"Failed to resolve the latest {key} version.")
        return resolved

    # -- build bookkeeping -----------------------------------------------

    def build(self, key: str, version: str | None) -> bool:
        """Decide whether this package's recipe should run."""
        if key not in registry.PACKAGES:
            raise BuildError(f"build() received unsupported package '{key}'.")
        if not self.package_enabled(key):
            self.packages_disabled += 1
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
                self.logger.debug(
                    "Force a rebuild with: " + shellquote.join(["rm", "-f", "--", str(marker)])
                )
                return False
            self.logger.warn(
                f"{key} has a completion marker but its artifacts are missing; rebuilding."
            )
        self._start_package_build(key, version, recorded[0] if recorded else "")
        return True

    def _start_package_build(self, key: str, version: str, prior_version: str) -> None:
        # Recipes install in place, so the marker goes before any write. A
        # library is linked into ImageMagick, which has to relink against it.
        self.marker_path(key).unlink(missing_ok=True)
        if registry.PACKAGES[key].kind is registry.Kind.LIBRARY:
            self.marker_path("imagemagick").unlink(missing_ok=True)
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
