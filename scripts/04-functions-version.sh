#!/usr/bin/env bash
# shellcheck shell=bash

# Version resolvers. Contract: every resolver prints "tag|version|commit"
# on stdout (tag/commit may be empty for tarball-only sources) and returns
# non-zero on any failure - an empty or "null" version can never leak into
# markers or download URLs. Git-hosted upstreams (GitHub, GitLab,
# googlesource) all resolve through resolve_latest_git_tag with a
# repository-specific tag grammar at the call site; there is deliberately
# no HTML scraping and no per-forge API client.

# GNU-style release-directory listing (m4, pkg-config): highest plain
# numeric "<name>-X.Y[.Z].tar.*" version. Rolling aliases like
# "m4-latest.tar.xz" never match, so markers always record a real version.
gnu_repo() {
    local listing ver
    listing=$(curl_listing "$1") || return 1
    ver=$(printf '%s\n' "$listing" |
        grep -oP '[a-zA-Z0-9_-]+-\K[0-9]+(\.[0-9]+)+(?=\.tar)' |
        sort -uV | tail -n 1)
    [[ -n "$ver" ]] || return 1
    printf '|%s|\n' "$ver"
}

# Ghostscript releases live in the ghostpdl-downloads repository with tags
# like gs10071 (= 10.07.1). The grammar is pinned to exactly five digits:
# a future six-digit tag would sort wrongly against five-digit ones, so it
# fails closed for a deliberate update instead. Digit repetition is spelled
# out because these grammars run under awk, and Ubuntu 22.04's mawk does
# not support {n} interval expressions.
resolve_ghostscript() {
    local trip tag commit fmt
    trip=$(resolve_latest_git_tag \
        "https://github.com/ArtifexSoftware/ghostpdl-downloads.git" \
        '^gs[0-9][0-9][0-9][0-9][0-9]$') || return 1
    IFS='|' read -r tag _ commit <<<"$trip"
    fmt=$(printf '%s\n' "$tag" | sed -E 's/^gs([0-9]{2})([0-9]{2})([0-9])$/\1.\2.\3/')
    [[ "$fmt" != "$tag" ]] || return 1
    printf '%s|%s|%s\n' "$tag" "$fmt" "$commit"
}
