# shellcheck shell=bash

echo
box_out_banner "Build ImageMagick"

find_git_repo "ImageMagick/ImageMagick" "1" "T"
if build "imagemagick" "$version"; then
    download "https://imagemagick.org/archive/releases/ImageMagick-$version.tar.lz" "imagemagick-$version.tar.lz"
    execute autoreconf -fi
    [[ ! -d build ]] && mkdir build
    cd build || exit 1
    execute sh ../configure --prefix=/usr/local \
                         --enable-ccmalloc \
                         --enable-delegate-build \
                         --enable-hdri \
                         --enable-hugepages \
                         --enable-legacy-support \
                         --enable-opencl \
                         --with-dmalloc \
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
                         --with-tcmalloc \
                         --with-utilities \
                         --without-autotrace \
                         CFLAGS="$CFLAGS -DCL_TARGET_OPENCL_VERSION=300" \
                         CXXFLAGS="$CFLAGS" \
                         CPPFLAGS="$CPPFLAGS -I$workspace/include/CL" \
                         PKG_CONFIG="$workspace/bin/pkg-config"
    execute make "-j$cpu_threads"
    execute use_root make install
fi
