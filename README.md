# imagemagick-build-script
A smart build script for Imagemagick and its additional modules. Automatically locates the latest code available each time the script is run.

### To install ImageMagick use one of the below methods

#### Git Clone
```bash
git clone https://github.com/slyfox1186/imagemagick-build-script.git
cd imagemagick-build-script
sudo bash build-magick.sh
```

```
 -------------------------------
|                               |
| ImageMagick Build Script v1.1 |
|                               |
 -------------------------------

Installing required APT packages
==========================================
[INFO] No missing packages to install or all missing packages are unavailable.

Building magick-libs - version 7.1.1-29
==========================================
$ alien -d ./magick-libs-7.1.1-29.rpm
$ dpkg -i ./imagemagick-libs_7.1.1-30_amd64.deb

Building m4 - version latest
==========================================
Downloading "https://ftp.gnu.org/gnu/m4/m4-latest.tar.xz" saving as "m4-latest.tar.xz"
Download Completed
File extracted: m4-latest.tar.xz

$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --disable-nls --enable-c++ --enable-threads=posix
$ make -j32
$ make install

Building autoconf - version latest
==========================================
Downloading "http://ftp.gnu.org/gnu/autoconf/autoconf-latest.tar.xz" saving as "autoconf-latest.tar.xz"
Download Completed
File extracted: autoconf-latest.tar.xz

$ autoreconf -fi
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace M4=/home/jman/tmp/magick-build-script/workspace/bin/m4
$ make -j32
$ make install

Building libtool - version 2.4.7
==========================================
Downloading "https://ftp.gnu.org/gnu/libtool/libtool-2.4.7.tar.xz" saving as "libtool-2.4.7.tar.xz"
Download Completed
File extracted: libtool-2.4.7.tar.xz

$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-pic M4=/home/jman/tmp/magick-build-script/workspace/bin/m4
$ make -j32
$ make install

Building pkg-config - version 0.29.2
==========================================
Downloading "https://pkgconfig.freedesktop.org/releases/pkg-config-0.29.2.tar.gz" saving as "pkg-config-0.29.2.tar.gz"
Download Completed
File extracted: pkg-config-0.29.2.tar.gz

$ autoconf
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-pc-path=/home/jman/tmp/magick-build-script/workspace/lib64/pkgconfig:/home/jman/tmp/magick-build-script/workspace/lib/x86_64-linux-gnu/pkgconfig:/home/jman/tmp/magick-build-script/workspace/lib/pkgconfig:/home/jman/tmp/magick-build-script/workspace/share/pkgconfig:/usr/local/lib64/pkgconfig:/usr/local/lib/x86_64-linux-gnu/pkgconfig:/usr/local/lib/pkgconfig:/usr/local/share/pkgconfig:/usr/lib64/pkgconfig:/usr/lib/pkgconfig:/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/share/pkgconfig:/lib64/pkgconfig:/lib/x86_64-linux-gnu/pkgconfig:/lib/pkgconfig CFLAGS=-I/home/jman/tmp/magick-build-script/workspace/include LDFLAGS=-L/home/jman/tmp/magick-build-script/workspace/lib64 -L/home/jman/tmp/magick-build-script/workspace/lib
$ make -j32
$ make install

Building zlib - version 1.3.1
==========================================
Downloading "https://github.com/madler/zlib/releases/download/v1.3.1/zlib-1.3.1.tar.gz" saving as "zlib-1.3.1.tar.gz"
Download Completed
File extracted: zlib-1.3.1.tar.gz

$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace
$ make -j32
$ make install

Building libtiff - version 4.6.0
==========================================
Downloading "https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/v4.6.0" saving as "libtiff-4.6.0.tar.gz"
Download Completed
File extracted: libtiff-4.6.0.tar.gz

$ ./autogen.sh
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --enable-cxx --with-pic
$ make -j32
$ make install

Building jpeg-turbo-git - version 575eddd
==========================================
Cloning completed: 575eddd
$ cmake -S . -DCMAKE_INSTALL_PREFIX=/home/jman/tmp/magick-build-script/workspace -DCMAKE_BUILD_TYPE=Release -DENABLE_SHARED=ON -DENABLE_STATIC=ON -G Ninja -Wno-dev
$ ninja -j32
$ ninja -j32 install

Building libfpx-git - version 9b547af
==========================================
Cloning completed: 9b547af
$ autoreconf -fi
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-pic
$ make -j32
$ make install

Building ghostscript - version gs10021
==========================================
Downloading "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10021/ghostscript-10.02.1.tar.xz" saving as "ghostscript-10.02.1.tar.xz"
Download Completed
File extracted: ghostscript-10.02.1.tar.xz

$ ./autogen.sh
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-libiconv=native
$ make -j32
$ make install

Building libpng - version 1.6.43
==========================================
Downloading "https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.43.tar.gz" saving as "libpng-1.6.43.tar.gz"
Download Completed
File extracted: libpng-1.6.43.tar.gz

$ autoreconf -fi
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-pic
$ make -j32
$ make install

Building libwebp-git - version 1.3.2
==========================================
Cloning completed: 1.3.2
$ autoreconf -fi
$ cmake -B build -DCMAKE_INSTALL_PREFIX=/home/jman/tmp/magick-build-script/workspace -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DZLIB_INCLUDE_DIR=/home/jman/tmp/magick-build-script/workspace/include -DWEBP_BUILD_ANIM_UTILS=OFF -DWEBP_BUILD_CWEBP=ON -DWEBP_BUILD_DWEBP=ON -DWEBP_BUILD_EXTRAS=OFF -DWEBP_BUILD_VWEBP=OFF -DWEBP_ENABLE_SWAP_16BIT_CSP=OFF -DWEBP_LINK_STATIC=ON -G Ninja -Wno-dev
$ ninja -j32 -C build
$ ninja -C build install

Building freetype - version 2.13.2
==========================================
Downloading "https://gitlab.freedesktop.org/freetype/freetype/-/archive/VER-2-13-2/freetype-VER-2-13-2.tar.bz2" saving as "freetype-2.13.2.tar.bz2"
Download Completed
File extracted: freetype-2.13.2.tar.bz2

$ ./autogen.sh
$ meson setup build --prefix=/home/jman/tmp/magick-build-script/workspace --buildtype=release --default-library=static --strip -Dharfbuzz=disabled -Dpng=disabled -Dbzip2=disabled -Dbrotli=disabled -Dzlib=disabled -Dtests=disabled
$ ninja -j32 -C build
$ ninja -C build install

Building libxml2 - version 2.12.0
==========================================
Downloading "https://gitlab.gnome.org/GNOME/libxml2/-/archive/v2.12.0/libxml2-v2.12.0.tar.bz2" saving as "libxml2-2.12.0.tar.bz2"
Download Completed
File extracted: libxml2-2.12.0.tar.bz2

$ ./autogen.sh
$ cmake -B build -DCMAKE_INSTALL_PREFIX=/home/jman/tmp/magick-build-script/workspace -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -G Ninja -Wno-dev
$ ninja -j32 -C build
$ ninja -C build install

Building fontconfig - version 2.15.0
==========================================
Downloading "https://gitlab.freedesktop.org/fontconfig/fontconfig/-/archive/2.15.0/fontconfig-2.15.0.tar.bz2" saving as "fontconfig-2.15.0.tar.bz2"
Download Completed
File extracted: fontconfig-2.15.0.tar.bz2

$ ./autogen.sh --noconf
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --disable-docbook --disable-docs --disable-shared --disable-nls --enable-iconv --enable-libxml2 --enable-static --with-arch=x86_64 --with-libiconv-prefix=/usr --with-pic
$ make -j32
$ make install

Building c2man-git - version 577ed40
==========================================
Cloning completed: 577ed40
$ ./Configure -desO -D bin=/home/jman/tmp/magick-build-script/workspace/bin -D cc=/usr/bin/cc -D d_gnu=/usr/lib/x86_64-linux-gnu -D gcc=/usr/bin/gcc -D installmansrc=/home/jman/tmp/magick-build-script/workspace/share/man -D ldflags=-L/home/jman/tmp/magick-build-script/workspace/lib -DLIBXML_STATIC -D libpth=/usr/lib64 /usr/lib /lib64 /lib -D locincpth=/home/jman/tmp/magick-build-script/workspace/include /usr/local/include /usr/include -D loclibpth=/home/jman/tmp/magick-build-script/workspace/lib64 /home/jman/tmp/magick-build-script/workspace/lib /usr/local/lib64 /usr/local/lib -D osname=Debian -D prefix=/home/jman/tmp/magick-build-script/workspace -D privlib=/home/jman/tmp/magick-build-script/workspace/lib/c2man -D privlibexp=/home/jman/tmp/magick-build-script/workspace/lib/c2man
$ make depend
$ make -j32
$ make install

Building fribidi - version 1.0.13
==========================================
Downloading "https://github.com/fribidi/fribidi/archive/refs/tags/v1.0.13.tar.gz" saving as "fribidi-1.0.13.tar.gz"
Download Completed
File extracted: fribidi-1.0.13.tar.gz

$ autoreconf -fi
$ meson setup build --prefix=/home/jman/tmp/magick-build-script/workspace --buildtype=release --default-library=static --strip -Ddocs=false -Dtests=false
$ ninja -j32 -C build
$ ninja -C build install

Building harfbuzz - version 8.3.0
==========================================
Downloading "https://github.com/harfbuzz/harfbuzz/archive/refs/tags/8.3.0.tar.gz" saving as "harfbuzz-8.3.0.tar.gz"
Download Completed
File extracted: harfbuzz-8.3.0.tar.gz

$ ./autogen.sh
$ meson setup build --prefix=/home/jman/tmp/magick-build-script/workspace --buildtype=release --default-library=static --strip -Dbenchmark=disabled -Dcairo=disabled -Ddocs=disabled -Dglib=disabled -Dgobject=disabled -Dicu=disabled -Dintrospection=disabled -Dtests=disabled
$ ninja -j32 -C build
$ ninja -C build install

Building raqm - version 0.10.1
==========================================
Downloading "https://codeload.github.com/host-oman/libraqm/tar.gz/refs/tags/v0.10.1" saving as "raqm-0.10.1.tar.gz"
Download Completed
File extracted: raqm-0.10.1.tar.gz

$ meson setup build --prefix=/home/jman/tmp/magick-build-script/workspace --includedir=/home/jman/tmp/magick-build-script/workspace/include --buildtype=release --default-library=static --strip -Ddocs=false
$ ninja -j32 -C build
$ ninja -C build install

Building jemalloc - version 5.3.0
==========================================
Downloading "https://github.com/jemalloc/jemalloc/archive/refs/tags/5.3.0.tar.gz" saving as "jemalloc-5.3.0.tar.gz"
Download Completed
File extracted: jemalloc-5.3.0.tar.gz

$ ./autogen.sh
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --disable-debug --disable-doc --disable-fill --disable-log --disable-prof --disable-stats --enable-autogen --enable-static --enable-xmalloc CFLAGS=-fPIC
$ make -j32
$ make install

Building opencl-sdk-git - version 5.3.0
==========================================
Cloning completed: 2023.12.14
$ cmake -S . -B build -DCMAKE_INSTALL_PREFIX=/home/jman/tmp/magick-build-script/workspace -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF -DBUILD_DOCS=OFF -DBUILD_EXAMPLES=OFF -DOPENCL_SDK_BUILD_SAMPLES=OFF -DOPENCL_SDK_TEST_SAMPLES=OFF -DCMAKE_C_FLAGS=-g -O3 -march=native -DNOLIBTOOL -DCMAKE_CXX_FLAGS=-g -O3 -march=native -DOPENCL_HEADERS_BUILD_CXX_TESTS=OFF -DOPENCL_ICD_LOADER_BUILD_SHARED_LIBS=ON -DOPENCL_SDK_BUILD_OPENGL_SAMPLES=OFF -DOPENCL_SDK_BUILD_SAMPLES=OFF -DOPENCL_SDK_TEST_SAMPLES=OFF -DTHREADS_PREFER_PTHREAD_FLAG=ON -G Ninja -Wno-dev
$ ninja -j32 -C build
$ ninja -C build install

Building openjpeg - version 2.5.2
==========================================
Downloading "https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/v2.5.2" saving as "openjpeg-2.5.2.tar.gz"
Download Completed
File extracted: openjpeg-2.5.2.tar.gz

$ cmake -B build -DCMAKE_INSTALL_PREFIX=/home/jman/tmp/magick-build-script/workspace -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE -DBUILD_SHARED_LIBS=ON -DBUILD_TESTING=OFF -DBUILD_THIRDPARTY=ON -G Ninja -Wno-dev
$ ninja -j32 -C build
$ ninja -C build install

Building lcms2 - version 2.16
==========================================
Downloading "https://github.com/mm2/Little-CMS/archive/refs/tags/lcms2.16.tar.gz" saving as "lcms2-2.16.tar.gz"
Download Completed
File extracted: lcms2-2.16.tar.gz

$ ./autogen.sh
$ ./configure --prefix=/home/jman/tmp/magick-build-script/workspace --with-pic --with-threaded
$ make -j32
$ make install

Building dejavu-fonts-git - version 9b5d1b2
==========================================
Cloning completed: 9b5d1b2
$ ln -sf /home/jman/tmp/magick-build-script/packages/fontconfig-2.15.0/fc-lang resources/fc-lang
$ make -j32 full-ttf

 -------------------
|                   |
| Build ImageMagick |
|                   |
 -------------------

Building imagemagick-git - version 7.1.1-29
==========================================
Cloning completed: 7.1.1-29
$ autoreconf -fi
$ ../configure --prefix=/usr/local --enable-ccmalloc --enable-delegate-build --enable-hdri --enable-hugepages --enable-legacy-support --enable-opencl --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu --with-dmalloc --with-fontpath=/usr/share/fonts --with-fpx --with-gslib --with-gvc --with-heic --with-jemalloc --with-modules --with-perl --with-pic --with-pkgconfigdir=/home/jman/tmp/magick-build-script/workspace/lib/pkgconfig --with-png --with-quantum-depth=16 --with-rsvg --with-tcmalloc --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35 --with-utilities --without-autotrace CFLAGS=-g -O3 -march=native -DNOLIBTOOL -DCL_TARGET_OPENCL_VERSION=300
$ make -j32
$ make install

[INFO] ImageMagick's new version is:

Version: ImageMagick 7.1.1-30 (Beta) Q16-HDRI x86_64 53bbd00:20240302 https://imagemagick.org
Copyright: (C) 1999 ImageMagick Studio LLC
License: https://imagemagick.org/script/license.php
Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5) TCMalloc
Delegates (built-in): bzlib cairo djvu fontconfig freetype gslib heic jbig jng jp2 jpeg jxl lcms lqr ltdl lzma openexr png ps raqm raw rsvg tiff webp wmf x xml zlib zstd
Compiler: gcc (12.2)

========================================================
        Do you want to clean up the build files?
========================================================

[1] Yes
[2] No

Your choices are (1 or 2):
```
