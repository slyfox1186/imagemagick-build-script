#!/usr/bin/env bash
# shellcheck shell=bash

# The workspace harfbuzz.pc shadows the system one, so any SYSTEM .pc that
# exact-pins the system harfbuzz version cannot resolve. On Debian 13,
# librsvg's Requires chain reaches harfbuzz-gobject ("requires harfbuzz =
# 10.2.0"), which silently killed ImageMagick's rsvg delegate probe
# (upstream configure.ac zeroes RSVG_CFLAGS/RSVG_LIBS, so the precious-
# variable override is impossible). This companion shim forwards to the
# system library at our harfbuzz version, keeping the chain consistent
# WITHOUT adding Requires to harfbuzz.pc itself (doing that dragged the
# system -L dir into raqm's link resolution and broke it).
ensure_harfbuzz_gobject_shim() {
    local hb_version="$1" hb_pc_dir
    local sys_gobject_pc="/usr/lib/$MULTIARCH_TUPLE/pkgconfig/harfbuzz-gobject.pc"
    [[ -f "$sys_gobject_pc" ]] || return 0
    for hb_pc_dir in "$workspace/lib/pkgconfig" "$workspace/lib64/pkgconfig" \
        "$workspace/lib/$MULTIARCH_TUPLE/pkgconfig"; do
        [[ -f "$hb_pc_dir/harfbuzz.pc" ]] || continue
        cat >"$hb_pc_dir/harfbuzz-gobject.pc" <<SHIM
Name: harfbuzz-gobject (workspace compatibility shim)
Description: Forwards to the system harfbuzz-gobject while the workspace shadows harfbuzz
Version: $hb_version
Requires: harfbuzz
Libs: -L/usr/lib/$MULTIARCH_TUPLE -lharfbuzz-gobject
Cflags: -I/usr/include/harfbuzz
SHIM
        log "Wrote the harfbuzz-gobject compatibility shim to $hb_pc_dir"
        return 0
    done
}

stage_build_text_libs() {
    local tag ver commit
    local -a extracmds iconv_cmake_flags
    local fontconfig_cflags fontconfig_ldflags _dir _inc

    # freetype tags use dashes (VER-2-13-3); the recorded version is the
    # dotted form, which is a no-op on the marker-reuse path.
    resolve_into freetype
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

    resolve_into libxml2
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

    resolve_into fontconfig
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

    resolve_into fribidi
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

    resolve_into harfbuzz
    if build harfbuzz "$ver"; then
        download "https://github.com/harfbuzz/harfbuzz/archive/refs/tags/$tag.tar.gz" "harfbuzz-$ver.tar.gz"
        # glib/gobject must stay DISABLED: enabling them adds a glib
        # Requires to the workspace harfbuzz.pc, which drags the system -L
        # directory into consumers' link resolution - raqm then resolved
        # the SYSTEM libharfbuzz.so (older, no hb_ft_font_get_ft_face)
        # instead of the workspace static library (verified on Debian 13).
        # The Debian-13 librsvg/harfbuzz-gobject probe conflict is solved
        # in the ImageMagick stage with explicit RSVG_CFLAGS/RSVG_LIBS.
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
    ensure_harfbuzz_gobject_shim "$ver"

    resolve_into raqm
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
