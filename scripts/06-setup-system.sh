#!/usr/bin/env bash
# shellcheck shell=bash

# Install APT packages
echo
echo "Installing required APT packages"
echo "=========================================="

# GET THE OS NAME
get_os_version
VER_MAJOR="${VER%%.*}"

# DISCOVER WHAT VERSION OF LINUX WE ARE RUNNING (DEBIAN OR UBUNTU)
case "$OS" in
    Arch) ;;
    Debian) debian_version ;;
    Ubuntu) apt_pkgs ;;
    *) fail "Could not detect the OS architecture. Line: ${LINENO}" ;;
esac

# ImageMagick's shared libraries (libMagickCore/libMagickWand) are built from
# source in Phase 6 (12-build-imagemagick.sh). There is intentionally no
# prebuilt-RPM shortcut here: the upstream CentOS archive lags the source
# release, and installing a prebuilt libMagickCore alongside the source build
# (built with different configure flags) risks runtime library conflicts.

# INSTALL COMPOSER TO COMPILE GRAPHVIZ
if [[ ! -f "/usr/bin/composer" ]]; then
    composer_tmp=$(mktemp -d)
    cd "$composer_tmp" || fail "Failed to cd to temp directory"
    EXPECTED_CHECKSUM=$(php -r 'copy("https://composer.github.io/installer.sig", "php://stdout");')
    php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
    ACTUAL_CHECKSUM=$(php -r "echo hash_file('sha384', 'composer-setup.php');")

    if [[ "$EXPECTED_CHECKSUM" != "$ACTUAL_CHECKSUM" ]]; then
        warn "Composer checksum mismatch, skipping composer installation"
        rm -f "composer-setup.php"
        rm -rf "$composer_tmp"
    else
        if ! exec_root php composer-setup.php --install-dir=/usr/bin --filename=composer --quiet; then
            warn "Failed to install composer, continuing without it"
        fi
        rm -rf "$composer_tmp" composer-setup.php
    fi
    cd "$cwd" || exit 1
fi
