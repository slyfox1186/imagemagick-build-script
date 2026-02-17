# shellcheck shell=bash

find_git_repo "7950" "2"
version="${version#VER-}"
version1="${version//-/.}"
if build "freetype" "$version1"; then
    download "https://gitlab.freedesktop.org/freetype/freetype/-/archive/VER-$version/freetype-VER-$version.tar.bz2" "freetype-$version1.tar.bz2"
    extracmds=("-D"{harfbuzz,png,bzip2,brotli,zlib,tests}"=disabled")
    execute sh ./autogen.sh
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "freetype" "$version1"
fi

find_git_repo "1665" "3" "T"
if build "libxml2" "$version"; then
    download "https://gitlab.gnome.org/GNOME/libxml2/-/archive/v$version/libxml2-v$version.tar.bz2" "libxml2-$version.tar.bz2"
    if command -v python3.11-config &>/dev/null; then
        PYTHON_CFLAGS=$(python3.11-config --cflags)
        PYTHON_LIBS=$(python3.11-config --ldflags)
    else
        PYTHON_CFLAGS=$(python3.12-config --cflags)
        PYTHON_LIBS=$(python3.12-config --ldflags)
    fi
    export PYTHON_CFLAGS PYTHON_LIBS
    execute sh ./autogen.sh
    execute cmake -B build -DCMAKE_INSTALL_PREFIX="$workspace" \
                           -DCMAKE_BUILD_TYPE=Release \
                           -DBUILD_SHARED_LIBS=OFF \
                           -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "libxml2" "$version"
fi

find_git_repo "890" "2"
if build "fontconfig" "$version"; then
    download "https://gitlab.freedesktop.org/fontconfig/fontconfig/-/archive/$version/fontconfig-$version.tar.bz2"

    # Explicitly add paths for zlib and lzma, and link them
    fontconfig_ldflags="$LDFLAGS -DLIBXML_STATIC -L/usr/lib/x86_64-linux-gnu -lz -llzma"
    fontconfig_cflags="$CFLAGS -I/usr/include -I/usr/include/libxml2"

    # Update the pkg-config file to include LIBXML_STATIC
    sed -i "s|Cflags:|& -DLIBXML_STATIC|" "fontconfig.pc.in"

    execute sh ./autogen.sh --noconf
    execute sh ./configure --prefix="$workspace" \
                        --disable-docbook \
                        --disable-docs \
                        --disable-shared \
                        --disable-nls \
                        --enable-iconv \
                        --enable-libxml2 \
                        --enable-static \
                        --with-arch="$(uname -m)" \
                        --with-libiconv-prefix=/usr \
                        --with-pic \
                        CFLAGS="$fontconfig_cflags" \
                        LDFLAGS="$fontconfig_ldflags"

    execute make "-j$cpu_threads"
    execute make install
    build_done "fontconfig" "$version"
fi

# c2man is optional - it's an old tool for generating man pages from C comments
# Skip it as it has compatibility issues with modern systems
if command -v c2man &>/dev/null; then
    log "c2man already available, skipping build"
else
    warn "c2man not available, skipping (optional - used for man page generation)"
fi

find_git_repo "fribidi/fribidi" "1" "T"
if build "fribidi" "$version"; then
    download "https://github.com/fribidi/fribidi/archive/refs/tags/v$version.tar.gz" "fribidi-$version.tar.gz"
    extracmds=("-D"{docs,tests}"=false")
    execute autoreconf -fi
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "fribidi" "$version"
fi

find_git_repo "harfbuzz/harfbuzz" "1" "T"
if build "harfbuzz" "$version"; then
    download "https://github.com/harfbuzz/harfbuzz/archive/refs/tags/$version.tar.gz" "harfbuzz-$version.tar.gz"
    extracmds=("-D"{benchmark,cairo,docs,glib,gobject,icu,introspection,tests}"=disabled")
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "harfbuzz" "$version"
fi

find_git_repo "host-oman/libraqm" "1" "T"
if build "raqm" "$version"; then
    download "https://codeload.github.com/host-oman/libraqm/tar.gz/refs/tags/v$version" "raqm-$version.tar.gz"
    execute meson setup build --prefix="$workspace" \
                              --includedir="$workspace/include" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              -Ddocs=false
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "raqm" "$version"
fi
