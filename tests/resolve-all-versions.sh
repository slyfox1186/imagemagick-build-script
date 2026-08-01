#!/usr/bin/env bash
# Resolution gate: runs every upstream version resolver through the same
# resolve_pkg dispatch table the build stages use (scripts/04) and fails
# on any empty/"null"/"unknown" result. Network required.

set -o pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

SCRIPT_VERSION=resolve-gate
latest_flag=1

# shellcheck source=scripts/01-variables.sh
source "$repo_root/scripts/01-variables.sh"
# shellcheck source=scripts/02-functions-core.sh
source "$repo_root/scripts/02-functions-core.sh"
# shellcheck source=scripts/03-functions-build.sh
source "$repo_root/scripts/03-functions-build.sh"
# shellcheck source=scripts/04-functions-version.sh
source "$repo_root/scripts/04-functions-version.sh"

packages=(
    m4 pkg-config
    libjpeg-turbo libtiff libfpx ghostscript libpng libwebp
    freetype libxml2 fontconfig fribidi harfbuzz raqm
    jemalloc opencl-sdk openjpeg lcms2
    source-code-pro source-sans-pro source-serif-pro roboto Fira
    imagemagick
)

failures=0
for name in "${packages[@]}"; do
    if ! triplet=$(resolve_pkg "$name"); then
        printf '%-16s RESOLUTION FAILED\n' "$name"
        failures=$((failures + 1))
        continue
    fi
    IFS='|' read -r tag ver commit <<<"$triplet"
    if [[ -z "$ver" || "$ver" == "null" || "$ver" == "unknown" ]]; then
        printf '%-16s INVALID VERSION %q\n' "$name" "$ver"
        failures=$((failures + 1))
        continue
    fi
    printf '%-16s tag=%-14s version=%-12s commit=%s\n' \
        "$name" "${tag:--}" "$ver" "${commit:--}"
done

if [[ "$failures" -gt 0 ]]; then
    printf '%d resolver(s) FAILED\n' "$failures" >&2
    exit 1
fi
printf 'All resolvers returned valid results.\n'
