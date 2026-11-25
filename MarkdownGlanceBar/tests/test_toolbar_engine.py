from __future__ import annotations

import unittest

from core.toolbar_engine import (
    DEFAULT_BUTTONS,
    ButtonSpec,
    build_toolbar_html,
    compute_toolbar_signature,
    normalize_buttons,
    parse_action_href,
)


class TestNormalizeButtons(unittest.TestCase):
    def test_none_or_invalid_type_falls_back_to_defaults(self) -> None:
        self.assertEqual(normalize_buttons(None), DEFAULT_BUTTONS)
        self.assertEqual(normalize_buttons("side_by_side"), DEFAULT_BUTTONS)
        self.assertEqual(normalize_buttons(123), DEFAULT_BUTTONS)

    def test_empty_list_disables_all_buttons(self) -> None:
        self.assertEqual(normalize_buttons([]), ())

    def test_accepts_strings_and_dicts_with_custom_labels(self) -> None:
        result = normalize_buttons(
            [
                "side_by_side",
                {"action": "full_screen", "label": "Full"},
                {"action": "browser"},
            ]
        )
        self.assertEqual(
            result,
            (
                ButtonSpec("side_by_side", "分屏预览"),
                ButtonSpec("full_screen", "Full"),
                ButtonSpec("browser", "浏览器"),
            ),
        )

    def test_ignores_unknown_blank_and_duplicate_actions(self) -> None:
        result = normalize_buttons(
            [
                {"action": "unknown", "label": "Nope"},
                {"action": "  ", "label": "Empty"},
                {"action": "outline", "label": "大纲"},
                {"action": "outline", "label": "Duplicate"},
                42,
                {"action": "side_by_side", "label": "   "},
            ]
        )
        self.assertEqual(
            result,
            (
                ButtonSpec("outline", "大纲"),
                ButtonSpec("side_by_side", "分屏预览"),
            ),
        )


class TestParseActionHref(unittest.TestCase):
    def test_valid_hrefs(self) -> None:
        self.assertEqual(parse_action_href("action:side_by_side"), "side_by_side")
        self.assertEqual(parse_action_href("action:full_screen"), "full_screen")
        self.assertEqual(parse_action_href("action:outline"), "outline")
        self.assertEqual(parse_action_href("action:browser"), "browser")

    def test_invalid_hrefs(self) -> None:
        self.assertIsNone(parse_action_href(None))
        self.assertIsNone(parse_action_href(""))
        self.assertIsNone(parse_action_href("side_by_side"))
        self.assertIsNone(parse_action_href("action:unknown"))
        self.assertIsNone(parse_action_href("https://example.com"))


class TestBuildToolbarHtml(unittest.TestCase):
    def test_empty_buttons_returns_empty_string(self) -> None:
        self.assertEqual(build_toolbar_html(()), "")

    def test_renders_default_buttons_and_active_highlight(self) -> None:
        rendered = build_toolbar_html(
            DEFAULT_BUTTONS,
            active_actions={"side_by_side"},
            separator=" · ",
        )
        self.assertIn('<body id="markdown-glance-bar">', rendered)
        self.assertIn('<a class="btn-active" href="action:side_by_side">分屏预览</a>', rendered)
        self.assertIn('<a class="btn" href="action:full_screen">全屏</a>', rendered)
        self.assertIn('<a class="btn" href="action:outline">目录</a>', rendered)
        self.assertIn('<span class="sep">&nbsp;·&nbsp;</span>', rendered)

    def test_escapes_html_in_labels_and_separator(self) -> None:
        buttons = (
            ButtonSpec("side_by_side", "A <B> & \"C\""),
            ButtonSpec("outline", "TOC"),
        )
        rendered = build_toolbar_html(buttons, separator=" | ")
        self.assertIn("A &lt;B&gt; &amp; &quot;C&quot;", rendered)
        self.assertNotIn("<B>", rendered)
        self.assertIn('<span class="sep">&nbsp;|&nbsp;</span>', rendered)


class TestToolbarSignature(unittest.TestCase):
    def test_signature_order_independent_for_active_actions(self) -> None:
        sig1 = compute_toolbar_signature(
            enabled=True,
            show_toolbar=True,
            buttons=DEFAULT_BUTTONS,
            active_actions=["outline", "side_by_side"],
            separator=" · ",
            annotation_color="transparent",
        )
        sig2 = compute_toolbar_signature(
            enabled=True,
            show_toolbar=True,
            buttons=DEFAULT_BUTTONS,
            active_actions={"side_by_side", "outline"},
            separator=" · ",
            annotation_color="transparent",
        )
        self.assertEqual(sig1, sig2)

    def test_signature_changes_when_state_differs(self) -> None:
        sig1 = compute_toolbar_signature(
            enabled=True,
            show_toolbar=True,
            buttons=DEFAULT_BUTTONS,
            active_actions=(),
            separator=" · ",
            annotation_color="transparent",
        )
        sig2 = compute_toolbar_signature(
            enabled=True,
            show_toolbar=True,
            buttons=DEFAULT_BUTTONS,
            active_actions=("side_by_side",),
            separator=" · ",
            annotation_color="transparent",
        )
        self.assertNotEqual(sig1, sig2)


if __name__ == "__main__":
    unittest.main()
