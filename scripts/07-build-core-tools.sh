#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_core_tools() {
    local resolved ver
    local pkg_config_cppflags pkg_config_ldflags
    local -a pkg_config_iconv_args

    resolved=$(resolve_pkg_version m4 gnu_repo "$GNU_PRIMARY_MIRROR/m4/") ||
        fail "Failed to resolve the latest m4 version."
    IFS='|' read -r _ ver _ <<<"$resolved"
    if build m4 "$ver"; then
        download_with_fallback "$GNU_PRIMARY_MIRROR/m4/m4-$ver.tar.xz" \
            "$GNU_FALLBACK_MIRROR/m4/m4-$ver.tar.xz"
        execute sh configure --prefix="$workspace" --enable-c++ --enable-threads=posix
        execute make "-j$cpu_threads"
        execute make install
        build_done m4 "$ver"
    fi

    case "$OS:$VER_MAJOR" in
        Ubuntu:22) ver=2.4.6 ;;
        Ubuntu:24) ver=2.4.7 ;;
        Debian:12|Debian:13) ver=2.4.7 ;;
        *) fail "Unsupported OS version for libtool: $OS $VER. Line: ${LINENO}" ;;
    esac
    if build libtool "$ver"; then
        download "https://ftp.gnu.org/gnu/libtool/libtool-$ver.tar.xz"
        execute sh configure --prefix="$workspace" --with-pic M4="$workspace/bin/m4"
        execute make "-j$cpu_threads"
        execute make install
        build_done libtool "$ver"
    fi

    resolved=$(resolve_pkg_version pkg-config gnu_repo "https://pkgconfig.freedesktop.org/releases/") ||
        fail "Failed to resolve the latest pkg-config version."
    IFS='|' read -r _ ver _ <<<"$resolved"
    if build pkg-config "$ver"; then
        pkg_config_cppflags="$CPPFLAGS"
        pkg_config_ldflags="$LDFLAGS"
        pkg_config_iconv_args=()

        download "https://pkgconfig.freedesktop.org/releases/pkg-config-$ver.tar.gz"
        execute autoconf

        # If GNU libiconv is installed in /usr/local, use its headers and library
        # together so bundled GLib doesn't mix them with glibc's iconv detection.
        if [[ -f /usr/local/include/iconv.h ]] &&
           [[ -f /usr/local/lib/libiconv.a || -f /usr/local/lib/libiconv.so ||
              -f /usr/local/lib64/libiconv.a || -f /usr/local/lib64/libiconv.so ]]; then
            pkg_config_cppflags="-I$workspace/include -I/usr/local/include -I/usr/include -D_FORTIFY_SOURCE=2"
            pkg_config_ldflags="$pkg_config_ldflags -L/usr/local/lib64 -L/usr/local/lib"
            pkg_config_iconv_args+=(--with-libiconv=gnu)
        fi

        execute sh configure --prefix="$workspace" --with-internal-glib "${pkg_config_iconv_args[@]}" \
                             --with-pc-path="$WORKSPACE_PKG_CONFIG_DIRS" CFLAGS="$CFLAGS" \
                             CPPFLAGS="$pkg_config_cppflags" LDFLAGS="$pkg_config_ldflags"
        execute make "-j$cpu_threads"
        execute make install
        build_done pkg-config "$ver"
    fi
}
