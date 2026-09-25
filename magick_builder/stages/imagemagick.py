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
from ..runtime.context import MAGICK_BINARY, BuildContext
from ..runtime.errors import BuildError
from ..runtime.paths import safe_remove_tree
from ..runtime.state import CONFIGURE_FINGERPRINT_SUFFIX, publish_atomically

# Part of the configure fingerprint. Bump it when the recipe changes what gets
# built without changing a configure argument, so existing installs rebuild once.
# Revision 2: configure is no longer regenerated with autoreconf, which had
# baked this repository's Git commit into ImageMagick's version string.
RECIPE_REVISION = "2"
MANIFEST_DIRECTORY = "usr/local/share/imagemagick-build-script"


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


def configure_arguments(context: BuildContext) -> list[str]:
    """ImageMagick's configure arguments.

    Most optional delegates (djvu, lqr, openexr, pango, raw, wmf, zip) default
    to yes and activate once their APT development packages are installed;
    fftw defaults to no. `--with-pkgconfigdir` is absent because upstream's
    Makefile.am overrides it, and `--enable-delegate-build` is absent because it
    means in-tree delegate builds, which this external workspace is not.
    """
    env = context.env
    cflags, cxxflags, cppflags = env["CFLAGS"], env["CXXFLAGS"], env["CPPFLAGS"]
    if context.package_enabled("opencl-sdk"):
        opencl = "--enable-opencl"
        cflags += " -DCL_TARGET_OPENCL_VERSION=300"
        cxxflags += " -DCL_TARGET_OPENCL_VERSION=300"
        cppflags += f" -I{context.workspace}/include/CL"
    else:
        opencl = "--disable-opencl"
    return [
        "--prefix=/usr/local",
        "--enable-hdri",
        "--enable-hugepages",
        "--enable-legacy-support",
        opencl,
        "--with-fftw",
        "--with-fontpath=/usr/share/fonts/truetype",
        "--with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu",
        "--with-gs-font-dir=/usr/share/fonts/ghostscript",
        "--with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35",
        "--with-gvc",
        "--with-heic",
        "--with-modules",
        "--with-perl",
        "--with-pic",
        "--with-quantum-depth=16",
        "--with-rsvg",
        "--with-utilities",
        "--without-autotrace",
        *toggle_arguments(context),
        f"CFLAGS={cflags}",
        f"CXXFLAGS={cxxflags}",
        f"CPPFLAGS={cppflags}",
        f"PKG_CONFIG={pkg_config_command(context)}",
    ]


def configure_fingerprint(arguments: list[str]) -> str:
    payload = "".join(f"{argument}\n" for argument in [*arguments, f"recipe={RECIPE_REVISION}"])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def reported_version_matches(line: str, version: str) -> bool:
    return f"ImageMagick {version} " in f"{line} "


class ImageMagickStage:
    def __init__(self, context: BuildContext) -> None:
        self.context = context
        self.logger = context.logger

    # -- validation ------------------------------------------------------

    def validate_staged_install(self, staging: Path, version: str) -> None:
        """Nothing outside ./usr, and a staged magick reporting this version."""
        staged_magick = staging / "usr/local/bin/magick"
        if not os.access(staged_magick, os.X_OK):
            raise BuildError("The staged install is missing usr/local/bin/magick.")
        outside = sorted(entry.name for entry in staging.iterdir() if entry.name != "usr")
        if outside:
            raise BuildError(f"The staged install wrote outside /usr: {', '.join(outside)}")
        completed = self.context.runner.capture(
            [str(staged_magick), "-version"],
            env_overrides={"LD_LIBRARY_PATH": f"{staging}/usr/local/lib:{staging}/usr/local/lib64"},
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
        self.logger.blank()
        for line in report:
            if line.startswith(("Version", "Features", "Delegates")):
                self.logger.magick(line)
        if not any(reported_version_matches(line, version) for line in report):
            raise BuildError(
                f"The installed magick reports a different version than this build ({version})."
            )

        delegates_line = next(
            (line.split(": ", 1)[-1] for line in report if line.startswith("Delegates")), ""
        )
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

        policy = runner.capture([str(magick), "identify", "-list", "policy"])
        policy_path = next(
            (
                line.split(": ", 1)[1].strip()
                for line in policy.stdout.splitlines()
                if line.startswith("Path:") and ": " in line
            ),
            "unknown",
        )
        self.logger.blank()
        self.logger.info(f"Security policy: {policy_path} (details: magick identify -list policy)")

        smoke = Path(tempfile.mkdtemp(prefix=".smoke.", dir=context.cwd))
        context.register_temporary_path(smoke)
        try:
            for source, target, step in (
                ("logo:", smoke / "logo.png", "magick logo: -> PNG"),
                (str(smoke / "logo.png"), smoke / "logo.webp", "PNG -> WebP conversion"),
            ):
                if runner.capture([str(magick), source, str(target)], timeout=120).returncode:
                    raise BuildError(f"Functional smoke test failed: {step}.")
                if not target.is_file() or target.stat().st_size == 0:
                    raise BuildError("Functional smoke test produced empty output files.")
        finally:
            safe_remove_tree(smoke, context.cwd)
            context.unregister_temporary_path(smoke)
        self.logger.info("Functional smoke test passed (logo: -> PNG -> WebP).")
        context.magick_validated = True

    # -- publication -----------------------------------------------------

    def publish(self, staging: Path) -> None:
        """One privileged copy of the validated tree, with an inspectable manifest.

        Upstream's install recipe never runs as root. `--no-overwrite-dir` keeps
        the ownership and modes of existing directories such as /usr/local.
        """
        context = self.context
        manifest_directory = staging / MANIFEST_DIRECTORY
        manifest_directory.mkdir(parents=True, exist_ok=True)
        entries = sorted(
            str(path.relative_to(staging))
            for path in (staging / "usr").rglob("*")
            if path.is_symlink() or path.is_file()
        )
        manifest = f"{MANIFEST_DIRECTORY}/manifest.txt"
        entries.append(manifest)
        publish_atomically(staging / manifest, "\n".join(sorted(entries)) + "\n")

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
                    "usr",
                ]
            )
            self.logger.info(
                "Publishing the staged install to /usr/local (single privileged copy)."
            )
            context.sudo("tar", "-C", "/", "--no-overwrite-dir", "-xf", str(archive))
        finally:
            archive.unlink(missing_ok=True)
            context.unregister_temporary_path(archive)
        self.logger.info(f"Install manifest: /{manifest}")

    # -- the stage -------------------------------------------------------

    def run(self) -> None:
        context = self.context
        if not context.package_enabled("imagemagick"):
            context.packages_disabled += 1
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
        if resolved is None or not context.build("imagemagick", resolved.version):
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
        context.execute(["sh", "../configure", *arguments], cwd=build_directory)
        context.make(build_directory)

        staging = context.packages / "imagemagick-staging"
        if staging.exists() or staging.is_symlink():
            safe_remove_tree(staging, context.packages)
        context.execute(["make", f"DESTDIR={staging}", "install"], cwd=build_directory)
        self.validate_staged_install(staging, version)
        self.publish(staging)
        context.sudo("ldconfig")
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


def report_installed_version(context: BuildContext) -> None:
    """The one-line summary when this run did not build and validate ImageMagick."""
    if context.magick_validated or not context.package_enabled("imagemagick"):
        return
    completed = context.runner.capture([str(MAGICK_BINARY), "-version"])
    if completed.returncode != 0:
        raise BuildError(f"Failure to execute the command: {MAGICK_BINARY} -version")
    context.logger.blank()
    context.logger.magick(completed.stdout.split("\n", 1)[0])
