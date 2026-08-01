#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_imagemagick() {
    local resolved tag ver commit

    echo
    box_out_banner "Build ImageMagick"

    resolved=$(resolve_pkg_version imagemagick resolve_latest_git_tag \
        "https://github.com/ImageMagick/ImageMagick.git" '^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$') ||
        fail "Failed to resolve the latest ImageMagick version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build imagemagick "$ver"; then
        download "https://github.com/ImageMagick/ImageMagick/archive/refs/tags/$tag.tar.gz" "imagemagick-$ver.tar.gz"
        execute autoreconf -fi
        [[ -d build/ ]] && rm -fr build/
        mkdir build/
        cd build/ || exit 1
        execute sh ../configure --prefix=/usr/local \
                                --enable-delegate-build \
                                --enable-hdri \
                                --enable-hugepages \
                                --enable-legacy-support \
                                --enable-opencl \
                                --with-fontpath=/usr/share/fonts/truetype \
                                --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu \
                                --with-gs-font-dir=/usr/share/fonts/ghostscript \
                                --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35 \
                                --with-fpx \
                                --with-gslib \
                                --with-gvc \
                                --with-heic \
                                --with-jemalloc \
                                --with-modules \
                                --with-perl \
                                --with-pic \
                                --with-pkgconfigdir="$workspace/lib/pkgconfig" \
                                --with-png \
                                --with-quantum-depth=16 \
                                --with-rsvg \
                                --with-utilities \
                                --without-autotrace \
                                CFLAGS="$CFLAGS -DCL_TARGET_OPENCL_VERSION=300" \
                                CXXFLAGS="$CXXFLAGS -DCL_TARGET_OPENCL_VERSION=300" \
                                CPPFLAGS="$CPPFLAGS -I$workspace/include/CL" \
                                PKG_CONFIG="$workspace/bin/pkg-config"
        execute make "-j$cpu_threads"
        execute exec_root make install
    fi
}
