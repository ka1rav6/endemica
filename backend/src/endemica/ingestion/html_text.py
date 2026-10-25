from __future__ import annotations

import html
import re

from selectolax.parser import HTMLParser

_WHITESPACE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")

_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "section",
        "article",
        "blockquote",
    }
)


def html_to_text(markup: str | None) -> str:
    if not markup:
        return ""
    tree = HTMLParser(markup)
    for node in tree.css("script, style, noscript"):
        node.decompose()
    body = tree.body or tree.root
    if body is None:
        return normalise_whitespace(html.unescape(markup))

    parts: list[str] = []
    for node in body.traverse(include_text=True):
        if node.tag == "-text":
            text = node.text(deep=False)
            if text and text.strip():
                parts.append(text)
        elif node.tag in _BLOCK_TAGS:
            parts.append("\n")
    return normalise_whitespace("".join(parts))


def normalise_whitespace(text: str) -> str:
    collapsed = _WHITESPACE.sub(" ", html.unescape(text))
    lines = [line.strip() for line in collapsed.split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def join_sections(*sections: str | None) -> str:
    rendered = [html_to_text(section) for section in sections]
    return normalise_whitespace("\n\n".join(part for part in rendered if part))
