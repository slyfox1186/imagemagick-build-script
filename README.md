# imagemagick-build-script

Builds ImageMagick 7 and ~20 of its dependencies from source on Debian and
Ubuntu, resolving the latest stable upstream release of every component and
installing the result to `/usr/local`.

## Supported systems

| OS | Releases | Architecture |
|---|---|---|
| Debian | 12 (bookworm), 13 (trixie) | x86_64 only |
| Ubuntu | 22.04 (jammy), 24.04 (noble) | x86_64 only |

The builder detects the distribution and release itself and selects the
matching APT package set - a few package names differ between releases
(for example `libgegl-0.4-0` vs `libgegl-0.4-0t64`, `libcamd2` vs
`libcamd3`, and `libjxl-dev`, which Ubuntu 22.04 does not package).
All package operations use the `apt` command.

Anything else fails up front, before packages are installed or build work
starts. Builds use `-march=native`, so binaries are tuned for (and may only
run on) the CPU that built them.

## Requirements

- A regular (non-root) user with `sudo`. The builder refuses to run as root:
  everything is built unprivileged, and privilege is used only for APT
  installs, font installation, publishing the validated install tree, and
  `ldconfig`.
- `git`, `curl`, and Python 3.12 or newer. When Conda is installed
  (`~/miniconda3`, `~/miniforge3`, or `~/anaconda3`), the launcher runs the
  build inside a dedicated `install-imagemagick` environment and offers to
  create it on first use; otherwise it uses the newest system `python3` that
  is 3.12 or newer. Ubuntu 22.04 and Debian 12 ship an older `python3`, so
  install Miniconda there. The build itself uses only the standard library.

## Quick start

```bash
git clone https://github.com/slyfox1186/imagemagick-build-script.git
cd imagemagick-build-script
python3 build-magick.py --build
```

## Options

```text

ImageMagick Build Script 3.0.0
Usage: build-magick.py [options]

Actions:
  -b, --build                 Build and install ImageMagick
  -c, --cleanup               Remove this project's build root and build leftovers

Options:
  -h, --help                  Show this help without changing the filesystem
  -v, --version               Show the script version
      --config <path>         Load build/package choices from TOML
  -j, --jobs <count>          Set parallel build jobs (default: available CPUs)
  -g, --gcc-version <9-14>    GCC major version (default: newest for this OS)
  -l, --latest                Refresh upstream versions and rebuild outdated packages
  -d, --debug                 Stream command output while also logging it

Long options also accept --option=value (for example: --jobs=8).

Environment:
  BUILD_ROOT=/path            Override the default ./build directory

Examples:
  python3 build-magick.py --build
  python3 build-magick.py --build --latest --jobs 8 --gcc-version 13
  python3 build-magick.py --build --config ./custom.toml


```

`--help` and `--version` are side-effect free: they create nothing, touch
nothing, never prompt for sudo, and never create an environment.

### GCC versions

The project supports GCC 9 through 14 where the matching `gcc-N` and `g++-N`
packages are available in the distribution's standard archive. The builder
installs and uses the exact pair selected with `--gcc-version`; without that
option it selects the highest version available for the detected release.

| OS release | Selectable versions | Default |
|---|---|---|
| Debian 12 | 11-12 | 12 |
| Debian 13 | 12-14 | 14 |
| Ubuntu 22.04 | 9-12 | 12 |
| Ubuntu 24.04 | 9-14 | 14 |

For example, `python3 build-magick.py --build --gcc-version 11` selects
`gcc-11` and `g++-11`. A version outside the release's range fails before
package installation.

## Package selection (`--config`)

```bash
cp example.toml custom.toml   # edit it, then:
python3 build-magick.py --build --config ./custom.toml
```

The config is a deliberately small TOML subset - `[build]` and
`[packages]` tables with `key = true|false` entries - and an explicit
allowlist: once a config is loaded, **every package omitted from it is
disabled**. Without `--config`, everything builds (the default full
build). `example.toml` lists every supported key with a description; it is
generated from the package registry, and the linter keeps the two identical.

- Disabling a package skips its source build and passes an explicit
  `--without` flag to ImageMagick's configure; its delegate is also
  removed from the final validation's required set.
- Impossible selections fail up front with the exact conflict (the raqm
  stack needs freetype/fribidi/harfbuzz, fontconfig needs
  freetype/libxml2, libtiff needs libjpeg-turbo).
- The APT baseline is not configurable: system-package delegates (heic,
  rsvg, gvc, bzlib, ...) are always installed.
- The active selection is recorded in the build context, so changing it
  automatically invalidates completed work - no manual cleanup needed.

## Build state model

All state lives under `./build/` (override with `BUILD_ROOT=/path`):

- Each package records a completion marker `packages/<name>.done`
  containing the built version and, for git sources, the exact 40-character
  commit. A rerun reuses recorded versions **offline** - no network traffic
  for completed packages - unless you pass `--latest`.
- To force one package to rebuild: `rm -f -- build/packages/<name>.done`
- Markers are only trusted while the package's artifacts still exist; if
  artifacts vanish, the package rebuilds automatically. Rebuilding any
  library also relinks ImageMagick.
- A build-context record (compiler, flags, CPU model, OS, selection)
  invalidates all markers and the workspace when any of them change,
  because `-march=native` and the selected GCC version make every artifact
  context-dependent. A build tree created by the Bash releases (2.x) is
  adopted as-is when none of those inputs changed.
- Git checkouts are pinned: the resolved tag's commit is recorded at
  resolution time and the clone is verified against it, so a moved tag
  fails instead of silently building different content.
- ImageMagick additionally records a fingerprint of its configure options,
  so enabling or disabling a delegate rebuilds it even at the same version.

## Safety model

- The whole build tree is user-owned; recursive deletion is bounded,
  never crosses filesystems, never escalates to root, and requires a
  path-bound marker (`.magick-build-root`) that a copied or unrelated
  directory cannot satisfy. `--cleanup` asks before removing anything.
- A directory lock prevents two builds from sharing one build root; the
  second is refused with the first one's PID.
- Downloads are HTTPS-only (including redirects), go to a temp file, and
  are published to the cache only after they validate as a single-root tar
  archive with no traversal/absolute paths, no special files, and no
  symlink/hardlink escapes; extraction is transactional.
- ImageMagick installs into a staging tree first (`make DESTDIR=...` as
  the build user). Only after the staged tree validates is it published
  to `/usr/local` in a single privileged copy - upstream's install recipe
  never runs as root. The installed file list is recorded at
  `/usr/local/share/imagemagick-build-script/manifest.txt`.
- Every build command runs with an allowlisted environment, so a Conda or
  virtual environment cannot leak compilers, flags, or library paths into
  the native builds, and upstream build systems cannot discover this
  repository's Git metadata.

### Trust model (read this once)

Transport security is HTTPS-only (including redirects) with certificate
verification. The `.sha256` files next to cached archives are
**cache-integrity records computed from our own download** - they detect
later corruption, they do not authenticate upstream. Most of the upstreams
built here do not publish signed artifacts, so first-time downloads are
trust-on-first-use over TLS.

### ImageMagick security policy

The build keeps upstream's default (open) security policy and prints the
active policy at the end of the build. If you process untrusted images,
install a stricter policy - see
<https://imagemagick.org/script/security-policy.php>.

## What "success" means

The builder only reports success after the installed `/usr/local/bin/magick`:

1. reports exactly the version that was resolved and built,
2. contains every delegate this project exists to provide
   (bzlib, fontconfig, freetype, fpx, gslib, gvc, heic, jbig, jng, jp2,
   jpeg, lcms, lzma, png, raqm, rsvg, tiff, webp, xml, zlib, zstd),
3. exposes a resolvable `MagickCore.pc` under `/usr/local/lib/pkgconfig`,
4. completes a real conversion round-trip (`logo:` -> PNG -> WebP).

A validated build reports, for example:

```text
[MAGICK] Version: ImageMagick 7.1.2-31 Q16-HDRI x86_64 8309dc92a:20260903 https://imagemagick.org
[MAGICK] Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5)
[MAGICK] Delegates (built-in): bzlib cairo djvu fftw fontconfig fpx freetype gslib gvc heic jbig jng jp2 jpeg jxl lcms lqr ltdl lzma openexr pangocairo png ps raqm raw rsvg tiff webp wmf x xml zip zlib zstd

[INFO] Security policy: /usr/local/etc/ImageMagick-7/policy.xml (details: magick identify -list policy)
[INFO] Functional smoke test passed (logo: -> PNG -> WebP).
```

Platform difference: the optional JPEG-XL (`jxl`) delegate is absent on
Ubuntu 22.04, which does not package `libjxl-dev`.

DejaVu fonts come from the distribution's `fonts-dejavu-core` package
(which provides the exact directory `--with-dejavu-font-dir` points at);
the Source Pro families, Roboto, and Fira are installed from their
upstream repositories pinned at the HEAD commit.

## Troubleshooting

- Full command output for every build step is appended to
  `build/build.log`; a failing command's output is replayed on screen.
  `--debug` streams all command output as it runs.
- Interrupted builds are safe to rerun: completed packages are skipped,
  partial downloads/extractions are never published, and the interrupted
  package restarts cleanly.
- `Another build is already running`: a second invocation is blocked by
  the build-root lock until the first finishes.

## Development

The builder is the `magick_builder` package; `build-magick.py` is only the
launcher. Use the project environment's interpreter:

```bash
~/miniconda3/envs/install-imagemagick/bin/python -m pip install '.[dev]'
~/miniconda3/envs/install-imagemagick/bin/python run_linter.py   # ruff, format, strict mypy, contracts
~/miniconda3/envs/install-imagemagick/bin/python -m pytest       # offline regression tests
python3 tools/container_matrix.py lint      # linter + tests in all four supported images
python3 tools/container_matrix.py apt       # APT availability gate in all four images
python3 tools/container_matrix.py resolve   # upstream resolvers in all four images
python3 tools/container_matrix.py full      # complete end-to-end builds (hours)
```

CI runs the linter and the tests on Python 3.12, 3.13, and 3.14 for every
push and pull request.
