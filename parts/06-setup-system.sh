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

# INSTALL OFFICIAL IMAGEMAGICK LIBS (optional - skip if version not available)
find_git_repo "imagemagick/imagemagick" "1" "T"
if build "magick-libs" "$version"; then
    [[ ! -d "$packages/deb-files" ]] && mkdir -p "$packages/deb-files"
    cd "$packages/deb-files" || exit 1
    if curl -LSso "magick-libs-$version.rpm" "https://imagemagick.org/archive/linux/CentOS/x86_64/ImageMagick-libs-$version.x86_64.rpm" 2>/dev/null; then
        execute use_root alien -d ./*.rpm || warn "alien conversion failed, continuing..."
        execute use_root dpkg --force-overwrite -i ./*.deb || warn "dpkg install failed, continuing..."
        build_done "magick-libs" "$version"
    else
        warn "magick-libs $version not available for download, skipping (will build from source)"
    fi
fi

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
        if ! use_root php composer-setup.php --install-dir=/usr/bin --filename=composer --quiet; then
            warn "Failed to install composer, continuing without it"
        fi
        rm -rf "$composer_tmp" composer-setup.php
    fi
    cd "$cwd" || exit 1
fi
