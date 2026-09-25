#!/usr/bin/env bash
# shellcheck shell=bash

# SET GLOBAL VARIABLES
cwd="$PWD/build"
packages="$cwd/packages"
workspace="$cwd/workspace"
GNU_PRIMARY_MIRROR="https://ftp.gnu.org/gnu"
# A fixed HTTPS mirror, not ftpmirror.gnu.org: that one redirects to a random
# mirror that may be plain HTTP, which curl's HTTPS-only redirect policy
# rejects. Same /gnu/<package>/ layout as the primary.
GNU_FALLBACK_MIRROR="https://mirrors.kernel.org/gnu"

# Pre-defined color variables
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# ANNOUNCE THE BUILD HAS BEGUN
box_out_banner() {
    local border color_border color_text color_reset inner_len text text_len
    text="$*"
    text_len=${#text}
    inner_len=$((text_len + 2))

    color_border="$(tput setaf 3 2>/dev/null || true)"
    color_text="$(tput setaf 4 2>/dev/null || true)"
    color_reset="$(tput sgr0 2>/dev/null || true)"

    printf -v border '%*s' "$inner_len" ''
    border=${border// /-}

    tput bold 2>/dev/null || true
    printf ' %b%s%b\n' "$color_border" "$border" "$color_reset"
    printf '|%*s|\n' "$inner_len" ''
    printf '| %b%s%b |\n' "$color_text" "$text" "$color_reset"
    printf '|%*s|\n' "$inner_len" ''
    printf ' %b%s%b\n' "$color_border" "$border" "$color_reset"
    tput sgr0 2>/dev/null || true
}

readonly GNU_COMPILER_MIN_VERSION=9
readonly GNU_COMPILER_MAX_VERSION=14

# The exact version is resolved from the detected OS release and installed in
# stage_setup_system. Until then, use the requested name (if any) or the
# unversioned bootstrap compiler solely for multiarch discovery.
GNU_COMPILER_VERSION="${GNU_COMPILER_REQUESTED_VERSION:-}"
if [[ -n "$GNU_COMPILER_VERSION" ]]; then
    CC="gcc-$GNU_COMPILER_VERSION"
    CXX="g++-$GNU_COMPILER_VERSION"
else
    CC=gcc
    CXX=g++
fi

set_multiarch_paths() {
    MULTIARCH_TUPLE="$("$CC" -print-multiarch 2>/dev/null || true)"
    [[ -z "$MULTIARCH_TUPLE" ]] && MULTIARCH_TUPLE="$(uname -m)-linux-gnu"

    WORKSPACE_PKG_CONFIG_DIRS="\
$workspace/lib64/pkgconfig:\
$workspace/lib/$MULTIARCH_TUPLE/pkgconfig:\
$workspace/lib/pkgconfig:\
$workspace/share/pkgconfig\
"
    SYSTEM_PKG_CONFIG_DIRS="\
/usr/lib/$MULTIARCH_TUPLE/pkgconfig:\
/usr/share/pkgconfig:\
/usr/lib/pkgconfig:\
/lib/$MULTIARCH_TUPLE/pkgconfig:\
/lib/pkgconfig\
"
    PKG_CONFIG_PATH="$WORKSPACE_PKG_CONFIG_DIRS"
    PKG_CONFIG_LIBDIR="$WORKSPACE_PKG_CONFIG_DIRS:$SYSTEM_PKG_CONFIG_DIRS"
    export MULTIARCH_TUPLE WORKSPACE_PKG_CONFIG_DIRS SYSTEM_PKG_CONFIG_DIRS
    export PKG_CONFIG_PATH PKG_CONFIG_LIBDIR
}

activate_gnu_compiler_pair() {
    local version="$1" cc_major cxx_major
    CC="gcc-$version"
    CXX="g++-$version"
    command -v "$CC" >/dev/null 2>&1 || fail "The selected compiler '$CC' is not executable."
    command -v "$CXX" >/dev/null 2>&1 || fail "The selected compiler '$CXX' is not executable."
    cc_major=$("$CC" -dumpversion) || fail "Cannot query $CC."
    cxx_major=$("$CXX" -dumpversion) || fail "Cannot query $CXX."
    [[ "${cc_major%%.*}" == "$version" && "${cxx_major%%.*}" == "$version" ]] ||
        fail "The selected compiler pair does not report GCC major version $version."
    GNU_COMPILER_VERSION="$version"
    set_multiarch_paths
    export CC CXX GNU_COMPILER_VERSION
}

# Multiarch tuple for system library paths, derived from the compiler rather
# than hard-coded, with a static fallback for bootstrap runs where the
# compiler is not installed yet (the APT stage installs it before any build).
set_multiarch_paths

CFLAGS="-O3 -fPIC -pipe -march=native -fstack-protector-strong"
CXXFLAGS="$CFLAGS"
CPPFLAGS="-I$workspace/include -I/usr/local/include -I/usr/include -D_FORTIFY_SOURCE=2"
# The workspace -L paths are required so configure-time link probes (for
# example ImageMagick's FlashPIX -lfpx check) can find workspace-built
# libraries that ship no pkg-config file.
LDFLAGS="-L$workspace/lib64 -L$workspace/lib -Wl,-O1 -Wl,--as-needed -Wl,-rpath,/usr/local/lib64:/usr/local/lib"
export CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS GNU_PRIMARY_MIRROR GNU_FALLBACK_MIRROR GNU_COMPILER_VERSION

# SET THE AVAILABLE CPU THREAD COUNT FOR PARALLEL PROCESSING
if [[ -n "${BUILD_MAGICK_WORKERS:-}" ]]; then
    cpu_threads="$BUILD_MAGICK_WORKERS"
elif [[ -f /proc/cpuinfo ]]; then
    cpu_threads=$(grep -c ^processor /proc/cpuinfo)
else
    cpu_threads=$(nproc --all 2>/dev/null || true)
fi
[[ -z "$cpu_threads" || "$cpu_threads" -lt 1 ]] && cpu_threads=2

# Prefer the workspace and standard system toolchain over inherited user shims.
PATH="/usr/lib/ccache:$workspace/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PATH
