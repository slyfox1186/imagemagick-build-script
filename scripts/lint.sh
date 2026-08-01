#!/usr/bin/env bash
# Repository-wide static-analysis gate. Run via: python3 run_linter.py

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$repo_root"

command -v shellcheck >/dev/null 2>&1 || {
    printf "'shellcheck' is required (install the 'shellcheck' package).\n" >&2
    exit 1
}
command -v python3 >/dev/null 2>&1 || {
    printf "'python3' is required.\n" >&2
    exit 1
}

shopt -s nullglob
shell_files=(build-magick.sh scripts/*.sh tests/*.sh)
standalone_shell_files=(scripts/lint.sh tests/*.sh)
text_files=(
    .gitignore
    README.md
    run_linter.py
    "${shell_files[@]}"
    .github/workflows/*.yml
    .github/workflows/*.yaml
)
shopt -u nullglob
((${#shell_files[@]} > 0)) || {
    printf 'No project shell scripts were found.\n' >&2
    exit 1
}

for shell_file in "${shell_files[@]}"; do
    bash -n "$shell_file"
done
printf 'bash syntax: OK (%d files)\n' "${#shell_files[@]}"

# The stage scripts under scripts/ are sourced by build-magick.sh, so they are
# analyzed in their real execution context: --check-sourced surfaces their
# diagnostics and --external-sources resolves the source chain. ShellCheck
# does NOT report sourced-file diagnostics without --check-sourced, so the
# flag is load-bearing. Standalone helpers (lint/tests) are checked directly.
shellcheck --external-sources --check-sourced --severity=style build-magick.sh
shellcheck --external-sources --severity=style "${standalone_shell_files[@]}"
printf 'ShellCheck: OK\n'

python3 -c \
    'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"), filename=sys.argv[1])' \
    run_linter.py
printf 'Python syntax: OK\n'

if grep -nE '[[:blank:]]+$' "${text_files[@]}" >/dev/null 2>&1; then
    printf 'Trailing whitespace was found in project text files.\n' >&2
    grep -nE '[[:blank:]]+$' "${text_files[@]}" >&2
    exit 1
fi
printf 'Whitespace: OK\n'

# A ShellCheck directive placed before a script's first command applies to the
# whole file and silently hides entire defect classes. Only line-specific,
# justified suppressions next to the offending line are allowed.
if awk 'FNR <= 3 && /^# shellcheck disable=/ { print FILENAME ":" FNR ": " $0; found = 1 } END { exit found }' "${shell_files[@]}"; then
    printf 'Suppression policy: OK\n'
else
    printf 'File-wide ShellCheck suppressions are not allowed.\n' >&2
    exit 1
fi
