# shellcheck shell=bash
# shellcheck disable=SC2034

# SET GLOBAL VARIABLES
script_ver=1.2.0
cwd="$PWD/magick-build-script"
packages="$cwd/packages"
workspace="$cwd/workspace"
regex_string='(Rc|rc|rC|RC|alpha|beta|master|pre)+[0-9]*$'
debug=OFF
GNU_PRIMARY_MIRROR="https://ftp.gnu.org/gnu"
GNU_FALLBACK_MIRROR="https://ftpmirror.gnu.org"

# Pre-defined color variables
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# ANNOUNCE THE BUILD HAS BEGUN
box_out_banner() {
    local text="$*"
    local input_char=${#text}
    line=$(printf '%*s' "$((input_char + 1))" '' | tr ' ' '-')
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

# CREATE OUTPUT DIRECTORIES
[[ ! -d "$packages" ]] && mkdir -p "$packages"
[[ ! -d "$workspace" ]] && mkdir -p "$workspace"

# SET THE COMPILERS TO USE AND THE COMPILER OPTIMIZATION FLAGS
select_gnu_compiler_pair() {
    local candidate candidate_version best_version=""

    shopt -s nullglob
    for candidate in /usr/bin/gcc-[1-9]*; do
        [[ -x "$candidate" ]] || continue
        candidate_version="${candidate##*/gcc-}"
        [[ "$candidate_version" =~ ^[0-9]+$ ]] || continue
        (( candidate_version >= 11 )) || continue
        [[ -x "/usr/bin/g++-$candidate_version" ]] || continue

        if [[ -z "$best_version" || "$candidate_version" -gt "$best_version" ]]; then
            best_version="$candidate_version"
        fi
    done
    shopt -u nullglob

    if [[ -n "$best_version" ]]; then
        CC="gcc-$best_version"
        CXX="g++-$best_version"
        GNU_COMPILER_VERSION="$best_version"
    else
        CC="gcc"
        CXX="g++"
        GNU_COMPILER_VERSION=""
    fi
}

select_gnu_compiler_pair
CFLAGS="-O3 -fPIC -pipe -march=native -fstack-protector-strong"
CXXFLAGS="$CFLAGS"
CPPFLAGS="-I$workspace/include -I/usr/local/include -I/usr/include -D_FORTIFY_SOURCE=2"
LDFLAGS="-Wl,-O1 -Wl,--as-needed -Wl,-rpath,/usr/local/lib64:/usr/local/lib"
export CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS GNU_PRIMARY_MIRROR GNU_FALLBACK_MIRROR GNU_COMPILER_VERSION

# SET THE AVAILABLE CPU THREAD COUNT FOR PARALLEL PROCESSING
if [[ -n "${BUILD_MAGICK_WORKERS:-}" ]]; then
    cpu_threads="$BUILD_MAGICK_WORKERS"
elif [[ -f /proc/cpuinfo ]]; then
    cpu_threads=$(grep -c ^processor /proc/cpuinfo)
else
    cpu_threads=$(nproc --all 2>/dev/null || true)
fi
[[ -z "$cpu_threads" || "$cpu_threads" -lt 1 ]] && cpu_threads=2

# Prefer the workspace and standard system toolchain over inherited user shims.
PATH="/usr/lib/ccache:$workspace/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$PATH"
export PATH

# Keep pkg-config discovery deterministic: prefer the workspace, allow
# explicit system package directories, and ignore /usr/local overrides.
WORKSPACE_PKG_CONFIG_DIRS="\
$workspace/lib64/pkgconfig:\
$workspace/lib/x86_64-linux-gnu/pkgconfig:\
$workspace/lib/pkgconfig:\
$workspace/share/pkgconfig\
"
SYSTEM_PKG_CONFIG_DIRS="\
/usr/lib/x86_64-linux-gnu/pkgconfig:\
/usr/share/pkgconfig:\
/usr/lib/pkgconfig:\
/lib/x86_64-linux-gnu/pkgconfig:\
/lib/pkgconfig\
"
PKG_CONFIG_PATH="$WORKSPACE_PKG_CONFIG_DIRS"
PKG_CONFIG_LIBDIR="$WORKSPACE_PKG_CONFIG_DIRS:$SYSTEM_PKG_CONFIG_DIRS"
export WORKSPACE_PKG_CONFIG_DIRS SYSTEM_PKG_CONFIG_DIRS PKG_CONFIG_PATH PKG_CONFIG_LIBDIR
