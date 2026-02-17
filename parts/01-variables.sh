# shellcheck shell=bash
# shellcheck disable=SC2034

# SET GLOBAL VARIABLES
script_ver=1.1.5
cwd="$PWD/magick-build-script"
packages="$cwd/packages"
workspace="$cwd/workspace"
regex_string='(Rc|rc|rC|RC|alpha|beta|master|pre)+[0-9]*$'
debug=OFF

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
CC="gcc"
CXX="g++"
CFLAGS="-O2 -fPIC -pipe -march=native -fstack-protector-strong"
CXXFLAGS="$CFLAGS"
CPPFLAGS="-I$workspace/include -I/usr/local/include -I/usr/include -D_FORTIFY_SOURCE=2"
LDFLAGS="-Wl,-O1 -Wl,--as-needed -Wl,-rpath,/usr/local/lib64:/usr/local/lib"
export CC CXX CFLAGS CXXFLAGS CPPFLAGS LDFLAGS

# SET THE AVAILABLE CPU COUNT FOR PARALLEL PROCESSING (SPEEDS UP THE BUILD PROCESS)
if [[ -f /proc/cpuinfo ]]; then
    cpu_threads=$(grep -c ^processor /proc/cpuinfo)
else
    cpu_threads=$(nproc --all 2>/dev/null || true)
fi
[[ -z "$cpu_threads" || "$cpu_threads" -lt 1 ]] && cpu_threads=2

# Set the path variable
PATH="/usr/lib/ccache:$workspace/bin:$PATH"
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
/usr/lib/x86_64-linux-gnu/pkgconfig\
"
export PKG_CONFIG_PATH
