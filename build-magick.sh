#!/usr/bin/env bash
set -o pipefail

# GitHub: https://github.com/slyfox1186/imagemagick-build-script
# Purpose: Build ImageMagick 7 from the source code obtained from ImageMagick's official GitHub repository
# Supported OS: Debian (12|13) | Ubuntu (22|24).04 on x86_64

SCRIPT_VERSION="2.0.0"
readonly SCRIPT_VERSION

# Resolve script directory for sourcing helper scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"
readonly SCRIPT_DIR SCRIPTS_DIR

print_usage() {
    cat <<'EOF'
Usage: build-magick.sh [OPTIONS]

Build ImageMagick and its dependencies from source.

Options:
  -w, --workers N    Parallel job count for make/ninja (positive integer).
                     Default: detected CPU thread count.
  -l, --latest       Re-resolve the latest upstream versions instead of
                     reusing the versions recorded by a previous run.
  -d, --debug        Stream build output to the terminal as well as the log.
      --cleanup      Remove the build directory after a successful build.
      --no-cleanup   Keep the build directory (skips the interactive prompt).
  -v, --version      Print the script version and exit.
  -h, --help         Show this help text and exit.

Examples:
  build-magick.sh
  build-magick.sh --workers 24 --latest
  build-magick.sh --no-cleanup
EOF
}

parse_args() {
    local workers_arg="" workers_set=0
    latest_flag=0
    debug=OFF
    cleanup_mode=prompt

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -w|--workers)
                [[ $# -lt 2 ]] && {
                    echo "Error: $1 requires an integer value." >&2
                    print_usage >&2
                    exit 1
                }
                workers_arg="$2"
                workers_set=1
                shift 2
                ;;
            --workers=*)
                workers_arg="${1#*=}"
                workers_set=1
                shift
                ;;
            -l|--latest)
                latest_flag=1
                shift
                ;;
            -d|--debug)
                debug=ON
                shift
                ;;
            --cleanup)
                [[ "$cleanup_mode" == "never" ]] && {
                    echo "Error: --cleanup and --no-cleanup are mutually exclusive." >&2
                    exit 1
                }
                cleanup_mode=always
                shift
                ;;
            --no-cleanup)
                [[ "$cleanup_mode" == "always" ]] && {
                    echo "Error: --cleanup and --no-cleanup are mutually exclusive." >&2
                    exit 1
                }
                cleanup_mode=never
                shift
                ;;
            -v|--version)
                echo "build-magick.sh $SCRIPT_VERSION"
                exit 0
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                echo "Error: Unknown argument: '$1'" >&2
                print_usage >&2
                exit 1
                ;;
        esac
    done

    if [[ "$workers_set" -eq 1 ]]; then
        if [[ ! "$workers_arg" =~ ^[1-9][0-9]*$ ]]; then
            echo "Error: --workers/-w must be a positive integer (got '$workers_arg')." >&2
            exit 1
        fi
        BUILD_MAGICK_WORKERS="$workers_arg"
    fi
}

# Building as root would leave root-owned files in the build tree and run
# upstream build systems with full privileges; privilege is only used for
# the narrow operations that need it (APT, fonts, install, ldconfig).
ensure_not_root() {
    if [[ "$EUID" -eq 0 ]]; then
        echo "Error: run this script as a regular user with sudo available, not as root." >&2
        exit 1
    fi
    if ! command -v sudo >/dev/null 2>&1; then
        echo "Error: sudo is required (APT package installation and the final install step)." >&2
        exit 1
    fi
}

# Tools that must exist before the APT stage can install everything else.
ensure_bootstrap_commands() {
    local cmd
    local -a missing=()
    for cmd in awk curl find flock git grep mktemp sed sha256sum sort tail tar; do
        command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
    done
    if [[ "${#missing[@]}" -gt 0 ]]; then
        echo "Error: required commands not found: ${missing[*]}" >&2
        exit 1
    fi
}

require_script() {
    if [[ ! -f "$1" ]]; then
        echo "Error: Missing required script: $1" >&2
        exit 1
    fi
}

parse_args "$@"
ensure_not_root
ensure_bootstrap_commands

# Phase 1: Variables and environment
require_script "$SCRIPTS_DIR/01-variables.sh"
# shellcheck source=scripts/01-variables.sh
source "$SCRIPTS_DIR/01-variables.sh"

# Phase 2: Function definitions
require_script "$SCRIPTS_DIR/02-functions-core.sh"
# shellcheck source=scripts/02-functions-core.sh
source "$SCRIPTS_DIR/02-functions-core.sh"

require_script "$SCRIPTS_DIR/03-functions-build.sh"
# shellcheck source=scripts/03-functions-build.sh
source "$SCRIPTS_DIR/03-functions-build.sh"

require_script "$SCRIPTS_DIR/04-functions-version.sh"
# shellcheck source=scripts/04-functions-version.sh
source "$SCRIPTS_DIR/04-functions-version.sh"

require_script "$SCRIPTS_DIR/05-functions-system.sh"
# shellcheck source=scripts/05-functions-system.sh
source "$SCRIPTS_DIR/05-functions-system.sh"

box_out_banner "ImageMagick Build Script v$SCRIPT_VERSION"

if [[ -n "${GNU_COMPILER_VERSION:-}" ]]; then
    log "Using GNU compiler toolchain version $GNU_COMPILER_VERSION: $CC and $CXX."
fi

if [[ -n "${BUILD_MAGICK_WORKERS:-}" ]]; then
    log "Parallel worker count manually set to $cpu_threads."
fi

if [[ "$latest_flag" -eq 1 ]]; then
    log "Version refresh requested (--latest): recorded versions will be re-resolved."
fi

install_traps
# sudo validation and its keepalive come BEFORE the build-root lock so the
# keepalive subshell never inherits the lock file descriptor (a hard-killed
# run must not leave the lock held by a surviving child).
require_sudo
start_sudo_keepalive
initialize_build_root

# Stage definitions (06-13 define one stage function each)
require_script "$SCRIPTS_DIR/06-setup-system.sh"
# shellcheck source=scripts/06-setup-system.sh
source "$SCRIPTS_DIR/06-setup-system.sh"

require_script "$SCRIPTS_DIR/07-build-core-tools.sh"
# shellcheck source=scripts/07-build-core-tools.sh
source "$SCRIPTS_DIR/07-build-core-tools.sh"

require_script "$SCRIPTS_DIR/08-build-image-libs.sh"
# shellcheck source=scripts/08-build-image-libs.sh
source "$SCRIPTS_DIR/08-build-image-libs.sh"

require_script "$SCRIPTS_DIR/09-build-text-libs.sh"
# shellcheck source=scripts/09-build-text-libs.sh
source "$SCRIPTS_DIR/09-build-text-libs.sh"

require_script "$SCRIPTS_DIR/10-build-extra-libs.sh"
# shellcheck source=scripts/10-build-extra-libs.sh
source "$SCRIPTS_DIR/10-build-extra-libs.sh"

require_script "$SCRIPTS_DIR/11-build-fonts.sh"
# shellcheck source=scripts/11-build-fonts.sh
source "$SCRIPTS_DIR/11-build-fonts.sh"

require_script "$SCRIPTS_DIR/12-build-imagemagick.sh"
# shellcheck source=scripts/12-build-imagemagick.sh
source "$SCRIPTS_DIR/12-build-imagemagick.sh"

require_script "$SCRIPTS_DIR/13-finalize.sh"
# shellcheck source=scripts/13-finalize.sh
source "$SCRIPTS_DIR/13-finalize.sh"

# Run the build stages in order
stage_setup_system
stage_build_core_tools
stage_build_image_libs
stage_build_text_libs
stage_build_extra_libs
stage_install_fonts
stage_build_imagemagick
stage_finalize
