# shellcheck shell=bash

case "$OS:$VER_MAJOR" in
    Ubuntu:22) version=2.4.6 ;;
    Ubuntu:24) version=2.4.7 ;;
    Debian:12|Debian:13) version=2.4.7 ;;
    *) fail "Unsupported OS version for libtool: $OS $VER. Line: ${LINENO}" ;;
esac
if build "libtool" "$version"; then
    download "https://ftp.gnu.org/gnu/libtool/libtool-$version.tar.xz"
    execute sh ./configure --prefix="$workspace" \
                        --with-pic \
                        M4="$workspace/bin/m4"
    execute make "-j$cpu_threads"
    execute make install
    build_done "libtool" "$version"
fi

gnu_repo "https://pkgconfig.freedesktop.org/releases/"
if build "pkg-config" "$version"; then
    download "https://pkgconfig.freedesktop.org/releases/pkg-config-$version.tar.gz"
    execute autoconf
    execute sh ./configure --prefix="$workspace" \
                        --with-internal-glib \
                        --with-pc-path="$PKG_CONFIG_PATH" \
                        CFLAGS="-I$workspace/include" \
                        LDFLAGS="-L$workspace/lib64 -L$workspace/lib"
    execute make "-j$cpu_threads"
    execute make install
    build_done "pkg-config" "$version"
fi
