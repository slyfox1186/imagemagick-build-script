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

test_help_is_pure
test_short_help_is_pure
test_unknown_option_fails_cleanly
test_workers_rejects_bad_values
test_workers_missing_value_fails
test_workers_valid_with_help_is_pure

printf '1..%d\n' "$test_count"
if [[ "$fail_count" -gt 0 ]]; then
    printf '# FAILED: %d of %d tests\n' "$fail_count" "$test_count"
    exit 1
fi
printf '# All %d tests passed\n' "$test_count"
