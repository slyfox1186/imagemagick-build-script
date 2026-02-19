# shellcheck shell=bash

download_fonts() {
    local -a font_urls=(
        "https://github.com/dejavu-fonts/dejavu-fonts.git"
        "https://github.com/adobe-fonts/source-code-pro.git"
        "https://github.com/adobe-fonts/source-sans-pro.git"
        "https://github.com/adobe-fonts/source-serif-pro.git"
        "https://github.com/googlefonts/roboto.git"
        "https://github.com/mozilla/Fira.git"
    )
    local font_url repo_name
    for font_url in "${font_urls[@]}"; do
        repo_name="${font_url##*/}"
        repo_name="${repo_name%.git}"
        git_caller "$font_url" "$repo_name"
        if build "$repo_name" "$version"; then
            git_clone "$git_url" "$repo_name" "$recurse_flag" "$version"
            execute use_root cp -fr . "/usr/share/fonts/truetype/"
            build_done "$repo_name" "$version"
        fi
    done
}

# Download and install fonts
download_fonts
