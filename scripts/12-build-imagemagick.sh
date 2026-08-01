#!/usr/bin/env bash
# shellcheck shell=bash

# The staged tree must contain nothing outside ./usr and a magick binary
# that runs (against its staged libraries) and reports exactly the version
# this run resolved. Only then is anything allowed to touch /usr/local.
validate_staged_install() {
    local staging="$1" expected_version="$2" entry staged_version
    local staged_magick="$staging/usr/local/bin/magick"
    [[ -x "$staged_magick" ]] ||
        fail "The staged install is missing usr/local/bin/magick."
    while IFS= read -r entry; do
        fail "The staged install wrote outside /usr: $entry"
    done < <(find "$staging" -mindepth 1 -maxdepth 1 ! -name usr)
    staged_version=$(env LD_LIBRARY_PATH="$staging/usr/local/lib:$staging/usr/local/lib64" \
        "$staged_magick" -version | head -n 1) ||
        fail "The staged magick binary failed to execute."
    grep -qF "ImageMagick $expected_version " <<<"$staged_version" ||
        fail "The staged magick reports '$staged_version' instead of version $expected_version."
    log "Staged install validated: $staged_version"
}

# One controlled privileged copy of the already-validated staged tree.
# Upstream's install recipe never runs as root; a file manifest is staged
# alongside so the installation is inspectable and manually reversible.
publish_staged_install() {
    local staging="$1"
    local manifest_dir="$staging/usr/local/share/imagemagick-build-script"
    mkdir -p "$manifest_dir" || fail "Cannot create the manifest directory in the staged tree."
    (cd "$staging" && find usr \( -type f -o -type l \) | sort) >"$manifest_dir/manifest.txt" ||
        fail "Cannot write the install manifest."
    log "Publishing the staged install to /usr/local (single privileged copy)..."
    if ! tar --owner=root --group=root -C "$staging" -cf - usr | exec_root tar -C / -xf -; then
        fail "Failed to publish the staged ImageMagick tree."
    fi
    log "Install manifest: /usr/local/share/imagemagick-build-script/manifest.txt"
}

# Success is claimed only after the live binary proves it: exact version,
# every delegate this script exists to provide, resolvable .pc files, the
# active security policy shown, and a real conversion round-trip.
validate_magick_installation() {
    # The second argument exists only so offline tests can point the
    # validator at a fixture binary; real runs validate /usr/local.
    local expected_version="$1" magick_bin="${2:-/usr/local/bin/magick}"
    local version_output delegates_line pc_version smoke_dir delegate
    local -a missing_delegates=()
    # Delegates guaranteed by this script's own dependency builds and APT
    # set. Host-provided extras (bzlib, jxl, lzma, x, zstd...) are welcome
    # but deliberately not required.
    local -a required_delegates=(
        fontconfig freetype fpx gslib gvc heic jng jp2 jpeg
        lcms png raqm rsvg tiff webp xml zlib
    )

    [[ -x "$magick_bin" ]] || fail "$magick_bin is missing or not executable."
    version_output=$("$magick_bin" -version) ||
        fail "Cannot execute $magick_bin -version."
    printf '%s\n' "$version_output"
    grep -qF "ImageMagick $expected_version " <<<"$version_output" ||
        fail "The installed magick reports a different version than this build ($expected_version)."

    delegates_line=$(printf '%s\n' "$version_output" | awk -F': ' '/^Delegates/ {print $2}')
    for delegate in "${required_delegates[@]}"; do
        grep -qw "$delegate" <<<"$delegates_line" || missing_delegates+=("$delegate")
    done
    if [[ "${#missing_delegates[@]}" -gt 0 ]]; then
        fail "The installed magick is missing expected delegates: ${missing_delegates[*]} (built with: ${delegates_line:-none})"
    fi

    pc_version=$(env PKG_CONFIG_LIBDIR=/usr/local/lib/pkgconfig \
        "$workspace/bin/pkg-config" --modversion MagickCore) ||
        fail "MagickCore.pc is not resolvable from /usr/local/lib/pkgconfig."
    # The .pc version omits the release suffix (7.1.2-29 -> 7.1.2).
    [[ "$pc_version" == "${expected_version%-*}" ]] ||
        fail "MagickCore.pc reports '$pc_version', expected '${expected_version%-*}'."

    echo
    log "Active security policy (upstream default unless you installed one):"
    "$magick_bin" identify -list policy || warn "Could not list the security policy."

    smoke_dir=$(mktemp -d "$cwd/.smoke.XXXXXX") || fail "Cannot create a smoke-test directory."
    "$magick_bin" logo: "$smoke_dir/logo.png" ||
        fail "Functional smoke test failed: magick logo: -> PNG."
    "$magick_bin" "$smoke_dir/logo.png" "$smoke_dir/logo.webp" ||
        fail "Functional smoke test failed: PNG -> WebP conversion."
    [[ -s "$smoke_dir/logo.png" && -s "$smoke_dir/logo.webp" ]] ||
        fail "Functional smoke test produced empty output files."
    safe_remove_tree "$smoke_dir" "$cwd"
    log "Functional smoke test passed (logo: -> PNG -> WebP)."
}

stage_build_imagemagick() {
    local resolved tag ver commit staging rsvg_cflags rsvg_libs
    local -a rsvg_env=()

    echo
    box_out_banner "Build ImageMagick"

    resolved=$(resolve_pkg_version imagemagick resolve_latest_git_tag \
        "https://github.com/ImageMagick/ImageMagick.git" '^[0-9]+\.[0-9]+\.[0-9]+-[0-9]+$') ||
        fail "Failed to resolve the latest ImageMagick version."
    IFS='|' read -r tag ver commit <<<"$resolved"
    if build imagemagick "$ver"; then
        download "https://github.com/ImageMagick/ImageMagick/archive/refs/tags/$tag.tar.gz" "imagemagick-$ver.tar.gz"
        execute autoreconf -fi
        [[ -d build/ ]] && execute rm -fr build/
        mkdir build/
        cd build/ || fail "Cannot enter the ImageMagick build directory."
        # librsvg is a SYSTEM library, and its Requires chain must resolve
        # in the system pkg-config view: on Debian 13 it traverses
        # harfbuzz-gobject, which pins the system harfbuzz version and
        # conflicts with the workspace harfbuzz.pc shadow. Explicit
        # RSVG_CFLAGS/RSVG_LIBS make configure's PKG_CHECK_MODULES skip
        # that broken shadowed probe (the version floor is enforced here).
        if rsvg_cflags=$(env -u PKG_CONFIG_LIBDIR -u PKG_CONFIG_PATH \
            /usr/bin/pkg-config --cflags "librsvg-2.0 >= 2.9.0" 2>/dev/null) &&
            rsvg_libs=$(env -u PKG_CONFIG_LIBDIR -u PKG_CONFIG_PATH \
                /usr/bin/pkg-config --libs "librsvg-2.0 >= 2.9.0" 2>/dev/null); then
            rsvg_env=("RSVG_CFLAGS=$rsvg_cflags" "RSVG_LIBS=$rsvg_libs")
        else
            warn "librsvg-2.0 is not resolvable via the system pkg-config; the rsvg delegate probe will run unaided."
        fi

        # Dropped relative to the historical flag set, with evidence:
        # --with-pkgconfigdir: ineffective upstream (Makefile.am overrides
        #   pkgconfigdir to $(libdir)/pkgconfig; verified live - the .pc
        #   files land in /usr/local/lib/pkgconfig regardless).
        # --enable-delegate-build: means "look for delegates in in-tree
        #   build subdirectories", which this external workspace is not.
        execute sh ../configure --prefix=/usr/local \
                                --enable-hdri \
                                --enable-hugepages \
                                --enable-legacy-support \
                                --enable-opencl \
                                --with-fontpath=/usr/share/fonts/truetype \
                                --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu \
                                --with-gs-font-dir=/usr/share/fonts/ghostscript \
                                --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35 \
                                --with-fpx \
                                --with-gslib \
                                --with-gvc \
                                --with-heic \
                                --with-jemalloc \
                                --with-modules \
                                --with-perl \
                                --with-pic \
                                --with-png \
                                --with-quantum-depth=16 \
                                --with-rsvg \
                                --with-utilities \
                                --without-autotrace \
                                CFLAGS="$CFLAGS -DCL_TARGET_OPENCL_VERSION=300" \
                                CXXFLAGS="$CXXFLAGS -DCL_TARGET_OPENCL_VERSION=300" \
                                CPPFLAGS="$CPPFLAGS -I$workspace/include/CL" \
                                PKG_CONFIG="$workspace/bin/pkg-config" \
                                "${rsvg_env[@]}"
        execute make "-j$cpu_threads"

        staging="$packages/imagemagick-staging"
        [[ -e "$staging" ]] && safe_remove_tree "$staging" "$packages"
        execute make DESTDIR="$staging" install
        validate_staged_install "$staging" "$ver"
        publish_staged_install "$staging"
        exec_root ldconfig || fail "ldconfig failed after installing ImageMagick."
        validate_magick_installation "$ver"
        build_done imagemagick "$ver" "$commit"
    fi
}
