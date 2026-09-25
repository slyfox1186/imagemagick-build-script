#!/usr/bin/env bash
# shellcheck shell=bash

# Install only real font files (.ttf/.otf) into a per-family directory.
# The old behavior copied entire repositories - .git history, sources,
# build scripts - straight into /usr/share/fonts/truetype/.
install_font_files() {
    local repo_name="$1" font_file
    local dest="/usr/share/fonts/truetype/$1"
    local -a font_files=() install_cmd
    while IFS= read -r -d '' font_file; do
        font_files+=("$font_file")
    done < <(find . -type f \( -iname '*.ttf' -o -iname '*.otf' \) -not -path './.git/*' -print0)
    [[ "${#font_files[@]}" -gt 0 ]] ||
        fail "No .ttf/.otf files found in the $repo_name repository; refusing to record it as installed."
    # -D creates $dest. The terminal shows a file count, not the file list.
    install_cmd=(exec_root install -D -m 644 -t "$dest")
    execute_as "${install_cmd[*]} <${#font_files[@]} font files>" \
        "${install_cmd[@]}" "${font_files[@]}"
}

stage_install_fonts() {
    # DejaVu is deliberately NOT in this list: its source repository ships
    # no built .ttf/.otf at HEAD (verified), so cloning it never installed
    # a usable font. The fonts-dejavu-core APT package provides
    # /usr/share/fonts/truetype/dejavu - the exact directory ImageMagick's
    # --with-dejavu-font-dir points at. Font repositories are pinned to
    # their HEAD commit (see resolve_pkg): their newest tags are years
    # older than current content, so a tag pin would regress fonts.
    local -a font_repos=(source-code-pro source-sans-pro source-serif-pro roboto Fira)
    local repo_name tag ver commit fonts_enabled=0

    for repo_name in "${font_repos[@]}"; do
        if package_enabled "$repo_name"; then
            fonts_enabled=1
        fi
        resolve_into "$repo_name"
        if build "$repo_name" "$ver"; then
            git_clone "$(pkg_repo_url "$repo_name")" "$repo_name" "" "$commit"
            install_font_files "$repo_name"
            build_done "$repo_name" "$ver"
        fi
    done

    # Rebuild the fontconfig cache so ImageMagick can see the new fonts.
    # Skipped when the config disabled every font repo: no fonts were
    # touched, and the cache refresh is the stage's only privileged step.
    if [[ "$fonts_enabled" -eq 1 ]]; then
        execute exec_root fc-cache -f
    fi
}
