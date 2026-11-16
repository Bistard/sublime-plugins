from __future__ import annotations

import unittest

from core.inline_engine import (
    apply_insert_link,
    apply_smart_paste_url,
    can_smart_paste_url,
    toggle_inline_span,
)


class InlineEngineTests(unittest.TestCase):
    def test_cjk_streaming_bold_flow(self) -> None:
        # 1. Insert `**|**` right after Chinese characters without swallowing clause
        line, a, b = toggle_inline_span("今天学习", 4, 4, "**")
        self.assertEqual((line, a, b), ("今天学习****", 6, 6))

        # 2. Pressing Ctrl+B immediately on empty `**|**` removes it cleanly
        undone, ua, ub = toggle_inline_span(line, a, b, "**")
        self.assertEqual((undone, ua, ub), ("今天学习", 4, 4))

        # 3. Typing inside `**重点|**` then pressing Ctrl+B jumps out past closing `**`
        typed = "今天学习**重点**"
        cursor_before_close = len("今天学习**重点")
        jumped, ja, jb = toggle_inline_span(typed, cursor_before_close, cursor_before_close, "**")
        self.assertEqual((jumped, ja, jb), ("今天学习**重点**", len(typed), len(typed)))

    def test_cursor_between_two_bold_spans_does_not_false_match(self) -> None:
        line = "这是 **第一处** 中间文字 **第二处** 结尾"
        pos = line.index("中间") + 1
        out, a, b = toggle_inline_span(line, pos, pos, "**")
        self.assertEqual(out, "这是 **第一处** 中****间文字 **第二处** 结尾")
        self.assertEqual((a, b), (pos + 2, pos + 2))

    def test_cursor_inside_existing_bold_unwraps(self) -> None:
        line = "今天**重点内容**结束"
        pos = line.index("点")
        out, a, b = toggle_inline_span(line, pos, pos, "**")
        self.assertEqual(out, "今天重点内容结束")
        self.assertEqual((a, b), (pos - 2, pos - 2))

    def test_bold_italic_xor_matrix(self) -> None:
        # Plain -> Bold -> Bold+Italic -> Italic -> Plain
        line, a, b = toggle_inline_span("hello world", 0, 5, "**")
        self.assertEqual((line, line[a:b]), ("**hello** world", "hello"))

        line, a, b = toggle_inline_span(line, a, b, "*")
        self.assertEqual((line, line[a:b]), ("***hello*** world", "hello"))

        line, a, b = toggle_inline_span(line, a, b, "**")
        self.assertEqual((line, line[a:b]), ("*hello* world", "hello"))

        line, a, b = toggle_inline_span(line, a, b, "*")
        self.assertEqual((line, line[a:b]), ("hello world", "hello"))

    def test_star_list_bullet_not_treated_as_italic_delimiter(self) -> None:
        line = "* 列表内容"
        pos = len(line)
        out, a, b = toggle_inline_span(line, pos, pos, "*")
        self.assertEqual(out, "* 列表内容**")
        self.assertEqual((a, b), (pos + 1, pos + 1))

    def test_inline_code_toggle_and_backtick_escaping(self) -> None:
        # Streaming after CJK
        line, a, b = toggle_inline_span("命令", 2, 2, "`")
        self.assertEqual((line, a, b), ("命令``", 3, 3))

        # Wrapping text containing a literal backtick uses double backticks
        raw = "use a`b here"
        out, sa, sb = toggle_inline_span(raw, 4, 7, "`")
        self.assertEqual(out, "use ``a`b`` here")
        self.assertEqual(out[sa:sb], "a`b")

        # Toggling again unwraps double backticks
        unwrapped, ua, ub = toggle_inline_span(out, sa, sb, "`")
        self.assertEqual(unwrapped, raw)
        self.assertEqual(unwrapped[ua:ub], "a`b")

    def test_strikethrough_toggle(self) -> None:
        line, a, b = toggle_inline_span("淘汰方案", 0, 2, "~~")
        self.assertEqual((line, line[a:b]), ("~~淘汰~~方案", "淘汰"))
        line2, a2, b2 = toggle_inline_span(line, a, b, "~~")
        self.assertEqual((line2, line2[a2:b2]), ("淘汰方案", "淘汰"))

    def test_smart_paste_url_and_guards(self) -> None:
        line = "请查看 官方文档 了解详情"
        a = line.index("官方文档")
        b = a + len("官方文档")
        res = apply_smart_paste_url(line, a, b, "https://www.sublimetext.com/docs/\n")
        assert res is not None
        new_line, na, nb = res
        self.assertEqual(new_line, "请查看 [官方文档](https://www.sublimetext.com/docs/) 了解详情")
        self.assertEqual(na, nb)

        # Guard 1: Replacing an existing URL with a new URL should NOT wrap
        url_line = "https://old.example.com"
        self.assertFalse(can_smart_paste_url(url_line, 0, len(url_line), "https://new.example.com"))

        # Guard 2: Inside inline code should NOT wrap
        code_line = "运行 `curl foo` 命令"
        ca = code_line.index("foo")
        self.assertFalse(can_smart_paste_url(code_line, ca, ca + 3, "https://example.com"))

        # Guard 3: Inside existing `[title](old_path)` destination should NOT wrap
        link_line = "[官网](https://example.com/old)"
        la = link_line.index("https://")
        lb = len(link_line) - 1
        self.assertFalse(can_smart_paste_url(link_line, la, lb, "https://example.com/new"))

    def test_insert_link_ergonomic_steps(self) -> None:
        # Empty -> `[|]()`
        line, a, b = apply_insert_link("参考", 2, 2)
        self.assertEqual((line, a, b), ("参考[]()", 3, 3))

        # Typed `[Sublime|]()` -> pressing Alt+K jumps into `(|)`
        typed = "参考[Sublime]()"
        pos = typed.index("](")
        line2, a2, b2 = apply_insert_link(typed, pos, pos)
        self.assertEqual((line2, a2, b2), ("参考[Sublime]()", len("参考[Sublime]("), len("参考[Sublime](")))

        # Selected URL -> `[|](url)`
        u = "https://sublimetext.com"
        line3, a3, b3 = apply_insert_link(u, 0, len(u))
        self.assertEqual((line3, a3, b3), (f"[]({u})", 1, 1))


if __name__ == "__main__":
    unittest.main()
