#!/usr/bin/env bash
# Resolution gate: runs every upstream version resolver with the exact
# per-package grammar the build stages use and asserts each returns a
# version-shaped result with a commit where applicable. Network required.
# NOTE: the grammars here mirror the call sites in scripts/07-12; when a
# grammar changes there, change it here too.

set -o pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

SCRIPT_VERSION=resolve-gate

# shellcheck source=scripts/01-variables.sh
source "$repo_root/scripts/01-variables.sh"
# shellcheck source=scripts/02-functions-core.sh
source "$repo_root/scripts/02-functions-core.sh"
# shellcheck source=scripts/03-functions-build.sh
source "$repo_root/scripts/03-functions-build.sh"
# shellcheck source=scripts/04-functions-version.sh
source "$repo_root/scripts/04-functions-version.sh"

failures=0

report() {
    local name="$1" triplet="${2:-}" tag ver commit
    if [[ -z "$triplet" ]]; then
        printf '%-14s RESOLUTION FAILED\n' "$name"
        failures=$((failures + 1))
        return
    fi
    IFS='|' read -r tag ver commit <<<"$triplet"
    if [[ -z "$ver" || "$ver" == "null" || "$ver" == "unknown" ]]; then
        printf '%-14s INVALID VERSION %q\n' "$name" "$ver"
        failures=$((failures + 1))
        return
    fi
    printf '%-14s tag=%-14s version=%-12s commit=%s\n' "$name" "${tag:--}" "$ver" "${commit:--}"
}

run_resolver() {
    local name="$1"
    shift
    local triplet
    triplet=$("$@") || triplet=""
    report "$name" "$triplet"
}

run_resolver m4 gnu_repo "$GNU_PRIMARY_MIRROR/m4/"
run_resolver pkg-config gnu_repo "https://pkgconfig.freedesktop.org/releases/"
run_resolver libtiff resolve_latest_git_tag "https://github.com/libsdl-org/libtiff.git" '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v'
run_resolver libjpeg-turbo resolve_latest_git_tag "https://github.com/libjpeg-turbo/libjpeg-turbo.git" '^[0-9]+\.[0-9]+\.[0-9]+$' '\.9[0-9]$'
run_resolver libfpx resolve_git_head "https://github.com/ImageMagick/libfpx.git"
run_resolver ghostscript resolve_ghostscript
run_resolver libpng resolve_latest_git_tag "https://github.com/pnggroup/libpng.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v'
run_resolver libwebp resolve_latest_git_tag "https://chromium.googlesource.com/webm/libwebp" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v'
run_resolver freetype resolve_latest_git_tag "https://gitlab.freedesktop.org/freetype/freetype.git" '^VER-[0-9]+(-[0-9]+)+$' '' 'VER-'
run_resolver libxml2 resolve_latest_git_tag "https://gitlab.gnome.org/GNOME/libxml2.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v'
run_resolver fontconfig resolve_latest_git_tag "https://gitlab.freedesktop.org/fontconfig/fontconfig.git" '^[0-9]+\.[0-9]+(\.[0-9]+)?$'
run_resolver fribidi resolve_latest_git_tag "https://github.com/fribidi/fribidi.git" '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v'
run_resolver harfbuzz resolve_latest_git_tag "https://github.com/harfbuzz/harfbuzz.git" '^[0-9]+\.[0-9]+\.[0-9]+$'
run_resolver raqm resolve_latest_git_tag "https://github.com/host-oman/libraqm.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v'
run_resolver jemalloc resolve_latest_git_tag "https://github.com/jemalloc/jemalloc.git" '^[0-9]+\.[0-9]+\.[0-9]+$'
run_resolver opencl-sdk resolve_latest_git_tag "https://github.com/KhronosGroup/OpenCL-SDK.git" '^v[0-9]{4}\.[0-9]{2}\.[0-9]{2}$' '' 'v'
run_resolver openjpeg resolve_latest_git_tag "https://github.com/uclouvain/openjpeg.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v'
run_resolver lcms2 resolve_latest_git_tag "https://github.com/mm2/Little-CMS.git" '^lcms[0-9]+(\.[0-9]+)+$' '' 'lcms'
run_resolver imagemagick resolve_latest_git_tag "https://github.com/ImageMagick/ImageMagick.git" '^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$'
run_resolver dejavu-fonts resolve_git_head "https://github.com/dejavu-fonts/dejavu-fonts.git"

if [[ "$failures" -gt 0 ]]; then
    printf '%d resolver(s) FAILED\n' "$failures" >&2
    exit 1
fi
printf 'All resolvers returned valid results.\n'
