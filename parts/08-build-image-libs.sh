# shellcheck shell=bash

find_git_repo "libsdl-org/libtiff" "1" "T"
if build "libtiff" "$version"; then
    download "https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/v$version" "libtiff-$version.tar.gz"
    execute autoreconf -fi
    execute sh ./configure --prefix="$workspace" \
                        --enable-cxx \
                        --disable-docs \
                        --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "libtiff" "$version"
fi

find_git_repo "gperftools/gperftools" "1" "T"
version="${version#gperftools-}"
if build "gperftools" "$version"; then
    download "https://github.com/gperftools/gperftools/releases/download/gperftools-$version/gperftools-$version.tar.gz" "gperftools-$version.tar.bz2"
    gperftools_cflags="$CFLAGS -DNOLIBTOOL"
    execute autoreconf -fi
    [[ ! -d build ]] && mkdir build
    cd build || exit 1
    execute sh ../configure --prefix="$workspace" \
                         --with-pic \
                         --with-tcmalloc-pagesize=256 \
                         CFLAGS="$gperftools_cflags"
    execute make "-j$cpu_threads"
    execute make install
    build_done "gperftools" "$version"
fi

git_caller "https://github.com/libjpeg-turbo/libjpeg-turbo.git" "jpeg-turbo-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url" "$repo_name" "$recurse_flag" "$version"
    execute cmake -S . \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DENABLE_STATIC=ON \
                  -DENABLE_SHARED=OFF \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads"
    execute ninja install
    build_done "$repo_name" "$version"
fi

git_caller "https://github.com/imageMagick/libfpx.git" "libfpx-git"
if build "$repo_name" "$version"; then
    git_clone "$git_url" "$repo_name" "$recurse_flag" "$version"
    execute autoreconf -fi
    execute sh ./configure --prefix="$workspace" --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "$repo_name" "$version"
fi

find_git_repo "ArtifexSoftware/ghostpdl-downloads" "1" "T"
find_ghostscript_version "$version"
if build "ghostscript" "$version"; then
    download "$gscript_url" "ghostscript-$version.tar.xz"
    execute sh ./autogen.sh
    execute sh ./configure --prefix="$workspace" \
                        --with-libiconv=native
    execute make "-j$cpu_threads"
    execute make install
    build_done "ghostscript" "$version"
fi

find_git_repo "pnggroup/libpng" "1" "T"
if build "libpng" "$version"; then
    download "https://github.com/pnggroup/libpng/archive/refs/tags/v$version.tar.gz" "libpng-$version.tar.gz"
    execute autoreconf -fi
    execute sh ./configure --prefix="$workspace" \
                        --enable-hardware-optimizations=yes \
                        --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "libpng" "$version"
fi

if [[ "$OS" == "Ubuntu" ]]; then
    version="1.2.59"
    if build "libpng12" "$version"; then
        download "https://github.com/pnggroup/libpng/archive/refs/tags/v$version.tar.gz" "libpng12-$version.tar.gz"
        execute autoreconf -fi
        execute sh ./configure --prefix="$workspace" --with-pic
        execute make "-j$cpu_threads"
        execute make install
        execute rm "$workspace/include/png.h"
        build_done "libpng12" "$version"
    fi
fi

git_caller "https://chromium.googlesource.com/webm/libwebp" "libwebp-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url" "$repo_name" "$recurse_flag" "$version"
    execute autoreconf -fi
    execute cmake -B build \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DBUILD_SHARED_LIBS=OFF \
                  -DZLIB_INCLUDE_DIR="$workspace/include" \
                  -DWEBP_BUILD_{CWEBP,DWEBP}=ON \
                  -DWEBP_BUILD_{ANIM_UTILS,EXTRAS,VWEBP}=OFF \
                  -DWEBP_ENABLE_SWAP_16BIT_CSP=OFF \
                  -DWEBP_LINK_STATIC=ON \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "$repo_name" "$version"
fi
