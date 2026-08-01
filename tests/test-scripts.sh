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

# The environment shared by every sandboxed unit invocation: baseline
# globals plus all project scripts and the test helpers, sourced in order.
unit_preamble() {
    printf '%s\n' \
        'set -o pipefail' \
        'debug=OFF' \
        'cleanup_mode=prompt' \
        'latest_flag=0'
    local script
    for script in "$repo_root"/scripts/[0-9]*.sh "$repo_root/tests/helpers.sh"; do
        printf "source '%s'\n" "$script"
    done
}

# Run a snippet with the unit preamble, inside a sandbox CWD, capturing
# stdout/stderr/status. Unit tests for the core helpers use this driver; the
# build root ($cwd) resolves inside the sandbox because 01 derives it from
# $PWD, and nothing touches the filesystem at source time. The snippet
# arrives on stdin (quoted heredoc at the call site), so variable
# references stay literal until the sandboxed bash evaluates them.
run_unit_in_sandbox() {
    local sandbox="$1" body
    body=$(cat)
    (cd "$sandbox" && env SCRIPT_VERSION=0-test repo_root="$repo_root" \
        timeout 20 bash -c "$(unit_preamble)
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
            source \"$repo_root/scripts/01-variables.sh\"
            source \"$repo_root/scripts/02-functions-core.sh\"
            acquire_build_root_lock
        " >/dev/null 2>lock-err.txt; then
            exit 7
        fi
        # The conflict message must identify the live holder and say how
        # to stop it.
        grep -q "PID $$" lock-err.txt || exit 8
        grep -q "kill $$" lock-err.txt || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the second acquisition unexpectedly succeeded" ;;
        8) tap_fail "$label" "the conflict message does not identify the holder PID and kill command" ;;
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

# --- Phase 4: tag selection, marker reuse, pinned clones -------------------

test_tag_selection_handles_libjpeg_turbo_grammar() {
    local label="tag selection excludes libjpeg-turbo dev tags and jpeg-* tags"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        fixture=$(printf '%s\trefs/tags/%s\n' \
            1111111111111111111111111111111111111111 3.1.1 \
            2222222222222222222222222222222222222222 3.1.2 \
            3333333333333333333333333333333333333333 3.1.90 \
            4444444444444444444444444444444444444444 jpeg-9f \
            5555555555555555555555555555555555555555 jpeg-10 \
            6666666666666666666666666666666666666666 jpeg-ari)
        result=$(printf '%s\n' "$fixture" |
            select_latest_stable_tag '^[0-9]+\.[0-9]+\.[0-9]+$' '\.9[0-9]$') || exit 7
        [[ "$result" == "3.1.2|3.1.2|2222222222222222222222222222222222222222" ]] || {
            echo "got: $result" >&2
            exit 8
        }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "selection returned nothing" ;;
        8) tap_fail "$label" "wrong selection: $(<"$sandbox/unit-err.txt")" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_tag_selection_prefers_peeled_commit() {
    local label="an annotated tag resolves to its peeled commit"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        fixture=$(printf '%s\trefs/tags/%s\n' \
            aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa v1.0.0 \
            bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb 'v1.0.0^{}')
        result=$(printf '%s\n' "$fixture" |
            select_latest_stable_tag '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v') || exit 7
        [[ "$result" == "v1.0.0|1.0.0|bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" ]] || {
            echo "got: $result" >&2
            exit 8
        }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        *) tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_tag_selection_excludes_prereleases() {
    local label="rc/alpha/beta tags are excluded"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        fixture=$(printf '%s\trefs/tags/%s\n' \
            cccccccccccccccccccccccccccccccccccccccc v1.6.50 \
            dddddddddddddddddddddddddddddddddddddddd v1.6.51-rc01 \
            eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee v1.7.0-beta2)
        result=$(printf '%s\n' "$fixture" |
            select_latest_stable_tag '^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9]+)?$' '' 'v') || exit 7
        [[ "$result" == v1.6.50\|1.6.50\|cccc* ]] || {
            echo "got: $result" >&2
            exit 8
        }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        *) tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_tag_selection_handles_ghostscript_and_freetype() {
    local label="ghostscript 5-digit and freetype VER- grammars select correctly"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        gs_fixture=$(printf '%s\trefs/tags/%s\n' \
            1111111111111111111111111111111111111111 gs9561 \
            2222222222222222222222222222222222222222 gs10051 \
            3333333333333333333333333333333333333333 gs10071 \
            4444444444444444444444444444444444444444 gs100501)
        result=$(printf '%s\n' "$gs_fixture" |
            select_latest_stable_tag '^gs[0-9][0-9][0-9][0-9][0-9]$') || exit 7
        [[ "$result" == gs10071\|gs10071\|3333* ]] || {
            echo "ghostscript got: $result" >&2
            exit 8
        }
        ft_fixture=$(printf '%s\trefs/tags/%s\n' \
            5555555555555555555555555555555555555555 VER-2-9-1 \
            6666666666666666666666666666666666666666 VER-2-13-2 \
            7777777777777777777777777777777777777777 VER-2-13-3)
        result=$(printf '%s\n' "$ft_fixture" |
            select_latest_stable_tag '^VER-[0-9]+(-[0-9]+)+$' '' 'VER-') || exit 9
        [[ "$result" == "VER-2-13-3|2-13-3|7777777777777777777777777777777777777777" ]] || {
            echo "freetype got: $result" >&2
            exit 10
        }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        *) tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_tag_selection_fails_closed_on_empty_input() {
    local label="tag selection fails closed on empty or tagless input"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        if printf '' | select_latest_stable_tag '^v'; then exit 7; fi
        if printf '%s\trefs/heads/main\n' aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa |
            select_latest_stable_tag '^v'; then exit 8; fi
        exit 0
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "empty input produced a selection" ;;
        8) tap_fail "$label" "tagless input produced a selection" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_tag_selection_survives_large_input_under_pipefail() {
    local label="tag selection is SIGPIPE-safe on a 300k-line listing under pipefail"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        python3 - >tags.txt <<'PY'
for i in range(300000):
    print("%040d\trefs/tags/v1.%d.%d" % (i, i // 1000, i % 1000))
PY
        selected=$(select_latest_stable_tag '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v' <tags.txt) || exit 7
        [[ "$selected" == v1.299.999\|1.299.999\|* ]] || {
            echo "got: $selected" >&2
            exit 8
        }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "selection failed (SIGPIPE under pipefail?)" ;;
        8) tap_fail "$label" "wrong selection: $(<"$sandbox/unit-err.txt")" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_resolve_reuses_marker_without_network() {
    local label="resolution reuses an intact marker with no resolver call"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace/bin"
        printf '#!/bin/sh\n' > "$workspace/bin/m4"
        chmod 755 "$workspace/bin/m4"
        build_done m4 1.4.19
        resolver_must_not_run() { echo "the resolver was called" >&2; exit 99; }
        out=$(resolve_pkg_version m4 resolver_must_not_run) || exit 7
        [[ "$out" == "|1.4.19|" ]] || { echo "got: $out" >&2; exit 8; }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "marker reuse failed" ;;
        8) tap_fail "$label" "wrong reuse output: $(<"$sandbox/unit-err.txt")" ;;
        99) tap_fail "$label" "the resolver was called despite a valid marker" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_latest_flag_forces_resolution() {
    local label="--latest forces re-resolution even with an intact marker"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace/bin"
        printf '#!/bin/sh\n' > "$workspace/bin/m4"
        chmod 755 "$workspace/bin/m4"
        build_done m4 1.4.19
        latest_flag=1
        fake_resolver() { printf '|9.9.9|\n'; }
        out=$(resolve_pkg_version m4 fake_resolver) || exit 7
        [[ "$out" == "|9.9.9|" ]] || { echo "got: $out" >&2; exit 8; }
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        *) tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_git_clone_verifies_pinned_commit() {
    local label="git_clone rejects a commit mismatch and accepts the pinned commit"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        # Local fixture repositories use the file transport, which the
        # production HTTPS-only policy blocks; neutralize it for this test.
        GIT_PROTOCOL_POLICY=()
        mkdir -p "$packages"
        git init -q fixture-repo
        git -C fixture-repo -c user.email=t@t.invalid -c user.name=t \
            commit -q --allow-empty -m one
        git -C fixture-repo tag v1.0.0
        good=$(git -C fixture-repo rev-parse HEAD)
        if (git_clone "$PWD/fixture-repo" fixture v1.0.0 \
            0000000000000000000000000000000000000000) >/dev/null 2>&1; then
            exit 7
        fi
        [[ ! -e "$packages/fixture" ]] || exit 8
        git_clone "$PWD/fixture-repo" fixture v1.0.0 "$good" >/dev/null 2>&1 || exit 9
        [[ "$(git -C "$packages/fixture" rev-parse HEAD)" == "$good" ]] || exit 10
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "a wrong pinned commit was accepted" ;;
        8) tap_fail "$label" "a rejected clone still published a checkout" ;;
        9) tap_fail "$label" "a correct pinned clone failed: $(<"$sandbox/unit-err.txt")" ;;
        10) tap_fail "$label" "the published checkout is not at the pinned commit" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

# --- Phase 6: installation validation ---------------------------------------

test_magick_validation_accepts_good_install() {
    local label="installation validation accepts a matching version and delegate set"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        make_fake_magick "7.9.9-99" "fontconfig freetype fpx gslib gvc heic jng jp2 jpeg lcms png raqm rsvg tiff webp xml zlib"
        validate_magick_installation "7.9.9-99" "$PWD/fake-magick"
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_magick_validation_rejects_missing_delegate() {
    local label="installation validation fails on a missing delegate and names it"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        make_fake_magick "7.9.9-99" "fontconfig freetype fpx gslib heic jng jp2 jpeg lcms png raqm rsvg tiff webp xml zlib"
        validate_magick_installation "7.9.9-99" "$PWD/fake-magick"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a missing delegate was accepted (status $status)"
    elif ! grep -q "missing expected delegates: gvc" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "the failure does not name the missing delegate: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_magick_validation_rejects_version_mismatch() {
    local label="installation validation fails on a version mismatch"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        make_fake_magick "7.9.9-99" "fontconfig freetype fpx gslib gvc heic jng jp2 jpeg lcms png raqm rsvg tiff webp xml zlib"
        validate_magick_installation "7.9.9-98" "$PWD/fake-magick"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a version mismatch was accepted (status $status)"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_staged_validation_rejects_out_of_prefix_files() {
    local label="staged-install validation rejects files outside /usr"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p staging/usr/local/bin staging/etc
        printf '#!/bin/sh\necho ok\n' > staging/usr/local/bin/magick
        chmod 755 staging/usr/local/bin/magick
        printf 'oops\n' > staging/etc/stray.conf
        validate_staged_install "$PWD/staging" "7.9.9-99"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "an out-of-prefix staged file was accepted (status $status)"
    elif ! grep -q "outside /usr" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "the failure does not identify the stray path"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

# --- Phase 5: APT hygiene and OS support ------------------------------------

test_apt_fails_closed_on_unavailable_required_package() {
    local label="a required-but-unavailable APT package aborts before any install"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        OS=Ubuntu
        VER=24.04
        VER_MAJOR=24
        dpkg-query() { printf 'unknown ok not-installed\n'; return 1; }
        apt-cache() { [[ "$2" == "libsharp-dev" ]] && return 100; return 0; }
        exec_root() { printf 'EXEC: %s\n' "$*" >> exec.log; }
        apt_pkgs
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "apt_pkgs did not abort (status $status)"
    elif ! grep -q "unavailable" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "the failure does not name unavailable packages"
    elif grep -q "apt-get install" "$sandbox/exec.log" 2>/dev/null; then
        tap_fail "$label" "apt-get install ran despite an unavailable required package"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_no_autoremove_anywhere() {
    local label="no APT autoremove/purge exists; removals only via the legacy allowlist"
    local removals
    if grep -rnE 'apt[-_]get[^|]*(autoremove|purge)' "$repo_root/build-magick.sh" "$repo_root/scripts/"*.sh >/dev/null 2>&1; then
        tap_fail "$label" "$(grep -rnE 'apt[-_]get[^|]*(autoremove|purge)' "$repo_root/build-magick.sh" "$repo_root/scripts/"*.sh)"
        return
    fi
    # The single permitted removal is the legacy-conflict migration, which
    # must only ever operate on the fixed allowlist array.
    removals=$(grep -rnE 'apt[-_]get remove' "$repo_root/build-magick.sh" "$repo_root/scripts/"*.sh)
    if [[ "$(printf '%s\n' "$removals" | grep -c .)" != "1" ]] ||
        ! printf '%s\n' "$removals" | grep -q 'legacy_conflicts'; then
        tap_fail "$label" "unexpected apt-get remove usage: $removals"
    else
        tap_ok "$label"
    fi
}

test_unsupported_distro_fails_before_mutation() {
    local label="an unsupported distribution fails before any package work"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        get_os_version() { OS=Arch; VER=1; }
        apt_pkgs() { echo "apt_pkgs must not run" >&2; exit 99; }
        stage_setup_system
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" || "$status" == "99" ]]; then
        tap_fail "$label" "unsupported distro was not rejected (status $status)"
    elif ! grep -q "Unsupported distribution" "$sandbox/unit-err.txt"; then
        tap_fail "$label" "no clear unsupported-distribution message"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_sigint_releases_lock_and_children() {
    local label="SIGINT exits 130, releases the lock, and leaves no children"
    local sandbox driver_pid inner_pid status tries=0
    sandbox=$(make_sandbox)
    local driver_body
    driver_body=$(cat <<'BODY'
        sudo() { true; }
        install_traps
        start_sudo_keepalive
        mkdir -p "$cwd"
        acquire_build_root_lock
        printf "%s" "$$" > ready
        sleep 300 &
        wait $!
BODY
    )
    (cd "$sandbox" && env repo_root="$repo_root" SCRIPT_VERSION=0-test \
        timeout 60 bash -c "$(unit_preamble)
        $driver_body" >driver-out.txt 2>driver-err.txt </dev/null) &
    driver_pid=$!
    while [[ ! -s "$sandbox/ready" && "$tries" -lt 100 ]]; do
        sleep 0.1
        tries=$((tries + 1))
    done
    if [[ ! -s "$sandbox/ready" ]]; then
        tap_fail "$label" "the driver never reached the locked state"
        kill "$driver_pid" 2>/dev/null
        rm -rf -- "$sandbox"
        return
    fi
    inner_pid=$(<"$sandbox/ready")
    kill -INT "$inner_pid" 2>/dev/null
    wait "$driver_pid"
    status=$?
    if [[ "$status" != "130" ]]; then
        tap_fail "$label" "exit status was $status, expected 130: $(<"$sandbox/driver-err.txt")"
    elif ! flock -n "$sandbox/magick-build-script/.magick-build-lock" -c true; then
        tap_fail "$label" "the lock is still held after SIGINT"
    elif pgrep -f "$sandbox" >/dev/null 2>&1; then
        tap_fail "$label" "child processes survived SIGINT: $(pgrep -af "$sandbox")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

# --- Phase 3: archive validation, transactional cache, markers -------------

test_tar_validation_accepts_benign_archive() {
    local label="tar validation accepts a benign single-root archive"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        python3 - <<'PY'
import io, tarfile
t = tarfile.open("good.tar", "w")
for name in ("root/a.txt", "root/sub/b.txt"):
    info = tarfile.TarInfo(name)
    data = b"content"
    info.size = len(data)
    t.addfile(info, io.BytesIO(data))
link = tarfile.TarInfo("root/sub/uplink")
link.type = tarfile.SYMTYPE
link.linkname = "../a.txt"
t.addfile(link)
hard = tarfile.TarInfo("root/hard")
hard.type = tarfile.LNKTYPE
hard.linkname = "root/a.txt"
t.addfile(hard)
t.close()
PY
        validate_tar_archive good.tar
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_tar_validation_rejects_hostile_archives() {
    local label="tar validation rejects traversal/absolute/multi-root/fifo/setuid/link escapes"
    local sandbox status kind ok=1
    for kind in absolute traversal multiroot fifo setuid symlink_escape abs_symlink hardlink_escape control_char; do
        sandbox=$(make_sandbox)
        run_unit_in_sandbox "$sandbox" <<UNIT
        kind="$kind" python3 - <<'PY'
import io, os, tarfile
kind = os.environ["kind"]
t = tarfile.open("evil.tar", "w")
def add_file(name, mode=0o644):
    info = tarfile.TarInfo(name)
    info.mode = mode
    data = b"x"
    info.size = len(data)
    t.addfile(info, io.BytesIO(data))
def add_link(name, target, hard=False):
    info = tarfile.TarInfo(name)
    info.type = tarfile.LNKTYPE if hard else tarfile.SYMTYPE
    info.linkname = target
    t.addfile(info)
add_file("root/anchor.txt")
if kind == "absolute":
    add_file("/etc/evil")
elif kind == "traversal":
    add_file("root/../../evil")
elif kind == "multiroot":
    add_file("other/evil")
elif kind == "fifo":
    info = tarfile.TarInfo("root/fifo")
    info.type = tarfile.FIFOTYPE
    t.addfile(info)
elif kind == "setuid":
    add_file("root/suid", mode=0o4755)
elif kind == "symlink_escape":
    add_link("root/link", "../../etc/passwd")
elif kind == "abs_symlink":
    add_link("root/link", "/etc/passwd")
elif kind == "hardlink_escape":
    add_link("root/hard", "elsewhere/file", hard=True)
elif kind == "control_char":
    add_file("root/evil\x01name")
t.close()
PY
        if (validate_tar_archive evil.tar) >/dev/null 2>&1; then
            exit 7
        fi
        exit 0
UNIT
        status=$(<"$sandbox/status.txt")
        if [[ "$status" != "0" ]]; then
            tap_fail "$label" "kind '$kind' was not rejected (status $status): $(<"$sandbox/unit-err.txt")"
            ok=0
            rm -rf -- "$sandbox"
            break
        fi
        rm -rf -- "$sandbox"
    done
    [[ "$ok" -eq 1 ]] && tap_ok "$label"
}

test_extraction_publishes_nothing_on_failure() {
    local label="failed extraction publishes no target directory"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        echo "this is not a tar archive" > "$packages/broken.tar"
        extract_archive_to_build_dir broken.tar "$packages/broken"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a broken archive did not abort (status $status)"
    elif [[ -e "$sandbox/magick-build-script/packages/broken" ]]; then
        tap_fail "$label" "a target directory was published for a broken archive"
    elif compgen -G "$sandbox/magick-build-script/packages/.extract.*" >/dev/null; then
        tap_fail "$label" "an extraction temp directory was left behind"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_checksum_roundtrip_and_tamper_detection() {
    local label="archive checksum records validate and detect tampering"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        printf 'payload' > "$packages/thing.tar"
        write_archive_checksum thing.tar
        archive_checksum_matches thing.tar || exit 7
        printf 'tampered' > "$packages/thing.tar"
        archive_checksum_matches thing.tar && exit 8
        exit 0
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "a freshly written checksum did not validate" ;;
        8) tap_fail "$label" "tampering was not detected" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_download_publishes_only_on_success() {
    local label="download publishes to the cache only after a successful transfer"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        python3 - <<'PY'
import io, tarfile
t = tarfile.open("good.tar", "w")
info = tarfile.TarInfo("root/a.txt")
data = b"content"
info.size = len(data)
t.addfile(info, io.BytesIO(data))
t.close()
PY
        curl() {
            local out=""
            while [[ $# -gt 0 ]]; do
                if [[ "$1" == "--output" ]]; then out="$2"; shift 2; else shift; fi
            done
            cp good.tar "$out"
        }
        download_archive_to_cache pkg.tar "https://example.invalid/pkg.tar"
        [[ -f "$packages/pkg.tar" ]] || exit 7
        archive_checksum_matches pkg.tar || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the archive was not published to the cache" ;;
        8) tap_fail "$label" "no valid checksum record was written" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_failed_download_leaves_no_partial_file() {
    local label="a failed download leaves no cache entry and no part-file"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        curl() {
            local out=""
            while [[ $# -gt 0 ]]; do
                if [[ "$1" == "--output" ]]; then out="$2"; shift 2; else shift; fi
            done
            echo "partial junk" > "$out"
            return 22
        }
        download_archive_to_cache pkg.tar "https://example.invalid/pkg.tar"
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a failed transfer did not abort (status $status)"
    elif [[ -e "$sandbox/magick-build-script/packages/pkg.tar" ]]; then
        tap_fail "$label" "a partial archive was published to the cache"
    elif compgen -G "$sandbox/magick-build-script/packages/.pkg.tar.part.*" >/dev/null; then
        tap_fail "$label" "a part-file was left behind"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_valid_cache_skips_the_network() {
    local label="a validated cached archive is reused without calling curl"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        python3 - <<'PY'
import io, tarfile
t = tarfile.open("good.tar", "w")
info = tarfile.TarInfo("root/a.txt")
data = b"content"
info.size = len(data)
t.addfile(info, io.BytesIO(data))
t.close()
PY
        cp good.tar "$packages/pkg.tar"
        write_archive_checksum pkg.tar
        curl() { echo "curl must not be called for a valid cache" >&2; exit 99; }
        download_archive_to_cache pkg.tar "https://example.invalid/pkg.tar"
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" != "0" ]]; then
        tap_fail "$label" "status $status: $(<"$sandbox/unit-err.txt")"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_corrupt_cache_is_refetched() {
    local label="a corrupt cached archive is wiped and refetched"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages"
        python3 - <<'PY'
import io, tarfile
t = tarfile.open("good.tar", "w")
info = tarfile.TarInfo("root/a.txt")
data = b"content"
info.size = len(data)
t.addfile(info, io.BytesIO(data))
t.close()
PY
        echo "corrupt cached bytes" > "$packages/pkg.tar"
        write_archive_checksum pkg.tar
        curl() {
            local out=""
            while [[ $# -gt 0 ]]; do
                if [[ "$1" == "--output" ]]; then out="$2"; shift 2; else shift; fi
            done
            cp good.tar "$out"
        }
        download_archive_to_cache pkg.tar "https://example.invalid/pkg.tar"
        tar -tf "$packages/pkg.tar" >/dev/null || exit 7
        archive_checksum_matches pkg.tar || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the corrupt archive was not replaced" ;;
        8) tap_fail "$label" "the refreshed checksum record is invalid" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_build_done_requires_artifacts() {
    local label="build_done refuses to record completion without artifacts"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace"
        build_done m4 1.4.19
        exit 7
UNIT
    status=$(<"$sandbox/status.txt")
    if [[ "$status" == "0" || "$status" == "7" ]]; then
        tap_fail "$label" "a marker was recorded without artifacts (status $status)"
    elif [[ -e "$sandbox/magick-build-script/packages/m4.done" ]]; then
        tap_fail "$label" "a marker file exists despite the refusal"
    else
        tap_ok "$label"
    fi
    rm -rf -- "$sandbox"
}

test_marker_records_version_and_commit() {
    local label="markers record version plus commit and read back exactly"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace/bin"
        printf '#!/bin/sh\n' > "$workspace/bin/m4"
        chmod 755 "$workspace/bin/m4"
        commit="0123456789abcdef0123456789abcdef01234567"
        build_done m4 1.4.19 "$commit"
        [[ "$(read_marker_version m4)" == "1.4.19" ]] || exit 7
        [[ "$(read_marker_commit m4)" == "$commit" ]] || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the recorded version did not read back" ;;
        8) tap_fail "$label" "the recorded commit did not read back" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_build_skips_when_marker_and_artifacts_match() {
    local label="build skips a package whose marker and artifacts are intact"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace/bin"
        printf '#!/bin/sh\n' > "$workspace/bin/m4"
        chmod 755 "$workspace/bin/m4"
        build_done m4 1.4.19
        if build m4 1.4.19; then exit 7; fi
        exit 0
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "the package was not skipped" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_build_self_heals_marker_without_artifacts() {
    local label="build self-heals a marker whose artifacts are gone"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace"
        printf '1.4.19\n' > "$packages/m4.done"
        build m4 1.4.19 || exit 7
        [[ ! -e "$packages/m4.done" ]] || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "build did not request a rebuild" ;;
        8) tap_fail "$label" "the stale marker was not removed" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
    rm -rf -- "$sandbox"
}

test_legacy_marker_triggers_rebuild() {
    local label="a legacy/malformed marker is treated as absent"
    local sandbox status
    sandbox=$(make_sandbox)
    run_unit_in_sandbox "$sandbox" <<'UNIT'
        mkdir -p "$packages" "$workspace/bin"
        printf '#!/bin/sh\n' > "$workspace/bin/m4"
        chmod 755 "$workspace/bin/m4"
        printf 'not a! valid marker line\n' > "$packages/m4.done"
        build m4 1.4.19 || exit 7
        [[ ! -e "$packages/m4.done" ]] || exit 8
UNIT
    status=$(<"$sandbox/status.txt")
    case "$status" in
        0) tap_ok "$label" ;;
        7) tap_fail "$label" "a malformed marker was accepted" ;;
        8) tap_fail "$label" "the malformed marker was not removed" ;;
        *) tap_fail "$label" "unexpected status $status: $(<"$sandbox/unit-err.txt")" ;;
    esac
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
test_tar_validation_accepts_benign_archive
test_tar_validation_rejects_hostile_archives
test_extraction_publishes_nothing_on_failure
test_checksum_roundtrip_and_tamper_detection
test_download_publishes_only_on_success
test_failed_download_leaves_no_partial_file
test_valid_cache_skips_the_network
test_corrupt_cache_is_refetched
test_build_done_requires_artifacts
test_marker_records_version_and_commit
test_build_skips_when_marker_and_artifacts_match
test_build_self_heals_marker_without_artifacts
test_legacy_marker_triggers_rebuild
test_tag_selection_handles_libjpeg_turbo_grammar
test_tag_selection_prefers_peeled_commit
test_tag_selection_excludes_prereleases
test_tag_selection_handles_ghostscript_and_freetype
test_tag_selection_fails_closed_on_empty_input
test_tag_selection_survives_large_input_under_pipefail
test_resolve_reuses_marker_without_network
test_latest_flag_forces_resolution
test_git_clone_verifies_pinned_commit
test_apt_fails_closed_on_unavailable_required_package
test_no_autoremove_anywhere
test_unsupported_distro_fails_before_mutation
test_sigint_releases_lock_and_children
test_magick_validation_accepts_good_install
test_magick_validation_rejects_missing_delegate
test_magick_validation_rejects_version_mismatch
test_staged_validation_rejects_out_of_prefix_files

printf '1..%d\n' "$test_count"
if [[ "$fail_count" -gt 0 ]]; then
    printf '# FAILED: %d of %d tests\n' "$fail_count" "$test_count"
    exit 1
fi
printf '# All %d tests passed\n' "$test_count"
