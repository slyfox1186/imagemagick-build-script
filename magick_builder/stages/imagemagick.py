"""Configure, build, stage, validate, publish, and verify ImageMagick.

The install is staged with `make DESTDIR=` as the build user and validated
there; only then is it published to /usr/local in a single privileged copy,
and success is claimed only after the live binary proves it.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .. import registry
from ..runtime import shellquote
from ..runtime.context import MAGICK_BINARY, BuildContext, link_mode
from ..runtime.errors import BuildError
from ..runtime.exec import defer_cancellation
from ..runtime.paths import DirectoryLock, safe_remove_tree
from ..runtime.state import CONFIGURE_FINGERPRINT_SUFFIX, publish_atomically, read_marker
from .perlmagick import PERL, build_static_perlmagick
from .self_contained import (
    BUNDLED_LIBRARY_DIRECTORY,
    SelfContainedInstall,
    audit_published_install,
)

# Part of the configure fingerprint. Bump it when the recipe changes what gets
# built without changing a configure argument, so existing installs rebuild once.
# Revision 2: configure is no longer regenerated with autoreconf, which had
# baked this repository's Git commit into ImageMagick's version string.
# Revision 3: the install bundles its workspace libraries and no longer
# depends on the build root (see self_contained.py). Revision 4: the link mode
# decides the install's layout, and the manifest prunes everything the
# previous install left under /usr/local. Revision 5: the static build installs
# PerlMagick (see perlmagick.py).
RECIPE_REVISION = "5"
MANIFEST_DIRECTORY = "usr/local/share/imagemagick-build-script"
MANIFEST_FILE = f"{MANIFEST_DIRECTORY}/manifest.txt"
POLICY_FILE = "usr/local/etc/ImageMagick-7/policy.xml"
# The digest of the default policy this builder last published: a later publish
# replaces an untouched default but never an administrator's edited policy.
POLICY_RECORD = f"{MANIFEST_DIRECTORY}/policy.sha256"
# What this workspace published, file by file: `<sha256>  <path>`, or
# `link-<sha256 of the target>  <path>` for a symlink, so the first field never
# holds a space. A finished build is reused only while
# /usr/local still holds exactly these files, so an ImageMagick another build
# root or a manual install put there, even of the same release, is rebuilt.
INSTALL_RECEIPT_NAME = "imagemagick.installed"
# Every file a publish will replace or remove, saved first and restored if the
# new install fails its checks. It sits beside the manifest, not in a build
# root: its presence is what tells every build root and user that an install
# was never committed or rolled back, and the next install waits for it.
BACKUP_FILE = f"{MANIFEST_DIRECTORY}/previous-install.tar"
INSTALL_PREFIX = Path("/usr/local")
# Where manifest entries (relative paths such as usr/local/bin/magick) live.
SYSTEM_ROOT = Path("/")
# What --enable-legacy-support installs beside magick.
LEGACY_UTILITIES = (
    "animate",
    "compare",
    "composite",
    "conjure",
    "convert",
    "display",
    "identify",
    "import",
    "magick-script",
    "mogrify",
    "montage",
    "stream",
)
# ExtUtils::Install's record of every module installed into the site tree. A
# staged copy names only ImageMagick, so it is never published, and a copy an
# older install's manifest recorded is the system's own record, never pruned.
PERL_LOCAL_RECORD = "perllocal.pod"
# Loads Image::Magick, reads a built-in image and checks the release it reports.
PERLMAGICK_SMOKE_TEST = """
my ($release) = @ARGV;
my $image = Image::Magick->new;
my $error = $image->Read("logo:");
die "$error\\n" if $error;
my $version = $image->Get("version");
die "Image::Magick reports '$version'\\n" unless index("$version ", "ImageMagick $release ") >= 0;
print "$version\\n";
"""
# One row of `magick -list format`: name, module, then the r/w/+ mode column.
_FORMAT_ROW = re.compile(r"^\s*\S+\s+\S+\s+([r-])([w-])[+-]\s")


def toggle_arguments(context: BuildContext) -> list[str]:
    """One `--with`/`--without` per source-built delegate, in fixed table order.

    Disabled packages get an explicit `--without` so a stray system development
    package cannot silently re-enable what the config turned off.
    """
    return [
        f"--with-{delegate.flag}"
        if context.package_enabled(delegate.package)
        else f"--without-{delegate.flag}"
        for delegate in registry.DELEGATES
    ]


def required_delegates(context: BuildContext) -> list[str]:
    """The APT baseline plus one token per enabled source-built provider.

    jng is the JPEG-in-PNG delegate and needs both of its providers.
    """
    tokens = list(registry.BASELINE_DELEGATES)
    tokens += [
        delegate.token
        for delegate in registry.DELEGATES
        if delegate.token and context.package_enabled(delegate.package)
    ]
    if context.package_enabled("libjpeg-turbo") and context.package_enabled("libpng"):
        tokens.append("jng")
    return tokens


def pkg_config_command(context: BuildContext) -> str:
    """The workspace pkg-config when it is built, otherwise the APT one."""
    if context.package_enabled("pkg-config"):
        return str(context.workspace / "bin/pkg-config")
    found = context.runner.which("pkg-config")
    if found is None:
        raise BuildError("No system pkg-config found and the workspace build is disabled.")
    return found


STATIC_PKG_CONFIG_NAME = "magick-pkg-config"
# The wrapper configure runs in static mode. `--static` makes pkg-config add
# Libs.private, which the workspace archives need on the link line
# (libsharpyuv behind libwebp, the codecs behind libtiff, zlib behind libpng).
# It must not apply to the system delegates: their private dependencies are
# shared libraries whose development packages are not installed (libzip names
# -lssl -lcrypto), and a missing one fails every later configure link test.
# ImageMagick's configure also ignores <PROBE>_LIBS overrides, so the switch
# happens where pkg-config is called, per module list.
_STATIC_PKG_CONFIG_TEMPLATE = """\
#!/bin/sh
# Written by the ImageMagick stage of imagemagick-build-script.
# Adds --static when every requested module's .pc file lives in the workspace.
real={real}
workspace={workspace}
static=--static
for argument in "$@"; do
    case $argument in
    -*) continue ;;
    esac
    directories=$("$real" --variable=pcfiledir "$argument" 2>/dev/null) || {{ static=; break; }}
    for directory in $directories; do
        case $directory in
        "$workspace"/*) ;;
        *) static=; break 2 ;;
        esac
    done
done
exec "$real" $static "$@"
"""


def static_pkg_config(context: BuildContext) -> Path:
    return context.workspace / "bin" / STATIC_PKG_CONFIG_NAME


def write_static_pkg_config(context: BuildContext) -> Path:
    """Write the wrapper into the workspace; it is deleted with the build root."""
    wrapper = static_pkg_config(context)
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(
        _STATIC_PKG_CONFIG_TEMPLATE.format(
            real=shellquote.quote(pkg_config_command(context)),
            workspace=shellquote.quote(str(context.workspace)),
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def link_mode_arguments(context: BuildContext) -> list[str]:
    """The arguments that differ between the static default and `--shared`.

    Static: the coders are compiled into libMagickCore (`--with-modules` under
    `--disable-shared` is only a warned no-op), and `--with-perl` would build a
    separate statically linked Perl interpreter instead of an Image::Magick
    module, so perlmagick.py builds the module. libfpx is C++ and ImageMagick
    links with the C driver, so the runtime is named here.
    """
    if context.shared:
        return [
            "--enable-shared",
            "--enable-static",
            "--with-modules",
            "--with-perl",
            f"PKG_CONFIG={pkg_config_command(context)}",
        ]
    arguments = [
        "--disable-shared",
        "--enable-static",
        "--without-modules",
        "--without-perl",
        f"PKG_CONFIG={static_pkg_config(context)}",
    ]
    if context.package_enabled("libfpx"):
        arguments.append("LIBS=-lstdc++")
    return arguments


def configure_arguments(context: BuildContext) -> list[str]:
    """ImageMagick's configure arguments.

    Most optional delegates (djvu, lqr, openexr, pango, raw, wmf, zip) default
    to yes and activate once their APT development packages are installed;
    fftw defaults to no. `--with-pkgconfigdir` is absent because upstream's
    Makefile.am overrides it, and `--enable-delegate-build` is absent because it
    means in-tree delegate builds, which this external workspace is not.
    `--enable-hugepages` is absent because its one effect is a MAP_HUGETLB
    attempt before every large mapping, which fails on hosts without reserved
    huge pages. OpenCL comes from the APT ICD loader (see system_setup).
    `--with-wmf` is explicit because its default is `$build_modules`, which
    would silently drop the delegate from the static build.
    """
    env = context.env
    opencl_target = " -DCL_TARGET_OPENCL_VERSION=300"
    return [
        "--prefix=/usr/local",
        "--enable-hdri",
        "--enable-legacy-support",
        "--enable-opencl",
        "--with-fftw",
        "--with-fontpath=/usr/share/fonts/truetype",
        "--with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu",
        "--with-gs-font-dir=/usr/share/fonts/ghostscript",
        "--with-gslib",
        "--with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35",
        "--with-gvc",
        "--with-heic",
        "--with-pic",
        "--with-quantum-depth=16",
        "--with-rsvg",
        "--with-utilities",
        "--with-wmf",
        "--without-autotrace",
        *toggle_arguments(context),
        *link_mode_arguments(context),
        f"CFLAGS={env['CFLAGS']}{opencl_target}",
        f"CXXFLAGS={env['CXXFLAGS']}{opencl_target}",
        f"CPPFLAGS={env['CPPFLAGS']}",
    ]


def configure_fingerprint(arguments: list[str]) -> str:
    payload = "".join(f"{argument}\n" for argument in [*arguments, f"recipe={RECIPE_REVISION}"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reported_version_matches(line: str, version: str) -> bool:
    return f"ImageMagick {version} " in f"{line} "


def report_field(report: list[str], name: str) -> str:
    """The value of a `magick -version` line such as `Features: ...`, which magick
    ends with a space."""
    return next(
        (line.split(": ", 1)[1].strip() for line in report if line.startswith(f"{name}: ")), ""
    )


def read_installed_manifest() -> list[str]:
    """The entries the previous publish recorded, or none when it left no readable record."""
    try:
        return (SYSTEM_ROOT / MANIFEST_FILE).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []


def stale_entries(previous: list[str], current: list[str]) -> list[str]:
    """Files the previous publish installed under /usr/local that this one does not.

    ImageMagick loads every coder module in its versioned module directory, so a
    module left by a build with more delegates keeps a disabled format working,
    and a static build must not leave the shared libraries, modules and bundled
    workspace libraries of the build it replaces. Only manifest-recorded files
    are candidates: a library nobody else installed under /usr/local is never
    touched, and the policy is always among the staged entries.
    """
    kept = set(current)
    return [
        entry
        for entry in recorded_entries(previous)
        if entry not in kept and Path(entry).name != PERL_LOCAL_RECORD
    ]


def recorded_entries(previous: list[str]) -> list[str]:
    """Manifest entries safe to act on as root: relative paths under usr/local."""
    return [
        entry
        for entry in previous
        if entry.startswith("usr/local/") and ".." not in Path(entry).parts
    ]


def mutated_entries(entries: list[str], excluded: list[str], previous: list[str]) -> list[str]:
    """Every path a publish writes or removes: the staged files it copies and
    the previous install's leftovers. Paths the copy excludes are never touched."""
    skipped = {item.removeprefix("--exclude=") for item in excluded}
    copied = [entry for entry in recorded_entries(entries) if entry not in skipped]
    return sorted({*copied, *stale_entries(previous, entries)})


@dataclass(frozen=True)
class Backup:
    """What a publish saved first: the archive (None when nothing it touches
    existed), the paths that existed, and whether the archive's directory was
    created for it."""

    archive: Path | None
    existing: frozenset[str]
    created_directory: bool


def restore_command(archive: Path) -> str:
    return f"sudo tar -C / --keep-directory-symlink -xf {archive} && sudo rm -f -- {archive}"


@contextmanager
def prefix_lock() -> Iterator[None]:
    """Hold the lock on /usr/local that every build root and user shares.

    Taken for every read of the installed tree as well as for the install, so
    no check sees another build's half-published files.
    """
    lock = DirectoryLock(INSTALL_PREFIX)
    timeout = int(os.environ.get("HOST_MUTATION_LOCK_TIMEOUT") or "3600")
    if not lock.acquire(timeout=timeout):
        raise BuildError(
            f"Timed out waiting for another build to finish installing into {INSTALL_PREFIX}."
        )
    with lock:
        yield


def install_receipt(entries: list[str]) -> str:
    """One line per published entry describing what is there now.

    The security policy is left out: administrators edit it, and an edited
    policy is kept on purpose.
    """
    lines: list[str] = []
    for entry in sorted(entries):
        if entry == POLICY_FILE:
            continue
        path = SYSTEM_ROOT / entry
        if path.is_symlink():
            target = os.readlink(path).encode("utf-8", "surrogateescape")
            lines.append(f"link-{hashlib.sha256(target).hexdigest()}  {entry}")
        else:
            lines.append(f"{file_digest(path) or 'missing'}  {entry}")
    return "".join(f"{line}\n" for line in lines)


def receipt_entries(receipt: str) -> list[str]:
    return [line.split("  ", 1)[1] for line in receipt.splitlines() if "  " in line]


def file_digest(path: Path) -> str | None:
    """The sha256 of a file, or None when it is absent or unreadable."""
    try:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError:
        return None


def read_policy_record(record: Path) -> str | None:
    """The digest of the default policy the previous publish installed, if recorded."""
    try:
        return record.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def needed_libraries(context: BuildContext, path: Path) -> list[str]:
    """The sonames an installed ELF object loads (its DT_NEEDED entries)."""
    completed = context.runner.capture(["patchelf", "--print-needed", str(path)])
    if completed.returncode != 0:
        raise BuildError(f"patchelf --print-needed {path} failed: {completed.stderr.strip()}")
    return completed.stdout.split()


def installed_modules(magick: Path) -> list[Path]:
    """The coder and filter modules installed under magick's prefix."""
    return sorted((magick.parent.parent / "lib").glob("ImageMagick-*/modules-*/*/*.so"))


def verify_link_mode(context: BuildContext, report: list[str], magick: Path) -> str:
    """The evidence that the installed magick has the build's link mode.

    Three independent facts must all agree with the mode: the Features line
    (`Modules`), the sonames the binary loads (`libMagick*`) and the coder and
    filter modules. Any disagreement is a failed build, not a note.
    """
    features = report_field(report, "Features").split()
    libraries = [
        soname.split("-", 1)[0]
        for soname in needed_libraries(context, magick)
        if soname.startswith("libMagick")
    ]
    modules = installed_modules(magick)
    facts = [
        "Modules feature" if "Modules" in features else "no Modules feature",
        f"{' and '.join(libraries)} linked" if libraries else "no libMagick shared objects",
        f"{len(modules)} module{'' if len(modules) == 1 else 's'}" if modules else "no modules",
    ]
    evidence = ", ".join(facts)
    observed = ("Modules" in features, bool(libraries), bool(modules))
    if observed != (context.shared,) * 3:
        raise BuildError(f"The installed magick is not a {link_mode(context)} build: {evidence}.")
    return evidence


class ImageMagickStage:
    def __init__(self, context: BuildContext) -> None:
        self.context = context
        self.logger = context.logger

    # -- validation ------------------------------------------------------

    def validate_staged_install(self, staging: Path, version: str) -> None:
        """Nothing outside ./usr/local, and a staged magick reporting this version."""
        staged_magick = staging / "usr/local/bin/magick"
        if not os.access(staged_magick, os.X_OK):
            raise BuildError("The staged install is missing usr/local/bin/magick.")
        outside = sorted(entry.name for entry in staging.iterdir() if entry.name != "usr")
        if outside:
            raise BuildError(f"The staged install wrote outside /usr: {', '.join(outside)}")
        usr = staging / "usr"
        local = usr / "local"
        if usr.is_symlink() or local.is_symlink() or not local.is_dir():
            raise BuildError("The staged /usr/local prefix must contain real directories.")
        outside = sorted(entry.name for entry in usr.iterdir() if entry.name != "local")
        if outside:
            raise BuildError(f"The staged install wrote outside /usr/local: {', '.join(outside)}")
        completed = self.context.runner.capture(
            [str(staged_magick), "-version"],
            # The bundled libraries are found through a run path that names
            # their published location, which does not exist until publication.
            env_overrides={
                "LD_LIBRARY_PATH": ":".join(
                    str(staging / directory)
                    for directory in (
                        "usr/local/lib",
                        "usr/local/lib64",
                        BUNDLED_LIBRARY_DIRECTORY.relative_to("/"),
                    )
                )
            },
        )
        line = completed.stdout.split("\n", 1)[0]
        if completed.returncode != 0:
            raise BuildError("The staged magick binary failed to execute.")
        if not reported_version_matches(line, version):
            raise BuildError(f"The staged magick reports '{line}' instead of version {version}.")
        self.logger.info(f"Staged install validated: {line}")

    def validate_installation(self, version: str, magick: Path = MAGICK_BINARY) -> None:
        """Exact version, every expected delegate, MagickCore.pc, and a round trip."""
        context = self.context
        runner = context.runner
        if not os.access(magick, os.X_OK):
            raise BuildError(f"{magick} is missing or not executable.")
        completed = runner.capture([str(magick), "-version"])
        if completed.returncode != 0:
            raise BuildError(f"Cannot execute {magick} -version.")
        report = completed.stdout.splitlines()
        if not any(reported_version_matches(line, version) for line in report):
            raise BuildError(
                f"The installed magick reports a different version than this build ({version})."
            )
        verify_link_mode(context, report, magick)

        delegates_line = report_field(report, "Delegates (built-in)")
        present = set(delegates_line.split())
        missing = [token for token in required_delegates(context) if token not in present]
        if missing:
            raise BuildError(
                f"The installed magick is missing expected delegates: {' '.join(missing)} "
                f"(built with: {delegates_line or 'none'})"
            )

        pc = runner.capture(
            [pkg_config_command(context), "--modversion", "MagickCore"],
            env_overrides={"PKG_CONFIG_LIBDIR": "/usr/local/lib/pkgconfig", "PKG_CONFIG_PATH": ""},
        )
        if pc.returncode != 0:
            raise BuildError("MagickCore.pc is not resolvable from /usr/local/lib/pkgconfig.")
        # The .pc version omits the release suffix (7.1.2-29 -> 7.1.2).
        base_version = version.rsplit("-", 1)[0]
        if pc.stdout.strip() != base_version:
            raise BuildError(
                f"MagickCore.pc reports '{pc.stdout.strip()}', expected '{base_version}'."
            )

        config_script = magick.parent / "MagickCore-config"
        if config_script.exists() and runner.capture([str(config_script), "--cflags"]).returncode:
            raise BuildError(f"{config_script} --cflags fails.")

        smoke = Path(tempfile.mkdtemp(prefix=".smoke.", dir=context.cwd))
        context.register_temporary_path(smoke)
        formats = [
            extension
            for package, extension in (("libpng", "png"), ("libwebp", "webp"))
            if context.package_enabled(package)
        ] or ["miff"]
        source = "logo:"
        steps = ["logo:"]
        try:
            for extension in formats:
                target = smoke / f"logo.{extension}"
                label = "WebP" if extension == "webp" else extension.upper()
                steps.append(label)
                if runner.capture([str(magick), source, str(target)], timeout=120).returncode:
                    raise BuildError(f"Functional smoke test failed: {' -> '.join(steps)}.")
                if not target.is_file() or target.stat().st_size == 0:
                    raise BuildError("Functional smoke test produced empty output files.")
                source = str(target)
        finally:
            safe_remove_tree(smoke, context.cwd)
            context.unregister_temporary_path(smoke)
        self.logger.info(f"Functional smoke test passed ({' -> '.join(steps)}).")
        self.verify_perlmagick(version)

    def verify_perlmagick(self, version: str) -> None:
        """The system perl loads the published Image::Magick and runs this release.

        PERL_DL_NONLAZY binds every symbol at load time, so a missing library
        symbol fails here instead of at the first call that needs it.
        """
        completed = self.context.runner.capture(
            [PERL, "-MImage::Magick", "-e", PERLMAGICK_SMOKE_TEST, version],
            env_overrides={"PERL_DL_NONLAZY": "1"},
            timeout=120,
        )
        if completed.returncode != 0:
            detail = next(
                (line for line in completed.stderr.splitlines() if line.strip()), "no output"
            )
            raise BuildError(f"PerlMagick smoke test failed: {detail}")
        self.logger.info(f"PerlMagick smoke test passed ({completed.stdout.strip()}).")

    # -- publication -----------------------------------------------------

    def prepare_publication(self, staging: Path) -> tuple[list[str], list[str]]:
        """Write the manifest into the staged tree; returns (entries, tar exclusions).

        An edited security policy is kept, like a dpkg conffile: it is excluded
        from the copy, and only a policy that is still the default this
        builder installed is replaced.
        """
        manifest_directory = staging / MANIFEST_DIRECTORY
        manifest_directory.mkdir(parents=True, exist_ok=True)
        excluded: list[str] = []
        staged_policy = staging / POLICY_FILE
        if staged_policy.is_file():
            digest = hashlib.sha256(staged_policy.read_bytes()).hexdigest()
            publish_atomically(staging / POLICY_RECORD, f"{digest}\n")
            installed = SYSTEM_ROOT / POLICY_FILE
            installed_digest = file_digest(installed)
            if installed_digest != digest and (installed.exists() or installed.is_symlink()):
                recorded = read_policy_record(SYSTEM_ROOT / POLICY_RECORD)
                if recorded is not None and recorded == installed_digest:
                    self.logger.info(
                        f"Replacing the untouched default /{POLICY_FILE} with this "
                        "release's default."
                    )
                else:
                    excluded.append(f"--exclude={POLICY_FILE}")
                    if recorded is None:
                        # An install from before the record existed: the policy
                        # may be an older default or an edit, so it is kept.
                        # Every publish writes the record, so this happens once.
                        self.logger.warn(
                            "No record of the previously installed default policy; keeping "
                            f"the existing /{POLICY_FILE}. This release's default is at "
                            f"{staged_policy}."
                        )
                    else:
                        self.logger.info(
                            f"Keeping your edited /{POLICY_FILE}; this release's default "
                            f"policy is at {staged_policy}."
                        )
        entries = [
            str(path.relative_to(staging))
            for path in (staging / "usr").rglob("*")
            if path.is_symlink() or path.is_file()
        ]
        entries = sorted([*entries, MANIFEST_FILE])
        publish_atomically(staging / MANIFEST_FILE, "\n".join(entries) + "\n")
        return entries, excluded

    def publish(
        self, staging: Path, entries: list[str], excluded: list[str], previous: list[str]
    ) -> list[Path]:
        """One privileged copy of the validated tree, with an inspectable manifest.

        Upstream's install recipe never runs as root. `--no-overwrite-dir` keeps
        the ownership and modes of existing directories such as /usr/local, and
        files the previous publish left in ImageMagick's own trees are removed.
        """
        context = self.context
        stale = stale_entries(previous, entries)
        archive = context.packages / "imagemagick-install.tar"
        context.register_temporary_path(archive)
        try:
            context.execute(
                [
                    "tar",
                    "--owner=root",
                    "--group=root",
                    "-C",
                    str(staging),
                    "-cf",
                    str(archive),
                    *excluded,
                    "usr",
                ]
            )
            self.logger.info(
                "Publishing the staged install to /usr/local (single privileged copy)."
            )
            # tar replaces a directory symlink with a real directory unless told
            # to keep it, as with Debian's /usr/local/man -> share/man.
            context.sudo(
                "tar",
                "-C",
                "/",
                "--no-overwrite-dir",
                "--keep-directory-symlink",
                "-xf",
                str(archive),
            )
            if stale:
                context.sudo(
                    "rm",
                    "-f",
                    "--",
                    *(f"/{entry}" for entry in stale),
                    display=f"sudo rm -f -- <{len(stale)} files the previous install left>",
                )
        finally:
            archive.unlink(missing_ok=True)
            context.unregister_temporary_path(archive)
        self.logger.info(f"Install manifest: /{MANIFEST_FILE}")
        return [SYSTEM_ROOT / entry for entry in entries]

    # -- backup and rollback ---------------------------------------------

    @property
    def backup_file(self) -> Path:
        return SYSTEM_ROOT / BACKUP_FILE

    def back_up(self, mutated: list[str]) -> Backup:
        """Save every file the publish will replace or remove before it starts.

        That includes files no manifest recorded, such as a manual install's
        magick: a failed install must put them back, not delete them. Root
        reads them, since a file need not be readable by the build user.
        """
        context = self.context
        existing = [entry for entry in mutated if os.path.lexists(SYSTEM_ROOT / entry)]
        if not existing:
            return Backup(None, frozenset(), False)
        backup = Backup(
            self.backup_file,
            frozenset(existing),
            not os.path.lexists(SYSTEM_ROOT / MANIFEST_DIRECTORY),
        )
        listing = context.packages / f"{Path(BACKUP_FILE).name}.list"
        listing.write_text("".join(f"{entry}\0" for entry in existing), encoding="utf-8")
        try:
            if backup.created_directory:
                context.sudo("mkdir", "-p", "--", f"/{MANIFEST_DIRECTORY}")
            context.sudo(
                "tar",
                "-C",
                "/",
                "--no-recursion",
                "--null",
                "-T",
                str(listing),
                "-cf",
                str(self.backup_file),
                display=f"sudo tar -C / -cf {self.backup_file} <{len(existing)} installed files>",
            )
        except BaseException:
            # Nothing has been replaced yet, so a partial archive must not stay
            # behind to read as an unrestored install.
            self.discard_backup(backup)
            raise
        finally:
            listing.unlink(missing_ok=True)
        return backup

    def discard_backup(self, backup: Backup) -> None:
        if backup.archive is None:
            return
        context = self.context
        context.sudo("rm", "-f", "--", f"/{BACKUP_FILE}")
        if backup.created_directory:
            context.sudo("rmdir", "--ignore-fail-on-non-empty", "--", f"/{MANIFEST_DIRECTORY}")

    def roll_back(self, mutated: list[str], backup: Backup) -> None:
        """Put back what a failed publish or installed check changed.

        Files that did not exist before are removed, then the saved ones are
        restored and the linker cache rebuilt. Every step runs even when one
        fails, and cancellation waits until they have: stopping halfway would
        leave a mix of both installs. Paths the copy excluded, such as an
        edited policy, are neither saved nor restored, so a later edit stays.
        """
        context = self.context
        added = [entry for entry in mutated if entry not in backup.existing]
        archive = backup.archive
        steps: list[tuple[str, list[str], str | None]] = []
        if added:
            steps.append(
                (
                    "removing the files this install added",
                    ["rm", "-f", "--", *(f"/{entry}" for entry in added)],
                    f"sudo rm -f -- <{len(added)} files this install added>",
                )
            )
        if archive is not None:
            steps.append(
                (
                    "restoring the saved files",
                    ["tar", "-C", "/", "--keep-directory-symlink", "-xf", str(archive)],
                    None,
                )
            )
        steps.append(("rebuilding the linker cache", ["ldconfig"], None))
        self.logger.warn("Restoring the previous ImageMagick installation under /usr/local.")
        failures: list[str] = []
        with defer_cancellation() as deferred:
            for description, arguments, display in steps:
                try:
                    context.sudo(*arguments, display=display)
                except Exception as error:
                    failures.append(f"{description}: {error}")
        if deferred:
            self.logger.warn(
                "Cancellation was held off until the previous installation was restored."
            )
        if failures:
            manual = f" Restore it by hand with: {restore_command(archive)}" if archive else ""
            raise BuildError(
                f"Restoring the previous installation failed ({'; '.join(failures)}).{manual}"
            )
        self.discard_backup(backup)
        self.logger.info(
            "The previous installation was restored."
            if backup.existing
            else "The files this install added were removed."
        )

    def install(self, staging: Path, version: str) -> list[str]:
        """Publish, verify, and put the previous install back when this one fails.

        The whole sequence holds the lock on /usr/local itself, which every build
        root and user of this project shares, so two builds never interleave
        their manifests, copies and stale-file removals. sudo is revalidated
        first: a long compile can outlive the cached credential.
        """
        context = self.context
        with prefix_lock():
            if os.path.lexists(self.backup_file):
                # Left by an install whose restore failed or that was killed,
                # from any build root: it may hold the only copy of the install
                # before that one.
                raise BuildError(
                    f"An earlier install's backup is still at '{self.backup_file}'. Restore it "
                    f"with '{restore_command(self.backup_file)}', or delete it with "
                    f"'sudo rm -f -- {self.backup_file}', then run the build again."
                )
            context.runner.require_sudo()
            entries, excluded = self.prepare_publication(staging)
            previous = read_installed_manifest()
            mutated = mutated_entries(entries, excluded, previous)
            backup = self.back_up(mutated)
            try:
                published = self.publish(staging, entries, excluded, previous)
                context.sudo("ldconfig")
                audit_published_install(context, published)
                self.validate_installation(version)
            except BaseException:
                self.logger.warn("The new installation did not complete.")
                self.roll_back(mutated, backup)
                raise
            self.discard_backup(backup)
            publish_atomically(self.receipt_file, install_receipt(entries))
        return entries

    # -- reuse -----------------------------------------------------------

    @property
    def receipt_file(self) -> Path:
        return self.context.packages / INSTALL_RECEIPT_NAME

    def reuse_problem(self, version: str) -> str | None:
        """Why the ImageMagick under /usr/local is not this workspace's build, or None."""
        with prefix_lock():
            return self._reuse_problem(version)

    def _reuse_problem(self, version: str) -> str | None:
        try:
            receipt = self.receipt_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return (
                "This workspace has no record of the files it installed "
                f"({self.receipt_file.name}), so the ImageMagick under /usr/local cannot be "
                "confirmed as its own."
            )
        if install_receipt(receipt_entries(receipt)) != receipt:
            return (
                "The ImageMagick files under /usr/local changed since this workspace installed "
                "them (another build or a manual install replaced them)."
            )
        try:
            self.validate_installation(version)
        except BuildError as error:
            return str(error)
        return None

    # -- the stage -------------------------------------------------------

    def run(self) -> None:
        context = self.context
        if not context.package_enabled("imagemagick"):
            self.logger.info(
                "imagemagick is disabled by the package selection config; the dependency "
                "build is complete."
            )
            return
        self.logger.banner("Building ImageMagick")

        arguments = configure_arguments(context)
        fingerprint = configure_fingerprint(arguments)
        self.invalidate_stale_marker(fingerprint)

        resolved = context.resolve("imagemagick")
        if resolved is None:
            return
        marker = context.marker_path("imagemagick")
        recorded = read_marker(marker)
        if (
            recorded is not None
            and recorded[0] == resolved.version
            and context.artifacts_present("imagemagick")
        ):
            # /usr/local is shared: another build root or a manual install can
            # have replaced what this marker describes. Rebuild it now rather
            # than report someone else's install as this build.
            problem = self.reuse_problem(resolved.version)
            if problem is not None:
                self.logger.warn(f"{problem} Rebuilding ImageMagick {resolved.version}.")
                context.invalidate("imagemagick")
        if not context.build("imagemagick", resolved.version):
            return
        version = resolved.version
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+-[0-9]+", version):
            raise BuildError(f"Invalid ImageMagick release version '{version}'.")

        source = context.download(
            f"https://github.com/ImageMagick/ImageMagick/archive/refs/tags/{resolved.tag or version}.tar.gz",
            f"imagemagick-{version}.tar.gz",
        )
        # The release tree ships upstream's generated configure, which carries
        # upstream's own revision; regenerate only when it is missing.
        if not (source / "configure").is_file():
            context.execute(["autoreconf", "-fi"], cwd=source)
        build_directory = source / "build"
        if build_directory.exists():
            safe_remove_tree(build_directory, source)
        build_directory.mkdir()
        if not context.shared:
            write_static_pkg_config(context)
        context.execute(["sh", "../configure", *arguments], cwd=build_directory)
        context.make(build_directory)

        staging = context.packages / "imagemagick-staging"
        if staging.exists() or staging.is_symlink():
            safe_remove_tree(staging, context.packages)
        context.execute(["make", f"DESTDIR={staging}", "install"], cwd=build_directory)
        if not context.shared:
            build_static_perlmagick(context, build_directory, staging, pkg_config_command(context))
        for record in (staging / "usr").rglob(PERL_LOCAL_RECORD):
            record.unlink()
        self_contained = SelfContainedInstall(context, staging)
        bundled = self_contained.apply()
        if not context.shared:
            self_contained.assert_static(bundled)
        self.validate_staged_install(staging, version)
        self.install(staging, version)
        context.build_done("imagemagick", version, resolved.commit)
        publish_atomically(self.fingerprint_file, f"{fingerprint}\n")

    @property
    def fingerprint_file(self) -> Path:
        return self.context.packages / f"imagemagick{CONFIGURE_FINGERPRINT_SUFFIX}"

    def invalidate_stale_marker(self, fingerprint: str) -> None:
        """Configure options are an input to the artifact, like the version.

        Observed live: newly enabled delegate packages did nothing because
        ImageMagick's version marker still matched, so a fingerprint mismatch,
        or a missing record, rebuilds it.
        """
        context = self.context
        if not context.marker_path("imagemagick").exists():
            return
        try:
            recorded = self.fingerprint_file.read_text(encoding="utf-8").split("\n", 1)[0]
        except OSError:
            recorded = ""
        if recorded != fingerprint:
            self.logger.warn(
                "ImageMagick's configure options or recipe changed since the last build; "
                "rebuilding it."
            )
            context.invalidate("imagemagick")


def report_success(context: BuildContext) -> None:
    """The closing summary, read from the installed binary's own capabilities."""
    logger = context.logger
    if not context.package_enabled("imagemagick"):
        logger.banner("Dependency build completed successfully")
        return
    with prefix_lock():
        report_installed(context)


def report_installed(context: BuildContext) -> None:
    logger = context.logger

    def ask(*arguments: str) -> str:
        completed = context.runner.capture([str(MAGICK_BINARY), *arguments], timeout=60)
        if completed.returncode != 0:
            raise BuildError(
                f"Failure to execute the command: {MAGICK_BINARY} {' '.join(arguments)}"
            )
        return completed.stdout

    report = ask("-version").splitlines()
    delegates = report_field(report, "Delegates (built-in)").split()
    formats = [
        match for line in ask("-list", "format").splitlines() if (match := _FORMAT_ROW.match(line))
    ]
    readable = sum(1 for match in formats if match.group(1) == "r")
    writable = sum(1 for match in formats if match.group(2) == "w")
    policy = next(
        (
            line.split(": ", 1)[1].strip()
            for line in ask("identify", "-list", "policy").splitlines()
            if line.startswith("Path:") and ": " in line
        ),
        "unknown",
    )
    utilities = [
        name for name in LEGACY_UTILITIES if os.access(MAGICK_BINARY.parent / name, os.X_OK)
    ]
    evidence = verify_link_mode(context, report, MAGICK_BINARY)
    # "ImageMagick 7.1.2-34 Q16-HDRI x86_64 <commit>:<date> <url>": the release
    # and the quantum are what a reader compares.
    version = " ".join(report_field(report, "Version").split()[1:3]) or "unknown"

    logger.banner("ImageMagick build completed successfully")
    logger.field("Version", [(version, "yellow", True)])
    logger.field(
        "Link mode",
        [(link_mode(context), "green", True), (f"  verified: {evidence}", "dim", False)],
    )
    logger.field("Features", report_field(report, "Features"))
    logger.field("Installed", f"{MAGICK_BINARY} and {len(utilities)} legacy utilities")
    logger.field(
        "Formats",
        [
            (str(readable), "", True),
            (" readable, ", "", False),
            (str(writable), "", True),
            (" writable", "", False),
        ],
    )
    logger.field(
        "Delegates", [(str(len(delegates)), "", True), ("  " + " ".join(delegates), "", False)]
    )
    logger.field("Policy", policy)
    logger.field("Manifest", f"/{MANIFEST_FILE}")
