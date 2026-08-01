#!/usr/bin/env bash
# Availability gate: verifies that EVERY required APT package for the
# detected OS/release exists in the package archive. Read-only - run
# `apt update` first so the package index is current.
# Intended for fresh Debian/Ubuntu containers and CI.

set -o pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

SCRIPT_VERSION=apt-gate

# shellcheck source=scripts/01-variables.sh
source "$repo_root/scripts/01-variables.sh"
# shellcheck source=scripts/02-functions-core.sh
source "$repo_root/scripts/02-functions-core.sh"
# shellcheck source=scripts/05-functions-system.sh
source "$repo_root/scripts/05-functions-system.sh"

get_os_version
VER_MAJOR="${VER%%.*}"

pkg_list=$(apt_required_packages) || exit 1

unavailable=()
count=0
while IFS= read -r pkg; do
    [[ -n "$pkg" ]] || continue
    count=$((count + 1))
    if ! apt show "$pkg" >/dev/null 2>&1; then
        unavailable+=("$pkg")
    fi
done <<<"$pkg_list"

if [[ "${#unavailable[@]}" -gt 0 ]]; then
    printf 'UNAVAILABLE on %s %s (%d of %d): %s\n' \
        "$OS" "$VER" "${#unavailable[@]}" "$count" "${unavailable[*]}" >&2
    exit 1
fi
printf 'All %d required packages are available on %s %s.\n' "$count" "$OS" "$VER"
