"""The package registry: every selectable key and what it means.

This is the single source of truth that the configuration parser, the version
resolver, the artifact checks, the build stages and the generated
`example.toml` all read. An unregistered key in a configuration file is a hard
error by design: a misspelled entry must not silently disable a package.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Kind(Enum):
    TOOL = "tool"
    """A build-time program; disabling it falls back to the APT copy."""

    LIBRARY = "library"
    """Linked into ImageMagick, so a rebuild of it must relink ImageMagick."""

    FONT = "font"
    """A font family installed under /usr/share/fonts/truetype."""

    APPLICATION = "application"


class Source(Enum):
    GIT_TAG = "git-tag"
    """The highest stable tag matching the package's grammar, pinned to its commit."""

    GIT_HEAD = "git-head"
    """The HEAD commit itself, for repositories whose tags do not track content."""

    LISTING = "listing"
    """The newest archive in an HTTPS release-directory listing."""

    FIXED = "fixed"
    """A version chosen per OS release by the recipe, never looked up."""


GNU_PRIMARY_MIRROR = "https://ftp.gnu.org/gnu"
# A fixed HTTPS mirror, not ftpmirror.gnu.org: that one redirects to a random
# mirror that may be plain HTTP, which the HTTPS-only redirect policy rejects.
# Same /gnu/<package>/ layout as the primary.
GNU_FALLBACK_MIRROR = "https://mirrors.kernel.org/gnu"


@dataclass(frozen=True)
class Package:
    """One selectable `[packages]` key.

    `accept`, `exclude` and `prefix` are the tag grammar for GIT_TAG sources:
    `accept` must match the whole tag, `exclude` rejects matches (for example a
    development series), and `prefix` is stripped to form the version.
    """

    key: str
    summary: str
    kind: Kind
    group: str
    source: Source
    repository: str = ""
    accept: str = ""
    exclude: str = ""
    prefix: str = ""
    listings: tuple[str, ...] = ()
    artifact: tuple[str, ...] = ()
    """`("bin", name)`, `("pc", module)`, `("lib", basename)`, `("font",)` or
    `("magick",)`: what must exist for a completion marker to be believed."""


GROUP_TOOLS = "Build tools (disabling one falls back to the APT-installed version)"
GROUP_IMAGE = "Image format libraries and their delegates"
GROUP_TEXT = "Text rendering stack"
GROUP_EXTRA = "Color management, memory, and GPU support"
GROUP_FONTS = (
    "Font families installed to /usr/share/fonts/truetype (DejaVu comes from\n"
    "# the fonts-dejavu-core APT package and is not listed here)"
)
GROUP_APPLICATION = "Final application"
GROUPS = (GROUP_TOOLS, GROUP_IMAGE, GROUP_TEXT, GROUP_EXTRA, GROUP_FONTS, GROUP_APPLICATION)

_SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"
_V_SEMVER = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
_V_MAJOR_MINOR_PATCH = r"^v[0-9]+\.[0-9]+(\.[0-9]+)?$"


def _font(key: str, summary: str, repository: str) -> Package:
    return Package(
        key,
        summary,
        Kind.FONT,
        GROUP_FONTS,
        Source.GIT_HEAD,
        repository=repository,
        artifact=("font",),
    )


# Build order. The build context records the enabled keys in exactly this
# order, so reordering entries here changes that record.
PACKAGE_LIST: tuple[Package, ...] = (
    Package(
        "m4",
        "Macro processor used by Autotools",
        Kind.TOOL,
        GROUP_TOOLS,
        Source.LISTING,
        listings=(f"{GNU_PRIMARY_MIRROR}/m4/", f"{GNU_FALLBACK_MIRROR}/m4/"),
        artifact=("bin", "m4"),
    ),
    Package(
        "libtool",
        "Portable library build and linking helper",
        Kind.TOOL,
        GROUP_TOOLS,
        Source.FIXED,
        artifact=("bin", "libtool"),
    ),
    Package(
        "pkg-config",
        "Dependency resolver used by every configure probe",
        Kind.TOOL,
        GROUP_TOOLS,
        Source.LISTING,
        listings=("https://pkgconfig.freedesktop.org/releases/",),
        artifact=("bin", "pkg-config"),
    ),
    Package(
        "libjpeg-turbo",
        "JPEG encoding/decoding (jpeg delegate; jng with libpng)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://github.com/libjpeg-turbo/libjpeg-turbo.git",
        # x.y.9z tags are the development series (2.1.90 was the 3.0 beta).
        accept=_SEMVER,
        exclude=r"\.9[0-9]$",
        artifact=("lib", "libjpeg"),
    ),
    Package(
        "libtiff",
        "TIFF encoding/decoding (tiff delegate; needs libjpeg-turbo)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://github.com/libsdl-org/libtiff.git",
        accept=_V_MAJOR_MINOR_PATCH,
        prefix="v",
        artifact=("pc", "libtiff-4"),
    ),
    Package(
        "libfpx",
        "FlashPix format support (fpx delegate)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        # An ImageMagick-maintained mirror whose tags do not track HEAD.
        Source.GIT_HEAD,
        repository="https://github.com/ImageMagick/libfpx.git",
        artifact=("lib", "libfpx"),
    ),
    Package(
        "ghostscript",
        "PostScript/PDF library (gslib delegate)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://github.com/ArtifexSoftware/ghostpdl-downloads.git",
        accept=r"^gs[0-9]{5}$",
        artifact=("bin", "gs"),
    ),
    Package(
        "libpng",
        "PNG encoding/decoding (png delegate; jng with libjpeg-turbo)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://github.com/pnggroup/libpng.git",
        accept=_V_SEMVER,
        prefix="v",
        artifact=("pc", "libpng16"),
    ),
    Package(
        "libwebp",
        "WebP encoding/decoding (webp delegate)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://chromium.googlesource.com/webm/libwebp",
        accept=_V_SEMVER,
        prefix="v",
        artifact=("lib", "libwebp"),
    ),
    Package(
        "freetype",
        "Font loading and rasterization (freetype delegate)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://gitlab.freedesktop.org/freetype/freetype.git",
        accept=r"^VER-[0-9]+(-[0-9]+)+$",
        prefix="VER-",
        artifact=("pc", "freetype2"),
    ),
    Package(
        "libxml2",
        "XML parsing (xml delegate; required by fontconfig)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://gitlab.gnome.org/GNOME/libxml2.git",
        accept=_V_SEMVER,
        prefix="v",
        artifact=("pc", "libxml-2.0"),
    ),
    Package(
        "fontconfig",
        "Font discovery (fontconfig delegate; needs freetype+libxml2)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://gitlab.freedesktop.org/fontconfig/fontconfig.git",
        accept=r"^[0-9]+\.[0-9]+(\.[0-9]+)?$",
        artifact=("pc", "fontconfig"),
    ),
    Package(
        "fribidi",
        "Unicode bidirectional text (required by raqm)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://github.com/fribidi/fribidi.git",
        accept=_V_MAJOR_MINOR_PATCH,
        prefix="v",
        artifact=("pc", "fribidi"),
    ),
    Package(
        "harfbuzz",
        "Complex text shaping (needs freetype; required by raqm)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://github.com/harfbuzz/harfbuzz.git",
        accept=_SEMVER,
        artifact=("pc", "harfbuzz"),
    ),
    Package(
        "raqm",
        "Complex text layout (raqm delegate; needs freetype/fribidi/harfbuzz)",
        Kind.LIBRARY,
        GROUP_TEXT,
        Source.GIT_TAG,
        repository="https://github.com/host-oman/libraqm.git",
        accept=_V_SEMVER,
        prefix="v",
        artifact=("pc", "raqm"),
    ),
    Package(
        "jemalloc",
        "General-purpose memory allocator (--with-jemalloc)",
        Kind.LIBRARY,
        GROUP_EXTRA,
        Source.GIT_TAG,
        repository="https://github.com/jemalloc/jemalloc.git",
        accept=_SEMVER,
        artifact=("pc", "jemalloc"),
    ),
    Package(
        "opencl-sdk",
        "Khronos OpenCL headers and loader (--enable-opencl)",
        Kind.LIBRARY,
        GROUP_EXTRA,
        Source.GIT_TAG,
        repository="https://github.com/KhronosGroup/OpenCL-SDK.git",
        accept=r"^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}$",
        prefix="v",
        artifact=("lib", "libOpenCL"),
    ),
    Package(
        "openjpeg",
        "JPEG 2000 encoding/decoding (jp2 delegate)",
        Kind.LIBRARY,
        GROUP_IMAGE,
        Source.GIT_TAG,
        repository="https://github.com/uclouvain/openjpeg.git",
        accept=_V_SEMVER,
        prefix="v",
        artifact=("pc", "libopenjp2"),
    ),
    Package(
        "lcms2",
        "ICC color management with Little CMS (lcms delegate)",
        Kind.LIBRARY,
        GROUP_EXTRA,
        Source.GIT_TAG,
        repository="https://github.com/mm2/Little-CMS.git",
        accept=r"^lcms[0-9]+(\.[0-9]+)+$",
        prefix="lcms",
        artifact=("pc", "lcms2"),
    ),
    _font(
        "source-code-pro",
        "Adobe Source Code Pro",
        "https://github.com/adobe-fonts/source-code-pro.git",
    ),
    _font(
        "source-sans-pro", "Adobe Source Sans", "https://github.com/adobe-fonts/source-sans-pro.git"
    ),
    _font(
        "source-serif-pro",
        "Adobe Source Serif",
        "https://github.com/adobe-fonts/source-serif-pro.git",
    ),
    _font("roboto", "Google Roboto", "https://github.com/googlefonts/roboto.git"),
    _font("Fira", "Mozilla Fira", "https://github.com/mozilla/Fira.git"),
    Package(
        "imagemagick",
        "ImageMagick itself (disable to build only the dependencies)",
        Kind.APPLICATION,
        GROUP_APPLICATION,
        Source.GIT_TAG,
        repository="https://github.com/ImageMagick/ImageMagick.git",
        accept=r"^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$",
        artifact=("magick",),
    ),
)

PACKAGES: dict[str, Package] = {package.key: package for package in PACKAGE_LIST}
PACKAGE_NAMES: tuple[str, ...] = tuple(PACKAGES)
FONT_PACKAGES: tuple[str, ...] = tuple(p.key for p in PACKAGE_LIST if p.kind is Kind.FONT)


@dataclass(frozen=True)
class Delegate:
    """A source-built provider, its ImageMagick configure flag, and the token
    `magick -version` reports for it (empty for a feature, not a delegate)."""

    package: str
    flag: str
    token: str


# The single source for both the configure arguments and the required-delegate
# validation set, so a selection change can never make the two disagree. The
# order is the configure argument order and must stay fixed.
DELEGATES: tuple[Delegate, ...] = (
    Delegate("libjpeg-turbo", "jpeg", "jpeg"),
    Delegate("libtiff", "tiff", "tiff"),
    Delegate("libpng", "png", "png"),
    Delegate("libwebp", "webp", "webp"),
    Delegate("libfpx", "fpx", "fpx"),
    Delegate("ghostscript", "gslib", "gslib"),
    Delegate("freetype", "freetype", "freetype"),
    Delegate("fontconfig", "fontconfig", "fontconfig"),
    Delegate("raqm", "raqm", "raqm"),
    Delegate("libxml2", "xml", "xml"),
    Delegate("openjpeg", "openjp2", "jp2"),
    Delegate("lcms2", "lcms", "lcms"),
    Delegate("jemalloc", "jemalloc", ""),
)

# Delegates the APT baseline guarantees whatever the selection.
BASELINE_DELEGATES = ("bzlib", "gvc", "heic", "jbig", "lzma", "rsvg", "zlib", "zstd")


@dataclass(frozen=True)
class Requirement:
    """A hard requirement of this project's own recipes, checked before any work.

    The text stack links the workspace freetype/fribidi/harfbuzz static
    libraries, fontconfig is built against the workspace freetype and libxml2,
    and libtiff's jpeg support comes from the workspace libjpeg-turbo (no system
    jpeg development package is guaranteed).
    """

    package: str
    needs: str

    def message(self) -> str:
        return f"'{self.package} = true' requires '{self.needs} = true'"


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement("harfbuzz", "freetype"),
    Requirement("raqm", "freetype"),
    Requirement("raqm", "fribidi"),
    Requirement("raqm", "harfbuzz"),
    Requirement("fontconfig", "freetype"),
    Requirement("fontconfig", "libxml2"),
    Requirement("libtiff", "libjpeg-turbo"),
)
