#!/usr/bin/env bash
# shellcheck shell=bash

stage_finalize() {
    # LDCONFIG MUST BE RUN NEXT TO UPDATE FILE CHANGES OR THE MAGICK COMMAND WILL NOT WORK
    exec_root ldconfig || fail "ldconfig failed; the installed libraries may not be resolvable."

    # SHOW THE NEWLY INSTALLED MAGICK VERSION
    show_version

    # PROMPT THE USER TO CLEAN UP THE BUILD FILES
    cleanup

    # SHOW EXIT MESSAGE
    exit_fn
}
