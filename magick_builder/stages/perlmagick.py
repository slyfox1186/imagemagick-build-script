"""PerlMagick (`Image::Magick`) for the static build.

Under `--disable-shared`, upstream's `--with-perl` builds a separate perl
interpreter with the module linked in (makeaperl) instead of a module the
system perl can load, so the static build configures `--without-perl` and
builds the module here: upstream's own Makefile.PL, with the link overridden on
the make command line, the one place that reaches the `default/` and
`quantum/` subdirectories (MakeMaker hands a Makefile.PL's arguments to no
child). Every archive in the workspace is PIC, so the XS module carries
libMagickWand, libMagickCore and the workspace libraries and loads only
distribution libraries:

- libMagickWand and libMagickCore form a link group: the WMF coder, compiled
  into libMagickCore, calls MagickWand's drawing API.
- jemalloc stays out. ImageMagick links it only to replace malloc process-wide,
  which an object perl dlopens cannot do, so memory would cross allocators.
- `--exclude-libs,ALL` keeps the linked-in copies of libpng, freetype and the
  rest private, so the distribution libraries the module loads (cairo, pango)
  and other perl modules never bind to them.
- The archives are named by path and perl's `lddlflags` are replaced: they add
  `-L/usr/local/lib`, where an earlier install's libMagick* would be found.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from ..runtime.context import BuildContext
from ..runtime.errors import BuildError

# The system perl, whose site tree receives the module.
PERL = "perl"
# Not linked into the module; see the module docstring.
EXCLUDED_LIBRARIES = frozenset({"-ljemalloc"})


def link_libraries(pkg_config_libs: list[str], libdir: str, archives: list[Path]) -> list[str]:
    """The module's LDLOADLIBS: the libMagick archives as one group, then every
    dependency `pkg-config --static --libs` reports, minus the installed
    libMagick search path and names and the excluded libraries."""
    dropped = {f"-L{libdir}", *EXCLUDED_LIBRARIES}
    dropped.update(
        f"-l{archive.name.removeprefix('lib').removesuffix('.a')}" for archive in archives
    )
    return [
        "-Wl,--start-group",
        *(str(archive) for archive in archives),
        "-Wl,--end-group",
        *(token for token in pkg_config_libs if token not in dropped),
    ]


def library_archive(build_directory: Path, library: str) -> Path:
    """libtool's uninstalled archive, such as MagickCore/.libs/libMagickCore-7.Q16HDRI.a."""
    found = sorted((build_directory / library / ".libs").glob(f"lib{library}-*.a"))
    if len(found) != 1:
        raise BuildError(
            f"Expected one lib{library} archive in {build_directory / library / '.libs'}, "
            f"found {len(found)}."
        )
    return found[0]


def pkg_config_query(context: BuildContext, pkg_config: str, *arguments: str) -> str:
    completed = context.runner.capture([pkg_config, *arguments])
    if completed.returncode != 0:
        raise BuildError(f"pkg-config {' '.join(arguments)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def build_static_perlmagick(
    context: BuildContext, build_directory: Path, staging: Path, pkg_config: str
) -> None:
    """Build Image::Magick against the static archives and stage it with DESTDIR."""
    archives = [library_archive(build_directory, name) for name in ("MagickWand", "MagickCore")]
    pc_file = str(build_directory / "MagickCore" / "MagickCore.pc")
    libdir = pkg_config_query(context, pkg_config, "--variable=libdir", pc_file)
    dependencies = shlex.split(pkg_config_query(context, pkg_config, "--static", "--libs", pc_file))
    libraries = link_libraries(dependencies, libdir, archives)

    # PERLMAGICK is set only under WITH_PERL, which --without-perl leaves off.
    context.make(build_directory, "PERLMAGICK=PerlMagick", "perl-sources", jobs=False)
    perl_directory = build_directory / "PerlMagick"
    # The top-level Magick.xs builds an Image::Magick module that nothing loads:
    # the installed Image/Magick.pm is default/'s, a subclass of quantum/'s
    # Image::Magick::Q16HDRI. Statically linked, it would be a second copy of
    # MagickCore, so only quantum/ builds an XS module.
    (perl_directory / "Magick.xs").unlink(missing_ok=True)
    context.execute([PERL, "Makefile.PL"], cwd=perl_directory)
    overrides = [
        f"CC={context.env['CC']}",
        f"LDDLFLAGS=-shared -Wl,--exclude-libs,ALL {context.env['LDFLAGS']}",
        # make hands the value to /bin/sh, so POSIX quoting, not Bash's.
        f"LDLOADLIBS={shlex.join(libraries)}",
    ]
    # Serial: under -j the top level and default/ copy their Magick.pm into
    # blib at the same time, and default/'s copy must be the one installed.
    context.make(perl_directory, *overrides, jobs=False)
    # pure_install writes no perllocal.pod, which would replace the system's
    # record of every locally installed perl module.
    context.make(perl_directory, *overrides, f"DESTDIR={staging}", "pure_install", jobs=False)
