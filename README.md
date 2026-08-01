# imagemagick-build-script

Builds ImageMagick 7 and ~20 of its dependencies from source on Debian and
Ubuntu, resolving the latest stable upstream release of every component and
installing the result to `/usr/local`.

## Supported systems

| OS | Releases | Architecture |
|---|---|---|
| Debian | 12 (bookworm), 13 (trixie) | x86_64 only |
| Ubuntu | 22.04 (jammy), 24.04 (noble) | x86_64 only |

The script detects the distribution and release itself and selects the
matching APT package set - a few package names differ between releases
(for example `libgegl-0.4-0` vs `libgegl-0.4-0t64`, `libcamd2` vs
`libcamd3`, and `libjxl-dev`, which Ubuntu 22.04 does not package).
All package operations use the `apt` command.

Anything else fails up front, before packages are installed or build work
starts. Ubuntu 20.04 is outside this project's tested support (its standard
support ended in May 2025); Ubuntu 26.04 has not been tested. Builds use
`-march=native`, so binaries are tuned for (and may only run on) the CPU
that built them.

## Requirements

- A regular (non-root) user with `sudo`. The script refuses to run as root:
  everything is built unprivileged, and privilege is used only for APT
  installs, font installation, publishing the validated install tree, and
  `ldconfig`.
- `git` and `curl` (`sudo apt install git curl`). Every other build
  tool is installed by the script through APT.

## Quick start

```bash
git clone https://github.com/slyfox1186/imagemagick-build-script.git
cd imagemagick-build-script
bash build-magick.sh
```

## Options

| Option | Meaning |
|---|---|
| `-w, --workers N` | Parallel job count for make/ninja. Default: detected CPU threads. |
| `-l, --latest` | Re-resolve the latest upstream versions instead of reusing the versions recorded by a previous run. |
| `-d, --debug` | Stream build output to the terminal as well as the log. |
| `--cleanup` | Remove the build directory after a successful build. |
| `--no-cleanup` | Keep the build directory (skips the interactive prompt). |
| `-v, --version` | Print the script version and exit. |
| `-h, --help` | Show help and exit. |

`--help` and `--version` are side-effect free: they create nothing, touch
nothing, and never prompt for sudo.

## Build state model

All state lives under `./magick-build-script/` (created in the directory
you run from):

- Each package records a completion marker `packages/<name>.done`
  containing the built version and, for git sources, the exact 40-character
  commit. A rerun reuses recorded versions **offline** - no network traffic
  for completed packages - unless you pass `--latest`.
- To force one package to rebuild: `rm -f -- magick-build-script/packages/<name>.done`
- Markers are only trusted while the package's artifacts still exist; if
  artifacts vanish, the package rebuilds automatically. Markers from
  releases of this script before 2.0.0 use an older format and trigger a
  clean rebuild once.
- A build-context record (compiler, flags, CPU model, OS) invalidates all
  markers when any of them change, because `-march=native` and the
  highest-installed-GCC selection make every artifact context-dependent.
- Git checkouts are pinned: the resolved tag's commit is recorded at
  resolution time and the clone is verified against it, so a moved tag
  fails instead of silently building different content.

## Safety model

- The whole build tree is user-owned; recursive deletion is bounded,
  never crosses filesystems, never escalates to root, and requires a
  path-bound marker (`.magick-build-root`) that a copied or unrelated
  directory cannot satisfy.
- A lock (`flock`) prevents two builds from sharing one build root.
- Downloads go to a temp file and are published to the cache only after
  they parse as tar archives; every archive's full member list is
  validated (single root, no traversal/absolute paths, no special files,
  no setuid bits, no symlink/hardlink escapes) before a transactional
  extraction.
- ImageMagick installs into a staging tree first (`make DESTDIR=...` as
  the build user). Only after the staged tree validates is it published
  to `/usr/local` in a single privileged copy - upstream's install recipe
  never runs as root. The installed file list is recorded at
  `/usr/local/share/imagemagick-build-script/manifest.txt`.

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

The script only reports success after the installed `/usr/local/bin/magick`:

1. reports exactly the version that was resolved and built,
2. contains every delegate this script exists to provide
   (bzlib, fontconfig, freetype, fpx, gslib, gvc, heic, jbig, jng, jp2,
   jpeg, lcms, lzma, png, raqm, rsvg, tiff, webp, xml, zlib, zstd),
3. exposes a resolvable `MagickCore.pc` under `/usr/local/lib/pkgconfig`,
4. completes a real conversion round-trip (`logo:` → PNG → WebP).

A validated container build reports, for example:

```text
Version: ImageMagick 7.1.2-29 Q16-HDRI x86_64 20260727 https://imagemagick.org
Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5)
Delegates (built-in): bzlib cairo fontconfig fpx freetype gslib gvc heic jbig jng jp2 jpeg jxl lcms ltdl lzma png ps raqm rsvg tiff webp x xml zlib zstd
```

Platform difference: the optional JPEG-XL (`jxl`) delegate is absent on
Ubuntu 22.04, which does not package `libjxl-dev`.

DejaVu fonts come from the distribution's `fonts-dejavu-core` package
(which provides the exact directory `--with-dejavu-font-dir` points at);
the Source Pro families, Roboto, and Fira are installed from their
upstream repositories pinned at the HEAD commit.

## Troubleshooting

- Full command output for every build step is appended to
  `magick-build-script/build.log`; failures replay the last 40 lines.
- Interrupted builds are safe to rerun: completed packages are skipped,
  partial downloads/extractions are never published, and the interrupted
  package restarts cleanly.
- `Another build is already running`: a second invocation is blocked by
  the build-root lock until the first finishes.

## Development

```bash
python3 run_linter.py         # bash -n, ShellCheck (whole-program), whitespace, policy checks
bash tests/test-scripts.sh    # offline regression tests (sandboxed, no network/sudo)
bash tests/run-container-matrix.sh lint     # lint+tests in all four supported images
bash tests/run-container-matrix.sh apt      # APT availability gate in all four images
bash tests/run-container-matrix.sh resolve  # upstream resolvers in all four images
bash tests/run-container-matrix.sh full     # complete end-to-end builds (hours)
```

CI runs the linter and the offline tests on every push and pull request.
