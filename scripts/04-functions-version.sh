#!/usr/bin/env bash
# shellcheck shell=bash

# Version resolution. Contract: every resolver prints "tag|version|commit"
# on stdout (tag/commit may be empty for tarball-only sources) and returns
# non-zero on any failure - an empty or "null" version can never leak into
# markers or download URLs. The repository URLs and per-repository tag
# grammars live ONLY in the two tables below; the build stages and
# tests/resolve-all-versions.sh both dispatch through resolve_pkg, so
# there is no second copy to keep in sync.

# GNU-style release-directory listing (m4, pkg-config): highest plain
# numeric "<name>-X.Y[.Z].tar.*" version. Rolling aliases like
# "m4-latest.tar.xz" never match, so markers always record a real version.
# Arguments: listing_url [fallback_listing_url...], tried in order.
gnu_repo() {
    local url listing ver
    for url in "$@"; do
        listing=$(curl_listing "$url") || continue
        ver=$(printf '%s\n' "$listing" |
            grep -oP '[a-zA-Z0-9_-]+-\K[0-9]+(\.[0-9]+)+(?=\.tar)' |
            sort -uV | tail -n 1)
        if [[ -n "$ver" ]]; then
            printf '|%s|\n' "$ver"
            return 0
        fi
    done
    return 1
}

# Ghostscript releases live in the ghostpdl-downloads repository with tags
# like gs10071 (= 10.07.1). The grammar is pinned to exactly five digits:
# a future six-digit tag would sort wrongly against five-digit ones, so it
# fails closed for a deliberate update instead.
resolve_ghostscript() {
    local trip tag commit fmt
    trip=$(resolve_latest_git_tag "$(pkg_repo_url ghostscript)" \
        '^gs[0-9][0-9][0-9][0-9][0-9]$') || return 1
    IFS='|' read -r tag _ commit <<<"$trip"
    fmt=$(printf '%s\n' "$tag" | sed -E 's/^gs([0-9]{2})([0-9]{2})([0-9])$/\1.\2.\3/')
    [[ "$fmt" != "$tag" ]] || return 1
    printf '%s|%s|%s\n' "$tag" "$fmt" "$commit"
}

# Upstream repository per package (also used by the clone call sites).
pkg_repo_url() {
    case "$1" in
        libtiff)          echo "https://github.com/libsdl-org/libtiff.git" ;;
        libjpeg-turbo)    echo "https://github.com/libjpeg-turbo/libjpeg-turbo.git" ;;
        libfpx)           echo "https://github.com/ImageMagick/libfpx.git" ;;
        ghostscript)      echo "https://github.com/ArtifexSoftware/ghostpdl-downloads.git" ;;
        libpng)           echo "https://github.com/pnggroup/libpng.git" ;;
        libwebp)          echo "https://chromium.googlesource.com/webm/libwebp" ;;
        freetype)         echo "https://gitlab.freedesktop.org/freetype/freetype.git" ;;
        libxml2)          echo "https://gitlab.gnome.org/GNOME/libxml2.git" ;;
        fontconfig)       echo "https://gitlab.freedesktop.org/fontconfig/fontconfig.git" ;;
        fribidi)          echo "https://github.com/fribidi/fribidi.git" ;;
        harfbuzz)         echo "https://github.com/harfbuzz/harfbuzz.git" ;;
        raqm)             echo "https://github.com/host-oman/libraqm.git" ;;
        jemalloc)         echo "https://github.com/jemalloc/jemalloc.git" ;;
        opencl-sdk)       echo "https://github.com/KhronosGroup/OpenCL-SDK.git" ;;
        openjpeg)         echo "https://github.com/uclouvain/openjpeg.git" ;;
        lcms2)            echo "https://github.com/mm2/Little-CMS.git" ;;
        imagemagick)      echo "https://github.com/ImageMagick/ImageMagick.git" ;;
        source-code-pro)  echo "https://github.com/adobe-fonts/source-code-pro.git" ;;
        source-sans-pro)  echo "https://github.com/adobe-fonts/source-sans-pro.git" ;;
        source-serif-pro) echo "https://github.com/adobe-fonts/source-serif-pro.git" ;;
        roboto)           echo "https://github.com/googlefonts/roboto.git" ;;
        Fira)             echo "https://github.com/mozilla/Fira.git" ;;
        *) return 1 ;;
    esac
}

# Single resolver dispatch: package name -> "tag|version|commit" triplet,
# marker-first (offline reuse) via resolve_pkg_version. Digit repetition
# is spelled out where awk evaluates the grammar because Ubuntu 22.04's
# mawk does not support {n} interval expressions.
resolve_pkg() {
    local name="$1" url
    url=$(pkg_repo_url "$name") || url=""
    case "$name" in
        m4)
            resolve_pkg_version "$name" gnu_repo "$GNU_PRIMARY_MIRROR/m4/" \
                "$GNU_FALLBACK_MIRROR/m4/" ;;
        pkg-config)
            resolve_pkg_version "$name" gnu_repo "https://pkgconfig.freedesktop.org/releases/" ;;
        ghostscript)
            resolve_pkg_version "$name" resolve_ghostscript ;;
        libtiff)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v' ;;
        libjpeg-turbo)
            # The tag list carries x.y.9z development tags (2.1.90 was the
            # 3.0 beta) and inherited upstream-jpeg tags (jpeg-9e, jpeg-10),
            # so the grammar accepts plain x.y.z minus the .9x dev series.
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^[0-9]+\.[0-9]+\.[0-9]+$' '\.9[0-9]$' ;;
        libpng|libwebp|libxml2|raqm|openjpeg)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^v[0-9]+\.[0-9]+\.[0-9]+$' '' 'v' ;;
        fribidi)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^v[0-9]+\.[0-9]+(\.[0-9]+)?$' '' 'v' ;;
        freetype)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^VER-[0-9]+(-[0-9]+)+$' '' 'VER-' ;;
        fontconfig)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^[0-9]+\.[0-9]+(\.[0-9]+)?$' ;;
        harfbuzz|jemalloc)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^[0-9]+\.[0-9]+\.[0-9]+$' ;;
        opencl-sdk)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^v[0-9][0-9][0-9][0-9]\.[0-9][0-9]\.[0-9][0-9]$' '' 'v' ;;
        lcms2)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^lcms[0-9]+(\.[0-9]+)+$' '' 'lcms' ;;
        imagemagick)
            resolve_pkg_version "$name" resolve_latest_git_tag "$url" \
                '^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$' ;;
        libfpx|source-code-pro|source-sans-pro|source-serif-pro|roboto|Fira)
            # Repositories whose tags do not track HEAD (libfpx is an
            # ImageMagick-maintained mirror; the font repos' newest tags
            # are years older than current content): pin the HEAD commit.
            resolve_pkg_version "$name" resolve_git_head "$url" ;;
        *) fail "No resolver is defined for package '$name'." ;;
    esac
}

# Resolve a package into the caller's tag/ver/commit variables (bash
# dynamic scoping: the caller declares them local), failing the build on
# any resolution error.
resolve_into() {
    local resolved
    # Disabled packages resolve to a placeholder without any network
    # traffic; build() then skips them via the same config gate.
    if ! package_enabled "$1"; then
        tag="" ver="disabled" commit=""
        return 0
    fi
    resolved=$(resolve_pkg "$1") ||
        fail "Failed to resolve the latest $1 version."
    IFS='|' read -r tag ver commit <<<"$resolved"
}
