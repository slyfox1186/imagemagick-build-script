#!/usr/bin/env bash
# shellcheck shell=bash

stage_build_extra_libs() {
    local tag ver commit

    resolve_into jemalloc
    if build jemalloc "$ver"; then
        download "https://github.com/jemalloc/jemalloc/archive/refs/tags/$tag.tar.gz" "jemalloc-$ver.tar.gz"
        execute sh autogen.sh
        execute sh configure --prefix="$workspace" \
                            --disable-debug \
                            --disable-doc \
                            --disable-fill \
                            --disable-log \
                            --disable-prof \
                            --disable-stats \
                            --enable-autogen \
                            --enable-static \
                            --enable-xmalloc \
                            CFLAGS="$CFLAGS"
        execute make "-j$cpu_threads"
        execute make install
        build_done jemalloc "$ver" "$commit"
    fi

    resolve_into opencl-sdk
    if build opencl-sdk "$ver"; then
        git_clone "$(pkg_repo_url opencl-sdk)" opencl-sdk "$tag" "$commit" 1
        execute cmake \
                -S . \
                -B build \
                -DCMAKE_INSTALL_PREFIX="$workspace" \
                -DCMAKE_BUILD_TYPE=Release \
                -DCMAKE_POSITION_INDEPENDENT_CODE=true \
                -DBUILD_SHARED_LIBS=OFF \
                -DBUILD_{DOCS,EXAMPLES,TESTING}=OFF \
                -DOPENCL_SDK_{BUILD_SAMPLES,TEST_SAMPLES}=OFF \
                -DCMAKE_C_FLAGS="$CFLAGS" \
                -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
                -DOPENCL_HEADERS_BUILD_CXX_TESTS=OFF \
                -DOPENCL_ICD_LOADER_BUILD_SHARED_LIBS=OFF \
                -DOPENCL_SDK_BUILD_{OPENGL_SAMPLES,SAMPLES}=OFF \
                -DOPENCL_SDK_TEST_SAMPLES=OFF \
                -DTHREADS_PREFER_PTHREAD_FLAG=ON \
                -G Ninja -Wno-dev
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done opencl-sdk "$ver" "$commit"
    fi

    resolve_into openjpeg
    if build openjpeg "$ver"; then
        download "https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/$tag" "openjpeg-$ver.tar.gz"
        execute cmake -B build \
                      -DCMAKE_INSTALL_PREFIX="$workspace" \
                      -DCMAKE_BUILD_TYPE=Release \
                      -DCMAKE_POSITION_INDEPENDENT_CODE=true \
                      -DBUILD_CODEC=OFF \
                      -DBUILD_{SHARED_LIBS,TESTING}=OFF \
                      -DBUILD_THIRDPARTY=OFF \
                      -G Ninja -Wno-dev
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done openjpeg "$ver" "$commit"
    fi

    resolve_into lcms2
    if build lcms2 "$ver"; then
        download "https://github.com/mm2/Little-CMS/archive/refs/tags/$tag.tar.gz" "lcms2-$ver.tar.gz"
        execute sh autogen.sh
        execute sh configure --prefix="$workspace" --with-pic --with-threaded
        execute make "-j$cpu_threads"
        execute make install
        build_done lcms2 "$ver" "$commit"
    fi
}
