#!/usr/bin/env bash
# shellcheck shell=bash

exit_fn() {
    echo
    echo -e "${GREEN}[INFO]${NC} Make sure to ${YELLOW}star${NC} this repository to show your support!"
    echo -e "${GREEN}[INFO]${NC} https://github.com/slyfox1186/script-repo"
    echo
    exit 0
}

fail() {
    echo
    echo -e "${RED}[ERROR]${NC} $1\n"
    echo -e "${GREEN}[INFO]${NC} For help or to report a bug, create an issue at: https://github.com/slyfox1186/script-repo/issues"
    echo
    exit 1
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

resolve_working_meson() {
    local candidate primary_meson

    primary_meson=$(type -P meson 2>/dev/null || true)

    while IFS= read -r candidate; do
        [[ -x "$candidate" ]] || continue
        if "$candidate" --version >/dev/null 2>&1; then
            if [[ -n "$primary_meson" && "$candidate" != "$primary_meson" ]]; then
                log "Using fallback meson executable: $candidate" >&2
            fi
            printf '%s\n' "$candidate"
            return 0
        fi
    done < <(type -aP meson 2>/dev/null)

    return 1
}

meson() {
    if [[ -z "${MESON_BIN:-}" ]]; then
        MESON_BIN=$(resolve_working_meson) ||
            fail "Could not find a working meson executable. Install the system meson package or fix your Python environment."
        export MESON_BIN
    fi

    command "$MESON_BIN" "$@"
}

exec_root() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif command -v sudo &>/dev/null; then
        sudo "$@"
    else
        fail "sudo is not available and you are not root. Cannot run: $*"
    fi
}

safe_rm_rf() {
    local target="$1"

    [[ -z "$target" || "$target" == "/" ]] && fail "Refusing to remove unsafe path: \"$target\""
    [[ -e "$target" ]] || return 0

    case "$target" in
        "$cwd"|"$cwd"/*) ;;
        *) fail "Refusing to remove path outside build root: \"$target\"" ;;
    esac

    exec_root rm -rf -- "$target"
}

cleanup() {
    local choice

    while true; do
        echo
        echo "========================================================"
        echo "       Would you like to clean up the build files?      "
        echo "========================================================"
        echo
        echo "[1] Yes"
        echo "[2] No"
        echo

        read -rp "Your choices are (1 or 2): " choice

        case "${choice,,}" in
            1|y|yes) safe_rm_rf "$cwd"; return ;;
            2|n|no)  return ;;
            *)       echo "Invalid choice. Please enter 1 or 2." ;;
        esac
    done
}
