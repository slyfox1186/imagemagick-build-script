#!/usr/bin/env bash
# Offline regression tests for the build scripts (TAP output).
# Run via: bash tests/test-scripts.sh
# No test may touch the network, sudo, or paths outside its own sandbox.

set -u

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_count=0
fail_count=0

tap_ok() {
    test_count=$((test_count + 1))
    printf 'ok %d - %s\n' "$test_count" "$1"
}

tap_fail() {
    test_count=$((test_count + 1))
    fail_count=$((fail_count + 1))
    printf 'not ok %d - %s\n' "$test_count" "$1"
    [[ -n "${2:-}" ]] && printf '# %s\n' "$2"
}

make_sandbox() {
    mktemp -d "${TMPDIR:-/tmp}/magick-tests.XXXXXX"
}

# Run the entry script inside a sandbox CWD with stdin closed (non-tty),
# capturing stdout/stderr/status into sandbox files. The timeout is a
# harness-level backstop: no argument-handling test may ever reach real
# build work, and a hang/runaway must fail the test rather than the host.
run_entry_in_sandbox() {
    local sandbox="$1"
    shift
    (cd "$sandbox" && timeout 20 bash "$repo_root/build-magick.sh" "$@" \
        >stdout.txt 2>stderr.txt </dev/null)
    printf '%s' "$?" >"$sandbox/status.txt"
}

# Assert the sandbox contains only the capture files the harness itself wrote.
sandbox_is_clean() {
    local sandbox="$1" leftovers
    leftovers=$(cd "$sandbox" && find . -mindepth 1 \
        ! -name stdout.txt ! -name stderr.txt ! -name status.txt)
    [[ -z "$leftovers" ]]
}

test_help_is_pure() {
    local label="--help exits 0, prints usage, creates nothing"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" --help
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "exit status was $status"
    elif ! grep -q '^Usage: build-magick.sh' "$sandbox/stdout.txt"; then
        tap_fail "$label" "usage text missing from stdout"
    elif ! sandbox_is_clean "$sandbox"; then
        tap_fail "$label" "files were created: $(cd "$sandbox" && find . -mindepth 1)"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_short_help_is_pure() {
    local label="-h behaves identically to --help"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" -h
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "exit status was $status"
    elif ! grep -q '^Usage: build-magick.sh' "$sandbox/stdout.txt"; then
        tap_fail "$label" "usage text missing from stdout"
    elif ! sandbox_is_clean "$sandbox"; then
        tap_fail "$label" "files were created"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_unknown_option_fails_cleanly() {
    local label="unknown option fails without side effects"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" --no-such-option
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" ]]; then
        tap_fail "$label" "unknown option was accepted"
    elif ! grep -q -- '--no-such-option' "$sandbox/stderr.txt"; then
        tap_fail "$label" "error message does not name the bad option"
    elif ! sandbox_is_clean "$sandbox"; then
        tap_fail "$label" "files were created"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_workers_rejects_bad_values() {
    local label="--workers rejects non-positive-integer values"
    local sandbox status value ok=1
    for value in 0 -3 abc 1.5; do
        sandbox=$(make_sandbox)
        run_entry_in_sandbox "$sandbox" --workers "$value"
        status=$(<"$sandbox/status.txt")
        if [[ "$status" == "0" ]]; then
            tap_fail "$label" "value '$value' was accepted"
            ok=0
            rm -rf -- "$sandbox"
            break
        fi
        rm -rf -- "$sandbox"
    done
    [[ "$ok" -eq 1 ]] && tap_ok "$label"
}

test_workers_missing_value_fails() {
    local label="--workers without a value fails"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" --workers
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" ]]; then
        tap_fail "$label" "missing value was accepted"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_workers_valid_with_help_is_pure() {
    local label="--workers=8 combined with --help stays side-effect free"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" --workers=8 --help
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "exit status was $status"
    elif ! sandbox_is_clean "$sandbox"; then
        tap_fail "$label" "files were created"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

# Run a snippet with scripts/01+02 sourced, inside a sandbox CWD, capturing
# stdout/stderr/status. Unit tests for the core helpers use this driver; the
# build root ($cwd) resolves inside the sandbox because 01 derives it from
# $PWD, and nothing in 01/02 touches the filesystem at source time. The
# snippet arrives on stdin (quoted heredoc at the call site), so variable
# references stay literal until the sandboxed bash evaluates them.
run_unit_in_sandbox() {
    local sandbox="$1" body
    body=$(cat)
    (cd "$sandbox" && env SCRIPT_VERSION=0-test repo_root="$repo_root" \
        timeout 20 bash -c "
        set -o pipefail
        debug=OFF
        cleanup_mode=prompt
        latest_flag=0
        source '$repo_root/scripts/01-variables.sh'
        source '$repo_root/scripts/02-functions-core.sh'
        $body
    " >unit-out.txt 2>unit-err.txt </dev/null)
    printf '%s' "$?" >"$sandbox/status.txt"
}

test_version_flag_is_pure() {
    local label="--version prints the exact version and creates nothing"
    local sandbox status
    sandbox=$(make_sandbox)
    run_entry_in_sandbox "$sandbox" --version
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "exit status was $status"
    elif [[ "$(<"$sandbox/stdout.txt")" != "build-magick.sh 2.0.0" ]]; then
        tap_fail "$label" "unexpected stdout: $(<"$sandbox/stdout.txt")"
    elif ! sandbox_is_clean "$sandbox"; then
        tap_fail "$label" "files were created"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_cleanup_flags_are_mutually_exclusive() {
    local label="--cleanup and --no-cleanup are mutually exclusive"
    local sandbox status ok=1 combo
    for combo in "--cleanup --no-cleanup" "--no-cleanup --cleanup"; do
        sandbox=$(make_sandbox)
        # shellcheck disable=SC2086 # combo is a deliberate two-word option list
        run_entry_in_sandbox "$sandbox" $combo
        status=$(<"$sandbox/status.txt")
        if [[ "$status" == "0" ]]; then
            tap_fail "$label" "'$combo' was accepted"
            ok=0
            rm -rf -- "$sandbox"
            break
        fi
        rm -rf -- "$sandbox"
    done
    [[ "$ok" -eq 1 ]] && tap_ok "$label"
}

test_workers_rejects_empty_value() {
    local label="--workers with an empty value is rejected, not ignored"
    local sandbox status ok=1 arg
    for arg in "--workers=" "--workers ''"; do
        sandbox=$(make_sandbox)
        if [[ "$arg" == "--workers=" ]]; then
            run_entry_in_sandbox "$sandbox" --workers=
        else
            run_entry_in_sandbox "$sandbox" --workers ""
        fi
        status=$(<"$sandbox/status.txt")
        if [[ "$status" == "0" ]]; then
            tap_fail "$label" "empty value via '$arg' was accepted"
            ok=0
            rm -rf -- "$sandbox"
            break
        fi
        rm -rf -- "$sandbox"
    done
    [[ "$ok" -eq 1 ]] && tap_ok "$label"
}

test_safe_remove_tree_removes_child() {
    local label="safe_remove_tree removes a strict descendant"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p root/child/sub
        safe_remove_tree root/child root
        [[ ! -e root/child && -d root ]]
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_safe_remove_tree_refuses_root_itself() {
    local label="safe_remove_tree refuses to remove the allowed root itself"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p root
        safe_remove_tree root root
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" ]]; then
        tap_fail "$label" "removal of the root was allowed"
    elif [[ ! -d "$sandbox/root" ]]; then
        tap_fail "$label" "the root directory was actually removed"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_safe_remove_tree_refuses_prefix_sibling() {
    local label="safe_remove_tree refuses a sibling that shares a name prefix"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p root rootEVIL
        safe_remove_tree rootEVIL root
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" ]]; then
        tap_fail "$label" "the prefix-colliding sibling was allowed"
    elif [[ ! -d "$sandbox/rootEVIL" ]]; then
        tap_fail "$label" "the sibling directory was actually removed"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_build_root_marker_rejects_copies() {
    local label="a copied build-root marker does not validate elsewhere"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        write_build_root_marker
        build_root_marker_matches || exit 7
        mkdir -p other
        cp "$cwd/.magick-build-root" other/
        cwd="$PWD/other"
        if build_root_marker_matches; then exit 8; fi
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the genuine marker did not validate" ;;
        8) tap_fail "$label" "a copied marker validated in a different directory" ;;
        *) tap_fail "$label" "unexpected status $status" ;;
    esac
    rm -rf -- "$sandbox"
}

test_build_root_lock_is_exclusive() {
    local label="a second lock acquisition on the same build root fails"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        acquire_build_root_lock
        if bash -c "
            set -o pipefail
            debug=OFF
            source \"'"$repo_root"'/scripts/01-variables.sh\"
            source \"'"$repo_root"'/scripts/02-functions-core.sh\"
            acquire_build_root_lock
        " >/dev/null 2>&1; then
            exit 7
        fi
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the second acquisition unexpectedly succeeded" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_execute_appends_to_build_log() {
    local label="execute appends the command and its output to the build log"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        init_build_log
        execute echo hello-from-execute
        grep -q "^\\$ echo hello-from-execute$" "$BUILD_LOG" || exit 7
        grep -q "^hello-from-execute$" "$BUILD_LOG" || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the command line was not logged" ;;
        8) tap_fail "$label" "the command output was not logged" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_execute_failure_replays_log_tail() {
    local label="execute failure replays the log tail and exits nonzero"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        init_build_log
        execute bash -c "echo doomed-output; exit 3"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a failing command did not abort (status $status)"
    elif ! grep -q "doomed-output" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "the log tail was not replayed to stderr"
    elif ! grep -q "exit 3" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "the failure message does not include the exit status"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_init_build_log_refuses_symlink() {
    local label="the build log refuses to follow a symlink"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        touch elsewhere.log
        ln -s "$PWD/elsewhere.log" "$cwd/build.log"
        init_build_log
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a symlinked build log was accepted (status $status)"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_cleanup_noninteractive_preserves_files() {
    local label="non-interactive cleanup preserves files and prints the removal command"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        write_build_root_marker
        cleanup
        [[ -d "$cwd" ]] || exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    elif ! grep -q "preserved" "$sandbox/unit-out.txt"; then
        tap_fail "$label" "no preservation notice was printed"
    elif ! grep -q "rm -rf" "$sandbox/unit-out.txt"; then
        tap_fail "$label" "the manual removal command was not printed"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_cleanup_always_removes_marked_root() {
    local label="--cleanup mode removes a marker-validated build root"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd"
        write_build_root_marker
        cleanup_mode=always
        cleanup
        [[ ! -e "$cwd" ]]
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_remove_build_root_requires_marker() {
    local label="build-root removal refuses a directory without a valid marker"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$cwd/precious"
        remove_build_root
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "an unmarked build root was removed (status $status)"
    elif [[ ! -d "$sandbox/magick-build-script/precious" ]]; then
        tap_fail "$label" "the unmarked directory contents were deleted"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_help_is_pure
test_short_help_is_pure
test_unknown_option_fails_cleanly
test_workers_rejects_bad_values
test_workers_missing_value_fails
test_workers_valid_with_help_is_pure
test_version_flag_is_pure
test_cleanup_flags_are_mutually_exclusive
test_workers_rejects_empty_value
test_safe_remove_tree_removes_child
test_safe_remove_tree_refuses_root_itself
test_safe_remove_tree_refuses_prefix_sibling
test_build_root_marker_rejects_copies
test_build_root_lock_is_exclusive
test_execute_appends_to_build_log
test_execute_failure_replays_log_tail
test_init_build_log_refuses_symlink
test_cleanup_noninteractive_preserves_files
test_cleanup_always_removes_marked_root
test_remove_build_root_requires_marker

printf '1..%d\n' "$test_count"
if [[ "$fail_count" -gt 0 ]]; then
    printf '# FAILED: %d of %d tests\n' "$fail_count" "$test_count"
    exit 1
fi
printf '# All %d tests passed\n' "$test_count"
