#!/usr/bin/env bash
# shellcheck shell=bash

apt_pkgs() {
    local pkg
    local -a pkgs=() extra_pkgs=("$@")
    local -a missing_packages=() unavailable_packages=()

    pkgs=(
        "${extra_pkgs[@]}" autoconf autoconf-archive
        binutils bison build-essential cmake curl
        flex fontforge git gperf intltool jq libc6
        libx11-dev libxext-dev libxt-dev
        libcpu-features-dev
        libfont-ttf-perl libgc-dev libgc1 libgegl-common
        libgl2ps-dev libglib2.0-dev libgraphviz-dev libgs-dev libheif-dev
        libhwy-dev libjxl-dev librsvg2-dev librust-jpeg-decoder-dev
        librust-malloc-buf-dev libsharp-dev libticonv-dev
        libtool libtool-bin libyuv-dev libyuv-utils libyuv0
        lsb-release m4 meson nasm ninja-build
        pkg-config python3-dev yasm zlib1g-dev
    )

    [[ "$OS" == "Debian" ]] && pkgs+=(libjpeg62-turbo libjpeg62-turbo-dev)
    [[ "$OS" == "Ubuntu" ]] && pkgs+=(libjpeg62 libjpeg62-dev)

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

debian_version() {
    case "$VER_MAJOR" in
        12) apt_pkgs libgegl-0.4-0 libcamd2 ;;
        13) apt_pkgs libgegl-0.4-0t64 libcamd3 ;;
        *)  fail "Unsupported Debian version '$VER'. Supported: 12, 13. Line: ${LINENO}" ;;
    esac
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
