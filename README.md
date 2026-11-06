# imagemagick-build-script

Builds ImageMagick 7 and ~20 of its dependencies from source on Debian and
Ubuntu, resolving the latest stable upstream release of every component and
installing the result to `/usr/local`.

## Latest changes (since 3.1.0)

- **Conda is never required.** The launcher runs the build with the Python you
  started it with when that is Python 3.12 or newer. Otherwise it uses an
  existing `install-imagemagick` Conda environment or the newest compatible
  system Python. Only when none exists and Conda happens to be installed does it
  offer, with your consent, to create that environment; declining changes
  nothing and explains how to install Python 3.12 any way you like.
- **Choose the compiler: GCC or Clang.** `--compiler clang` (or `--clang`, or
  `compiler = "clang"` in `[build]`) builds everything with the release's
  default Clang and LLVM's OpenMP runtime (`clang`, `libomp-dev`).
  `--gcc-version` still selects the GCC major version for GCC builds.
- **Choose the CPU the build is optimized for.** `--cpu-target` (or
  `cpu_target` in `[build]`) takes `native`, the default and fastest, or a
  portable target: `generic` runs on any x86-64 CPU, and `x86-64-v2`, `-v3` or
  `-v4` on any CPU with that instruction-set level. `--generic` is short for
  `--cpu-target generic`. A level this CPU cannot run is rejected before
  anything is installed.
- **`[build]` remembers every build choice:** `compiler`, `gcc_version`,
  `cpu_target`, `shared` and `latest`. Command-line options override the file.
- **The build reports the machine it runs on**: CPU model, usable threads and
  instruction-set level, the CPU the compiler resolves `-march=native` to,
  memory, the distribution as it names itself with its point release, the
  kernel, and the C and C++ compiler banners (naming the compiler behind a
  ccache shim). The default job count now respects a container's CPU quota and
  keeps 2 GiB of available memory per job; `--jobs` still overrides it.
- **A native workspace moved to a different CPU is detected** by its
  instruction-set extensions, not only its model name, and rebuilt. Existing
  workspaces are adopted without a rebuild.
- **Starting a build stops a competing build of the same build root** (and its
  worker processes, including ones whose parent already exited) instead of
  refusing, so a stuck or forgotten run never blocks you. Other build roots and
  other users' processes are never touched, and neither is a build in the middle
  of a privileged step (APT, the font install or the ImageMagick install): the
  new build then names the PID to wait for or stop.
- **Installing into `/usr/local` is serialized and reversible.** Every build
  root and user shares one lock on `/usr/local`. Every file the install will
  replace or remove, including files a manual install left, is backed up first
  and restored if the new one fails to publish or fails its checks, even when
  you press Ctrl+C during the restore.
  sudo is revalidated right before the install, so a long build never stops at
  a hidden password prompt.
- **A finished build is reused only while `/usr/local` still holds its own
  files.** The build records a SHA-256 of every file it installs
  (`packages/imagemagick.installed`). An ImageMagick another build root or a
  manual install put there, even of the same release, is rebuilt in the same
  run instead of failing. Existing workspaces rebuild ImageMagick once; their
  dependencies are reused.
- **Missing artifacts are repaired at the recorded release** instead of
  silently upgrading the package, and a pinned Git release that moved upstream
  stops with the two ways forward. Rebuilding a library now also rebuilds the
  packages built against it (harfbuzz, raqm and fontconfig after freetype, for
  example) at the releases they already had.
- **The build log keeps the lines printed before the build banner**, such as the
  loaded config, and a run stopped by the request or sudo checks leaves the
  previous log untouched.
- **Commands never run in the directory you started the build from.** A command
  that needs no particular directory runs in `/`, so a Git repository or Python
  modules there cannot affect the build.
- **Cache folders in the checkout are deleted automatically** after every
  build and on `--cleanup`, without asking: `__pycache__/`, `.pytest_cache/`,
  `.ruff_cache/`, `.mypy_cache/` and `*.egg-info/`, which Python tools recreate
  when needed. The cleanup prompt now covers only `build/` and old build
  folders, and nothing inside a build root is ever counted as a cache.
  To keep them while you work on this repository, set
  `BYPASS_CACHE_DELETE=true` in your [settings file](#settings-file-env) or in
  the environment.
- **A settings file.** Every environment setting the script reads (build
  folder, colors, download and Git time limits, lock waits, the cache bypass)
  can be saved in a `.env` file beside the script. `.env.example` lists each one
  with what it does and its default; see [Settings file](#settings-file-env).
- Prompts ignore arrow and Home/End key codes and anything typed before the
  question appeared.
- Single-letter options can be grouped: `-bls` is `-b -l -s`, and `-bj8` is
  `-b -j 8`. The help screen is laid out in sections and colored on terminals.
- CMake configures never consult a host CMake package registry, Meson never
  downloads a subproject in place of a missing dependency, and a dead primary
  GNU mirror is abandoned after seconds instead of minutes.
- Ubuntu derivatives (Linux Mint, Zorin OS, Pop!_OS, ...) built on a supported
  Ubuntu LTS are accepted, WSL2 is recognized and WSL1 is refused with the fix.

## Supported systems

| OS | Releases | Architecture |
|---|---|---|
| Debian | 12 (bookworm), 13 (trixie) | x86_64 only |
| Ubuntu | 22.04 (jammy), 24.04 (noble), 26.04 (resolute) | x86_64 only |

The builder detects the distribution and release itself and selects the
matching APT package set (`libjxl-dev`, the JPEG-XL delegate, is the one
package Ubuntu 22.04 does not ship). All package operations use the `apt`
command. An Ubuntu derivative that declares `ID_LIKE=ubuntu` with a
`UBUNTU_CODENAME` of `jammy`, `noble` or `resolute` (Linux Mint and Zorin OS
among them) is built as that Ubuntu release. WSL2 running a supported
userspace works; WSL1 is refused (convert with
`wsl.exe --set-version <distro> 2`).

Anything else fails up front, before packages are installed or build work
starts. By default the build is tuned for the CPU that runs it
(`--cpu-target native`); see [CPU target](#cpu-target) for builds that run on
other machines.

## Requirements

- A regular (non-root) user with `sudo`. The builder refuses to run as root:
  everything is built unprivileged, and privilege is used only for APT
  installs, font installation, publishing the validated install tree, and
  `ldconfig`.
- `git`, `curl`, and Python 3.12 or newer. The build uses only the standard
  library, and **Conda is optional**. The launcher picks an interpreter in this
  order, without invoking Conda unless the last step is reached:
  1. the Python running the launcher, when it is a stable 3.12 or newer
     (`python3.13 build-magick.py --build` uses Python 3.13);
  2. an existing `install-imagemagick` Conda environment, found through
     `CONDA_EXE`, a `conda` on `PATH`, or `~/miniconda3`, `~/miniforge3` or
     `~/anaconda3` (one older than 3.12, or whose version cannot be read, is
     reported and skipped);
  3. the newest stable `python3` or `python3.N` on `PATH` or in `/usr/bin`
     that is 3.12 or newer (empty and relative `PATH` entries are ignored);
  4. only when none of those exists and Conda is installed, an offer to
     create the `install-imagemagick` environment with Python 3.14 from
     conda-forge (no Anaconda Terms of Service needed). The default answer is
     no, and a non-interactive run never creates it.

  Without a compatible Python the launcher stops with instructions to install
  Python 3.12 or newer by any method (distribution packages, python.org,
  pyenv, uv or Conda). Ubuntu 22.04 and Debian 12 ship an older `python3`.

## Quick start

```bash
git clone https://github.com/slyfox1186/imagemagick-build-script.git
cd imagemagick-build-script
python3 build-magick.py --build
```

## Options

```text

ImageMagick Build Script 3.2.0

Usage: python3 build-magick.py <action> [options]

  Builds ImageMagick 7 and its libraries from source and installs it under
  /usr/local. Run it as a normal user with sudo access. Choose one action; with
  none, this help is shown.

Actions:
  -b, --build                     Build and install ImageMagick
  -l, --latest                    Refresh upstream versions and rebuild outdated
                                  packages (with --build)
  -c, --cleanup                   Delete the build root and temporary caches

Build options:
      --config <file>             Build only the packages this TOML file
                                  enables; start from example.toml
                                  (default: every package)
      --compiler <gcc|clang>      Compiler to use (default: gcc)
      --gcc, --clang              Same as --compiler gcc / --compiler clang
  -g, --gcc-version <9-16>        GCC major version, for GCC builds only
                                  (default: newest stable for this OS)
      --cpu-target <target>       CPU to optimize for: native, generic,
                                  x86-64-v2, x86-64-v3 or x86-64-v4; only
                                  generic and the levels run on other CPUs
                                  (default: native)
      --generic                   Same as --cpu-target generic
  -j, --jobs <count>              Parallel build jobs; the default keeps 2 GiB
                                  of free memory per job (default: usable CPUs)
  -s, --shared                    Build shared libraries and coder modules
                                  (default: static)
  -d, --debug                     Stream all command output to the terminal; the
                                  build log is still written

General options:
  -h, --help                      Show this help; changes nothing on disk
  -v, --version                   Show the script version

  Options that take a value also accept --option=value, for example --jobs=8.
  Single-letter options can be grouped: -bls is -b -l -s, and -bj8 is -b -j 8.

Environment variables:
  BUILD_ROOT=<dir>                Build workspace
                                  (default: build/ in this checkout)
  NO_COLOR=1                      Never color the terminal output
  .env                            Every setting in .env.example can be saved in
                                  a .env file beside this script

Examples:
  # Build every package and install ImageMagick
  python3 build-magick.py --build

  # Build the packages enabled in your config (copy example.toml first)
  python3 build-magick.py --build --config ./custom.toml

  # Build with clang on 8 cores as shared libraries
  python3 build-magick.py --build --clang --jobs 8 --shared

  # Build a portable ImageMagick that runs on any x86-64-v3 (AVX2) CPU
  python3 build-magick.py --build --cpu-target x86-64-v3

  # Update outdated packages to their newest upstream releases with GCC 13
  python3 build-magick.py --build --latest --gcc-version 13

  # Start over with an empty workspace
  python3 build-magick.py --cleanup

Build log: $BUILD_ROOT/build.log    Full guide: README.md


```

`--help` and `--version` are side-effect free: they create nothing, touch
nothing, never prompt for sudo, and never create an environment. On a terminal
the help is colored; `NO_COLOR=1` turns color off, and piped or redirected
output stays plain unless `FORCE_COLOR=1` is set. Arguments are validated
before any config file is read.

The default job count is the number of usable CPU threads (the affinity mask,
reduced by a cgroup v2 CPU quota), capped so each job has 2 GiB of available
memory (also reduced by a cgroup v2 memory limit). The start of the build log
names the CPU, its instruction-set level, the CPU target, memory and the reason
for the job count.

### CPU target

By default the result is tuned for the machine that built it
(`--cpu-target native`, `-march=native`), so the installed binaries may fault
with an illegal instruction on a different CPU. To build for other machines,
choose a portable target: `--cpu-target generic` (any x86-64 CPU) or
`x86-64-v2`, `x86-64-v3` (AVX2) or `x86-64-v4` (AVX-512). The target is the
single source of CPU tuning: it sets `-march` in `CFLAGS` and `CXXFLAGS` for
ImageMagick and every library built here, and no recipe adds native switches
of its own. libjpeg-turbo's and libwebp's SIMD code still picks the fastest
instructions the running CPU offers; OpenJPEG and MagickCore use what the
target allows. The build host must implement the chosen level, because the
build runs what it compiles, and the `x86-64-vN` levels need GCC 11 or newer
(any supported Clang). jemalloc probes the host's virtual-address width at
configure time; every x86-64 CPU this targets gives programs the same 47-bit
user address space unless a program asks for more.

A native build records the CPU it was tuned for, so moving a native workspace
to another CPU rebuilds it. A portable workspace can move between machines.

### Link mode: static by default, `--shared` on request

The default build is **static**: every library built from source (libpng,
libtiff, libjpeg-turbo, libwebp, the text stack, OpenJPEG, Little CMS,
jemalloc, libfpx, libltdl) is an archive linked into `magick` and the other
utilities, the coders are compiled into `libMagickCore`, and nothing under
`/usr/local/lib` is a shared object of this build. Only the distribution's own
libraries (librsvg, libheif, graphviz, pango, cairo, glib, X11, fftw, libgs,
the OpenCL ICD loader, glibc) are loaded at run time, which is why the binary
is not a fully static executable: Debian and Ubuntu ship no static archives
for those delegates. `libMagickCore-7.*.a`, `libMagickWand-7.*.a` and
`MagickCore.pc` are installed for programs that link ImageMagick.

Both modes install PerlMagick (`Image::Magick`) for the system `perl`. With
static libraries, upstream's `--with-perl` builds a separate Perl interpreter
instead of a module, so the static build configures `--without-perl` and links
upstream's module itself: its `Q16HDRI.so` carries libMagickWand, libMagickCore
and the workspace libraries, keeps their symbols private, and loads only
distribution libraries. jemalloc stays out of it, because a library `perl`
loads at run time cannot replace `malloc` for the whole process.

`--shared` builds what releases before 3.1 built: shared `libMagickCore` and
`libMagickWand`, coder modules loaded on demand, and the workspace libraries
bundled into `/usr/local/lib/imagemagick-build-script`. Switching modes rebuilds
every package once, because every workspace library is built differently, and
the install replaces the other mode's files through the manifest.

### Compilers

`--compiler gcc` (the default) or `--compiler clang` selects the toolchain for
ImageMagick and every library built here; `--gcc` and `--clang` are short
forms, and `compiler` in `[build]` saves the choice. A Clang build installs the
release's default `clang` and `libomp-dev` (LLVM's OpenMP runtime, which
MagickCore uses) and compiles C++ against the libstdc++ of the GCC installation
Clang selects; when that GCC's `libstdc++-N-dev` is missing it is installed.
Before any package builds, the selected compilers must compile, link and run a
small C++ OpenMP program with the build's flags. Switching compilers rebuilds
every package once.

| OS release | Default Clang |
|---|---|
| Debian 12 | 14 |
| Debian 13 | 19 |
| Ubuntu 22.04 | 14 |
| Ubuntu 24.04 | 18 |
| Ubuntu 26.04 | 21 |

### GCC versions

The project supports GCC 9 through 16 where the matching `gcc-N` and `g++-N`
packages are available in the distribution's standard archive. The builder
installs and uses the exact pair selected with `--gcc-version`; without that
option it selects the newest stable version for the detected release. Ubuntu
26.04's `gcc-16` is a pre-release snapshot (16-20260322), so it is opt-in and
that release defaults to its own system compiler, GCC 15.

| OS release | Selectable versions | Default |
|---|---|---|
| Debian 12 | 11-12 | 12 |
| Debian 13 | 12-14 | 14 |
| Ubuntu 22.04 | 9-12 | 12 |
| Ubuntu 24.04 | 9-14 | 14 |
| Ubuntu 26.04 | 11-16 | 15 |

For example, `python3 build-magick.py --build --gcc-version 11` selects
`gcc-11` and `g++-11`. A version outside the release's range fails before
package installation. `--gcc-version` applies only to GCC builds; with
`--clang` it is an error, and a config's `gcc_version` is ignored with a
warning.

## Settings file (`.env`)

Settings you would otherwise type before the command, such as
`BUILD_ROOT=/data/im python3 build-magick.py --build`, can be saved once:

```bash
cp .env.example .env
```

Then open `.env`, delete the `# ` in front of each `NAME=value` line you want
to change, and edit its value. [`.env.example`](.env.example) lists every
setting with what it does, its allowed values and its default; every value
shown is the default, so a line uncommented unchanged changes nothing.

- `.env` sits next to `build-magick.py` and is ignored by Git.
- A variable set in the shell wins over `.env` for that run.
- Only the settings listed in `.env.example` are read. Any other line, such as
  a misspelled name or one that starts with `export`, is reported with its line
  number and ignored, so the file cannot change variables such as `PATH`.
- Values are checked exactly as if they had been exported; an invalid one stops
  the build before anything is installed. An unreadable `.env` stops the run.

## Package selection (`--config`)

```bash
cp example.toml custom.toml   # edit it, then:
python3 build-magick.py --build --config ./custom.toml
```

The config is a deliberately small TOML subset - `[build]` and
`[packages]` tables with `key = true|false` entries - and an explicit
allowlist: once a config is loaded, **every package omitted from it is
disabled**. `[build]` also takes `compiler = "gcc"|"clang"`,
`cpu_target = "native"|"generic"|"x86-64-v2"|"x86-64-v3"|"x86-64-v4"`,
`gcc_version = <9-16>`, `shared = true|false` and `latest = true|false`:

```toml
[build]
compiler = "gcc"
gcc_version = 14
cpu_target = "native"
shared = false
latest = false
```

An explicit command-line option overrides the file (`--compiler`, `--clang`,
`--cpu-target`, `--gcc-version`), and the opt-ins `--shared` and `--latest`
win over a `false` entry. Without `--config`, everything builds (the default full
build). `example.toml` lists every supported key with a description; it is
generated from the package registry, and the linter keeps the two identical.

- Disabling a package skips its source build and passes an explicit
  `--without` flag to ImageMagick's configure; its delegate is also
  removed from the final validation's required set.
- Impossible selections fail up front with the exact conflict (the raqm
  stack needs freetype/fribidi/harfbuzz, fontconfig needs
  freetype/libxml2, libtiff needs libjpeg-turbo).
- The APT baseline is not configurable: system-package delegates (heic,
  rsvg, gvc, gslib, bzlib, ...) and the OpenCL ICD loader are always
  installed. Ghostscript and OpenCL are deliberately not built from source:
  ImageMagick renders PostScript and PDF through the system `libgs` and runs
  the system `gs` for conversions, and on Linux it loads the system
  `libOpenCL.so` at run time whatever it was linked against. A config file
  that still names the old `ghostscript` or `opencl-sdk` keys fails with
  that explanation.
- The active selection is recorded in the build context, so changing it
  automatically invalidates completed work - no manual cleanup needed.

## Build state model

All state lives under `./build/` (override with `BUILD_ROOT=/path`):

- Each package records a completion marker `packages/<name>.done`
  containing the built version and, for git sources, the exact 40-character
  commit. A rerun reuses recorded versions **offline** - no network traffic
  for completed packages - unless you pass `--latest`.
- To force one package to rebuild: `rm -f -- build/packages/<name>.done`.
  Every `[SKIP] ... is already built.` line is followed by that marker's full
  path on its own line, ready to copy.
- Markers are only trusted while the package's artifacts still exist; if
  artifacts vanish, the package is repaired at its recorded release (not
  upgraded). A Git release whose tag or HEAD moved upstream since it was
  recorded stops the build with the choice to restore it or rerun with
  `--latest`. Rebuilding a package also rebuilds every package built against
  it (harfbuzz, raqm and fontconfig after freetype, libtiff after
  libjpeg-turbo or libwebp, ImageMagick after libtool's libltdl), and
  rebuilding any library relinks ImageMagick. A package being rebuilt keeps
  its release in `packages/<name>.pin` until it completes, so an invalidated
  or interrupted rebuild resumes at that release instead of upgrading;
  `--latest` ignores pins.
- A build-context record (compiler, flags, CPU target, OS, selection, and for
  a native build the CPU model and instruction-set extensions) invalidates all
  markers and the workspace when any of them change, because the CPU target
  and the selected compiler make every artifact context-dependent. A build
  tree created by the Bash releases (2.x), or by 3.x releases that recorded
  only the CPU model, is adopted as-is when none of those inputs changed.
- Git checkouts are pinned: the resolved tag's commit is recorded at
  resolution time and the clone is verified against it, so a moved tag
  fails instead of silently building different content.
- ImageMagick additionally records a fingerprint of its configure options,
  so enabling or disabling a delegate rebuilds it even at the same version,
  and a SHA-256 receipt of every file it installed
  (`packages/imagemagick.installed`). A finished build is reused only while
  the files under `/usr/local` still match that receipt and pass the checks
  under [What "success" means](#what-success-means); otherwise ImageMagick is
  rebuilt in the same run.
- `build.log` is started only once the request, sudo and the toolchain
  environment have been checked, and it begins with the lines printed before
  the build banner. A run those checks stop leaves the previous log as it was;
  APT and the compiler checks run after it starts, so they are in the log.

## Safety model

- The whole build tree is user-owned; recursive deletion is bounded,
  never crosses filesystems, never escalates to root, and requires a
  path-bound marker (`.magick-build-root`) that a copied or unrelated
  directory cannot satisfy. `--cleanup` asks before removing the build root
  or an old build folder; the checkout's cache folders are deleted without
  asking, and a symlinked one is never followed.
- A directory lock prevents two builds from sharing one build root. Starting a
  build stops a competing build that holds the same build root's lock: the
  owner named by the kernel's lock record and its worker processes are pinned
  through `/proc` descriptors, stopped, and killed before the new build takes
  the lock. Processes of other users, other build roots and unrelated
  processes are never signalled. A worker whose parent already exited is
  still found: every command runs in a process group of its own, and each of
  those groups is stopped and killed while its stopped leader keeps the group
  ID from being reused. If a worker belongs to another user (sudo and the
  privileged step it runs) or cannot be stopped, the takeover fails, names
  the build to wait for or stop, and survivors are resumed.
  `--cleanup` never takes over: it refuses while a build holds the lock.
- Downloads are HTTPS-only (including redirects), go to a temp file, and
  are published to the cache only after they validate as a single-root tar
  archive with no traversal/absolute paths, no special files, and no
  symlink/hardlink escapes; extraction is transactional.
- ImageMagick installs into a staging tree first (`make DESTDIR=...` as
  the build user). Only after the staged tree validates is it published
  to `/usr/local` in a single privileged copy - upstream's install recipe
  never runs as root. Publishing holds a lock on `/usr/local` itself, shared by
  every build root and user of this project, and first saves every file it
  will replace or remove, recorded or not, to
  `/usr/local/share/imagemagick-build-script/previous-install.tar`. If the
  publish or the installed checks fail (or the build is interrupted there),
  the files that did not exist before are removed and the saved ones are
  restored; cancellation waits until every restore step has run. A backup
  whose restore failed is kept, named in the error, and every build root's
  next install waits until you restore or delete it. The installed file list is recorded at
  `/usr/local/share/imagemagick-build-script/manifest.txt`; every file the
  previous install recorded there that this one no longer has is removed, so
  a disabled delegate's old coder module cannot keep loading and a switch
  between the static and shared modes leaves no stale libraries, modules or
  bundled copies behind. Files nobody recorded in the manifest are never
  removed, an edited `policy.xml` is never touched, and Perl's
  `perllocal.pod` (its record of every locally installed module) is never
  replaced or removed.
- The published install never depends on the build root, so `--cleanup`
  cannot break it. The static default links the workspace libraries in; a
  `--shared` build copies every workspace shared library it loads into
  `/usr/local/lib/imagemagick-build-script`, a private directory only
  ImageMagick's run paths name, so the system's own copies are never
  shadowed. Build-root run paths are removed with `patchelf`, and the
  libtool, pkg-config, `*-config` and Perl records stop naming the build
  root. fontconfig and libxml2 are compiled to read the system's `/etc` and
  `/var`. A static build that still carries a shared library, a coder module
  or a bundled workspace library is refused before publication.
- Every build command runs with an allowlisted environment, so a Conda or
  virtual environment cannot leak compilers, flags, or library paths into
  the native builds, and upstream build systems cannot discover this
  repository's Git metadata. A command that needs no particular directory
  runs in `/`, never in the directory the build was started from. CMake
  configures never consult a host CMake package registry, and Meson never
  downloads a subproject in place of a missing dependency.
- sudo stays in the terminal's foreground process group, so its password
  prompt is always visible and Ctrl+C reaches it. It is validated before the
  first privileged step and again right before ImageMagick is installed.

### Trust model (read this once)

Transport security is HTTPS-only (including redirects) with certificate
verification. The `.sha256` files next to cached archives are
**cache-integrity records computed from our own download** - they detect
later corruption, they do not authenticate upstream. Most of the upstreams
built here do not publish signed artifacts, so first-time downloads are
trust-on-first-use over TLS.

### ImageMagick security policy

The build installs upstream's default (open) security policy and prints the
active policy at the end of the build. If you process untrusted images,
install a stricter policy - see
<https://imagemagick.org/script/security-policy.php>. Rebuilds keep an
edited `/usr/local/etc/ImageMagick-7/policy.xml` (reported as an `[INFO]`
line naming where this release's default was staged) and only replace a
policy that is still the default this builder installed. An install made by
a release that kept no record of its default is kept too, with one warning;
every later publish records the digest, so the warning never repeats.

## What "success" means

The builder only reports success after the installed `/usr/local/bin/magick`:

1. reports exactly the version that was resolved and built,
2. contains every delegate this project exists to provide
   (bzlib, fontconfig, freetype, fpx, gslib, gvc, heic, jbig, jng, jp2,
   jpeg, lcms, lzma, png, raqm, rsvg, tiff, webp, xml, zlib, zstd),
3. reports the requested link mode (`Modules` in its feature list only for a
   `--shared` build),
4. exposes a resolvable `MagickCore.pc` under `/usr/local/lib/pkgconfig`
   and a working `MagickCore-config`,
5. loads every library of every installed program, library and module
   from outside the build root,
6. completes a real conversion round-trip (`logo:` -> PNG -> WebP),
7. has a PerlMagick module the system `perl` loads with every symbol bound
   (`PERL_DL_NONLAZY=1`), reading an image and reporting this release.

Selections that disable PNG or WebP test only the enabled formats; a selection
with both disabled tests ImageMagick's native MIFF format.

A validated build closes with a report read from the installed binary, for
example (Debian 12, static default):

```text
[INFO] Functional smoke test passed (logo: -> PNG -> WebP).
[INFO] PerlMagick smoke test passed (ImageMagick 7.1.2-34 Q16-HDRI x86_64 ... https://imagemagick.org).
[DONE] imagemagick 7.1.2-34 built in 53s

┌────────────────────────────────────────────┐
│  ImageMagick build completed successfully  │
└────────────────────────────────────────────┘

  Version     7.1.2-34 Q16-HDRI
  Link mode   static  verified: no Modules feature, no libMagick shared objects, no modules
  Features    Cipher DPC HDRI OpenCL OpenMP(4.5)
  Installed   /usr/local/bin/magick and 12 legacy utilities
  Formats     265 readable, 202 writable
  Delegates   34  bzlib cairo djvu fftw fontconfig fpx freetype gslib gvc heic jbig jng
              jp2 jpeg jxl lcms lqr ltdl lzma openexr pangocairo png ps raqm raw rsvg tiff
              webp wmf x xml zip zlib zstd
  Policy      /usr/local/etc/ImageMagick-7/policy.xml
  Manifest    /usr/local/share/imagemagick-build-script/manifest.txt
  Build log   /home/user/imagemagick-build-script/build/build.log
```

The link mode row is checked, not assumed: the build fails unless the
`Modules` feature, the `libMagick*` libraries `magick` loads, and the installed
coder modules all match the requested mode. Cleanup then deletes the
checkout's cache folders and lists what a "yes" deletes, with sizes:

```text
[INFO] Deleted 3 cache folders (1.1 MB).

  Cleanup will free 1.7 GB by deleting:
    build/  1.7 GB  Downloaded sources, compiled libraries and the build log
  Your installed ImageMagick and its settings are not affected.
  Answering "no" keeps build/ and makes the next build faster.

[PROMPT] Delete these folders? (yes/no):
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
- `Force-killing competing build PID ...`: a new build of the same build
  root stopped the one already running there. `--cleanup` instead reports
  `Another build is already running` with that build's PID.
- `An earlier install's backup is still at ...`: a previous install's restore
  failed or was killed. Restore it with the printed `sudo tar` command, or
  delete the file if the current `/usr/local` is what you want, then rerun.
- A failure report ends with `Raised from: <file>:<line>`, which names the
  check that stopped the build; include it when reporting a bug.

## Development

The builder is the `magick_builder` package; `build-magick.py` is only the
launcher. Install the pinned development tools into any Python 3.12+
environment you manage (a virtual environment or a Conda environment) and run
the gates with that environment's interpreter:

```bash
python -m pip install '.[dev]'
python run_linter.py   # ruff, format, strict mypy, contracts
```

The linter and the tests run locally; the repository has no hosted CI.
