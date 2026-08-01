#!/usr/bin/env bash
# shellcheck shell=bash

CURL_USER_AGENT="imagemagick-build-script/$SCRIPT_VERSION (+https://github.com/slyfox1186/imagemagick-build-script)"

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
        jpeg-turbo-git|libjpeg-turbo) workspace_lib_exists libjpeg ;;
        libfpx-git|libfpx) workspace_lib_exists libfpx ;;
        ghostscript) [[ -x "$workspace/bin/gs" ]] ;;
        libpng)      workspace_pc_exists libpng16 ;;
        libpng12)    workspace_lib_exists libpng12 ;;
        libwebp-git|libwebp) workspace_lib_exists libwebp ;;
        freetype)    workspace_pc_exists freetype2 ;;
        libxml2)     workspace_pc_exists libxml-2.0 ;;
        fontconfig)  workspace_pc_exists fontconfig ;;
        fribidi)     workspace_pc_exists fribidi ;;
        harfbuzz)    workspace_pc_exists harfbuzz ;;
        raqm)        workspace_pc_exists raqm ;;
        jemalloc)    workspace_pc_exists jemalloc ;;
        opencl-sdk-git|opencl-sdk) workspace_lib_exists libOpenCL ;;
        openjpeg)    workspace_pc_exists libopenjp2 ;;
        lcms2)       workspace_pc_exists lcms2 ;;
        dejavu-fonts|source-code-pro|source-sans-pro|source-serif-pro|roboto|Fira)
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
    if ! listing=$(tar -tvf "$archive_path" 2>/dev/null); then
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
                print "unsupported member type \x27" type "\x27: " $0
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
            if (name ~ /[\x01-\x1f\x7f]/) { print "control characters in a member name"; exit 1 }
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

download() {
    local url="$1" archive="${2:-${1##*/}}" target_dir
    download_archive_to_cache "$archive" "$url"
    target_dir="$packages/${archive%.tar*}"
    extract_archive_to_build_dir "$archive" "$target_dir"
    cd "$target_dir" || fail "Unable to change the working directory to \"$target_dir\"."
}

download_with_fallback() {
    local primary_url="$1" fallback_url="$2" archive="${3:-${1##*/}}" target_dir
    download_archive_to_cache "$archive" "$primary_url" "$fallback_url"
    target_dir="$packages/${archive%.tar*}"
    extract_archive_to_build_dir "$archive" "$target_dir"
    cd "$target_dir" || fail "Unable to change the working directory to \"$target_dir\"."
}

# ---------------------------------------------------------------------------
# Git sources
# ---------------------------------------------------------------------------

git_latest_version() {
    local repo_url="$1"
    local tag_list="" latest="" head_info=""

    if ! tag_list=$(git ls-remote --tags "$repo_url" 2>/dev/null); then
        return 1
    fi

    latest=$(printf '%s\n' "$tag_list" |
        awk -F'/' '/\/v?[0-9]+\.[0-9]+(\.[0-9]+)?(-[0-9]+)?(\^\{\})?$/ {
            tag = $3;
            sub(/^v/, "", tag);
            print tag
        }' |
        grep -v '\^{}' |
        sort -rV |
        head -n1
    )

    if [[ -z "$latest" ]]; then
        if ! head_info=$(git ls-remote "$repo_url" 2>/dev/null); then
            return 1
        fi
        latest=$(printf '%s\n' "$head_info" | awk '/HEAD/ {print substr($1,1,7)}')
    fi

    [[ -z "$latest" ]] && latest="unknown"
    printf '%s' "$latest"
}

git_caller() {
    git_url="$1"
    repo_name="$2"
    recurse_flag=0

    [[ "$3" == "recurse" ]] && recurse_flag=1

    version=$(git_latest_version "$git_url") || fail "Failed to determine latest version for \"$git_url\". Line: ${LINENO}"
}

git_clone() {
    local repo_url repo_name target_directory version store_prior_version recurse_opt
    local recurse="${3:-0}"
    local version_arg="${4:-}"

    repo_url="$1"
    repo_name="${2:-"${1##*/}"}"
    repo_name="${repo_name//\./-}"
    target_directory="$packages/$repo_name"

    if [[ -n "$version_arg" ]]; then
        version="$version_arg"
    else
        version=$(git_latest_version "$repo_url") || fail "Failed to determine latest version for \"$repo_url\". Line: ${LINENO}"
    fi

    [[ -f "$packages/$repo_name.done" ]] && store_prior_version=$(<"$packages/$repo_name.done")

    if [[ ! "$version" == "$store_prior_version" ]]; then
        [[ "$recurse" -eq 1 ]] && recurse_opt="--recursive"
        [[ -d "$target_directory" ]] && safe_rm_rf "$target_directory"
        log "Cloning repo: $repo_name"
        # Clone the repository
        if ! git clone --depth 1 ${recurse_opt:+"$recurse_opt"} -q "$repo_url" "$target_directory"; then
            echo
            echo -e "${RED}[ERROR]${NC} Failed to clone \"$target_directory\". Second attempt in 10 seconds..."
            echo
            sleep 10
            if ! git clone --depth 1 ${recurse_opt:+"$recurse_opt"} -q "$repo_url" "$target_directory"; then
                fail "Failed to clone \"$target_directory\". Exiting script. Line: ${LINENO}"
            fi
        fi
        cd "$target_directory" || fail "Failed to cd into \"$target_directory\". Line: ${LINENO}"
    fi

    log "Cloning completed: $version"
    return 0
}

show_version() {
    echo
    log "ImageMagick's new version is:"
    echo
    magick -version 2>/dev/null || fail "Failure to execute the command: magick -version. Line: ${LINENO}"
}
