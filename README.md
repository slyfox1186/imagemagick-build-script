# imagemagick-build-script
A smart build script for ImageMagick and its additional modules. Automatically locates the latest code available each time the script is run.

### To install ImageMagick use one of the below methods

#### Git Clone
```bash
git clone https://github.com/slyfox1186/imagemagick-build-script.git
cd imagemagick-build-script
sudo bash build-magick.sh
```

Set a specific parallel worker count:
```bash
sudo bash build-magick.sh --workers 24
sudo bash build-magick.sh -w 24
```

#### Output
```text
 -------------------------------
|                               |
| ImageMagick Build Script v1.2.0 |
|                               |
 -------------------------------

[INFO] Parallel worker count manually set to 24.

Installing required APT packages
==========================================
[INFO] No missing packages to install or all missing packages are unavailable.

Building m4 - version latest
==========================================
[INFO] Downloading "https://ftp.gnu.org/gnu/m4/m4-latest.tar.xz" saving as "m4-latest.tar.xz"
[INFO] File extracted: m4-latest.tar.xz

$ sh configure --prefix=/home/jman/tmp/magick-build-script/workspace --enable-c++ --enable-threads=posix
$ make -j24
$ make install

Building dejavu-fonts - version 9b5d1b2
==========================================
[INFO] Cloning repo: dejavu-fonts
[INFO] Cloning completed: 9b5d1b2
$ exec_root cp -fr ./ /usr/share/fonts/truetype/

 -------------------
|                   |
| Build ImageMagick |
|                   |
 -------------------

Building imagemagick - version 7.1.2-16
==========================================
[INFO] Downloading "https://imagemagick.org/archive/releases/ImageMagick-7.1.2-16.tar.lz" saving as "imagemagick-7.1.2-16.tar.lz"
$ autoreconf -fi
$ sh ../configure --prefix=/usr/local --enable-delegate-build --enable-hdri --enable-hugepages --enable-legacy-support --enable-opencl --with-fontpath=/usr/share/fonts/truetype --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu --with-gs-font-dir=/usr/share/fonts/ghostscript --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35 --with-fpx --with-gslib --with-gvc --with-heic --with-jemalloc --with-modules --with-perl --with-pic --with-pkgconfigdir=/home/jman/tmp/magick-build-script/workspace/lib/pkgconfig --with-png --with-quantum-depth=16 --with-rsvg --with-utilities --without-autotrace CFLAGS=-O3 -fPIC -pipe -march=native -fstack-protector-strong -DCL_TARGET_OPENCL_VERSION=300 CXXFLAGS=-O3 -fPIC -pipe -march=native -fstack-protector-strong -DCL_TARGET_OPENCL_VERSION=300
$ make -j24
$ exec_root make install

[INFO] ImageMagick's new version is:
```
