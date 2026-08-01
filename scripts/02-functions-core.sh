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
    echo >&2
    echo -e "${RED}[ERROR]${NC} $1\n" >&2
    echo -e "${GREEN}[INFO]${NC} For help or to report a bug, create an issue at: https://github.com/slyfox1186/script-repo/issues" >&2
    echo >&2
    exit 1
}

log() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARNING]${NC} $1" >&2
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

canonicalize_path() {
    readlink -m -- "$1"
}

path_is_strictly_within() {
    local child parent
    child=$(canonicalize_path "$1")
    parent=$(canonicalize_path "$2")
    [[ -n "$child" && -n "$parent" && "$parent" != "/" ]] || return 1
    [[ "$child" != "$parent" && "$child" == "$parent"/* ]]
}

# Bounded recursive deletion: the target must be a strict descendant of the
# allowed root, and deletion never crosses filesystems and never escalates
# to root. The build tree is created entirely unprivileged, so root-owned
# content inside it indicates something this script must not delete blindly.
safe_remove_tree() {
    local target="$1" allowed_root="$2"
    [[ -n "$target" && -n "$allowed_root" ]] || fail "safe_remove_tree: both a target and an allowed root are required."
    path_is_strictly_within "$target" "$allowed_root" ||
        fail "Refusing to remove '$target': not strictly inside '$allowed_root'."
    [[ -e "$target" || -L "$target" ]] || return 0
    rm -rf --one-file-system -- "$(canonicalize_path "$target")" ||
        fail "Failed to remove '$target'. If root-owned files are present, inspect and remove them manually: sudo rm -rf -- '$target'"
}

# Compatibility wrapper: bounds deletion to the build root.
safe_rm_rf() {
    safe_remove_tree "$1" "$cwd"
}

# The build-root marker records the canonical path it was created for, so a
# copied or moved directory (or an unrelated directory that happens to share
# the name) never validates for recursive deletion.
write_build_root_marker() {
    local marker="$cwd/.magick-build-root" tmp
    tmp=$(mktemp "$cwd/.marker.XXXXXX") || fail "Cannot create the build-root marker in '$cwd'."
    printf 'magick-build-root %s\n' "$(canonicalize_path "$cwd")" >"$tmp" ||
        fail "Cannot write the build-root marker in '$cwd'."
    mv -f -- "$tmp" "$marker" || fail "Cannot publish the build-root marker in '$cwd'."
}

build_root_marker_matches() {
    local marker="$cwd/.magick-build-root" recorded
    [[ -f "$marker" && ! -L "$marker" ]] || return 1
    recorded=$(head -n1 -- "$marker")
    [[ "$recorded" == "magick-build-root $(canonicalize_path "$cwd")" ]]
}

# The lock file is opened in append mode so a FAILED attempt can never
# truncate the holder's PID record. After acquiring, the file is rewritten
# with this process's PID - purely diagnostic; the flock is authoritative.
acquire_build_root_lock() {
    local lock_file="$cwd/.magick-build-lock" holder_pid holder_info
    exec {MAGICK_LOCK_FD}>>"$lock_file" ||
        fail "Cannot open the lock file '$lock_file'."
    if ! flock -n "$MAGICK_LOCK_FD"; then
        holder_pid=$(head -n 1 -- "$lock_file" 2>/dev/null)
        if [[ "$holder_pid" =~ ^[0-9]+$ ]] && kill -0 "$holder_pid" 2>/dev/null; then
            holder_info=$(ps -o pid=,etime=,cmd= -p "$holder_pid" 2>/dev/null)
            fail "Another build is already running in '$cwd' (PID $holder_pid, ${holder_info:-unknown command}). Wait for it, or stop it with: kill $holder_pid"
        fi
        fail "Another build is already running in '$cwd', but its main process is gone - a child of an earlier run is still holding the lock. Find it with: fuser -v '$lock_file' (it releases the lock when it exits or is killed)."
    fi
    : >"$lock_file"
    printf '%s\n' "$$" >>"$lock_file"
}

init_build_log() {
    BUILD_LOG="$cwd/build.log"
    [[ -L "$BUILD_LOG" ]] && fail "Refusing to write the build log: '$BUILD_LOG' is a symlink."
    : >"$BUILD_LOG" || fail "Cannot write the build log '$BUILD_LOG'."
}

# Completion markers are only valid for the configuration that produced them:
# -march=native and the highest-installed-GCC selection mean a CPU, compiler,
# flag, or OS change silently changes every artifact. Any context change
# invalidates all completion markers so the next run rebuilds consistently.
compute_build_context() {
    local compiler_path compiler_version cpu_model
    compiler_path=$(type -P "$CC" 2>/dev/null || echo "$CC")
    compiler_version=$("$CC" --version 2>/dev/null | head -n1 || true)
    cpu_model=$(awk -F': ' '/^model name/ {print $2; exit}' /proc/cpuinfo 2>/dev/null || true)
    printf 'schema=1\n'
    printf 'script_version=%s\n' "$SCRIPT_VERSION"
    printf 'os=%s %s\n' "${OS:-unknown}" "${VER:-unknown}"
    printf 'arch=%s\n' "$(uname -m)"
    printf 'multiarch=%s\n' "$MULTIARCH_TUPLE"
    printf 'cpu_model=%s\n' "$cpu_model"
    printf 'compiler=%s %s\n' "$compiler_path" "$compiler_version"
    printf 'cflags=%s\n' "$CFLAGS"
    printf 'cxxflags=%s\n' "$CXXFLAGS"
    printf 'cppflags=%s\n' "$CPPFLAGS"
    printf 'ldflags=%s\n' "$LDFLAGS"
}

refresh_build_context() {
    local ctx_file="$cwd/.magick-build-context" current tmp
    current=$(compute_build_context)
    if [[ -f "$ctx_file" ]] && ! printf '%s\n' "$current" | cmp -s -- - "$ctx_file"; then
        warn "The build context changed since the last run (compiler, flags, OS, or CPU)."
        warn "Invalidating all completion markers AND the workspace so everything rebuilds consistently."
        diff -u -- "$ctx_file" <(printf '%s\n' "$current") >>"$BUILD_LOG" 2>&1
        rm -f -- "$packages"/*.done
        # The workspace must go with the markers: stale artifacts from the
        # old context would otherwise feed later packages' configure probes
        # with libraries the new sequential build has not produced yet
        # (observed live: libtiff picking up a previous context's libwebp).
        safe_remove_tree "$workspace" "$cwd"
        mkdir -p -- "$workspace" || fail "Cannot recreate the workspace after context invalidation."
    fi
    tmp=$(mktemp "$cwd/.context.XXXXXX") || fail "Cannot record the build context in '$cwd'."
    printf '%s\n' "$current" >"$tmp"
    mv -f -- "$tmp" "$ctx_file"
}

initialize_build_root() {
    [[ "$(uname -m)" == "x86_64" ]] ||
        fail "Unsupported architecture '$(uname -m)'. Only x86_64 is supported and tested."
    umask 022
    mkdir -p -- "$packages" "$workspace" || fail "Cannot create the build directories under '$cwd'."
    if [[ -e "$cwd/.magick-build-root" ]]; then
        build_root_marker_matches ||
            fail "'$cwd' contains a build-root marker for a different path. Refusing to reuse it."
    fi
    write_build_root_marker
    acquire_build_root_lock
    init_build_log
}

install_traps() {
    trap 'handle_signal INT 130' INT
    trap 'handle_signal TERM 143' TERM
    trap 'handle_signal HUP 129' HUP
    trap 'handle_exit' EXIT
}

handle_signal() {
    local name="$1" code="$2"
    trap - INT TERM HUP EXIT
    stop_sudo_keepalive
    # Terminate remaining direct children: bash runs background children
    # with SIGINT ignored, so a ^C that killed this script would otherwise
    # leave them running - and holding the build-root lock they inherited.
    pkill -TERM -P $$ 2>/dev/null
    echo >&2
    echo -e "${YELLOW}[WARNING]${NC} Received SIG$name; stopping. Build files are preserved in '$cwd'." >&2
    exit "$code"
}

handle_exit() {
    stop_sudo_keepalive
}

require_sudo() {
    log "Validating sudo credentials (needed for APT, fonts, and the final install step)..."
    sudo -v || fail "sudo authentication failed."
}

# Started BEFORE the build-root lock is acquired so the loop never
# inherits the lock file descriptor, and self-terminating when the main
# process dies: a SIGKILLed/hung-up run must not leave an immortal child
# holding the lock while sudo's credential cache keeps it alive.
start_sudo_keepalive() {
    [[ -n "${SUDO_KEEPALIVE_PID:-}" ]] && return 0
    local parent_pid=$$
    (
        while kill -0 "$parent_pid" 2>/dev/null; do
            sudo -n true 2>/dev/null || exit
            sleep 60
        done
    ) &
    SUDO_KEEPALIVE_PID=$!
}

stop_sudo_keepalive() {
    if [[ -n "${SUDO_KEEPALIVE_PID:-}" ]]; then
        kill "$SUDO_KEEPALIVE_PID" 2>/dev/null
        wait "$SUDO_KEEPALIVE_PID" 2>/dev/null
        SUDO_KEEPALIVE_PID=""
    fi
}

# Run a command, append its complete output to the build log, and on failure
# replay a bounded tail of the log instead of buffering everything in memory.
# In debug mode the output additionally streams to the terminal; PIPESTATUS
# is captured immediately so tee can never mask the command's status.
execute() {
    echo "\$ $*"
    printf '$ %s\n' "$*" >>"$BUILD_LOG"
    local exit_status
    if [[ "$debug" == "ON" ]]; then
        "$@" 2>&1 | tee -a "$BUILD_LOG"
        exit_status=${PIPESTATUS[0]}
    else
        "$@" >>"$BUILD_LOG" 2>&1
        exit_status=$?
    fi
    if [[ "$exit_status" -ne 0 ]]; then
        echo >&2
        tail -n 40 -- "$BUILD_LOG" >&2
        fail "Failed to execute: $* (exit $exit_status). Full log: $BUILD_LOG"
    fi
}

remove_build_root() {
    build_root_marker_matches ||
        fail "Refusing to remove '$cwd': its build-root marker is missing or does not match this path."
    local parent
    parent=$(dirname -- "$(canonicalize_path "$cwd")")
    safe_remove_tree "$cwd" "$parent"
    log "Removed the build directory: $cwd"
}

cleanup() {
    local choice

    case "$cleanup_mode" in
        always) remove_build_root; return ;;
        never)
            log "Build files preserved: $cwd"
            return
            ;;
    esac

    if [[ ! -t 0 ]]; then
        log "Non-interactive session; build files preserved: $cwd"
        log "Remove them later with: rm -rf -- '$cwd' (or rerun with --cleanup)"
        return
    fi

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
            1|y|yes) remove_build_root; return ;;
            2|n|no)  return ;;
            *)       echo "Invalid choice. Please enter 1 or 2." ;;
        esac
    done
}
