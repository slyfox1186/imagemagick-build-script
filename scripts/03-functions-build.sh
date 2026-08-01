#!/usr/bin/env bash
# shellcheck shell=bash

CURL_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64; rv:153.0) Gecko/20100101 Firefox/153.0'

# ---------------------------------------------------------------------------
# Completion markers and artifact contracts
# ---------------------------------------------------------------------------

workspace_pc_exists() {
    local dir
    for dir in "$workspace/lib/pkgconfig" "$workspace/lib64/pkgconfig" \
        "$workspace/lib/$MULTIARCH_TUPLE/pkgconfig" "$workspace/share/pkgconfig"; do
        [[ -f "$dir/$1.pc" ]] && return 0
    done
    return 1
}

workspace_lib_exists() {
    local dir ext
    for dir in "$workspace/lib" "$workspace/lib64" "$workspace/lib/$MULTIARCH_TUPLE"; do
        for ext in a so; do
            [[ -e "$dir/$1.$ext" ]] && return 0
        done
    done
    return 1
}

font_dir_populated() {
    [[ -d "/usr/share/fonts/truetype/$1" ]] &&
        find "/usr/share/fonts/truetype/$1" -mindepth 1 -print -quit 2>/dev/null | grep -q .
}

# Every package must define a concrete artifact check: a completion marker
# without usable output is a lie, so build_done refuses to write one and
# build() self-heals by rebuilding when the artifacts have vanished.
package_artifacts_present() {
    local name="$1"
    case "$name" in
        m4)          [[ -x "$workspace/bin/m4" ]] ;;
        libtool)     [[ -x "$workspace/bin/libtool" ]] ;;
        pkg-config)  [[ -x "$workspace/bin/pkg-config" ]] ;;
        libtiff)     workspace_pc_exists libtiff-4 ;;
        libjpeg-turbo) workspace_lib_exists libjpeg ;;
        libfpx)      workspace_lib_exists libfpx ;;
        ghostscript) [[ -x "$workspace/bin/gs" ]] ;;
        libpng)      workspace_pc_exists libpng16 ;;
        libwebp)     workspace_lib_exists libwebp ;;
        freetype)    workspace_pc_exists freetype2 ;;
        libxml2)     workspace_pc_exists libxml-2.0 ;;
        fontconfig)  workspace_pc_exists fontconfig ;;
        fribidi)     workspace_pc_exists fribidi ;;
        harfbuzz)    workspace_pc_exists harfbuzz ;;
        raqm)        workspace_pc_exists raqm ;;
        jemalloc)    workspace_pc_exists jemalloc ;;
        opencl-sdk)  workspace_lib_exists libOpenCL ;;
        openjpeg)    workspace_pc_exists libopenjp2 ;;
        lcms2)       workspace_pc_exists lcms2 ;;
        source-code-pro|source-sans-pro|source-serif-pro|roboto|Fira)
            font_dir_populated "$name" ;;
        imagemagick) [[ -x /usr/local/bin/magick ]] ;;
        *) fail "No artifact contract is defined for package '$name'." ;;
    esac
}

# Marker format: "VERSION" or "VERSION COMMIT" (full 40-char commit hash).
# Anything else is treated as absent so a legacy or truncated marker causes
# a clean rebuild instead of a wrong-version reuse.
read_marker_version() {
    local file="$packages/$1.done" line
    [[ -f "$file" && ! -L "$file" ]] || return 1
    IFS= read -r line <"$file" || [[ -n "$line" ]] || return 1
    [[ "$line" =~ ^([A-Za-z0-9][A-Za-z0-9._+-]*)([[:space:]]([0-9a-f]{40}))?$ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[1]}"
}

read_marker_commit() {
    local file="$packages/$1.done" line
    [[ -f "$file" && ! -L "$file" ]] || return 1
    IFS= read -r line <"$file" || [[ -n "$line" ]] || return 1
    [[ "$line" =~ ^([A-Za-z0-9][A-Za-z0-9._+-]*)[[:space:]]([0-9a-f]{40})$ ]] || return 1
    printf '%s\n' "${BASH_REMATCH[2]}"
}

# Returns 0 when the package must be built, 1 when it can be skipped.
build() {
    local name="$1" version="$2" recorded
    # Central config gate: stage code calls resolve_into/build
    # unconditionally, and disabled packages fall through here.
    if ! package_enabled "$name"; then
        echo
        log "$name is disabled by the package selection config; skipping."
        return 1
    fi
    echo
    echo -e "${GREEN}Building ${YELLOW}$name${NC} - ${GREEN}version ${YELLOW}$version${NC}"
    echo "=========================================="

    if recorded=$(read_marker_version "$name"); then
        if [[ "$recorded" == "$version" ]]; then
            if package_artifacts_present "$name"; then
                echo "$name version $version already built. To force a rebuild run: rm -f -- \"$packages/$name.done\""
                return 1
            fi
            warn "A completion marker for $name exists but its artifacts are missing; rebuilding."
            rm -f -- "$packages/$name.done"
        fi
    elif [[ -e "$packages/$name.done" ]]; then
        warn "The completion marker for $name is unreadable or in a legacy format; rebuilding."
        rm -f -- "$packages/$name.done"
    fi
    return 0
}

# Atomically record completion, but only when the package's artifact
# contract holds. Arguments: name version [commit].
build_done() {
    local name="$1" version="$2" commit="${3:-}" tmp
    package_artifacts_present "$name" ||
        fail "Refusing to record completion for '$name': its expected artifacts are missing."
    tmp=$(mktemp "$packages/.$name.done.XXXXXX") ||
        fail "Cannot create a completion marker for '$name'."
    if [[ -n "$commit" ]]; then
        printf '%s %s\n' "$version" "$commit" >"$tmp"
    else
        printf '%s\n' "$version" >"$tmp"
    fi
    mv -f -- "$tmp" "$packages/$name.done" ||
        fail "Cannot publish the completion marker for '$name'."
}

# A package whose configure options changed must rebuild even when its
# resolved version is unchanged (observed live: newly enabled delegate
# packages did nothing because ImageMagick's version marker still
# matched). The caller computes a fingerprint over its configure
# arguments; a mismatch or missing record invalidates the marker.
invalidate_marker_on_config_change() {
    local name="$1" fingerprint_file="$2" fingerprint="$3" recorded
    [[ -f "$packages/$name.done" ]] || return 0
    recorded=$(head -n 1 -- "$fingerprint_file" 2>/dev/null)
    if [[ "$recorded" != "$fingerprint" ]]; then
        warn "$name's configure options changed since the last build; rebuilding it."
        rm -f -- "$packages/$name.done"
    fi
}

record_configure_fingerprint() {
    local fingerprint_file="$1" fingerprint="$2" tmp
    tmp=$(mktemp "${fingerprint_file%/*}/.fingerprint.XXXXXX") ||
        fail "Cannot record the configure fingerprint."
    printf '%s\n' "$fingerprint" >"$tmp"
    mv -f -- "$tmp" "$fingerprint_file" ||
        fail "Cannot publish the configure fingerprint."
}

# ---------------------------------------------------------------------------
# Downloads: transactional cache with an integrity record
# ---------------------------------------------------------------------------

archive_checksum_path() {
    printf '%s\n' "$packages/$1.sha256"
}

# The digest is computed from our own download, so it is a CACHE-INTEGRITY
# record (detects partial writes and later corruption). It does NOT
# authenticate the upstream origin; transport trust comes from HTTPS with
# certificate verification (see the README trust notes).
write_archive_checksum() {
    local archive="$1" tmp sum
    sum=$(sha256sum -- "$packages/$archive") ||
        fail "Cannot hash the downloaded archive '$archive'."
    sum="${sum%% *}"
    tmp=$(mktemp "$packages/.$archive.sha256.XXXXXX") ||
        fail "Cannot create the checksum record for '$archive'."
    printf '%s  %s\n' "$sum" "$archive" >"$tmp"
    mv -f -- "$tmp" "$(archive_checksum_path "$archive")" ||
        fail "Cannot publish the checksum record for '$archive'."
}

archive_checksum_matches() {
    local archive="$1" record recorded actual
    record=$(archive_checksum_path "$archive")
    [[ -f "$record" && ! -L "$record" ]] || return 1
    recorded=$(awk 'NR == 1 {print $1}' "$record")
    [[ "$recorded" =~ ^[0-9a-f]{64}$ ]] || return 1
    actual=$(sha256sum -- "$packages/$archive") || return 1
    [[ "$recorded" == "${actual%% *}" ]]
}

curl_transfer() {
    local url="$1" output="$2"
    curl --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 1800 \
        --retry 5 --retry-delay 5 --retry-all-errors --retry-max-time 900 \
        --max-filesize 1073741824 \
        --user-agent "$CURL_USER_AGENT" \
        --output "$output" "$url"
}

# Small text fetch (release-directory listings) to stdout, same policy but
# tighter time budget.
curl_listing() {
    curl --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --tlsv1.2 \
        --connect-timeout 15 --max-time 120 \
        --retry 3 --retry-delay 5 --retry-all-errors --retry-max-time 300 \
        --user-agent "$CURL_USER_AGENT" \
        "$1"
}

# Fetch into a temporary part-file and publish into the cache only after tar
# can read the result, so an interrupted transfer can never poison the cache.
# A cached archive is revalidated (checksum + tar listing) before reuse and
# refetched when either check fails. Arguments: archive url [fallback_url].
download_archive_to_cache() {
    local archive="$1" url="$2" fallback_url="${3:-}" target tmp
    target="$packages/$archive"

    if [[ -f "$target" ]]; then
        if archive_checksum_matches "$archive" && tar -tf "$target" >/dev/null 2>&1; then
            log "The file \"$archive\" is already downloaded."
            return 0
        fi
        warn "The cached archive \"$archive\" failed validation; refetching it."
        rm -f -- "$target" "$(archive_checksum_path "$archive")"
    fi

    tmp=$(mktemp "$packages/.$archive.part.XXXXXX") ||
        fail "Cannot create a download temp file for '$archive'."
    log "Downloading \"$url\" saving as \"$archive\""
    if ! curl_transfer "$url" "$tmp"; then
        if [[ -n "$fallback_url" ]]; then
            warn "Primary download failed for \"$archive\", trying the fallback mirror."
            if ! curl_transfer "$fallback_url" "$tmp"; then
                rm -f -- "$tmp"
                fail "Failed to download \"$archive\" from both the primary and fallback URLs."
            fi
        else
            rm -f -- "$tmp"
            fail "Failed to download \"$archive\"."
        fi
    fi
    tar -tf "$tmp" >/dev/null 2>&1 || {
        rm -f -- "$tmp"
        fail "The downloaded file \"$archive\" is not a readable tar archive."
    }
    mv -f -- "$tmp" "$target" || {
        rm -f -- "$tmp"
        fail "Cannot publish \"$archive\" into the download cache."
    }
    write_archive_checksum "$archive"
}

# ---------------------------------------------------------------------------
# Extraction: validate the full member list, then extract transactionally
# ---------------------------------------------------------------------------

# GNU tar (>= 1.29) already refuses ".." members and strips leading "/" at
# extraction time; this validation is the explicit contract on top of that:
# a single top-level root, no traversal or absolute paths, no control
# characters, only file/dir/symlink/hardlink members, no setuid/setgid bits,
# and no symlink or hardlink that resolves outside the extracted tree.
validate_tar_archive() {
    local archive_path="$1" listing verdict tar_error
    # stderr is kept out of the listing: tar warnings (for example
    # "Removing leading '/'") would otherwise be parsed as member lines.
    # The quoting style is pinned so control/meta characters always appear
    # as backslash escapes regardless of environment defaults.
    if ! listing=$(tar --quoting-style=escape -tvf "$archive_path" 2>/dev/null); then
        tar_error=$(tar -tf "$archive_path" 2>&1 >/dev/null | head -n 3)
        fail "Cannot read the archive '$archive_path': ${tar_error:-tar listing failed}"
    fi
    [[ -n "$listing" ]] || fail "The archive '$archive_path' is empty."
    if ! verdict=$(printf '%s\n' "$listing" | LC_ALL=C awk '
        function walk_depth(start, path,   n, parts, i, d) {
            d = start
            n = split(path, parts, "/")
            for (i = 1; i <= n; i++) {
                if (parts[i] == "" || parts[i] == ".") continue
                if (parts[i] == "..") {
                    d--
                    if (d < 1) return -1
                } else {
                    d++
                }
            }
            return d
        }
        {
            mode = $1
            type = substr(mode, 1, 1)
            if (type !~ /^[-dlh]$/) {
                print "unsupported member type " type ": " $0
                exit 1
            }
            if (substr(mode, 2) ~ /[sS]/) {
                print "setuid/setgid mode bits: " $0
                exit 1
            }
            line = $0
            sub(/^[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ +[^ ]+ /, "", line)
            name = line
            target = ""
            if (type == "l") {
                idx = index(line, " -> ")
                if (idx == 0) { print "unparseable symlink entry: " $0; exit 1 }
                name = substr(line, 1, idx - 1)
                target = substr(line, idx + 4)
            } else if (type == "h") {
                idx = index(line, " link to ")
                if (idx == 0) { print "unparseable hardlink entry: " $0; exit 1 }
                name = substr(line, 1, idx - 1)
                target = substr(line, idx + 9)
            }
            # With --quoting-style=escape, control and meta characters in
            # member names surface as backslash escapes; a raw control byte
            # (non-GNU tar) is also rejected directly.
            if (name ~ /\\/ || name ~ /[[:cntrl:]]/) { print "escaped or control characters in a member name"; exit 1 }
            if (name ~ /^\//) { print "absolute member path: " name; exit 1 }
            if (name ~ /(^|\/)\.\.(\/|$)/) { print "path traversal in member name: " name; exit 1 }
            root = name
            sub(/\/.*$/, "", root)
            if (roots == "") roots = root
            else if (root != roots) { print "multiple top-level entries: " roots " and " root; exit 1 }
            if (type == "h") {
                if (target ~ /^\//) { print "absolute hardlink target: " name " -> " target; exit 1 }
                if (target ~ /(^|\/)\.\.(\/|$)/) { print "hardlink traversal: " name " -> " target; exit 1 }
                troot = target
                sub(/\/.*$/, "", troot)
                if (troot != roots) { print "hardlink escapes the archive: " name " -> " target; exit 1 }
            }
            if (type == "l") {
                if (target ~ /^\//) { print "absolute symlink target: " name " -> " target; exit 1 }
                dir = name
                if (dir ~ /\//) sub(/\/[^\/]*$/, "", dir)
                else dir = ""
                d = walk_depth(0, dir)
                if (walk_depth(d, target) < 0) {
                    print "symlink escapes the archive: " name " -> " target
                    exit 1
                }
            }
            entries++
        }
        END {
            if (entries == 0) { print "no members found"; exit 1 }
        }
    '); then
        fail "Archive validation failed for '$archive_path': ${verdict:-unknown reason}"
    fi
}

# Extract into a temporary directory next to the destination and swap it in
# only on success; the previous tree (if any) survives every failure path.
extract_archive_to_build_dir() {
    local archive="$1" target_dir="$2" tmpdir stale=""
    local archive_path="$packages/$archive"
    validate_tar_archive "$archive_path"
    tmpdir=$(mktemp -d "$packages/.extract.XXXXXX") ||
        fail "Cannot create an extraction temp directory for '$archive'."
    if ! tar -xf "$archive_path" -C "$tmpdir" --strip-components=1 \
        --no-same-owner --no-same-permissions --delay-directory-restore; then
        safe_remove_tree "$tmpdir" "$packages"
        rm -f -- "$archive_path" "$(archive_checksum_path "$archive")"
        fail "Failed to extract \"$archive\" (the archive was removed so the next run refetches it)."
    fi
    if [[ -e "$target_dir" ]]; then
        stale="$target_dir.stale.$$"
        mv -T -- "$target_dir" "$stale" || {
            safe_remove_tree "$tmpdir" "$packages"
            fail "Cannot set aside the previous source tree '$target_dir'."
        }
    fi
    if ! mv -T -- "$tmpdir" "$target_dir"; then
        [[ -n "$stale" ]] && mv -T -- "$stale" "$target_dir"
        safe_remove_tree "$tmpdir" "$packages"
        fail "Cannot publish the extracted tree for \"$archive\"."
    fi
    [[ -n "$stale" ]] && safe_remove_tree "$stale" "$packages"
    log "File extracted: $archive"
}

enter_extracted_archive() {
    local archive="$1"
    local target_dir="$packages/${archive%.tar*}"
    extract_archive_to_build_dir "$archive" "$target_dir"
    cd "$target_dir" || fail "Unable to change the working directory to \"$target_dir\"."
}

download() {
    local url="$1" archive="${2:-${1##*/}}"
    download_archive_to_cache "$archive" "$url"
    enter_extracted_archive "$archive"
}

download_with_fallback() {
    local primary_url="$1" fallback_url="$2" archive="${3:-${1##*/}}"
    download_archive_to_cache "$archive" "$primary_url" "$fallback_url"
    enter_extracted_archive "$archive"
}

# ---------------------------------------------------------------------------
# Git sources: hardened network calls, pure tag selection, pinned clones
# ---------------------------------------------------------------------------

# Overridable so offline tests can exercise git_clone against local
# fixture repositories; production runs only ever allow HTTPS.
GIT_PROTOCOL_POLICY=(-c protocol.allow=never -c protocol.https.allow=always)

hardened_git() {
    timeout --foreground "${GIT_OPERATION_TIMEOUT:-600}" \
        env GIT_TERMINAL_PROMPT=0 git "${GIT_PROTOCOL_POLICY[@]}" "$@"
}

# Full tag listing including the peeled (^{}) lines, which carry the commit
# an annotated tag actually points to.
resolve_git_tags() {
    hardened_git ls-remote --tags "$1"
}

# Pure selection over a `git ls-remote --tags` listing on stdin.
# Arguments: accept_regex [exclude_regex] [strip_prefix].
# Emits "tag|version|commit" for the highest stable tag.
#
# Design constraints, both verified in this repo's test battery:
# - Every upstream needs its own tag grammar. libjpeg-turbo alone carries
#   x.y.9z development tags plus inherited jpeg-9e/jpeg-10 tags that a
#   generic version sort would happily select.
# - The pipeline must consume all input: `sort -ruV | head -1` dies with
#   SIGPIPE (exit 141) under pipefail on large listings, so the maximum is
#   taken with an ascending sort and tail, which reads to EOF.
select_latest_stable_tag() {
    local accept="$1" exclude="${2:-}" prefix="${3:-}" input best_pair tag ver sha
    input=$(cat)
    [[ -n "$input" ]] || return 1
    best_pair=$(printf '%s\n' "$input" |
        ACCEPT_RE="$accept" EXCLUDE_RE="$exclude" STRIP_PREFIX="$prefix" awk -F'\t' '
        BEGIN {
            accept = ENVIRON["ACCEPT_RE"]
            exclude = ENVIRON["EXCLUDE_RE"]
            prefix = ENVIRON["STRIP_PREFIX"]
        }
        $2 ~ /^refs\/tags\// {
            tag = substr($2, 11)
            if (tag ~ /\^\{\}$/) next
            if (tag !~ accept) next
            if (exclude != "" && tag ~ exclude) next
            if (tolower(tag) ~ /(rc|alpha|beta|pre|dev|preview)[._-]?[0-9]*$/) next
            ver = tag
            if (prefix != "" && index(ver, prefix) == 1) ver = substr(ver, length(prefix) + 1)
            print ver "\t" tag
        }' | sort -V | tail -n 1)
    [[ -n "$best_pair" ]] || return 1
    ver="${best_pair%%$'\t'*}"
    tag="${best_pair#*$'\t'}"
    sha=$(printf '%s\n' "$input" |
        awk -F'\t' -v want="refs/tags/$tag^{}" '$2 == want {print $1}' | tail -n 1)
    [[ -n "$sha" ]] || sha=$(printf '%s\n' "$input" |
        awk -F'\t' -v want="refs/tags/$tag" '$2 == want {print $1}' | tail -n 1)
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || return 1
    printf '%s|%s|%s\n' "$tag" "$ver" "$sha"
}

# Network fetch + pure selection. Arguments: url accept [exclude] [prefix].
resolve_latest_git_tag() {
    local tags
    tags=$(resolve_git_tags "$1") || return 1
    printf '%s\n' "$tags" | select_latest_stable_tag "$2" "${3:-}" "${4:-}"
}

# For repositories whose tags cannot represent current content (the font
# repositories' newest tags are years older than HEAD): pin the HEAD commit
# itself as the version, so markers stay truthful.
resolve_git_head() {
    local head_line sha
    head_line=$(hardened_git ls-remote "$1" HEAD) || return 1
    sha=$(printf '%s\n' "$head_line" | awk 'NR == 1 {print $1}')
    [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || return 1
    printf '|%s|%s\n' "$sha" "$sha"
}

# Marker-first resolution: when a completion marker exists, its artifacts
# are intact, and --latest was not given, the recorded version is reused
# with NO network traffic. Arguments: name resolver-function [args...].
resolve_pkg_version() {
    local name="$1" marker_ver marker_commit
    shift
    if [[ "$latest_flag" -eq 0 ]] && marker_ver=$(read_marker_version "$name") &&
        package_artifacts_present "$name"; then
        marker_commit=$(read_marker_commit "$name" || true)
        printf '|%s|%s\n' "$marker_ver" "$marker_commit"
        return 0
    fi
    "$@"
}

# Clone the given ref at --depth 1 into a temp directory, verify that the
# cloned HEAD is exactly the commit resolution recorded (annotated tags are
# compared against their peeled commit; a moved tag fails instead of
# silently substituting different content), then swap it into place and cd
# there. Arguments: url name ref expected_commit [recurse].
git_clone() {
    local repo_url="$1" repo_name="$2" ref="$3" expected_commit="$4" recurse="${5:-0}"
    local target_directory="$packages/$repo_name" tmpdir cloned_head stale=""
    # Checking out a tag detaches HEAD by design; git's multi-line advice
    # about it is pure noise in a build log.
    local -a clone_args=(-c advice.detachedHead=false --depth 1 -q)
    [[ "$recurse" -eq 1 ]] && clone_args+=(--recursive --shallow-submodules)
    [[ -n "$ref" ]] && clone_args+=(--branch "$ref")

    tmpdir=$(mktemp -d "$packages/.clone.$repo_name.XXXXXX") ||
        fail "Cannot create a clone temp directory for '$repo_name'."
    log "Cloning repo: $repo_name${ref:+ (tag $ref)}"
    if ! hardened_git clone "${clone_args[@]}" "$repo_url" "$tmpdir/src"; then
        warn "Failed to clone \"$repo_name\". Second attempt in 10 seconds..."
        sleep 10
        safe_remove_tree "$tmpdir/src" "$packages"
        if ! hardened_git clone "${clone_args[@]}" "$repo_url" "$tmpdir/src"; then
            safe_remove_tree "$tmpdir" "$packages"
            fail "Failed to clone \"$repo_url\"."
        fi
    fi
    cloned_head=$(git -C "$tmpdir/src" rev-parse 'HEAD^{commit}') || {
        safe_remove_tree "$tmpdir" "$packages"
        fail "Cannot read HEAD of the fresh clone of '$repo_name'."
    }
    if [[ "$cloned_head" != "$expected_commit" ]]; then
        safe_remove_tree "$tmpdir" "$packages"
        fail "Clone verification failed for '$repo_name': HEAD $cloned_head is not the resolved commit $expected_commit (the ref may have moved upstream; rerun the script)."
    fi
    if [[ -e "$target_directory" ]]; then
        stale="$target_directory.stale.$$"
        mv -T -- "$target_directory" "$stale" || {
            safe_remove_tree "$tmpdir" "$packages"
            fail "Cannot set aside the previous checkout of '$repo_name'."
        }
    fi
    if ! mv -T -- "$tmpdir/src" "$target_directory"; then
        [[ -n "$stale" ]] && mv -T -- "$stale" "$target_directory"
        safe_remove_tree "$tmpdir" "$packages"
        fail "Cannot publish the checkout of '$repo_name'."
    fi
    [[ -n "$stale" ]] && safe_remove_tree "$stale" "$packages"
    safe_remove_tree "$tmpdir" "$packages"
    log "Cloning completed: $repo_name at $expected_commit"
    cd "$target_directory" || fail "Failed to cd into \"$target_directory\"."
}

# One-line installed-version summary; skipped when the build stage already
# displayed and validated the full version block this run.
show_version() {
    [[ -n "${MAGICK_VALIDATED:-}" ]] && return 0
    # Nothing to show when the config skipped the final application.
    package_enabled imagemagick || return 0
    local version_line
    version_line=$(/usr/local/bin/magick -version | head -n 1) ||
        fail "Failure to execute the command: /usr/local/bin/magick -version"
    log "Installed: ${version_line#Version: }"
}
