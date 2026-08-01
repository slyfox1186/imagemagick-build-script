#!/usr/bin/env bash
# shellcheck shell=bash

# The complete required package list for the detected OS/release, one per
# line on stdout. Shared by the installer below and by
# tests/check-apt-availability.sh (the container availability gate).
apt_required_packages() {
    local -a pkgs=(
        autoconf autoconf-archive autopoint
        binutils bison build-essential bzip2 cmake curl
        flex fontforge fonts-dejavu-core git gperf intltool jq libc6
        libx11-dev libxext-dev libxt-dev
        libcpu-features-dev
        libfont-ttf-perl libgc-dev libgc1 libgegl-common
        libgl2ps-dev libglib2.0-dev libgraphviz-dev libgs-dev libheif-dev
        libhwy-dev librsvg2-dev librust-jpeg-decoder-dev
        librust-malloc-buf-dev libsharp-dev libticonv-dev
        libtool libtool-bin libyuv-dev libyuv-utils libyuv0
        lsb-release m4 meson nasm ninja-build
        pkg-config python3-dev xz-utils yasm zlib1g-dev
    )

    # The legacy libjpeg62* packages were removed from this list with
    # evidence: nothing consumes them (jpeg comes from the workspace-built
    # libjpeg-turbo), and on Ubuntu 24.04 libjpeg62-dev conflicts with the
    # libjpeg-turbo8-dev that the libgraphviz-dev chain requires.
    case "$OS" in
        Debian)
            pkgs+=(libjxl-dev)
            case "$VER_MAJOR" in
                12) pkgs+=(libgegl-0.4-0 libcamd2) ;;
                13) pkgs+=(libgegl-0.4-0t64 libcamd3) ;;
                *) fail "Unsupported Debian version '$VER'. Supported: 12, 13." ;;
            esac
            ;;
        Ubuntu)
            case "$VER_MAJOR" in
                # libjxl-dev is not packaged for 22.04 (verified via the
                # container availability gate), so builds there simply lack
                # the optional JPEG-XL delegate.
                22) ;;
                24) pkgs+=(libjxl-dev) ;;
                *) fail "Unsupported Ubuntu version '$VER'. Supported: 22.04, 24.04." ;;
            esac
            ;;
        *) fail "Unsupported distribution '$OS'." ;;
    esac

    printf '%s\n' "${pkgs[@]}"
}

apt_pkgs() {
    local pkg pkg_list
    local -a pkgs=()
    local -a missing_packages=() unavailable_packages=()

    pkg_list=$(apt_required_packages) ||
        fail "Could not determine the required APT package list for $OS $VER."
    mapfile -t pkgs <<<"$pkg_list"

    log "Checking package installation status..."

    # Loop through the array to find missing packages
    for pkg in "${pkgs[@]}"; do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            missing_packages+=("$pkg")
        fi
    done

    if [[ "${#missing_packages[@]}" -eq 0 ]]; then
        log "All required APT packages are already installed."
        return 0
    fi

    # Refresh the package index once, then verify every missing package is
    # actually installable BEFORE mutating anything: a missing package means
    # a silently degraded ImageMagick (failed configure probes), so this
    # fails closed instead of installing a partial set.
    exec_root apt-get update || fail "apt-get update failed. Line: ${LINENO}"

    for pkg in "${missing_packages[@]}"; do
        if ! apt-cache show "$pkg" >/dev/null 2>&1; then
            unavailable_packages+=("$pkg")
        fi
    done

    if [[ "${#unavailable_packages[@]}" -gt 0 ]]; then
        fail "Required APT packages are unavailable on $OS $VER: ${unavailable_packages[*]}"
    fi

    echo
    log "Installing missing packages:"
    printf "       %s\n" "${missing_packages[@]}"
    echo
    # --no-remove: refuse any solver-proposed removal of existing packages.
    # No autoremove: removing "no longer needed" packages is unrelated,
    # destructive host mutation and is not this script's business.
    exec_root env DEBIAN_FRONTEND=noninteractive \
        apt-get install -y --no-remove "${missing_packages[@]}" ||
        fail "apt-get install failed. Line: ${LINENO}"
    echo
}

get_os_version() {
    if command -v lsb_release &>/dev/null; then
        OS=$(lsb_release -si)
        VER=$(lsb_release -sr)
    elif [[ -f /etc/os-release ]]; then
        # The sourced file's variables (ID, NAME, VERSION_ID) only exist at
        # runtime, so ShellCheck must not follow or analyze the host's copy.
        # shellcheck source=/dev/null
        source /etc/os-release
        case "${ID:-}" in
            debian) OS="Debian" ;;
            ubuntu) OS="Ubuntu" ;;
            *) OS="${NAME:-${ID:-}}" ;;
        esac
        VER="${VERSION_ID:-}"
    else
        fail "Failed to define the \$OS and/or \$VER variables. Line: ${LINENO}"
    fi
}
