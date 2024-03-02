#!/usr/bin/env bash
# shellcheck disable=SC1091,SC2034,SC2046,SC2066,SC2068,SC2086,SC2119,SC2162,SC2181

##  Script Version: 1.1
##  Updated: 02.20.24
##  GitHub: https://github.com/slyfox1186/imagemagick-build-script
##  Purpose: Build ImageMagick 7 from the source code obtained from ImageMagick's official GitHub repository
##  Function: ImageMagick is the leading open-source command line image processor. It can blur, sharpen, warp,
##            reduce total file size, ect... The possibilities are vast
##  Method: The script will search GitHub for the latest released version and upon execution will import the
##            information into the script.
##  Added:
##          - Ubuntu OS support for versions, 22.04 23.04, 23.10, 24.04
##          - Debian OS support for versions, 11 & 12
##          - A browser user-agent string to the curl command
##          - A CPPFLAGS variable to ImageMagick's configure script
##          - A case command to determine the required libtool version based on the active OS
##          - Autotrace for Ubuntu (18/20/22).04 and Debian 10/11
##          - LCMS Support
##          - Deja-Vu Fonts
##          - APT package
##  Fixed:
##          - error with the pkg-config location when building ImageMagick
##          - error in the variable PKG_CONFIG_PATH
##  Removed:
##          - unnecessary commands in imagemagick's configure script

if [ "$EUID" -ne "0" ]; then
    echo "This script must be run with root/sudo"
    echo
    exit 1
fi

# SET GLOBAL VARIABLES
progname="${0}"
script_ver=1.1
cwd="$PWD/magick-build-script"
packages="$cwd/packages"
workspace="$cwd/workspace"
regex_string='(rc|RC|Rc|rC|alpha|beta|master|pre)+[0-9]*$'
debug=OFF # CHANGE THIS VARIABLE TO "ON" FOR HELP WITH TROUBLESHOOTING UNEXPECTED ISSUES DURING THE BUILD

# Pre-defined color variables
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# ANNOUNCE THE BUILD HAS BEGUN
box_out_banner_header() {
    input_char=$(echo "$@" | wc -c)
    line=$(for i in $(seq 0 $input_char); do printf "-"; done)
    tput bold
    line="$(tput setaf 3)$line"
    space="${line//-/ }"
    echo " $line"
    printf "|" ; echo -n "$space" ; printf "%s\n" "|";
    printf "| " ;tput setaf 4; echo -n "$@"; tput setaf 3 ; printf "%s\n" " |";
    printf "|" ; echo -n "$space" ; printf "%s\n" "|";
    echo " $line"
    tput sgr 0
}
box_out_banner_header "ImageMagick Build Script v$script_ver"

# CREATE OUTPUT DIRECTORIES
mkdir -p "$packages" "$workspace"

# SET THE COMPILERS TO USE AND THE COMPILER OPTIMIZATION FLAGS
CC=gcc
CXX=g++
CFLAGS="-g -O3 -march=native"
CXXFLAGS="-g -O3 -march=native"
EXTRALIBS="-ldl -lm -lpthread -lz"
LDFLAGS="-L$workspace/lib"
CPPFLAGS="-I$workspace/include"
export CC CFLAGS CXX CXXFLAGS

# SET THE AVAILABLE CPU COUNT FOR PARALLEL PROCESSING (SPEEDS UP THE BUILD PROCESS)
if [ -f /proc/cpuinfo ]; then
    cpu_threads=$(grep --count ^processor /proc/cpuinfo)
else
    cpu_threads=$(nproc --all)
fi

# SET THE PATH
if [ -d /usr/lib/ccache/bin ]; then
    ccache_dir=/usr/lib/ccache/bin
else
    ccache_dir=/usr/lib/ccache
fi

# Set the path variable
PATH="$ccache_dir:$workspace/bin:$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export PATH

# Set the pkg_config_path variable
PKG_CONFIG_PATH="\
$workspace/lib64/pkgconfig:\
$workspace/lib/x86_64-linux-gnu/pkgconfig:\
$workspace/lib/pkgconfig:\
$workspace/share/pkgconfig:\
/usr/local/lib64/pkgconfig:\
/usr/local/lib/x86_64-linux-gnu/pkgconfig:\
/usr/local/lib/pkgconfig:\
/usr/local/share/pkgconfig:\
/usr/lib64/pkgconfig:\
/usr/lib/pkgconfig:\
/usr/lib/x86_64-linux-gnu/pkgconfig:\
/usr/share/pkgconfig:\
/lib64/pkgconfig:\
/lib/x86_64-linux-gnu/pkgconfig:\
/lib/pkgconfig\
"
export PKG_CONFIG_PATH

exit_fn() {
    echo
    echo -e "${GREEN}[INFO]${NC} Make sure to ${YELLOW}star${NC} this repository to show your support!"
    echo -e "${GREEN}[INFO]${NC} https://github.com/slyfox1186/script-repo"
    echo
    exit 0
}

fail() {
    echo
    echo -e "${RED}[ERROR]${NC} $1"
    echo
    echo -e "${GREEN}[INFO]${NC} For help or to report a bug create an issue at: https://github.com/slyfox1186/script-repo/issues"
    echo
    exit 1
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

cleanup() {
    local choice

    echo
    echo "========================================================"
    echo "        Do you want to clean up the build files?        "
    echo "========================================================"
    echo
    echo "[1] Yes"
    echo "[2] No"
    echo

    read -p "Your choices are (1 or 2): " choice

    case "$choice" in
        1) rm -fr "$cwd" ;;
        2) return ;;
        *) unset choice
           cleanup
           ;;
    esac
}
execute() {
    echo "$ $*"

    if [ "$debug" = "ON" ]; then
        if ! output=$("$@"); then
            notify-send -t 5000 "Failed to execute: $*" 2>/dev/null
            fail "Failed to execute: $*"
        fi
    else
        if ! output=$("$@" 2>&1); then
            notify-send -t 5000 "Failed to execute: $*" 2>/dev/null
            fail "Failed to execute: $*"
        fi
    fi
}

build() {
    echo
    echo "Building $1 - version $2"
    echo "=========================================="

    if [ -f "$packages/$1.done" ]; then
        if grep -Fx "$2" "$packages/$1.done" >/dev/null; then
            echo "$1 version $2 already built. Remove $packages/$1.done lockfile to rebuild it."
            return 1
        fi
    fi
    return 0
}

build_done() {
    echo "$2" > "$packages/$1.done"
}

download() {
    dl_path="$packages"
    dl_url="$1"
    dl_file="${2:-"${1##*/}"}"

    if [[ "$dl_file" =~ tar. ]]; then
        output_dir="${dl_file%.*}"
        output_dir="${3:-"${output_dir%.*}"}"
    else
        output_dir="${3:-"${dl_file%.*}"}"
    fi

    target_file="$dl_path/$dl_file"
    target_dir="$dl_path/$output_dir"

    if [ -f "$target_file" ]; then
        log "The file \"$dl_file\" is already downloaded."
    else
        log "Downloading \"$dl_url\" saving as \"$dl_file\""
        if ! curl -Lso "$target_file" "$dl_url"; then
            echo
            warn "The script failed to download \"$dl_file\" and will try again in 10 seconds..."
            echo
            sleep 10
            if ! curl -Lso "$target_file" "$dl_url"; then
                fail "The script failed to download \"$dl_file\" twice and will now exit. Line: $LINENO"
            fi
        fi
        log "Download Completed"
    fi

    if [ -d "$target_dir" ]; then
        rm -fr "$target_dir"
    fi

    mkdir -p "$target_dir"

    if [ -n "$3" ]; then
        if ! tar -xf "$target_file" -C "$target_dir" 2>/dev/null >/dev/null; then
            rm "$target_file"
            fail "The script failed to extract \"$dl_file\" so it was deleted. Please re-run the script. Line: $LINENO"
        fi
    else
        if ! tar -xf "$target_file" -C "$target_dir" --strip-components 1 2>/dev/null >/dev/null; then
            rm "$target_file"
            fail "The script failed to extract \"$dl_file\" so it was deleted. Please re-run the script. Line: $LINENO"
        fi
    fi

    echo "File extracted: $dl_file"
    echo

    cd "$target_dir" || fail "Unable to change the working directory to \"$target_dir\" Line: $LINENO"
}

git_caller() {
    git_url="$1"
    repo_name="$2"
    recurse_flag=""
    if [[ "$3" == "recurse" ]]; then
        recurse_flag=1
    else
        version=$(git_clone "$git_url" "$repo_name")
    fi
    version="${version//Cloning completed: /}"
}

git_clone() {
    local repo_url="$1"
    local repo_name="${2:-"${1##*/}"}"
    local repo_name="${repo_name//\./-}"
    local repo_flag="$3"
    local target_directory="$packages/$repo_name"
    local version

    # Try to get the latest tag
    version=$(git ls-remote --tags "$repo_url" |
              awk -F'/' '/\/v?[0-9]+\.[0-9]+(\.[0-9]+)?(-[0-9]+)?(\^\{\})?$/ {
                  tag = $3;
                  sub(/^v/, "", tag);
                  print tag
              }' |
              grep -v '\^{}' |
              sort -rV |
              head -n1
         )

        # If no tags found, use the latest commit hash as the version
        if [[ -z "$version" ]]; then
            version=$(git ls-remote "$repo_url" |
                      grep "HEAD" |
                      awk '{print substr($1,1,7)}'
                 )
            if [[ -z "$version" ]]; then
                version="unknown"
            fi
        fi
    fi

    [[ -f "$packages/$repo_name.done" ]] && store_prior_version=$(cat "$packages/$repo_name.done")

    if [[ ! "$version" == "$store_prior_version" ]]; then
        if [[ "$recurse_flag" -eq 1 ]]; then
            recurse="--recursive"
        elif [[ -n "$3" ]]; then
            output_directory="$download_path/$3"
            target_directory="$output_directory"
        fi
        [[ -d "$target_directory" ]] && rm -fr "$target_directory"
        # Clone the repository
        if ! git clone --depth 1 $recurse -q "$repo_url" "$target_directory"; then
            echo
            echo -e "${RED}[ERROR]${NC} Failed to clone \"$target_directory\". Second attempt in 10 seconds..."
            echo
            sleep 10
            if ! git clone --depth 1 $recurse -q "$repo_url" "$target_directory"; then
                fail "Failed to clone \"$target_directory\". Exiting script. Line: $LINENO"
            fi
        fi
        cd "$target_directory" || fail "Failed to cd into \"$target_directory\". Line: $LINENO"
    fi

    echo "Cloning completed: $version"
    return 0
}

show_ver_fn() {
    echo
    log "ImageMagick's new version is:"
    echo
    if ! magick -version 2>/dev/null; then
        fail "Failure to execute the command: magick -version. Line: $LINENO"
    fi
}

github_repo() {
    # Initial count
    local count curl_results git_repo git_url
    git_repo="$1"
    git_url="$2"
    count=1

    # Loop until the condition is met or a maximum limit is reached
    while [ $count -le 10 ]  # You can set an upper limit to prevent an infinite loop
    do
        curl_results=$(curl -fsSL "https://github.com/$git_repo/$git_url")

        # Extract the specific line
        line=$(echo "$curl_results" | grep -o 'href="[^"]*\.tar\.gz"' | sed -n "${count}p")

        # Check if the line matches the pattern (version without 'RC'/'rc')
        if echo "$line" | grep -qoP '(\d+\.\d+\.\d+(-\d+)?)(?=.tar.gz)'; then
            # Extract and print the version number
            version=$(echo "$line" | grep -oP '(\d+\.\d+\.\d+(-\d+)?)(?=.tar.gz)')
            break
        else
            # Increment the count if no match is found
            ((count++))
        fi
    done

    # Check if a version was found
    if [ $count -gt 10 ]; then
        fail "No matching version found without RC/rc suffix."
    fi
}

gitlab_freedesktop_repo() {
    local count repo
    repo="$1"
    count=0
    version=""

    while true
    do
        if curl_results=$(curl -m 10 -sSL "https://gitlab.freedesktop.org/api/v4/projects/$repo/repository/tags"); then
            version=$(echo "$curl_results" | jq -r ".[$count].name")
            version="${version#v}"

            # Check if version contains "RC" and skip it
            if [[ $version =~ $regex_string ]]; then
                ((count++))
            else
                break  # Exit the loop when a non-RC version is found
            fi
        else
            fail "Failed to fetch data from GitLab API."
        fi
    done
}

gitlab_gnome_repo() {
    local count repo url

    repo="$1"
    url="$2"
    count=0
    version=""

    [[ -z "$repo" ]] && fail "Repository name is required."

    if curl_results=$(curl -sSL "https://gitlab.gnome.org/api/v4/projects/$repo/repository/$url"); then
        version=$(echo "$curl_results" | jq -r '.[0].name')
        version="${version#v}"
    fi

    # DENY INSTALLING A RELEASE CANDIDATE
    while [[ $version =~ $regex_string ]]; do
        if curl_results=$(curl -sSL "https://gitlab.gnome.org/api/v4/projects/$repo/repository/$url"); then
            version=$(echo "$curl_results" | jq -r ".[$count].name")
            version="${version#v}"
        fi
        ((count++))
    done
}

find_git_repo() {
    local url="$1"
    local git_repo_type="$2"
    local url_action="$3"

    case "$git_repo_type" in
        1) set_repo="github_repo" ;;
        2) set_repo="gitlab_freedesktop_repo" ;;
        3) set_repo="gitlab_gnome_repo" ;;
        *) fail "Error: Could not detect the variable \"\$git_repo_type\" in the function \"find_git_repo\". (Line: $LINENO)"
    esac

    case "$url_action" in
        T) set_action="tags" ;;
        *) set_action="$3" ;;
    esac

    "$set_repo" "$url" "$set_action" 2>/dev/null
}

# PRINT THE OPTIONS AVAILABLE WHEN MANUALLY RUNNING THE SCRIPT
pkgs_fn() {
    local missing_packages pkg pkgs available_packages unavailable_packages

    pkgs=(
        $1 alien autoconf autoconf-archive binutils bison build-essential
        cmake curl dbus-x11 flex fontforge git gperf imagemagick jq libc6
        libcamd2 libcpu-features-dev libdmalloc-dev libdmalloc5 libfont-ttf-perl
        libfontconfig-dev libgc-dev libgc1 libgegl-0.4-0 libgegl-common libgimp2.0
        libgimp2.0-dev libgl2ps-dev libglib2.0-dev libgs-dev libheif-dev libhwy-dev
        libjemalloc-dev libjemalloc2 libjxl-dev libnotify-bin libpstoedit-dev
        librust-jpeg-decoder-dev librust-malloc-buf-dev libsharp-dev libticonv-dev
        libtool libtool-bin libyuv-dev libyuv-utils libyuv0 m4 meson nasm ninja-build
        python3-dev yasm zlib1g-dev php-dev
)

    # Initialize arrays for missing, available, and unavailable packages
    missing_packages=()
    available_packages=()
    unavailable_packages=()

    # Loop through the array to find missing packages
    for pkg in "${pkgs[@]}"
    do
        if ! dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
            missing_packages+=("$pkg")
        fi
    done

    # Check availability of missing packages and categorize them
    for pkg in "${missing_packages[@]}"
    do
        if apt-cache show "$pkg" >/dev/null 2>&1; then
            available_packages+=("$pkg")
        else
            unavailable_packages+=("$pkg")
        fi
    done

    # Print unavailable packages
    if [ "${#unavailable_packages[@]}" -gt 0 ]; then
        log "Unavailable packages: ${unavailable_packages[*]}"
    fi

    # Install available missing packages
    if [ "${#available_packages[@]}" -gt 0 ]; then
        log "Installing available missing packages: ${available_packages[*]}"
        apt install "${available_packages[@]}"
    else
        log "No missing packages to install or all missing packages are unavailable."
    fi
}

install_autotrace_fn() {
    if build "autotrace" "0.40.0-20200219"; then
        curl -Lso "$packages/deb-files/autotrace-0.40.0-20200219.deb" "https://github.com/autotrace/autotrace/releases/download/travis-20200219.65/autotrace_0.40.0-20200219_all.deb"
        cd "$packages/deb-files" || exit 1
        execute apt -y install ./autotrace-0.40.0-20200219.deb
        build_done "autotrace" "0.40.0-20200219"
    fi
}

#
# INSTALL APT LIBRARIES
#

    echo
    echo "Installing required APT packages"
    echo "=========================================="

debian_ver_fn() {
    local pkgs_bookworm pkgs_bullseye pkgs_common pkgs_debian

    pkgs_bullseye="libvmmalloc1 libvmmalloc-dev"

    case "$VER" in
        11)     pkgs_fn $pkgs_bullseye ;;
        12)     pkgs_fn ;;
        *)      fail "Could not detect the Debian version. Line: $LINENO" ;;
    esac
}

if command -v lsb_release &>/dev/null; then
    OS=$(lsb_release -si)
    VER=$(lsb_release -sr)
elif [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$NAME
    VER=$VERSION_ID
else
    fail "Failed to define the \$OS and/or \$VER variables. Line: $LINENO"
fi

get_os_ver_fn() {
# DISCOVER WHAT VERSION OF LINUX WE ARE RUNNING (DEBIAN OR UBUNTU)
    case "$OS" in
        Arch)       return ;;
        Debian)     debian_ver_fn ;;
        Ubuntu)     pkgs_fn ;;
        *)          fail "Could not detect the OS architecture. Line: $LINENO" ;;
    esac
}

# GET THE OS NAME
get_os_ver_fn

# INSTALL OFFICIAL IMAGEMAGICK LIBS
find_git_repo "imagemagick/imagemagick" "1" "T"
if build "magick-libs" "$version"; then
    if [ ! -d "$packages/deb-files" ]; then
        mkdir -p "$packages/deb-files"
    fi
    cd "$packages/deb-files" || exit 1
    if ! curl -Lso "magick-libs-$version.rpm" "https://imagemagick.org/archive/linux/CentOS/x86_64/ImageMagick-libs-$version.x86_64.rpm"; then
        fail "Failed to download the magick-libs file. Line: $LINENO"
    fi
    execute alien -d ./*.rpm || fail "Error: alien -d ./*.rpm Line: $LINENO"
    execute dpkg -i ./*.deb
    build_done "magick-libs" "$version"
fi

# INSTALL AUTOTRACE
case "$OS" in
    Ubuntu)
                install_autotrace_fn
                autotrace_flag=true
                ;;
esac
if [[ "$autotrace_flag" == "true" ]]; then
    set_autotrace="--with-autotrace"
else
    set_autotrace="--without-autotrace"
fi

# INSTALL COMPOSER TO COMPILE GRAPHVIZ
if [ ! -f "/usr/bin/composer" ]; then
    EXPECTED_CHECKSUM=$(php -r 'copy("https://composer.github.io/installer.sig", "php://stdout");')
    php -r "copy('https://getcomposer.org/installer', 'composer-setup.php');"
    ACTUAL_CHECKSUM=$(php -r "echo hash_file('sha384', 'composer-setup.php');")

    if [ "$EXPECTED_CHECKSUM" != "$ACTUAL_CHECKSUM" ]; then
        >&2 echo "ERROR: Invalid installer checksum"
        rm "composer-setup.php"
        return 1
    fi
    if ! php composer-setup.php --install-dir="/usr/bin" --filename=composer --quiet; then
        fail "Failed to install: /usr/bin/composer. Line: $LINENO"
    fi
    rm "composer-setup.php"
fi

# BEGIN BUILDING FROM SOURCE CODE
if build "m4" "latest"; then
    download "https://ftp.gnu.org/gnu/m4/m4-latest.tar.xz"
    execute ./configure --prefix="$workspace" \
                        --disable-nls \
                        --enable-c++ \
                        --enable-threads=posix
    execute make "-j$cpu_threads"
    execute make install
    build_done "m4" "latest"
fi

if build "autoconf" "latest"; then
    download "http://ftp.gnu.org/gnu/autoconf/autoconf-latest.tar.xz"
    execute autoreconf -fi
    execute ./configure --prefix="$workspace" M4="$workspace/bin/m4"
    execute make "-j$cpu_threads"
    execute make install
    build_done "autoconf" "latest"
fi

if build "libtool" "2.4.7"; then
    download "https://ftp.gnu.org/gnu/libtool/libtool-2.4.7.tar.xz"
    execute ./configure --prefix="$workspace" --with-pic M4="$workspace"/bin/m4
    execute make "-j$cpu_threads"
    execute make install
    build_done "libtool" "2.4.7"
fi

if build "pkg-config" "0.29.2"; then
    download "https://pkgconfig.freedesktop.org/releases/pkg-config-0.29.2.tar.gz"
    execute autoconf
    execute ./configure --prefix="$workspace" \
                        --with-pc-path="$PKG_CONFIG_PATH" \
                        CFLAGS="-I$workspace/include" \
                        LDFLAGS="-L$workspace/lib64 -L$workspace/lib"
    execute make "-j$cpu_threads"
    execute make install
    build_done "pkg-config" "0.29.2"
fi

find_git_repo "madler/zlib" "1" "T"
if build "zlib" "$version"; then
    download "https://github.com/madler/zlib/releases/download/v$version/zlib-$version.tar.gz"
    execute ./configure --prefix="$workspace"
    execute make "-j$cpu_threads"
    execute make install
    build_done "zlib" "$version"
fi

find_git_repo "libsdl-org/libtiff" "1" "T"
if build "libtiff" "$version"; then
    download "https://codeload.github.com/libsdl-org/libtiff/tar.gz/refs/tags/v$version" "libtiff-$version.tar.gz"
    execute ./autogen.sh
    execute ./configure --prefix="$workspace" --enable-cxx --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "libtiff" "$version"
fi

git_caller "https://github.com/imageMagick/jpeg-turbo.git" "jpeg-turbo-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    execute cmake -S . \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DENABLE_SHARED=ON \
                  -DENABLE_STATIC=ON \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads"
    execute ninja "-j$cpu_threads" install
    save_version=$(build_done "$repo_name" "$version")
    $(build_done "$repo_name" "$version")
fi

git_caller "https://github.com/imageMagick/libfpx.git" "libfpx-git"
if build "$repo_name" "$version"; then
    git_clone "$git_url"
    execute autoreconf -fi
    execute ./configure --prefix="$workspace" --with-pic
    execute make "-j$cpu_threads"
    execute make install
    $(build_done "$repo_name" "$version")
fi

if build "ghostscript" "10.02.1"; then
    download "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10021/ghostscript-10.02.1.tar.xz"
    execute ./autogen.sh
    execute ./configure --prefix="$workspace" --with-libiconv=native
    execute make "-j$cpu_threads"
    execute make install
    build_done "ghostscript" "10.02.1"
fi

if build "libpng" "1.6.43"; then
    download "https://github.com/pnggroup/libpng/archive/refs/tags/v1.6.43.tar.gz" "libpng-1.6.43.tar.gz"
    execute autoreconf -fi
    execute ./configure --prefix="$workspace" --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "libpng" "1.6.43"
fi

git_caller "https://chromium.googlesource.com/webm/libwebp" "libwebp-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    execute autoreconf -fi
    execute cmake -B build \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DBUILD_SHARED_LIBS=ON \
                  -DZLIB_INCLUDE_DIR="$workspace/include" \
                  -DWEBP_BUILD_ANIM_UTILS=OFF \
                  -DWEBP_BUILD_CWEBP=ON \
                  -DWEBP_BUILD_DWEBP=ON \
                  -DWEBP_BUILD_EXTRAS=OFF \
                  -DWEBP_BUILD_VWEBP=OFF \
                  -DWEBP_ENABLE_SWAP_16BIT_CSP=OFF \
                  -DWEBP_LINK_STATIC=ON \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    $(build_done "$repo_name" "$version")
fi

find_git_repo "7950" "2"
version="${version#VER-}"
version1="${version//-/.}"
if build "freetype" "$version1"; then
    download "https://gitlab.freedesktop.org/freetype/freetype/-/archive/VER-$version/freetype-VER-$version.tar.bz2" "freetype-$version1.tar.bz2"
    extracmds=("-D"{harfbuzz,png,bzip2,brotli,zlib,tests}"=disabled")
    execute ./autogen.sh
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "freetype" "$version1"
fi

find_git_repo "1665" "3" "T"
if build "libxml2" "2.12.0"; then
    download "https://gitlab.gnome.org/GNOME/libxml2/-/archive/v2.12.0/libxml2-v2.12.0.tar.bz2" "libxml2-2.12.0.tar.bz2"
    CFLAGS+=" -DNOLIBTOOL"
    execute ./autogen.sh
    execute cmake -B build \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DBUILD_SHARED_LIBS=OFF \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "libxml2" "2.12.0"
fi

find_git_repo "890" "2"
fc_dir="$packages/fontconfig-$version"
if build "fontconfig" "$version"; then
    download "https://gitlab.freedesktop.org/fontconfig/fontconfig/-/archive/$version/fontconfig-$version.tar.bz2"
    LDFLAGS+=" -DLIBXML_STATIC"
    sed -i "s|Cflags:|& -DLIBXML_STATIC|" fontconfig.pc.in
    execute ./autogen.sh --noconf
    execute ./configure --prefix="$workspace" \
                        --disable-docbook \
                        --disable-docs \
                        --disable-shared \
                        --disable-nls \
                        --enable-iconv \
                        --enable-libxml2 \
                        --enable-static \
                        --with-arch=$(uname -m) \
                        --with-libiconv-prefix=/usr \
                        --with-pic
    execute make "-j$cpu_threads"
    execute make install
    build_done "fontconfig" "$version"
fi

git_caller "https://github.com/fribidi/c2man.git" "c2man-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    execute ./Configure -desO \
                        -D bin="$workspace/bin" \
                        -D cc="/usr/bin/cc" \
                        -D d_gnu="/usr/lib/x86_64-linux-gnu" \
                        -D gcc="/usr/bin/gcc" \
                        -D installmansrc="$workspace/share/man" \
                        -D ldflags="$LDFLAGS" \
                        -D libpth="/usr/lib64 /usr/lib /lib64 /lib" \
                        -D locincpth="$workspace/include /usr/local/include /usr/include" \
                        -D loclibpth="$workspace/lib64 $workspace/lib /usr/local/lib64 /usr/local/lib" \
                        -D osname="$OS" \
                        -D prefix="$workspace" \
                        -D privlib="$workspace/lib/c2man" \
                        -D privlibexp="$workspace/lib/c2man"
    execute make depend
    execute make "-j$cpu_threads"
    execute make install
    $(build_done "$repo_name" "$version")
fi

find_git_repo "fribidi/fribidi" "1" "T"
if build "fribidi" "$version"; then
    download "https://github.com/fribidi/fribidi/archive/refs/tags/v$version.tar.gz" "fribidi-$version.tar.gz"
    extracmds=("-D"{docs,tests}"=false")
    execute autoreconf -fi
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "fribidi" "$version"
fi

# UBUNTU BIONIC FAILS TO BUILD XML2
if [[ "$VER" != "18.04" ]]; then
    find_git_repo "harfbuzz/harfbuzz" "1" "T"
    if build "harfbuzz" "$version"; then
        download "https://github.com/harfbuzz/harfbuzz/archive/refs/tags/$version.tar.gz" "harfbuzz-$version.tar.gz"
        extracmds=("-D"{benchmark,cairo,docs,glib,gobject,icu,introspection,tests}"=disabled")
        execute ./autogen.sh
    execute meson setup build --prefix="$workspace" \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              "${extracmds[@]}"
        execute ninja "-j$cpu_threads" -C build
        execute ninja -C build install
        build_done "harfbuzz" "$version"
    fi
fi

find_git_repo "host-oman/libraqm" "1" "T"
if build "raqm" "$version"; then
    download "https://codeload.github.com/host-oman/libraqm/tar.gz/refs/tags/v$version" "raqm-$version.tar.gz"
    execute meson setup build --prefix="$workspace" \
                              --includedir="$workspace"/include \
                              --buildtype=release \
                              --default-library=static \
                              --strip \
                              -Ddocs=false
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "raqm" "$version"
fi

find_git_repo "jemalloc/jemalloc" "1" "T"
if build "jemalloc" "$version"; then
    download "https://github.com/jemalloc/jemalloc/archive/refs/tags/$version.tar.gz" "jemalloc-$version.tar.gz"
    execute ./autogen.sh
    execute ./configure --prefix="$workspace" \
                        --disable-debug \
                        --disable-doc \
                        --disable-fill \
                        --disable-log \
                        --disable-prof \
                        --disable-stats \
                        --enable-autogen \
                        --enable-static \
                        --enable-xmalloc
    execute make "-j$cpu_threads"
    execute make install
    build_done "jemalloc" "$version"
fi

git_caller "https://github.com/KhronosGroup/OpenCL-SDK.git" "opencl-sdk-git" "recurse"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    execute cmake \
            -S . \
            -B build \
            -DCMAKE_INSTALL_PREFIX="$workspace" \
            -DCMAKE_BUILD_TYPE=Release \
            -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE \
            -DBUILD_SHARED_LIBS=ON \
            -DBUILD_TESTING=OFF \
            -DBUILD_DOCS=OFF \
            -DBUILD_EXAMPLES=OFF \
            -DOPENCL_SDK_BUILD_SAMPLES=OFF \
            -DOPENCL_SDK_TEST_SAMPLES=OFF \
            -DCMAKE_C_FLAGS="$CFLAGS" \
            -DCMAKE_CXX_FLAGS="$CXXFLAGS" \
            -DOPENCL_HEADERS_BUILD_CXX_TESTS=OFF \
            -DOPENCL_ICD_LOADER_BUILD_SHARED_LIBS=ON \
            -DOPENCL_SDK_BUILD_OPENGL_SAMPLES=OFF \
            -DOPENCL_SDK_BUILD_SAMPLES=OFF \
            -DOPENCL_SDK_TEST_SAMPLES=OFF \
            -DTHREADS_PREFER_PTHREAD_FLAG=ON \
            -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    $(build_done "$repo_name" "$version")
fi

find_git_repo "uclouvain/openjpeg" "1" "T"
if build "openjpeg" "$version"; then
    download "https://codeload.github.com/uclouvain/openjpeg/tar.gz/refs/tags/v$version" "openjpeg-$version.tar.gz"
    execute cmake -B build \
                  -DCMAKE_INSTALL_PREFIX="$workspace" \
                  -DCMAKE_BUILD_TYPE=Release \
                  -DCMAKE_POSITION_INDEPENDENT_CODE=TRUE \
                  -DBUILD_SHARED_LIBS=ON \
                  -DBUILD_TESTING=OFF \
                  -DBUILD_THIRDPARTY=ON \
                  -G Ninja -Wno-dev
    execute ninja "-j$cpu_threads" -C build
    execute ninja -C build install
    build_done "openjpeg" "$version"
fi

find_git_repo "mm2/Little-CMS" "1" "T"
if build "lcms2" "$version"; then
    download "https://github.com/mm2/Little-CMS/archive/refs/tags/lcms$version.tar.gz" "lcms2-$version.tar.gz"
    execute ./autogen.sh
    execute ./configure --prefix="$workspace" \
                        --with-pic \
                        --with-threaded
    execute make "-j$cpu_threads"
    execute make install
    build_done "lcms2" "$version"
fi

git_caller "https://github.com/dejavu-fonts/dejavu-fonts.git" "dejavu-fonts-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    wget -cqP "resources" "http://www.unicode.org/Public/UNIDATA/UnicodeData.txt" "http://www.unicode.org/Public/UNIDATA/Blocks.txt"
    execute ln -sf "$fc_dir/fc-lang" "resources/fc-lang"
    execute make "-j$cpu_threads" full-ttf
    $(build_done "$repo_name" "$version")
fi

# BEGIN BUILDING IMAGEMAGICK
echo
box_out_banner_magick() {
    input_char=$(echo "$@" | wc -c)
    line=$(for i in $(seq 0 $input_char); do printf "-"; done)
    tput bold
    line="$(tput setaf 3)$line"
    space="${line//-/ }"
    echo " $line"
    printf "|" ; echo -n "$space" ; printf "%s\n" "|";
    printf "| " ;tput setaf 4; echo -n "$@"; tput setaf 3 ; printf "%s\n" " |";
    printf "|" ; echo -n "$space" ; printf "%s\n" "|";
    echo " $line"
    tput sgr 0
}
box_out_banner_magick "Build ImageMagick"

git_caller "https://github.com/imagemagick/imagemagick.git" "imagemagick-git"
if build "$repo_name" "${version//\$ /}"; then
    git_clone "$git_url"
    execute autoreconf -fi
    mkdir build; cd build || exit 1
    execute ../configure --prefix=/usr/local \
                         --enable-ccmalloc \
                         --enable-delegate-build \
                         --enable-hdri \
                         --enable-hugepages \
                         --enable-legacy-support \
                         --enable-opencl \
                         --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu \
                         --with-dmalloc \
                         --with-fontpath=/usr/share/fonts \
                         --with-fpx \
                         --with-gslib \
                         --with-gvc \
                         --with-heic \
                         --with-jemalloc \
                         --with-modules \
                         --with-perl \
                         --with-pic \
                         --with-png \
                         --with-pkgconfigdir="$workspace/lib/pkgconfig" \
                         --with-quantum-depth=16 \
                         --with-rsvg \
                         --with-tcmalloc \
                         --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35 \
                         --with-utilities \
                         "$set_autotrace" \
                         CFLAGS="$CFLAGS -DCL_TARGET_OPENCL_VERSION=300"
    execute make "-j$cpu_threads"
    execute make install
fi

# LDCONFIG MUST BE RUN NEXT IN ORDER TO UPDATE FILE CHANGES OR THE MAGICK COMMAND WILL NOT WORK
ldconfig /usr/local/lib

# SHOW THE NEWLY INSTALLED MAGICK VERSION
show_ver_fn

# PROMPT THE USER TO CLEAN UP THE BUILD FILES
cleanup

# SHOW EXIT MESSAGE
exit_fn
