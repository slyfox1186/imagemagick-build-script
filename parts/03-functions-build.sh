# shellcheck shell=bash

execute() {
    echo "$ $*"
    local output

    if [[ "$debug" == "ON" ]]; then
        if ! output=$("$@"); then
            notify-send -t 5000 "Failed to execute: $*" 2>/dev/null
            fail "Failed to execute: $*"
        fi
    else
        if ! output=$("$@" 2>&1); then
            notify-send -t 5000 "Failed to execute: $*" 2>/dev/null
            echo "$output" >&2
            fail "Failed to execute: $*. Line: ${LINENO}"
        fi
    fi
}

build() {
    echo
    echo -e "${GREEN}Building ${YELLOW}$1${NC} - ${GREEN}version ${YELLOW}$2${NC}"
    echo "=========================================="

    if [[ -f "$packages/$1.done" ]]; then
        if grep -Fx "$2" "$packages/$1.done" >/dev/null; then
            echo "$1 version $2 already built. Remove $packages/$1.done lockfile to rebuild it."
            return 1
        fi
    fi
    return 0
}

build_done() {
    echo "$2" > "$packages/$1.done"
}

download() {
    local archive url output_dir target_file target_dir
    url="$1"
    archive="${2:-${url##*/}}"
    output_dir="$3"
    target_file="$packages/$archive"
    target_dir="$packages/${output_dir:-${archive%.tar*}}"

    if [[ ! -f "$target_file" ]]; then
        log "Downloading \"$url\" saving as \"$archive\""
        if ! curl -fLSso "$target_file" "$url"; then
            fail "Failed to download \"$archive\". Line: ${LINENO}"
        fi
    else
        log "The file \"$archive\" is already downloaded."
    fi

    [[ -d "$target_dir" ]] && safe_rm_rf "$target_dir"
    [[ ! -d "$target_dir" ]] && mkdir -p "$target_dir"

    if [[ -n "$output_dir" ]]; then
        if ! tar -xf "$target_file" -C "$target_dir" 2>/dev/null; then
            rm "$target_file"
            fail "Failed to extract \"$archive\". Line: ${LINENO}"
        fi
    else
        if ! tar -xf "$target_file" -C "$target_dir" --strip-components=1 2>/dev/null; then
            rm "$target_file"
            fail "Failed to extract \"$archive\". Line: ${LINENO}"
        fi
    fi

    log "File extracted: $archive"
    cd "$target_dir" || fail "Unable to change the working directory to \"$target_dir\" Line: ${LINENO}"
}

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
