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
from pathlib import Path

from .. import registry
from ..runtime import shellquote
from ..runtime.context import MAGICK_BINARY, BuildContext, link_mode
from ..runtime.errors import BuildError
from ..runtime.paths import safe_remove_tree
from ..runtime.state import CONFIGURE_FINGERPRINT_SUFFIX, publish_atomically
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
# previous install left under /usr/local.
RECIPE_REVISION = "4"
MANIFEST_DIRECTORY = "usr/local/share/imagemagick-build-script"
MANIFEST_FILE = f"{MANIFEST_DIRECTORY}/manifest.txt"
POLICY_FILE = "usr/local/etc/ImageMagick-7/policy.xml"
# The digest of the default policy this builder last published: a later publish
# replaces an untouched default but never an administrator's edited policy.
POLICY_RECORD = f"{MANIFEST_DIRECTORY}/policy.sha256"
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
    separate statically linked Perl interpreter and install no Image::Magick
    module, so PerlMagick exists only in the shared build. libfpx is C++ and
    ImageMagick links with the C driver, so the runtime is named here.
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
        return Path("/", MANIFEST_FILE).read_text(encoding="utf-8").splitlines()
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
        for entry in previous
        if entry not in kept and entry.startswith("usr/local/") and ".." not in Path(entry).parts
    ]


def file_digest(path: Path) -> str | None:
    """The sha256 of a file, or None when it is absent or unreadable."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
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
    (`Modules`), the sonames the binary loads (`libMagick*`) and the module
    directory. Any disagreement is a failed build, not a note.
    """
    features = report_field(report, "Features").split()
    libraries = [
        soname for soname in needed_libraries(context, magick) if soname.startswith("libMagick")
    ]
    modules = installed_modules(magick)
    facts = [
        "Features lists Modules" if "Modules" in features else "Features lists no Modules",
        f"magick links {' and '.join(libraries)}"
        if libraries
        else "magick links no libMagick shared object",
        f"{len(modules)} coder and filter modules in {modules[0].parent.parent}"
        if modules
        else "no coder or filter modules installed",
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

    # -- publication -----------------------------------------------------

    def publish(self, staging: Path) -> list[Path]:
        """One privileged copy of the validated tree, with an inspectable manifest.

        Upstream's install recipe never runs as root. `--no-overwrite-dir` keeps
        the ownership and modes of existing directories such as /usr/local. An
        edited security policy is kept, like a dpkg conffile, and files the
        previous publish left in ImageMagick's own trees are removed.
        """
        context = self.context
        manifest_directory = staging / MANIFEST_DIRECTORY
        manifest_directory.mkdir(parents=True, exist_ok=True)
        excluded: list[str] = []
        staged_policy = staging / POLICY_FILE
        if staged_policy.is_file():
            digest = hashlib.sha256(staged_policy.read_bytes()).hexdigest()
            publish_atomically(staging / POLICY_RECORD, f"{digest}\n")
            installed = Path("/", POLICY_FILE)
            installed_digest = file_digest(installed)
            if installed_digest != digest and (installed.exists() or installed.is_symlink()):
                recorded = read_policy_record(Path("/", POLICY_RECORD))
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
        stale = stale_entries(read_installed_manifest(), entries)
        publish_atomically(staging / MANIFEST_FILE, "\n".join(entries) + "\n")

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
        return [Path("/", entry) for entry in entries]

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
        if not context.build("imagemagick", resolved.version):
            # /usr/local is shared: another build root or a manual install can
            # have replaced what this marker describes.
            try:
                self.validate_installation(resolved.version)
            except BuildError as error:
                context.marker_path("imagemagick").unlink(missing_ok=True)
                raise BuildError(
                    f"{error} Its completion marker was removed; the next run rebuilds it."
                ) from error
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
        self_contained = SelfContainedInstall(context, staging)
        bundled = self_contained.apply()
        if not context.shared:
            self_contained.assert_static(bundled)
        self.validate_staged_install(staging, version)
        published = self.publish(staging)
        context.sudo("ldconfig")
        audit_published_install(context, published)
        self.validate_installation(version)
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
        marker = self.context.marker_path("imagemagick")
        if not marker.exists():
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
            marker.unlink(missing_ok=True)


def report_success(context: BuildContext) -> None:
    """The closing summary, read from the installed binary's own capabilities."""
    logger = context.logger
    if not context.package_enabled("imagemagick"):
        logger.banner("Dependency build completed successfully")
        return

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

    logger.banner("ImageMagick build completed successfully")
    logger.info(f"Version: {report_field(report, 'Version')}")
    logger.info(f"Link mode: {link_mode(context)}, verified: {evidence}")
    logger.info(
        f"Installation: {MAGICK_BINARY.parent} (magick and {len(utilities)} legacy utilities: "
        f"{' '.join(utilities)})"
    )
    logger.info(f"Features: {report_field(report, 'Features')}")
    logger.info(f"Delegates ({len(delegates)}): {' '.join(delegates)}")
    logger.info(f"Formats: {readable} readable, {writable} writable")
    logger.info(f"Security policy: {policy} (details: magick identify -list policy)")
    logger.info(f"Install manifest: /{MANIFEST_FILE}")
