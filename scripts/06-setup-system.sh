#!/usr/bin/env bash
# shellcheck shell=bash

stage_setup_system() {
    echo
    echo "Installing required APT packages"
    echo "=========================================="

    # GET THE OS NAME
    get_os_version
    VER_MAJOR="${VER%%.*}"

    # ONLY DEBIAN AND UBUNTU ARE SUPPORTED; ANYTHING ELSE FAILS BEFORE ANY
    # PACKAGES ARE INSTALLED OR BUILD WORK STARTS.
    case "$OS" in
        Debian) debian_version ;;
        Ubuntu) apt_pkgs ;;
        *) fail "Unsupported distribution '$OS'. Supported: Debian 12/13, Ubuntu 22.04/24.04." ;;
    esac

    # ImageMagick's shared libraries (libMagickCore/libMagickWand) are built from
    # source in the ImageMagick stage. There is intentionally no prebuilt-RPM
    # shortcut here: the upstream CentOS archive lags the source release, and
    # installing a prebuilt libMagickCore alongside the source build (built with
    # different configure flags) risks runtime library conflicts.

    # The build context depends on the detected OS, so it is refreshed here
    # rather than at build-root initialization time.
    refresh_build_context
}
