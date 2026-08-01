#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_image_libs() {
    local resolved tag ver commit

    resolved=$(resolve_pkg_version libtiff resolve_latest_git_tag \
        "https://github.com/libsdl-org/libtiff.git" '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v') ||
        fail "Failed to resolve the latest libtiff version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libtiff "$ver"; then
        download "https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/$tag" "libtiff-$ver.tar.gz"
        execute autoreconf -fi
        execute sh configure --prefix="$workspace" --enable-cxx --disable-docs --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libtiff "$ver" "$commit"
    fi

    # libjpeg-turbo's tag list carries x.y.9z development tags (2.1.90 was
    # the 3.0 beta) and inherited upstream-jpeg tags (jpeg-9e, jpeg-10),
    # so the grammar accepts plain x.y.z and excludes the .9x dev series.
    resolved=$(resolve_pkg_version libjpeg-turbo resolve_latest_git_tag \
        "https://github.com/libjpeg-turbo/libjpeg-turbo.git" '^[0-9]+\.[0-9]+\.[0-9]+$' '\.9[0-9]$') ||
        fail "Failed to resolve the latest libjpeg-turbo version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libjpeg-turbo "$ver"; then
        git_clone "https://github.com/libjpeg-turbo/libjpeg-turbo.git" libjpeg-turbo "$tag" "$commit"
        execute cmake -S . \
                      -DCMAKE_INSTALL_PREFIX="$workspace" \
                      -DCMAKE_BUILD_TYPE=Release \
                      -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE \
                      -DENABLE_STATIC=ON -DENABLE_SHARED=OFF \
                      -G Ninja -Wno-dev
        execute ninja "-j$cpu_threads"
        execute ninja install
        build_done libjpeg-turbo "$ver" "$commit"
    fi

    # libfpx is an ImageMagick-maintained mirror whose tags do not track
    # HEAD, so the HEAD commit itself is the pinned version.
    resolved=$(resolve_pkg_version libfpx resolve_git_head "https://github.com/ImageMagick/libfpx.git") ||
        fail "Failed to resolve the libfpx HEAD commit."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libfpx "$ver"; then
        git_clone "https://github.com/ImageMagick/libfpx.git" libfpx "" "$commit"
        execute autoreconf -fi
        execute sh configure --prefix="$workspace" --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libfpx "$ver"
    fi

    resolved=$(resolve_pkg_version ghostscript resolve_ghostscript) ||
        fail "Failed to resolve the latest ghostscript version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build ghostscript "$ver"; then
        download "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/$tag/ghostscript-$ver.tar.xz" \
            "ghostscript-$ver.tar.xz"
        execute sh autogen.sh
        execute sh configure --prefix="$workspace" --with-libiconv=native
        execute make "-j$cpu_threads"
        execute make install
        build_done ghostscript "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version libpng resolve_latest_git_tag \
        "https://github.com/pnggroup/libpng.git" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v') ||
        fail "Failed to resolve the latest libpng version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libpng "$ver"; then
        download "https://github.com/pnggroup/libpng/archive/refs/tags/$tag.tar.gz" "libpng-$ver.tar.gz"
        execute autoreconf -fi
        execute sh configure --prefix="$workspace" --enable-hardware-optimizations=yes --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libpng "$ver" "$commit"
    fi

    resolved=$(resolve_pkg_version libwebp resolve_latest_git_tag \
        "https://chromium.googlesource.com/webm/libwebp" '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v') ||
        fail "Failed to resolve the latest libwebp version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build libwebp "$ver"; then
        git_clone "https://chromium.googlesource.com/webm/libwebp" libwebp "$tag" "$commit"
        execute autoreconf -fi
        execute cmake -B build \
                      -DCMAKE_INSTALL_PREFIX="$workspace" \
                      -DCMAKE_BUILD_TYPE=Release \
                      -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE \
                      -DBUILD_SHARED_LIBS=OFF \
                      -DZLIB_INCLUDE_DIR="$workspace/include" \
                      -DWEBP_BUILD_{CWEBP,DWEBP}=ON \
                      -DWEBP_BUILD_{ANIM_UTILS,EXTRAS,VWEBP}=OFF \
                      -DWEBP_ENABLE_SWAP_16BIT_CSP=OFF \
                      -DWEBP_LINK_STATIC=ON -G Ninja -Wno-dev
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done libwebp "$ver" "$commit"
    fi
}
