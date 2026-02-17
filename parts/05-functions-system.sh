# shellcheck shell=bash

apt_pkgs() {
    local pkg
    local -a pkgs=() extra_pkgs=("$@")
    local -a missing_packages=() available_packages=() unavailable_packages=()

    pkgs=(
        "${extra_pkgs[@]}" alien autoconf autoconf-archive
        binutils bison build-essential cmake curl dbus-x11
        flex fontforge git gperf intltool jq libc6
        libx11-dev libxext-dev libxt-dev
        libcpu-features-dev libdmalloc-dev libdmalloc5
        libfont-ttf-perl libgc-dev libgc1 libgegl-common
        libgl2ps-dev libglib2.0-dev libgs-dev libheif-dev
        libhwy-dev libjxl-dev libnotify-bin librust-jpeg-decoder-dev
        librust-malloc-buf-dev libsharp-dev libticonv-dev
        libtool libtool-bin libyuv-dev libyuv-utils libyuv0
        lsb-release lzip m4 meson nasm ninja-build php-dev
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

    # Check the availability of missing packages and categorize them
    for pkg in "${missing_packages[@]}"; do
        if apt-cache show "$pkg" >/dev/null 2>&1; then
            available_packages+=("$pkg")
        else
            unavailable_packages+=("$pkg")
        fi
    done

    # Print unavailable packages
    if [[ "${#unavailable_packages[@]}" -gt 0 ]]; then
        echo
        warn "Unavailable packages:"
        printf "          %s\n" "${unavailable_packages[@]}"
    fi

    # Install available missing packages
    if [[ "${#available_packages[@]}" -gt 0 ]]; then
        echo
        log "Installing available missing packages:"
        printf "       %s\n" "${available_packages[@]}"
        echo
        use_root apt-get update || fail "apt-get update failed. Line: ${LINENO}"
        use_root apt-get install -y "${available_packages[@]}" || fail "apt-get install failed. Line: ${LINENO}"
        use_root apt-get -y autoremove || warn "apt-get autoremove failed, continuing..."
        echo
    else
        log "No missing packages to install or all missing packages are unavailable."
    fi
}

debian_version() {
    case "$VER_MAJOR" in
        12) apt_pkgs libgegl-0.4-0 libcamd2 ;;
        13) apt_pkgs libgegl-0.4-0t64 libcamd3 ;;
        *)  fail "Could not detect the Debian version '$VER'. Supported: 12, 13. Line: ${LINENO}" ;;
    esac
}

get_os_version() {
    if command -v lsb_release &>/dev/null; then
        OS=$(lsb_release -si)
        VER=$(lsb_release -sr)
    elif [[ -f /etc/os-release ]]; then
        # shellcheck source=/etc/os-release
        source /etc/os-release
        case "$ID" in
            debian) OS="Debian" ;;
            ubuntu) OS="Ubuntu" ;;
            arch) OS="Arch" ;;
            *) OS="${NAME:-$ID}" ;;
        esac
        VER="$VERSION_ID"
    else
        fail "Failed to define the \$OS and/or \$VER variables. Line: ${LINENO}"
    fi
}
