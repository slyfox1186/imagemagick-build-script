#!/usr/bin/env bash
# shellcheck shell=bash

stage_finalize() {
    # ldconfig and the full live validation (version, delegates, policy,
    # functional smoke) already ran inside the ImageMagick stage before its
    # completion marker was written; this stage only reports and cleans up.
    show_version

    # PROMPT THE USER TO CLEAN UP THE BUILD FILES
    cleanup

    # SHOW EXIT MESSAGE
    exit_fn
}
