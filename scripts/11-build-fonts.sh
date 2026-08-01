#!/usr/bin/env bash
# shellcheck shell=bash

# Install only real font files (.ttf/.otf) into a per-family directory.
# The old behavior copied entire repositories - .git history, sources,
# build scripts - straight into /usr/share/fonts/truetype/.
install_font_files() {
    local repo_name="$1" font_file
    local dest="/usr/share/fonts/truetype/$1"
    local -a font_files=()
    while IFS= read -r -d '' font_file; do
        font_files+=("$font_file")
    done < <(find . -type f \( -iname '*.ttf' -o -iname '*.otf' \) -not -path './.git/*' -print0)
    [[ "${#font_files[@]}" -gt 0 ]] ||
        fail "No .ttf/.otf files found in the $repo_name repository; refusing to record it as installed."
    execute exec_root mkdir -p "$dest"
    execute exec_root install -m 644 -t "$dest" "${font_files[@]}"
    log "Installed ${#font_files[@]} font files to $dest"
}

stage_install_fonts() {
    # DejaVu is deliberately NOT in this list: its source repository ships
    # no built .ttf/.otf at HEAD (verified), so cloning it never installed
    # a usable font. The fonts-dejavu-core APT package provides
    # /usr/share/fonts/truetype/dejavu - the exact directory ImageMagick's
    # --with-dejavu-font-dir points at.
    local -a font_urls=(
        "https://github.com/adobe-fonts/source-code-pro.git"
        "https://github.com/adobe-fonts/source-sans-pro.git"
        "https://github.com/adobe-fonts/source-serif-pro.git"
        "https://github.com/googlefonts/roboto.git"
        "https://github.com/mozilla/Fira.git"
    )
    local font_url repo_name resolved ver commit

    for font_url in "${font_urls[@]}"; do
        repo_name="${font_url##*/}"
        repo_name="${repo_name%.git}"
        # Font repositories are pinned to their HEAD commit: their newest
        # tags are years older than the current content (dejavu's newest
        # tag is from 2016), so a tag pin would silently regress fonts.
        resolved=$(resolve_pkg_version "$repo_name" resolve_git_head "$font_url") ||
            fail "Failed to resolve the HEAD commit for $repo_name."
        IFS='|' read -r _ ver commit <<<"$resolved"
        if build "$repo_name" "$ver"; then
            git_clone "$font_url" "$repo_name" "" "$commit"
            install_font_files "$repo_name"
            build_done "$repo_name" "$ver"
        fi
    done

    # Rebuild the fontconfig cache so ImageMagick can see the new fonts.
    execute exec_root fc-cache -f
}
