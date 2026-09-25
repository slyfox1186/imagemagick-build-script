"""The orchestrator: validate the request, prepare the build root, run stages."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from types import FrameType

from . import registry
from .cli import (
    SCRIPT_NAME,
    SCRIPT_VERSION,
    Arguments,
    parse_arguments,
    requested_metadata,
    resolve_config_path,
    usage_text,
)
from .config import BuildSettings, Selection, load_config
from .runtime.context import BuildContext
from .runtime.errors import ISSUE_TRACKER_URL, REPOSITORY_URL, BuildError, SignalStop, UsageError
from .runtime.exec import Runner, base_environment, notify_failure
from .runtime.logging import Logger, format_duration
from .runtime.paths import (
    DirectoryLock,
    canonicalize,
    is_exclusive_regular_file,
    remove_tree_one_filesystem,
    safe_remove_tree,
)
from .runtime.settings import MAX_PROCESS_INTEGER, parse_integer
from .runtime.state import (
    BUILD_CONTEXT_NAME,
    BUILD_ROOT_MARKER_NAME,
    LEGACY_LOCK_NAME,
    assert_safe_build_root,
    build_context_changes,
    build_root_is_adoptable,
    build_root_marker_matches,
    parse_build_context,
    publish_atomically,
    render_build_context,
    write_build_root_marker,
)
from .stages.core_tools import install_core_tools
from .stages.extra_libraries import install_extra_libraries
from .stages.fonts import install_fonts
from .stages.image_libraries import install_image_libraries
from .stages.imagemagick import ImageMagickStage, report_installed_version
from .stages.system_setup import SystemSetup, configure_environment
from .stages.text_libraries import install_text_libraries

_POSITIVE_INTEGER_SETTINGS = (
    "DOWNLOAD_CONNECT_TIMEOUT",
    "DOWNLOAD_MAX_TIME",
    "DOWNLOAD_MAX_BYTES",
    "DOWNLOAD_MAX_EXTRACTED_BYTES",
    "DOWNLOAD_MAX_MEMBERS",
    "DOWNLOAD_LOCK_TIMEOUT",
    "HOST_MUTATION_LOCK_TIMEOUT",
    "GIT_OPERATION_TIMEOUT",
    "GIT_CLONE_TIMEOUT",
)
_NON_NEGATIVE_INTEGER_SETTINGS = ("DOWNLOAD_RETRY", "DOWNLOAD_RETRY_DELAY")

# Directories that running this project creates in a checkout beside the build
# root: Python bytecode and the development tools' caches. None are tracked.
LEFTOVER_ARTIFACT_NAMES = ("__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache")
# The build root used by releases before the current layout.
LEGACY_BUILD_ROOT_NAMES = ("magick-build-script",)


def validate_request(selection: Selection) -> None:
    """Everything checkable from the request alone, before any host change."""
    issues: list[str] = []
    for name in _POSITIVE_INTEGER_SETTINGS:
        value = os.environ.get(name, "")
        maximum = sys.maxsize if name.endswith("_BYTES") else MAX_PROCESS_INTEGER
        if value and parse_integer(value, maximum=maximum) is None:
            issues.append(f"'{name}' must be a positive integer; got '{value}'")
    for name in _NON_NEGATIVE_INTEGER_SETTINGS:
        value = os.environ.get(name, "")
        if value and parse_integer(value, minimum=0, maximum=MAX_PROCESS_INTEGER) is None:
            issues.append(f"'{name}' must be a non-negative integer; got '{value}'")
    issues += selection.problems()
    if issues:
        listed = "\n - ".join(issues)
        raise UsageError(f"Invalid build request:\n - {listed}")


class Orchestrator:
    def __init__(self, repo_root: Path, argv: list[str]) -> None:
        self.repo_root = repo_root
        self.argv = argv
        self.invocation_dir = Path.cwd()
        self.logger = Logger()
        self.runner = Runner(self.logger, base_environment())
        self.build_root = Path()
        self.context: BuildContext | None = None
        self._lock: DirectoryLock | None = None

    # -- build root ------------------------------------------------------

    def resolve_build_root(self) -> None:
        requested = os.environ.get("BUILD_ROOT") or str(self.repo_root / "build")
        if not requested.startswith("/"):
            requested = str(self.invocation_dir / requested)
        self.build_root = canonicalize(requested)

    def validate_build_root(self) -> None:
        root = self.build_root
        assert_safe_build_root(root, self.repo_root)
        if root.exists() and not root.is_dir():
            raise BuildError(f"The build root exists but is not a directory: '{root}'.")
        if not root.is_dir():
            return
        try:
            occupied = any(root.iterdir())
        except OSError as error:
            raise BuildError(f"Unable to inspect the build root '{root}'.") from error
        if not occupied or build_root_marker_matches(root / BUILD_ROOT_MARKER_NAME, root):
            return
        if build_root_is_adoptable(root):
            self.logger.warn(
                f"'{root}' holds only this project's empty scaffolding from an interrupted run; "
                "adopting it."
            )
            return
        raise BuildError(
            f"'{root}' already contains data and lacks a valid path-bound build-root marker. "
            "Refusing to reuse it."
        )

    def acquire_lock(self, root: Path) -> DirectoryLock:
        lock = DirectoryLock(root)
        if lock.acquire():
            return lock
        try:
            owner = lock.owner_pid()
        except BuildError:
            owner = None
        if owner is not None:
            raise BuildError(
                f"Another build is already running in '{root}' (PID {owner}). Wait for it, "
                f"or stop it with: kill {owner}"
            )
        raise BuildError(f"Another build is already running in '{root}'.")

    def initialize_build_root(self) -> None:
        root = self.build_root
        self.validate_build_root()
        # Created empty and marked before anything goes inside, so an interrupt
        # leaves an empty directory the next run accepts. There is deliberately
        # no `sudo` fallback: the marker means "this project created it".
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BuildError(f"Unable to create the build root '{root}'.") from error
        if not os.access(root, os.R_OK | os.W_OK | os.X_OK):
            raise BuildError(f"The build root '{root}' is not writable by the current user.")
        self._lock = self.acquire_lock(root)
        self._lock.assert_current()
        self.validate_build_root()

        managed = [root / name for name in ("packages", "workspace", "build.log")]
        managed += [root / BUILD_ROOT_MARKER_NAME, root / BUILD_CONTEXT_NAME]
        for path in managed:
            if path.is_symlink():
                raise BuildError(f"Refusing symlink at managed build path '{path}'.")
        for path in (root / "build.log", root / BUILD_ROOT_MARKER_NAME, root / BUILD_CONTEXT_NAME):
            if path.exists() and not is_exclusive_regular_file(path):
                raise BuildError(f"Refusing a managed path that is not a plain file: '{path}'.")
        write_build_root_marker(root)
        # Removed only while this run holds the directory lock, so no build of
        # either generation can be using it.
        legacy_lock = root / LEGACY_LOCK_NAME
        if is_exclusive_regular_file(legacy_lock):
            legacy_lock.unlink()
        (root / "packages").mkdir(exist_ok=True)
        (root / "workspace").mkdir(exist_ok=True)
        log_file = root / "build.log"
        log_file.write_text("", encoding="utf-8")
        self.logger.log_file = log_file
        self.runner.log_file = log_file

    # -- build context ---------------------------------------------------

    def current_build_context(self, context: BuildContext) -> str:
        """Every input that changes what -march=native and the compiler produce."""
        env = context.env
        compiler = env["CC"]
        path = context.runner.which(compiler) or compiler
        version = context.runner.capture([compiler, "--version"]).stdout.split("\n", 1)[0]
        cpu_model = ""
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("model name"):
                    cpu_model = line.split(": ", 1)[-1]
                    break
        except OSError:
            pass
        fields = {
            "os": f"{context.operating_system} {context.release_version}",
            "arch": os.uname().machine,
            "multiarch": context.multiarch,
            "cpu_model": cpu_model,
            "compiler": f"{path} {version}",
            "cflags": env["CFLAGS"],
            "cxxflags": env["CXXFLAGS"],
            "cppflags": env["CPPFLAGS"],
            "ldflags": env["LDFLAGS"],
        }
        if context.selection.has_config:
            # A selection change invalidates everything: configure probes see
            # whatever the workspace holds.
            fields["package_selection"] = " ".join(context.selection.enabled_names())
        return render_build_context(fields)

    def refresh_build_context(self, context: BuildContext) -> None:
        """Invalidate every marker and the workspace when the context changed.

        Stale workspace artifacts would otherwise feed later packages' configure
        probes with libraries the new build has not produced yet (observed
        live: libtiff picking up a previous context's libwebp).
        """
        context_file = context.cwd / BUILD_CONTEXT_NAME
        current = self.current_build_context(context)
        if context_file.is_file():
            previous = context_file.read_text(encoding="utf-8", errors="replace")
            changes = build_context_changes(previous, current)
            if changes:
                self.logger.warn(
                    "The build context changed since the last run; invalidating every completion "
                    "marker and the workspace so everything rebuilds consistently:\n"
                    + "\n".join(changes)
                )
                for marker in context.packages.glob("*.done"):
                    marker.unlink(missing_ok=True)
                safe_remove_tree(context.workspace, context.cwd)
                context.workspace.mkdir()
            elif parse_build_context(previous).get("schema") == "1":
                self.logger.info(
                    "Adopted the existing build tree; completed packages remain valid."
                )
        publish_atomically(context_file, current, mode=0o600)

    # -- cleanup ---------------------------------------------------------

    def _leftover_artifacts(self) -> list[Path]:
        """Directories a build and its tooling leave in the checkout."""
        repository = canonicalize(self.repo_root)
        candidates = [repository / name for name in LEFTOVER_ARTIFACT_NAMES]
        candidates.extend(sorted(repository.glob("*.egg-info")))
        candidates.extend(
            path
            for path in sorted(repository.rglob("__pycache__"))
            if ".git" not in path.relative_to(repository).parts
        )
        for legacy in LEGACY_BUILD_ROOT_NAMES:
            path = repository / legacy
            # A legacy root is only ours while it carries a marker or is empty.
            if path.is_dir() and not path.is_symlink():
                if (path / BUILD_ROOT_MARKER_NAME).exists() or not any(path.iterdir()):
                    candidates.append(path)
        targets: list[Path] = []
        for candidate in candidates:
            if candidate.is_dir() and not candidate.is_symlink() and candidate not in targets:
                targets.append(candidate)
        return targets

    def _ask(self, question: str) -> bool | None:
        """yes/no from an interactive terminal; None when there is no answer."""
        while True:
            try:
                choice = self.logger.prompt(f"{question} (yes/no): ").strip().lower()
            except EOFError:
                print()
                return None
            if choice in ("y", "yes"):
                return True
            if choice in ("n", "no", ""):
                return False
            self.logger.warn("Invalid input. Please enter 'yes' or 'no'.")

    def cleanup(self) -> None:
        root = self.build_root
        leftovers = self._leftover_artifacts()
        if not root.exists():
            self.logger.info(f"Build root does not exist; nothing to clean: '{root}'.")
            if (
                leftovers
                and sys.stdin.isatty()
                and self._ask(f"Remove {len(leftovers)} build leftover(s) in the checkout?")
            ):
                self._remove_leftovers(leftovers)
            return
        resolved = canonicalize(root)
        assert_safe_build_root(resolved, self.repo_root)
        # A build already holds this directory lock; a second descriptor would
        # contend with our own lock.
        lock = self._lock if self._lock is not None and self._lock.held else None
        owned = lock is None
        if lock is None:
            lock = self.acquire_lock(resolved)
        try:
            lock.assert_current()
            marked = build_root_marker_matches(resolved / BUILD_ROOT_MARKER_NAME, resolved)
            if not marked and not build_root_is_adoptable(resolved):
                raise BuildError(
                    f"Refusing to remove '{resolved}': its build-root marker is missing or does "
                    "not match this path."
                )
            if not sys.stdin.isatty():
                self.logger.info(f"Non-interactive session; build files preserved: '{resolved}'.")
                self.logger.hint(f"Remove them later with: python3 {SCRIPT_NAME} --cleanup")
                return
            question = f"Remove all build files under '{resolved}'"
            if leftovers:
                question += f" and {len(leftovers)} build leftover(s) in the checkout"
            answer = self._ask(f"{question}?")
            if not answer:
                self.logger.info(f"Build files preserved: '{resolved}'.")
                return
            try:
                lock.assert_current()
                remove_tree_one_filesystem(resolved)
            except OSError as error:
                raise BuildError(f"Failed to remove the build root '{resolved}'.") from error
            lock.release()
            self.logger.log_file = None
            self.runner.log_file = None
            self.logger.info(f"Removed the build root: '{resolved}'.")
            self._remove_leftovers(self._leftover_artifacts())
        finally:
            if owned:
                lock.release()

    def _remove_leftovers(self, targets: list[Path]) -> None:
        repository = canonicalize(self.repo_root)
        for target in targets:
            safe_remove_tree(target, repository)
            self.logger.info(f"Removed build leftover: '{target}'.")

    # -- the build -------------------------------------------------------

    def host_mutation_lock(self) -> DirectoryLock:
        """Serialize APT work across every run by this user.

        The build-root lock is per build root, so two builds with different
        roots would otherwise collide on dpkg's own lock. The lock lives in the
        per-user runtime directory, never in world-writable /tmp.
        """
        base = os.environ.get("XDG_RUNTIME_DIR") or f"{os.environ.get('HOME', '/tmp')}/.cache"
        lock_dir = canonicalize(base) / "imagemagick-build-script"
        try:
            lock_dir.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise BuildError(f"Unable to create the host-mutation lock in '{lock_dir}'.") from error
        lock = DirectoryLock(lock_dir)
        timeout = int(os.environ.get("HOST_MUTATION_LOCK_TIMEOUT") or "3600")
        if not lock.acquire(timeout=timeout):
            raise BuildError("Timed out waiting for the host-mutation lock; no host changes made.")
        return lock

    def build_context(
        self, arguments: Arguments, settings: BuildSettings, selection: Selection
    ) -> BuildContext:
        # The affinity mask, not the CPU count: under `taskset -c 0,1` a host
        # with 24 cores must launch 2 compile jobs, not 24.
        threads = arguments.jobs or len(os.sched_getaffinity(0))
        self.context = BuildContext(
            repo_root=self.repo_root,
            build_root=self.build_root,
            logger=self.logger,
            runner=self.runner,
            selection=selection,
            build_threads=threads,
            latest=arguments.latest or settings.latest,
            gcc_version=arguments.gcc_version,
        )
        return self.context

    def run_build(self, context: BuildContext) -> None:
        machine = os.uname().machine
        if machine != "x86_64":
            raise BuildError(f"Unsupported architecture '{machine}'. Only x86_64 is supported.")
        os.umask(0o022)
        self.initialize_build_root()
        configure_environment(context)
        # The first point where a password is worth asking for: everything
        # above validates the request or writes inside the user's build root.
        self.logger.info(
            "Validating sudo credentials (needed for APT, fonts, and the final install step)..."
        )
        self.runner.require_sudo()

        self.logger.banner(f"ImageMagick Build Script {SCRIPT_VERSION}")
        self.logger.info(f"Build root: {context.cwd}")
        self.logger.info(f"Parallel jobs: {context.build_threads}")
        selected = len(context.selection.enabled_names())
        self.logger.info(f"Selected packages: {selected} of {len(registry.PACKAGE_NAMES)}")
        self.logger.info("Completed packages are reused; 'already built' does not mean disabled.")
        if context.latest:
            self.logger.info("Version refresh requested: recorded versions will be re-resolved.")

        with self.host_mutation_lock():
            SystemSetup(context).run()
        self.refresh_build_context(context)

        install_core_tools(context)
        install_image_libraries(context)
        install_text_libraries(context)
        install_extra_libraries(context)
        install_fonts(context)
        ImageMagickStage(context).run()

        report_installed_version(context)
        self.logger.blank()
        if context.packages_disabled:
            self.logger.info(f"Disabled packages: {context.packages_disabled}")
        self.logger.info(f"Build log: {context.log_file}")
        self.logger.summary(
            built=context.packages_built,
            reused=context.packages_already_built,
            failed=0,
            elapsed=format_duration(self.logger.elapsed_seconds),
        )
        self.cleanup()
        self.logger.farewell(REPOSITORY_URL)

    def run(self) -> int:
        metadata = requested_metadata(self.argv)
        if metadata is not None:
            sys.stdout.write(metadata)
            return 0
        # Checked here, not inside run_build: --cleanup never reaches it, and
        # it is the one destructive action in the project.
        if os.geteuid() == 0:
            self.logger.error(
                f"Run '{SCRIPT_NAME}' as a regular user with sudo available, not as root; it "
                "uses sudo only for APT, fonts, and publishing the validated install."
            )
            return 1

        arguments = parse_arguments(self.argv)
        self.logger.debug_enabled = self.runner.debug = arguments.debug
        settings = BuildSettings()
        selection = Selection()
        if arguments.config_path is not None:
            loaded = load_config(
                resolve_config_path(arguments.config_path, self.invocation_dir), self.logger
            )
            settings, selection = loaded.settings, loaded.selection
        self.resolve_build_root()

        if arguments.cleanup:
            self.cleanup()
            return 0
        if not arguments.build:
            sys.stdout.write(usage_text())
            return 0
        validate_request(selection)
        self.run_build(self.build_context(arguments, settings, selection))
        return 0

    def teardown(self) -> None:
        self.runner.stop_sudo_keepalive()
        if self.context is not None:
            self.context.remove_registered_temporary_paths()
        if self._lock is not None:
            self._lock.release()
            self._lock = None


def _install_signal_handlers() -> None:
    def handler(signal_number: int, _frame: FrameType | None) -> None:
        name = signal.Signals(signal_number).name.removeprefix("SIG")
        raise SignalStop(name, {"HUP": 129, "INT": 130, "TERM": 143}.get(name, 1))

    for signal_name in ("SIGHUP", "SIGINT", "SIGTERM"):
        signal.signal(getattr(signal, signal_name), handler)


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    orchestrator = Orchestrator(repo_root, argv)
    _install_signal_handlers()
    try:
        return orchestrator.run()
    except SignalStop as stop:
        orchestrator.logger.warn(
            f"Received '{stop.name}'; stopping. Build files are preserved in "
            f"'{orchestrator.build_root}'."
        )
        return stop.exit_code
    except UsageError as error:
        orchestrator.logger.error(str(error))
        return 1
    except BuildError as error:
        _report_failure(orchestrator, error)
        return 1
    finally:
        orchestrator.teardown()


def _report_failure(orchestrator: Orchestrator, error: BuildError) -> None:
    """Report a fatal failure as one record, with the log and bug-report pointer under it."""
    context = orchestrator.context
    in_progress = context._package_in_progress if context is not None else ""
    detail = [str(error)]
    if context is not None and context.log_file.is_file():
        detail.append(f"Build log: {context.log_file}")
    detail.append(f"Report a bug: {ISSUE_TRACKER_URL}")
    print(file=sys.stderr)
    if context is not None and in_progress:
        orchestrator.logger.package_failed(in_progress, context._package_version, detail[0])
        for line in detail[1:]:
            orchestrator.logger.hint(line)
    else:
        orchestrator.logger.error("\n".join(detail))
    if context is not None:
        orchestrator.logger.summary(
            built=context.packages_built,
            reused=context.packages_already_built,
            failed=1 if in_progress else 0,
            elapsed=format_duration(orchestrator.logger.elapsed_seconds),
        )
    print(file=sys.stderr)
    notify_failure(str(error))
