#!/usr/bin/env bash
# shellcheck shell=bash

# Source-built delegate map: package -> ImageMagick configure flag ->
# delegate token in `magick -version`. The single source for both the
# configure arguments and the required-delegates validation set, so a
# selection change can never make the two disagree. openjpeg's flag is
# openjp2 but its token is jp2; jemalloc is a feature, not a delegate
# (token "-").
readonly -a MAGICK_PACKAGE_DELEGATES=(
    "libjpeg-turbo:jpeg:jpeg"
    "libtiff:tiff:tiff"
    "libpng:png:png"
    "libwebp:webp:webp"
    "libfpx:fpx:fpx"
    "ghostscript:gslib:gslib"
    "freetype:freetype:freetype"
    "fontconfig:fontconfig:fontconfig"
    "raqm:raqm:raqm"
    "libxml2:xml:xml"
    "openjpeg:openjp2:jp2"
    "lcms2:lcms:lcms"
    "jemalloc:jemalloc:-"
)

# One configure argument per toggleable package, in fixed table order so
# the configure fingerprint stays deterministic. Disabled packages get an
# explicit --without so a stray system dev package cannot silently
# re-enable what the config turned off.
magick_toggle_args() {
    local entry pkg flag
    for entry in "${MAGICK_PACKAGE_DELEGATES[@]}"; do
        pkg="${entry%%:*}"
        flag="${entry#*:}"
        flag="${flag%%:*}"
        if package_enabled "$pkg"; then
            printf -- '--with-%s\n' "$flag"
        else
            printf -- '--without-%s\n' "$flag"
        fi
    done
}

# The delegates the installed magick MUST report: the APT-guaranteed
# baseline plus one token per enabled source-built provider. jng is the
# JPEG-in-PNG delegate and needs both of its providers.
magick_required_delegates() {
    local -a tokens=(bzlib gvc heic jbig lzma rsvg zlib zstd)
    local entry pkg token
    for entry in "${MAGICK_PACKAGE_DELEGATES[@]}"; do
        pkg="${entry%%:*}"
        token="${entry##*:}"
        [[ "$token" == "-" ]] && continue
        if package_enabled "$pkg"; then
            tokens+=("$token")
        fi
    done
    if package_enabled libjpeg-turbo && package_enabled libpng; then
        tokens+=(jng)
    fi
    printf '%s\n' "${tokens[@]}"
}

# pkg-config for configure and validation: the workspace copy when it is
# built, otherwise the system pkg-config from the APT baseline.
magick_pkg_config() {
    if package_enabled pkg-config; then
        printf '%s\n' "$workspace/bin/pkg-config"
    else
        type -P pkg-config ||
            fail "No system pkg-config found and the workspace build is disabled."
    fi
}

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
    local -a missing_delegates=() required_delegates=()
    # Delegates guaranteed by this script's own dependency builds and APT
    # set, trimmed to the active package selection. Host-provided extras
    # (jxl on Ubuntu 22.04, x...) are welcome but deliberately not
    # required.
    mapfile -t required_delegates < <(magick_required_delegates)

    [[ -x "$magick_bin" ]] || fail "$magick_bin is missing or not executable."
    version_output=$("$magick_bin" -version) ||
        fail "Cannot execute $magick_bin -version."
    echo
    printf '%s\n' "$version_output" | grep -E '^(Version|Features|Delegates)'
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
        "$(magick_pkg_config)" --modversion MagickCore) ||
        fail "MagickCore.pc is not resolvable from /usr/local/lib/pkgconfig."
    # The .pc version omits the release suffix (7.1.2-29 -> 7.1.2).
    [[ "$pc_version" == "${expected_version%-*}" ]] ||
        fail "MagickCore.pc reports '$pc_version', expected '${expected_version%-*}'."

    local policy_path
    policy_path=$("$magick_bin" identify -list policy 2>/dev/null |
        awk -F': ' '/^Path:/ {print $2; exit}')
    log "Security policy: ${policy_path:-unknown} (details: magick identify -list policy)"

    smoke_dir=$(mktemp -d "$cwd/.smoke.XXXXXX") || fail "Cannot create a smoke-test directory."
    "$magick_bin" logo: "$smoke_dir/logo.png" ||
        fail "Functional smoke test failed: magick logo: -> PNG."
    "$magick_bin" "$smoke_dir/logo.png" "$smoke_dir/logo.webp" ||
        fail "Functional smoke test failed: PNG -> WebP conversion."
    [[ -s "$smoke_dir/logo.png" && -s "$smoke_dir/logo.webp" ]] ||
        fail "Functional smoke test produced empty output files."
    safe_remove_tree "$smoke_dir" "$cwd"
    log "Functional smoke test passed (logo: -> PNG -> WebP)."
    # Lets the finalize stage skip its redundant version display.
    MAGICK_VALIDATED=1
}

stage_build_imagemagick() {
    local tag ver commit staging fingerprint
    local magick_cflags="$CFLAGS" magick_cxxflags="$CXXFLAGS" magick_cppflags="$CPPFLAGS"
    local -a toggle_args=() opencl_args=()

    if ! package_enabled imagemagick; then
        echo
        log "imagemagick is disabled by the package selection config; skipping the final build."
        return 0
    fi

    echo
    box_out_banner "Build ImageMagick"

    mapfile -t toggle_args < <(magick_toggle_args)
    if package_enabled opencl-sdk; then
        opencl_args=(--enable-opencl)
        magick_cflags+=" -DCL_TARGET_OPENCL_VERSION=300"
        magick_cxxflags+=" -DCL_TARGET_OPENCL_VERSION=300"
        magick_cppflags+=" -I$workspace/include/CL"
    else
        opencl_args=(--disable-opencl)
    fi

    # Dropped relative to the historical flag set, with evidence:
    # --with-pkgconfigdir: ineffective upstream (Makefile.am overrides
    #   pkgconfigdir to $(libdir)/pkgconfig; verified live - the .pc
    #   files land in /usr/local/lib/pkgconfig regardless).
    # --enable-delegate-build: means "look for delegates in in-tree
    #   build subdirectories", which this external workspace is not.
    # Most optional delegates (djvu, lqr, openexr, pango, raw, wmf, zip)
    # default to yes and activate automatically once their dev packages
    # are installed; fftw is the one that defaults to no. The
    # source-built delegates arrive via magick_toggle_args, driven by the
    # package selection.
    local -a configure_args=(
        --prefix=/usr/local
        --enable-hdri
        --enable-hugepages
        --enable-legacy-support
        "${opencl_args[@]}"
        --with-fftw
        --with-fontpath=/usr/share/fonts/truetype
        --with-dejavu-font-dir=/usr/share/fonts/truetype/dejavu
        --with-gs-font-dir=/usr/share/fonts/ghostscript
        --with-urw-base35-font-dir=/usr/share/fonts/type1/urw-base35
        --with-gvc
        --with-heic
        --with-modules
        --with-perl
        --with-pic
        --with-quantum-depth=16
        --with-rsvg
        --with-utilities
        --without-autotrace
        "${toggle_args[@]}"
        CFLAGS="$magick_cflags"
        CXXFLAGS="$magick_cxxflags"
        CPPFLAGS="$magick_cppflags"
        PKG_CONFIG="$(magick_pkg_config)"
    )
    local fingerprint_file="$packages/imagemagick.configure.sha256"
    fingerprint=$(printf '%s\n' "${configure_args[@]}" | sha256sum)
    fingerprint="${fingerprint%% *}"

    resolve_into imagemagick
    invalidate_marker_on_config_change imagemagick "$fingerprint_file" "$fingerprint"
    if build imagemagick "$ver"; then
        download "https://github.com/ImageMagick/ImageMagick/archive/refs/tags/$tag.tar.gz" "imagemagick-$ver.tar.gz"
        execute autoreconf -fi
        [[ -d build/ ]] && execute rm -fr build/
        mkdir build/
        cd build/ || fail "Cannot enter the ImageMagick build directory."
        execute sh ../configure "${configure_args[@]}"
        execute make "-j$cpu_threads"

        staging="$packages/imagemagick-staging"
        [[ -e "$staging" ]] && safe_remove_tree "$staging" "$packages"
        execute make DESTDIR="$staging" install
        validate_staged_install "$staging" "$ver"
        publish_staged_install "$staging"
        exec_root ldconfig || fail "ldconfig failed after installing ImageMagick."
        validate_magick_installation "$ver"
        build_done imagemagick "$ver" "$commit"
        record_configure_fingerprint "$fingerprint_file" "$fingerprint"
    fi
}
