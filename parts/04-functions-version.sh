# shellcheck shell=bash

# Parse each git repository to find the latest release version number for each program
gnu_repo() {
    local url="$1"
    version=$(curl -fsS "$url" | grep -oP '[a-z]+-\K(([0-9\.]*[0-9]+)){2,}' | sort -rV | head -n1)
}

github_repo() {
    local count git_repo git_url
    git_repo="$1"
    git_url="$2"
    count=1
    version=""

    # Fetch GitHub tags page
    while [[ $count -le 10 ]]; do
        # Apply case-insensitive matching for RC versions to exclude them
        version=$(curl -fsSL "https://github.com/$git_repo/$git_url" |
                grep -oP 'href="[^"]*/tags/[^"]*\.tar\.gz"' |
                grep -oP '\/tags\/\K(v?[\w.-]+?)(?=\.tar\.gz)' |
                grep -iPv '(rc)[0-9]*' | head -n1 | sed 's/^v//')

        # Check if a non-RC version was found
        if [[ -n "$version" ]]; then
            break
        else
            ((count++))
        fi
    done
    # Handle cases where only release candidate versions are found after the script reaches the maximum attempts
    [[ -z "$version" ]] && fail "No matching version found without RC/rc suffix. Line: ${LINENO}"
}

gitlab_freedesktop_repo() {
    local count repo curl_results
    repo="$1"
    count=0
    version=""

    while true; do
        if curl_results=$(curl -fsSL "https://gitlab.freedesktop.org/api/v4/projects/$repo/repository/tags"); then
            version=$(echo "$curl_results" | jq -r ".[$count].name")
            version="${version#v}"

            # Check if the version contains "RC" and skip it
            if [[ $version =~ $regex_string ]]; then
                ((count++))
            else
                break # Exit the loop when a non-RC version is found
            fi
        else
            fail "Failed to fetch data from GitLab API. Line: ${LINENO}"
        fi
    done
}

gitlab_gnome_repo() {
    local count repo url curl_results
    repo="$1"
    url="$2"
    count=0
    version=""

    [[ -z "$repo" ]] && fail "Repository name is required. Line: ${LINENO}"

    if curl_results=$(curl -fsSL "https://gitlab.gnome.org/api/v4/projects/$repo/repository/$url"); then
        version=$(echo "$curl_results" | jq -r '.[0].name')
        version="${version#v}"
    fi

    # Deny installing a release candidate
    while [[ $version =~ $regex_string ]]; do
        if curl_results=$(curl -fsSL "https://gitlab.gnome.org/api/v4/projects/$repo/repository/$url"); then
            version=$(echo "$curl_results" | jq -r ".[$count].name" | sed 's/^v//')
        fi
        ((count++))
    done
}

find_git_repo() {
    local url="$1"
    local git_repo_type="$2"
    local url_action="$3"
    local set_repo set_action

    case "$git_repo_type" in
        1) set_repo="github_repo" ;;
        2) set_repo="gitlab_freedesktop_repo" ;;
        3) set_repo="gitlab_gnome_repo" ;;
        *) fail "Error: Could not detect the variable \"\$git_repo_type\" in the function \"find_git_repo\". Line: ${LINENO}"
    esac

    case "$url_action" in
        T) set_action="tags" ;;
        *) set_action="$3" ;;
    esac

    "$set_repo" "$url" "$set_action" 2>/dev/null
}

find_ghostscript_version() {
    version="$1"
    formatted_version=$(
                        echo "$version" |
                        sed -E 's/gs([0-9]{2})([0-9]{2})([0-9])/\1.\2.\3/'
                    )
    gscript_url="https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/${version}/ghostscript-${formatted_version}.tar.xz"
}
