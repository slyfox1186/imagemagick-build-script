#!/usr/bin/env bash
# shellcheck disable=SC2034
set -o pipefail

# Script Version: 1.2.0
# Updated: 12.2.25
# GitHub: https://github.com/slyfox1186/imagemagick-build-script
# Purpose: Build ImageMagick 7 from the source code obtained from ImageMagick's official GitHub repository
# Supported OS: Debian (12|13) | Ubuntu (20|22|24).04

# Check if sudo is available for commands that need root
if ! command -v sudo &>/dev/null && [[ "$EUID" -ne 0 ]]; then
    echo "Warning: sudo is not available and you are not root. Some operations may fail."
fi

# Resolve script directory for sourcing helper scripts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$SCRIPT_DIR/scripts"

print_usage() {
    cat <<'EOF'
Usage: build-magick.sh [OPTIONS]

Build ImageMagick and its dependencies from source.

Options:
  -w, --workers N    Set the parallel worker count used for make/ninja jobs.
                     N must be a positive integer.
  -h, --help         Show this help text and exit.

Default:
  If --workers is not provided, the script uses the detected CPU thread count.

Examples:
  build-magick.sh
  build-magick.sh --workers 24
  build-magick.sh -w 24
EOF
}

parse_args() {
    local workers_arg=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -w|--workers)
                [[ $# -lt 2 ]] && {
                    echo "Error: $1 requires an integer value." >&2
                    print_usage >&2
                    exit 1
                }
                workers_arg="$2"
                shift 2
                ;;
            --workers=*)
                workers_arg="${1#*=}"
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                echo "Error: Unknown argument: $1" >&2
                print_usage >&2
                exit 1
                ;;
        esac
    done

    if [[ -n "$workers_arg" ]]; then
        if [[ ! "$workers_arg" =~ ^[1-9][0-9]*$ ]]; then
            echo "Error: --workers/-w must be a positive integer." >&2
            exit 1
        fi
        export BUILD_MAGICK_WORKERS="$workers_arg"
    fi
}

require_script() {
    if [[ ! -f "$1" ]]; then
        echo "Error: Missing required script: $1" >&2
        exit 1
    fi
}

parse_args "$@"

# Phase 1: Variables and environment
require_script "$SCRIPTS_DIR/01-variables.sh"
# shellcheck source=scripts/01-variables.sh
source "$SCRIPTS_DIR/01-variables.sh"
box_out_banner "ImageMagick Build Script v$script_ver"

# Phase 2: Function definitions
require_script "$SCRIPTS_DIR/02-functions-core.sh"
# shellcheck source=scripts/02-functions-core.sh
source "$SCRIPTS_DIR/02-functions-core.sh"

if [[ -n "${GNU_COMPILER_VERSION:-}" ]]; then
    log "Using GNU compiler toolchain version $GNU_COMPILER_VERSION: $CC and $CXX."
fi

if [[ -n "${BUILD_MAGICK_WORKERS:-}" ]]; then
    log "Parallel worker count manually set to $cpu_threads."
fi

require_script "$SCRIPTS_DIR/03-functions-build.sh"
# shellcheck source=scripts/03-functions-build.sh
source "$SCRIPTS_DIR/03-functions-build.sh"

require_script "$SCRIPTS_DIR/04-functions-version.sh"
# shellcheck source=scripts/04-functions-version.sh
source "$SCRIPTS_DIR/04-functions-version.sh"

require_script "$SCRIPTS_DIR/05-functions-system.sh"
# shellcheck source=scripts/05-functions-system.sh
source "$SCRIPTS_DIR/05-functions-system.sh"

# Phase 3: System setup (OS detection, package installation, composer)
require_script "$SCRIPTS_DIR/06-setup-system.sh"
# shellcheck source=scripts/06-setup-system.sh
source "$SCRIPTS_DIR/06-setup-system.sh"

# Phase 4: Build dependencies
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

# Phase 5: Fonts
require_script "$SCRIPTS_DIR/11-build-fonts.sh"
# shellcheck source=scripts/11-build-fonts.sh
source "$SCRIPTS_DIR/11-build-fonts.sh"

# Phase 6: Build ImageMagick
require_script "$SCRIPTS_DIR/12-build-imagemagick.sh"
# shellcheck source=scripts/12-build-imagemagick.sh
source "$SCRIPTS_DIR/12-build-imagemagick.sh"

# Phase 7: Finalize
require_script "$SCRIPTS_DIR/13-finalize.sh"
# shellcheck source=scripts/13-finalize.sh
source "$SCRIPTS_DIR/13-finalize.sh"
