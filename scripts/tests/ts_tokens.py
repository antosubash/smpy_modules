"""A small TypeScript lexer for the parity check (#127).

Just enough to tell code from literals: strings, template literals (with their
``${…}`` holes), regular expressions and comments come back as single tokens
with their text untouched, so normalising whitespace *between* tokens can never
rewrite what a literal says. Everything else is an identifier, a number or an
operator.
"""

from __future__ import annotations

import re

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_NUMBER = re.compile(r"\.?\d[\w.]*")
_SPACE = re.compile(r"\s+")
_OPERATORS = sorted(
    (
        ">>>=",
        "...",
        "===",
        "!==",
        "**=",
        "<<=",
        ">>=",
        ">>>",
        "&&=",
        "||=",
        "??=",
        "=>",
        "==",
        "!=",
        "<=",
        ">=",
        "&&",
        "||",
        "??",
        "?.",
        "++",
        "--",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "&=",
        "|=",
        "^=",
        "**",
        "<<",
        ">>",
    ),
    key=len,
    reverse=True,
)
# After one of these, `/` starts a regex rather than dividing.
_REGEX_AFTER_WORD = {
    "return",
    "typeof",
    "instanceof",
    "in",
    "of",
    "new",
    "delete",
    "void",
    "throw",
    "case",
    "do",
    "else",
    "yield",
    "await",
}

Token = tuple[str, str]  # (kind, text); kind is one of comment/literal/word/op


def _scan_quoted(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src) and src[i] != quote:
        i += 2 if src[i] == "\\" else 1
    return i + 1


def _scan_regex(src: str, i: int) -> int:
    i += 1
    in_class = False
    while i < len(src) and (in_class or src[i] != "/"):
        if src[i] == "\\":
            i += 1
        elif src[i] == "[":
            in_class = True
        elif src[i] == "]":
            in_class = False
        i += 1
    i += 1
    match = _IDENT.match(src, i)
    return match.end() if match else i


def _scan_template(src: str, i: int) -> int:
    i += 1
    while i < len(src) and src[i] != "`":
        if src[i] == "\\":
            i += 2
        elif src.startswith("${", i):
            _, i = _lex(src, i + 2, until_brace=True)
            i += 1
        else:
            i += 1
    return i + 1


def _regex_allowed(previous: Token | None) -> bool:
    if previous is None:
        return True
    kind, text = previous
    if kind == "word":
        return text in _REGEX_AFTER_WORD
    return kind == "op" and text not in (")", "]", "}")


def _lex(src: str, i: int, until_brace: bool = False) -> tuple[list[Token], int]:
    tokens: list[Token] = []
    depth = 0
    previous: Token | None = None
    while i < len(src):
        space = _SPACE.match(src, i)
        if space:
            i = space.end()
            continue
        char = src[i]
        if until_brace and char == "}" and depth == 0:
            return tokens, i
        start = i
        if src.startswith("//", i):
            end = src.find("\n", i)
            i, kind = (len(src) if end < 0 else end), "comment"
        elif src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i, kind = (len(src) if end < 0 else end + 2), "comment"
        elif char in "'\"":
            i, kind = _scan_quoted(src, i), "literal"
        elif char == "`":
            i, kind = _scan_template(src, i), "literal"
        elif char == "/" and _regex_allowed(previous):
            i, kind = _scan_regex(src, i), "literal"
        elif (match := _IDENT.match(src, i) or _NUMBER.match(src, i)) is not None:
            i, kind = match.end(), "word"
        else:
            op = next((o for o in _OPERATORS if src.startswith(o, i)), char)
            i, kind = i + len(op), "op"
            depth += {"{": 1, "}": -1}.get(op, 0)
        token = (kind, src[start:i])
        tokens.append(token)
        if kind != "comment":
            previous = token
    return tokens, i


def strip_comments(src: str) -> str:
    """``src`` with every comment removed and everything else left where it was."""
    out: list[str] = []
    i = 0
    tokens, _ = _lex(src, 0)
    for kind, text in tokens:
        at = src.index(text, i)
        if kind != "comment":
            out.append(src[i : at + len(text)])
        else:
            out.append(src[i:at])
        i = at + len(text)
    out.append(src[i:])
    return "".join(out)


def code(src: str) -> str:
    """The tokens of ``src`` one space apart, with trailing commas dropped.

    That makes Biome's line wrapping invisible while leaving every literal as
    written: ``"a + b"`` and ``"a+b"`` stay different.
    """
    tokens = [text for kind, text in _lex(src, 0)[0] if kind != "comment"]
    kept = [
        text
        for text, following in zip(tokens, [*tokens[1:], ""], strict=True)
        if not (text == "," and following in (")", "]", "}"))
    ]
    return " ".join(kept)
