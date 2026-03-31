"""Shared HTML sanitization helpers for admin-managed content."""

from __future__ import annotations

import nh3

LEGAL_ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "br",
    "hr",
    "ul",
    "ol",
    "li",
    "a",
    "strong",
    "em",
    "b",
    "i",
    "u",
    "s",
    "blockquote",
    "code",
    "pre",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "span",
    "div",
    "section",
    "dl",
    "dt",
    "dd",
}
LEGAL_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title", "rel"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan", "scope"},
}


def is_legal_content_type(content_type: str | None) -> bool:
    return bool(content_type and content_type.startswith("legal_"))


def sanitize_legal_html(html: str) -> str:
    return nh3.clean(
        html,
        tags=LEGAL_ALLOWED_TAGS,
        attributes=LEGAL_ALLOWED_ATTRIBUTES,
        link_rel=None,
    )