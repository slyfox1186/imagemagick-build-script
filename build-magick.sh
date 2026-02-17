#!/usr/bin/env bash
# shellcheck disable=SC2034
set -o pipefail

# Script Version: 1.1.5
# Updated: 12.2.25
# GitHub: https://github.com/slyfox1186/imagemagick-build-script
# Purpose: Build ImageMagick 7 from the source code obtained from ImageMagick's official GitHub repository
# Supported OS: Debian (12|13) | Ubuntu (20|22|24).04

# Check if sudo is available for commands that need root
if ! command -v sudo &>/dev/null && [[ "$EUID" -ne 0 ]]; then
    echo "Warning: sudo is not available and you are not root. Some operations may fail."
fi

# Resolve script directory for sourcing parts
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARTS_DIR="$SCRIPT_DIR/parts"

require_part() {
    if [[ ! -f "$1" ]]; then
        echo "Error: Missing required part: $1" >&2
        exit 1
    fi
}

# Phase 1: Variables and environment
require_part "$PARTS_DIR/01-variables.sh"
# shellcheck source=parts/01-variables.sh
source "$PARTS_DIR/01-variables.sh"
box_out_banner "ImageMagick Build Script v$script_ver"

# Phase 2: Function definitions
require_part "$PARTS_DIR/02-functions-core.sh"
# shellcheck source=parts/02-functions-core.sh
source "$PARTS_DIR/02-functions-core.sh"

require_part "$PARTS_DIR/03-functions-build.sh"
# shellcheck source=parts/03-functions-build.sh
source "$PARTS_DIR/03-functions-build.sh"

require_part "$PARTS_DIR/04-functions-version.sh"
# shellcheck source=parts/04-functions-version.sh
source "$PARTS_DIR/04-functions-version.sh"

require_part "$PARTS_DIR/05-functions-system.sh"
# shellcheck source=parts/05-functions-system.sh
source "$PARTS_DIR/05-functions-system.sh"

# Phase 3: System setup (OS detection, package installation, composer)
require_part "$PARTS_DIR/06-setup-system.sh"
# shellcheck source=parts/06-setup-system.sh
source "$PARTS_DIR/06-setup-system.sh"

# Phase 4: Build dependencies
require_part "$PARTS_DIR/07-build-core-tools.sh"
# shellcheck source=parts/07-build-core-tools.sh
source "$PARTS_DIR/07-build-core-tools.sh"

require_part "$PARTS_DIR/08-build-image-libs.sh"
# shellcheck source=parts/08-build-image-libs.sh
source "$PARTS_DIR/08-build-image-libs.sh"

require_part "$PARTS_DIR/09-build-text-libs.sh"
# shellcheck source=parts/09-build-text-libs.sh
source "$PARTS_DIR/09-build-text-libs.sh"

require_part "$PARTS_DIR/10-build-extra-libs.sh"
# shellcheck source=parts/10-build-extra-libs.sh
source "$PARTS_DIR/10-build-extra-libs.sh"

# Phase 5: Fonts
require_part "$PARTS_DIR/11-build-fonts.sh"
# shellcheck source=parts/11-build-fonts.sh
source "$PARTS_DIR/11-build-fonts.sh"

# Phase 6: Build ImageMagick
require_part "$PARTS_DIR/12-build-imagemagick.sh"
# shellcheck source=parts/12-build-imagemagick.sh
source "$PARTS_DIR/12-build-imagemagick.sh"

# Phase 7: Finalize
require_part "$PARTS_DIR/13-finalize.sh"
# shellcheck source=parts/13-finalize.sh
source "$PARTS_DIR/13-finalize.sh"
