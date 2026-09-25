"""Shell-style quoting for the commands the build echoes and logs.

Bash's `printf '%q'` rules rather than `shlex.quote`: a logged command reads
the way the original shell build printed it, with flags such as `-O3\\ -pipe`
escaped instead of wrapped, and control characters shown as ANSI-C escapes.
The rules were derived by enumerating every byte through `printf '%q'` under
`LC_ALL=C`, the locale every build command runs in.
"""

from __future__ import annotations

# Printable characters Bash prefixes with a backslash. Everything else in the
# printable ASCII range, including `% + - . / : = @ _`, is emitted verbatim.
_BACKSLASH_ESCAPED = frozenset(" !\"$&'()*,;<>?[\\]^`{|}")

# `#` starts a comment only in the first position of a word. `~` starts an
# expansion in that position and also directly after `:` or `=`, which is what
# makes `PATH=a:~/bin` expand; Bash escapes it in exactly those three places.
_TILDE_EXPANSION_PREDECESSORS = frozenset(":=")

# Control characters with a named ANSI-C escape; every other non-printable byte
# becomes a three-digit octal escape.
_NAMED_ESCAPES = {
    0x07: "\\a",
    0x08: "\\b",
    0x09: "\\t",
    0x0A: "\\n",
    0x0B: "\\v",
    0x0C: "\\f",
    0x0D: "\\r",
    0x1B: "\\E",
}


def _needs_ansi_c(value: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) >= 0x7F for character in value)


def _ansi_c_quote(value: str) -> str:
    rendered = ["$'"]
    for byte in value.encode("utf-8", "surrogateescape"):
        if byte in _NAMED_ESCAPES:
            rendered.append(_NAMED_ESCAPES[byte])
        elif byte < 0x20 or byte >= 0x7F:
            rendered.append(f"\\{byte:03o}")
        elif byte in (0x27, 0x5C):
            rendered.append("\\" + chr(byte))
        else:
            rendered.append(chr(byte))
    rendered.append("'")
    return "".join(rendered)


def quote(value: str) -> str:
    """Encode one word exactly as `printf '%q'` would."""
    if not value:
        return "''"
    if _needs_ansi_c(value):
        return _ansi_c_quote(value)
    rendered: list[str] = []
    for position, character in enumerate(value):
        if character in _BACKSLASH_ESCAPED:
            escape = True
        elif character == "#":
            escape = position == 0
        elif character == "~":
            escape = position == 0 or value[position - 1] in _TILDE_EXPANSION_PREDECESSORS
        else:
            escape = False
        rendered.append(f"\\{character}" if escape else character)
    return "".join(rendered)


def join(arguments: list[str] | tuple[str, ...]) -> str:
    """Render an argument list the way the build logs a command."""
    return " ".join(quote(argument) for argument in arguments)
