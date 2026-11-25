"""Pure-Python toolbar normalization and minihtml annotation renderer."""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Collection, Sequence

ACTION_COMMANDS: dict[str, str] = {
    "side_by_side": "mdglance_open_side_by_side",
    "full_screen": "mdglance_toggle_full_screen",
    "outline": "mdglance_toggle_outline",
    "browser": "mdglance_open_in_browser",
}

DEFAULT_LABELS: dict[str, str] = {
    "side_by_side": "分屏预览",
    "full_screen": "全屏",
    "outline": "目录",
    "browser": "浏览器",
}

HREF_PREFIX = "action:"
DEFAULT_SEPARATOR = " · "
DEFAULT_ANNOTATION_COLOR = "transparent"


@dataclass(frozen=True)
class ButtonSpec:
    """Single clickable entry rendered in the top-right editor toolbar."""

    action: str
    label: str


DEFAULT_BUTTONS: tuple[ButtonSpec, ...] = (
    ButtonSpec("side_by_side", DEFAULT_LABELS["side_by_side"]),
    ButtonSpec("full_screen", DEFAULT_LABELS["full_screen"]),
    ButtonSpec("outline", DEFAULT_LABELS["outline"]),
)


def normalize_buttons(raw: Any) -> tuple[ButtonSpec, ...]:
    """Validate and normalize user-configured button entries.

    Accepts a sequence of dicts (`{"action": "...", "label": "..."}`) or bare
    action-name strings. Unknown entries are skipped and duplicate actions keep
    their first occurrence. Passing ``None`` or a non-sequence falls back to
    :data:`DEFAULT_BUTTONS`; an explicit empty list disables all buttons.
    """
    if raw is None or not isinstance(raw, (list, tuple)):
        return DEFAULT_BUTTONS

    result: list[ButtonSpec] = []
    seen: set[str] = set()

    for item in raw:
        action: str | None = None
        label: str | None = None

        if isinstance(item, str):
            action = item.strip()
        elif isinstance(item, dict):
            raw_action = item.get("action")
            if isinstance(raw_action, str):
                action = raw_action.strip()
            raw_label = item.get("label")
            if isinstance(raw_label, str):
                label = raw_label.strip()

        if not action or action not in ACTION_COMMANDS or action in seen:
            continue

        resolved_label = label or DEFAULT_LABELS[action]
        seen.add(action)
        result.append(ButtonSpec(action=action, label=resolved_label))

    return tuple(result)


def parse_action_href(href: str | None) -> str | None:
    """Extract and validate an action key from a toolbar link href."""
    if not isinstance(href, str) or not href.startswith(HREF_PREFIX):
        return None
    action = href[len(HREF_PREFIX) :].strip()
    if action in ACTION_COMMANDS:
        return action
    return None


def _escape_separator(separator: str) -> str:
    escaped = html.escape(separator, quote=True)
    return escaped.replace(" ", "&nbsp;")


def build_toolbar_html(
    buttons: Sequence[ButtonSpec],
    active_actions: Collection[str] = (),
    separator: str = DEFAULT_SEPARATOR,
) -> str:
    """Render a compact, theme-adaptive minihtml string for ST4 annotations."""
    if not buttons:
        return ""

    active_set = set(active_actions)
    sep_text = separator if isinstance(separator, str) else DEFAULT_SEPARATOR
    sep_html = f'<span class="sep">{_escape_separator(sep_text)}</span>'

    parts: list[str] = []
    for btn in buttons:
        css_class = "btn-active" if btn.action in active_set else "btn"
        href = html.escape(f"{HREF_PREFIX}{btn.action}", quote=True)
        label = html.escape(btn.label, quote=True)
        parts.append(f'<a class="{css_class}" href="{href}">{label}</a>')

    links_html = sep_html.join(parts)
    return (
        '<body id="markdown-glance-bar">'
        "<style>"
        "body { margin: 0; padding: 0; }"
        "a.btn { color: color(var(--foreground) alpha(0.72)); text-decoration: none; }"
        "a.btn-active { color: var(--bluish); text-decoration: none; font-weight: bold; }"
        "span.sep { color: color(var(--foreground) alpha(0.32)); }"
        "</style>"
        f"{links_html}"
        "</body>"
    )


def compute_toolbar_signature(
    *,
    enabled: bool,
    show_toolbar: bool,
    buttons: tuple[ButtonSpec, ...],
    active_actions: Collection[str],
    separator: str,
    annotation_color: str,
) -> tuple[Any, ...]:
    """Return a hashable signature used to skip redundant add_regions calls."""
    return (
        bool(enabled),
        bool(show_toolbar),
        buttons,
        frozenset(active_actions),
        separator,
        annotation_color,
    )
