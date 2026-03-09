# shellcheck shell=bash

if build "m4" "latest"; then
    download_with_fallback "$GNU_PRIMARY_MIRROR/m4/m4-latest.tar.xz" "$GNU_FALLBACK_MIRROR/m4/m4-latest.tar.xz"
    execute sh configure --prefix="$workspace" --enable-c++ --enable-threads=posix
    execute make "-j$cpu_threads"
    execute make install
    build_done "m4" "latest"
fi

case "$OS:$VER_MAJOR" in
    Ubuntu:22) version=2.4.6 ;;
    Ubuntu:24) version=2.4.7 ;;
    Debian:12|Debian:13) version=2.4.7 ;;
    *) fail "Unsupported OS version for libtool: $OS $VER. Line: ${LINENO}" ;;
esac
if build "libtool" "$version"; then
    download "https://ftp.gnu.org/gnu/libtool/libtool-$version.tar.xz"
    execute sh configure --prefix="$workspace" --with-pic M4="$workspace/bin/m4"
    execute make "-j$cpu_threads"
    execute make install
    build_done "libtool" "$version"
fi

gnu_repo "https://pkgconfig.freedesktop.org/releases/"
if build "pkg-config" "$version"; then
    pkg_config_cppflags="$CPPFLAGS"
    pkg_config_ldflags="$LDFLAGS -L$workspace/lib64 -L$workspace/lib"
    pkg_config_iconv_args=()

    download "https://pkgconfig.freedesktop.org/releases/pkg-config-$version.tar.gz"
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
    build_done "pkg-config" "$version"
fi
