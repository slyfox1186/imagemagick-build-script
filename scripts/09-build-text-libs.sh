#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_text_libs() {
    local resolved tag ver commit
    local -a extracmds iconv_cmake_flags
    local fontconfig_cflags fontconfig_ldflags _dir _inc

    # freetype tags use dashes (VER-2-13-3); the recorded version is the
    # dotted form, which is a no-op on the marker-reuse path.
    resolved=$(resolve_pkg_version freetype resolve_latest_git_tag \
        "https://gitlab.freedesktop.org/freetype/freetype.git" '^VER-[0-9]+(-[0-9]+)+$' '' 'VER-') ||
        fail "Failed to resolve the latest freetype version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    ver="${ver//-/.}"
    if build freetype "$ver"; then
        download "https://gitlab.freedesktop.org/freetype/freetype/-/archive/$tag/freetype-$tag.tar.bz2" \
            "freetype-$ver.tar.bz2"
        extracmds=("-D"{harfbuzz,png,bzip2,brotli,zlib,tests}"=disabled")
        execute sh autogen.sh
        execute meson setup build --prefix="$workspace" \
                                  --buildtype=release \
                                  --default-library=static \
                                  --strip \
                                  "${extracmds[@]}"
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done freetype "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version libxml2 resolve_latest_git_tag \
        "https://gitlab.gnome.org/GNOME/libxml2.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v') ||
        fail "Failed to resolve the latest libxml2 version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libxml2 "$ver"; then
        download "https://gitlab.gnome.org/GNOME/libxml2/-/archive/$tag/libxml2-$tag.tar.bz2" \
            "libxml2-$ver.tar.bz2"
        # This is a pure CMake build: the old code additionally ran the
        # Autotools autogen.sh bootstrap (pointless before cmake) and probed
        # python3.11/3.12-config - a hard failure on Ubuntu 22.04, which
        # ships only python3.10. ImageMagick needs no libxml2 python
        # bindings, so they are pinned OFF regardless of upstream defaults.

        # Detect standalone GNU libiconv (vs glibc built-in) so cmake links it properly
        iconv_cmake_flags=()
        for _dir in "$workspace/lib" /usr/local/lib /usr/lib; do
            if [[ -f "$_dir/libiconv.a" || -f "$_dir/libiconv.so" ]]; then
                _inc="${_dir%/lib}/include"
                if [[ -f "$_inc/iconv.h" ]]; then
                    iconv_cmake_flags+=("-DIconv_INCLUDE_DIR=$_inc")
                    if [[ -f "$_dir/libiconv.a" ]]; then
                        iconv_cmake_flags+=("-DIconv_LIBRARY=$_dir/libiconv.a")
                    else
                        iconv_cmake_flags+=("-DIconv_LIBRARY=$_dir/libiconv.so")
                    fi
                    break
                fi
            fi
        done

        execute cmake -B build -DCMAKE_INSTALL_PREFIX="$workspace" \
                               -DCMAKE_BUILD_TYPE=Release \
                               -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE \
                               -DBUILD_SHARED_LIBS=OFF \
                               -DLIBXML2_WITH_PYTHON=OFF \
                               "${iconv_cmake_flags[@]}" \
                               -G Ninja -Wno-dev
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done libxml2 "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version fontconfig resolve_latest_git_tag \
        "https://gitlab.freedesktop.org/fontconfig/fontconfig.git" '^[0-9]+\.[0-9]+(\.[0-9]+)?$') ||
        fail "Failed to resolve the latest fontconfig version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build fontconfig "$ver"; then
        download "https://gitlab.freedesktop.org/fontconfig/fontconfig/-/archive/$tag/fontconfig-$tag.tar.bz2"

        # Explicitly add paths for zlib and lzma, and link them
        fontconfig_ldflags="$LDFLAGS -DLIBXML_STATIC -L/usr/lib/$MULTIARCH_TUPLE -lz -llzma"
        fontconfig_cflags="$CFLAGS -I/usr/include -I/usr/include/libxml2"

        # Update the pkg-config file to include LIBXML_STATIC
        sed -i "s|Cflags:|& -DLIBXML_STATIC|" "fontconfig.pc.in"

        execute sh autogen.sh --noconf
        execute sh configure --prefix="$workspace" \
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
        build_done fontconfig "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version fribidi resolve_latest_git_tag \
        "https://github.com/fribidi/fribidi.git" '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v') ||
        fail "Failed to resolve the latest fribidi version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build fribidi "$ver"; then
        download "https://github.com/fribidi/fribidi/archive/refs/tags/$tag.tar.gz" "fribidi-$ver.tar.gz"
        extracmds=("-D"{docs,tests}"=false")
        execute autoreconf -fi
        execute meson setup build --prefix="$workspace" \
                                  --buildtype=release \
                                  --default-library=static \
                                  --strip \
                                  "${extracmds[@]}"
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done fribidi "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version harfbuzz resolve_latest_git_tag \
        "https://github.com/harfbuzz/harfbuzz.git" '^[0-9]+\.[0-9]+\.[0-9]+$') ||
        fail "Failed to resolve the latest harfbuzz version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build harfbuzz "$ver"; then
        download "https://github.com/harfbuzz/harfbuzz/archive/refs/tags/$tag.tar.gz" "harfbuzz-$ver.tar.gz"
        extracmds=("-D"{benchmark,cairo,docs,glib,gobject,icu,introspection,tests}"=disabled")
        execute meson setup build --prefix="$workspace" \
                                  --buildtype=release \
                                  --default-library=static \
                                  --strip \
                                  "${extracmds[@]}"
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done harfbuzz "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version raqm resolve_latest_git_tag \
        "https://github.com/host-oman/libraqm.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v') ||
        fail "Failed to resolve the latest raqm version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build raqm "$ver"; then
        download "https://codeload.github.com/host-oman/libraqm/tar.gz/refs/tags/$tag" "raqm-$ver.tar.gz"
        execute meson setup build --prefix="$workspace" \
                                  --includedir="$workspace/include" \
                                  --buildtype=release \
                                  --default-library=static \
                                  --strip \
                                  -Ddocs=false
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done raqm "$ver" "$commit"
    fi
}
