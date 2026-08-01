#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_image_libs() {
    local tag ver commit

    # libjpeg-turbo builds FIRST: libtiff's configure probes for jpeg, and
    # with no system jpeg dev package installed the workspace static
    # library is what provides it.
    resolve_into libjpeg-turbo
    if build libjpeg-turbo "$ver"; then
        git_clone "$(pkg_repo_url libjpeg-turbo)" libjpeg-turbo "$tag" "$commit"
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

    resolve_into libtiff
    if build libtiff "$ver"; then
        download "https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/$tag" "libtiff-$ver.tar.gz"
        execute autoreconf -fi
        # webp is explicitly off: libwebp builds AFTER libtiff, so a clean
        # run never has it; leaving the probe on made the result depend on
        # leftover workspace state (and libtiff's link line does not carry
        # libwebp's private libsharpyuv dependency).
        execute sh configure --prefix="$workspace" --enable-cxx --disable-docs --disable-webp --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libtiff "$ver" "$commit"
    fi

    # libfpx is an ImageMagick-maintained mirror whose tags do not track
    # HEAD, so the HEAD commit itself is the pinned version.
    resolve_into libfpx
    if build libfpx "$ver"; then
        git_clone "$(pkg_repo_url libfpx)" libfpx "" "$commit"
        execute autoreconf -fi
        execute sh configure --prefix="$workspace" --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libfpx "$ver"
    fi

    resolve_into ghostscript
    if build ghostscript "$ver"; then
        download "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/$tag/ghostscript-$ver.tar.xz" \
            "ghostscript-$ver.tar.xz"
        execute sh autogen.sh
        execute sh configure --prefix="$workspace" --with-libiconv=native
        execute make "-j$cpu_threads"
        execute make install
        build_done ghostscript "$ver" "$commit"
    fi

    resolve_into libpng
    if build libpng "$ver"; then
        download "https://github.com/pnggroup/libpng/archive/refs/tags/$tag.tar.gz" "libpng-$ver.tar.gz"
        execute autoreconf -fi
        execute sh configure --prefix="$workspace" --enable-hardware-optimizations=yes --with-pic
        execute make "-j$cpu_threads"
        execute make install
        build_done libpng "$ver" "$commit"
    fi

    resolve_into libwebp
    if build libwebp "$ver"; then
        git_clone "$(pkg_repo_url libwebp)" libwebp "$tag" "$commit"
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
