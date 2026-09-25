"""GNU `sort -V` ordering.

Release selection picks the newest tag or listed archive the way the original
shell build did with `sort -V`, so this needs the same total order. The standard library
has no equivalent: `distutils` was removed in 3.12 and `packaging` is not
stdlib, and neither implements this ordering anyway — GNU's is a filename
ordering that handles `~`, embedded digit runs and file suffixes, not PEP 440.

This is a transcription of gnulib's `filevercmp`, which is what coreutils `sort
-V` calls.
"""

from __future__ import annotations

import re

# The suffix `filevercmp` sets aside before comparing: zero or more `.`-led
# components that begin with a letter or `~`. `foo.tar.gz` has one; `3.10.2`
# has none, because a component must not begin with a digit.
_FILE_SUFFIX = re.compile(r"(?:\.[A-Za-z~][A-Za-z0-9~]*)*$")


def _order(character: str) -> int:
    """Rank one character: digits first, then letters, then `~`, then the rest.

    `~` ranks below the end of string, which is what makes `1.0~rc1` sort
    before `1.0`.
    """
    if character == "":
        return 0
    if character.isdigit() and character.isascii():
        return 0
    if character.isalpha() and character.isascii():
        return ord(character)
    if character == "~":
        return -1
    return ord(character) + 0x100


def _is_digit(text: str, index: int) -> bool:
    return index < len(text) and text[index].isascii() and text[index].isdigit()


def _verrevcmp(left: str, right: str) -> int:
    left_pos = 0
    right_pos = 0
    while left_pos < len(left) or right_pos < len(right):
        first_difference = 0
        while (left_pos < len(left) and not _is_digit(left, left_pos)) or (
            right_pos < len(right) and not _is_digit(right, right_pos)
        ):
            left_rank = _order(left[left_pos] if left_pos < len(left) else "")
            right_rank = _order(right[right_pos] if right_pos < len(right) else "")
            if left_rank != right_rank:
                return left_rank - right_rank
            left_pos += 1
            right_pos += 1

        while left_pos < len(left) and left[left_pos] == "0":
            left_pos += 1
        while right_pos < len(right) and right[right_pos] == "0":
            right_pos += 1

        while _is_digit(left, left_pos) and _is_digit(right, right_pos):
            if not first_difference:
                first_difference = ord(left[left_pos]) - ord(right[right_pos])
            left_pos += 1
            right_pos += 1

        # A longer remaining digit run is the larger number regardless of the
        # first differing digit.
        if _is_digit(left, left_pos):
            return 1
        if _is_digit(right, right_pos):
            return -1
        if first_difference:
            return first_difference
    return 0


def _prefix_length(value: str) -> int:
    match = _FILE_SUFFIX.search(value)
    prefix_length = match.start() if match else len(value)
    return prefix_length if prefix_length else len(value)


def version_compare(left: str, right: str) -> int:
    """Order two strings the way `sort -V` does."""
    if left == right:
        return 0
    if not left or not right:
        return (not right) - (not left)

    # Names beginning with `.` sort first: "." then ".." then other dotted
    # names, matching how `ls -v` groups them.
    if left.startswith(".") or right.startswith("."):
        if not left.startswith("."):
            return 1
        if not right.startswith("."):
            return -1
        for special in (".", ".."):
            if left == special or right == special:
                if left == right:
                    return 0
                return -1 if left == special else 1

    left_prefix = _prefix_length(left)
    right_prefix = _prefix_length(right)
    result = _verrevcmp(left[:left_prefix], right[:right_prefix])
    if result:
        return result
    return _verrevcmp(left, right)
