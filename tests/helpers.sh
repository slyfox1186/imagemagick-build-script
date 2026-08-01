#!/usr/bin/env bash
# shellcheck shell=bash
# Helpers sourced into unit-test sandboxes by tests/test-scripts.sh.
# $workspace and $cwd come from scripts/01-variables.sh, which the unit
# driver sources first; the :? guards make that dependency explicit.

# Writes a fake magick binary (./fake-magick) that reports the given
# version and delegates line, answers `identify` calls, and "converts" by
# writing bytes to its final argument. Also plants a fake workspace
# pkg-config reporting 7.9.9 and creates the build root for smoke files.
make_fake_magick() {
    local report_version="$1" report_delegates="$2"
    cat >fake-magick <<FAKE
#!/usr/bin/env bash
if [[ "\$1" == "-version" ]]; then
    printf 'Version: ImageMagick %s Q16-HDRI x86_64 test:20260101 https://imagemagick.org\n' '$report_version'
    printf 'Features: Cipher DPC HDRI Modules OpenCL OpenMP(4.5)\n'
    printf 'Delegates (built-in): %s\n' '$report_delegates'
    exit 0
fi
if [[ "\$1" == "identify" ]]; then
    printf 'Path: [built-in]\n'
    exit 0
fi
out="\${@: -1}"
printf 'image-bytes\n' > "\$out"
FAKE
    chmod 755 fake-magick
    mkdir -p "${workspace:?}/bin"
    printf '#!/bin/sh\necho 7.9.9\n' >"${workspace:?}/bin/pkg-config"
    chmod 755 "${workspace:?}/bin/pkg-config"
    mkdir -p "${cwd:?}"
}
