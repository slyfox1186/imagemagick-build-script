#!/usr/bin/env bash
# shellcheck shell=bash

# The complete required package list for the detected OS/release, one per
# line on stdout. Shared by the installer below and by
# tests/check-apt-availability.sh (the container availability gate).
apt_required_packages() {
    # Delegate-enabling packages, all verified available on every
    # supported release via the availability gate:
    # - libdjvulibre/fftw3/lqr/openexr/pango/raw/wmf/zip dev packages
    #   light up the djvu/fftw/lqr/openexr/pangocairo/raw/wmf/zip
    #   delegates.
    # - libbz2/libjbig/liblzma/libzstd dev packages make the
    #   bzlib/jbig/lzma/zstd delegates guaranteed instead of depending on
    #   transitive installs.
    # - fonts-urw-base35 provides the exact directory the
    #   --with-urw-base35-font-dir configure flag points at.
    # - ghostscript provides the runtime `gs` binary: delegates.xml
    #   shells out to it for PDF/PS work, and the workspace-built gs is
    #   deleted with the build tree on cleanup.
    # - ffmpeg is the runtime video delegate (mpeg/mp4/webm coders).
    local -a pkgs=(
        autoconf autoconf-archive autopoint
        binutils bison build-essential bzip2 cmake curl ffmpeg
        flex fontforge fonts-dejavu-core fonts-urw-base35 ghostscript
        git gperf intltool jq libbz2-dev libc6
        libx11-dev libxext-dev libxt-dev
        libcpu-features-dev libdjvulibre-dev libfftw3-dev
        libfont-ttf-perl libgc-dev libgc1 libgegl-common
        libgl2ps-dev libglib2.0-dev libgraphviz-dev libgs-dev libheif-dev
        libhwy-dev libjbig-dev liblqr-1-0-dev liblzma-dev
        libopenexr-dev libpango1.0-dev
        libraw-dev librsvg2-dev librust-jpeg-decoder-dev
        librust-malloc-buf-dev libsharp-dev libticonv-dev
        libtool libtool-bin libwmf-dev libyuv-dev libyuv-utils libyuv0
        libzip-dev libzstd-dev lsb-release m4 meson nasm ninja-build
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
                *) fail "Unsupported Debian release '$VER'. Supported: 12 (bookworm) through 13 (trixie)." ;;
            esac
            ;;
        Ubuntu)
            case "$VER_MAJOR" in
                # libjxl-dev is not packaged for 22.04 (verified via the
                # container availability gate), so builds there simply lack
                # the optional JPEG-XL delegate.
                22) ;;
                24) pkgs+=(libjxl-dev) ;;
                *) fail "Unsupported Ubuntu release '$VER'. Supported: 22.04 (jammy) through 24.04 (noble)." ;;
            esac
            ;;
        *) fail "Unsupported distribution '$OS'." ;;
    esac

    printf '%s\n' "${pkgs[@]}"
}

apt_package_installed() {
    dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "ok installed"
}

# All privileged package-manager work goes through `apt` (never apt-get,
# per project policy). Behavior verified live: `apt install` accepts
# --no-remove, and `apt show` exits 0/100 for available/missing packages
# exactly like apt-cache show did.
apt_cmd() {
    exec_root env DEBIAN_FRONTEND=noninteractive apt "$@"
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
        apt_package_installed "$pkg" || missing_packages+=("$pkg")
    done

    if [[ "${#missing_packages[@]}" -eq 0 ]]; then
        log "All required APT packages are already installed."
        return 0
    fi

    # Refresh the package index once, then verify every missing package is
    # actually installable BEFORE mutating anything: a missing package means
    # a silently degraded ImageMagick (failed configure probes), so this
    # fails closed instead of installing a partial set.
    apt_cmd update || fail "apt update failed. Line: ${LINENO}"

    for pkg in "${missing_packages[@]}"; do
        if ! apt show "$pkg" >/dev/null 2>&1; then
            unavailable_packages+=("$pkg")
        fi
    done

    if [[ "${#unavailable_packages[@]}" -gt 0 ]]; then
        fail "Required APT packages are unavailable on $OS $VER: ${unavailable_packages[*]}"
    fi

    # Migration: older versions of this script installed the legacy
    # libjpeg62 dev packages, whose headers conflict with the
    # libjpeg-turbo8-dev that the libgraphviz-dev chain needs (observed
    # live: apt refuses the install under --no-remove). They have no
    # consumer in this build - jpeg comes from the workspace-built
    # libjpeg-turbo - so exactly these known-legacy dev packages are
    # removed first. --no-remove still blocks every other solver-proposed
    # removal.
    local -a legacy_conflicts=()
    for pkg in libjpeg62-dev libjpeg62-turbo-dev; do
        apt_package_installed "$pkg" && legacy_conflicts+=("$pkg")
    done
    if [[ "${#legacy_conflicts[@]}" -gt 0 ]]; then
        warn "Removing legacy dev package(s) installed by older versions of this script: ${legacy_conflicts[*]}"
        apt_cmd remove -y "${legacy_conflicts[@]}" ||
            fail "Failed to remove the legacy package(s): ${legacy_conflicts[*]}"
    fi

    echo
    log "Installing missing packages:"
    printf "       %s\n" "${missing_packages[@]}"
    echo
    # --no-remove: refuse any solver-proposed removal of existing packages.
    # No autoremove: removing "no longer needed" packages is unrelated,
    # destructive host mutation and is not this script's business.
    apt_cmd install -y --no-remove "${missing_packages[@]}" ||
        fail "apt install failed. Line: ${LINENO}"
    echo
}

# Sets OS (Debian/Ubuntu), VER (numeric release), and CODENAME (bookworm,
# trixie, jammy, noble, ...). Debian testing/unstable has no VERSION_ID,
# so VER stays empty there and the release check rejects it.
get_os_version() {
    if command -v lsb_release &>/dev/null; then
        OS=$(lsb_release -si)
        VER=$(lsb_release -sr)
        CODENAME=$(lsb_release -sc)
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
        CODENAME="${VERSION_CODENAME:-}"
    else
        fail "Failed to define the \$OS and/or \$VER variables. Line: ${LINENO}"
    fi
}
