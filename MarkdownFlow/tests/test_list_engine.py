from __future__ import annotations

import unittest

from core.list_engine import (
    handle_backspace_at_marker,
    handle_enter,
    handle_indent,
    handle_soft_return,
    is_at_list_marker_end,
    parse_block_line,
    renumber_range,
)


class ListEngineTests(unittest.TestCase):
    def test_thematic_breaks_and_non_lists_ignored(self) -> None:
        for line in ("---", "- - -", "***", "* * *", "*italic*", "-3.14", "2026.11", "# Heading"):
            self.assertIsNone(parse_block_line(line), msg=f"Should ignore {line!r}")

    def test_unordered_enter_and_split(self) -> None:
        out = handle_enter(["* hello world"], 0, len("* hello"))
        assert out is not None
        self.assertEqual(out.lines, ["* hello", "*  world"])
        self.assertEqual(out.cursors, [(1, 2)])

    def test_ordered_insert_middle_and_renumber(self) -> None:
        lines = ["1. First", "2. Second", "3. Third"]
        out = handle_enter(lines, 0, len("1. First"))
        assert out is not None
        self.assertEqual(out.lines, ["1. First", "2. ", "3. Second", "4. Third"])
        self.assertEqual(out.cursors, [(1, 3)])

    def test_nine_to_ten_cursor_shift(self) -> None:
        lines = [f"{i}. Item {i}" for i in range(1, 10)]
        out = handle_enter(lines, 8, len("9. Item 9"))
        assert out is not None
        self.assertEqual(out.lines[9], "10. ")
        self.assertEqual(out.cursors, [(9, 4)])

    def test_custom_start_number_preserved(self) -> None:
        lines = ["5. Alpha", "6. Beta"]
        out = handle_enter(lines, 0, len("5. Alpha"))
        assert out is not None
        self.assertEqual(out.lines, ["5. Alpha", "6. ", "7. Beta"])

    def test_task_checked_resets_to_unchecked_on_enter(self) -> None:
        lines = ["- [x] Ship v1"]
        out = handle_enter(lines, 0, len(lines[0]))
        assert out is not None
        self.assertEqual(out.lines, ["- [x] Ship v1", "- [ ] "])
        self.assertEqual(out.cursors, [(1, 6)])

    def test_nested_empty_item_stepwise_outdent_and_exit(self) -> None:
        lines = [
            "1. Parent",
            "    - sub1",
            "    - ",
            "2. Next parent",
        ]
        # Step 1: Enter on empty `    - ` outdents to parent ordered list (`2. `) and bumps Next parent to `3.`
        out1 = handle_enter(lines, 2, len("    - "))
        assert out1 is not None
        self.assertEqual(
            out1.lines,
            [
                "1. Parent",
                "    - sub1",
                "2. ",
                "3. Next parent",
            ],
        )
        self.assertEqual(out1.cursors, [(2, 3)])

        # Step 2: Enter again on empty top-level `2. ` exits list and restores `2. Next parent`
        out2 = handle_enter(out1.lines, 2, out1.cursors[0][1])
        assert out2 is not None
        self.assertEqual(
            out2.lines,
            [
                "1. Parent",
                "    - sub1",
                "",
                "2. Next parent",
            ],
        )
        self.assertEqual(out2.cursors, [(2, 0)])

    def test_quoted_list_continuation_and_stepwise_exit(self) -> None:
        lines = ["> 1. Quoted item"]
        out1 = handle_enter(lines, 0, len(lines[0]))
        assert out1 is not None
        self.assertEqual(out1.lines, ["> 1. Quoted item", "> 2. "])

        # Empty quoted list item -> plain quote `> `
        out2 = handle_enter(out1.lines, 1, len("> 2. "))
        assert out2 is not None
        self.assertEqual(out2.lines, ["> 1. Quoted item", "> "])

        # Empty quote `> ` -> blank line `""`
        out3 = handle_enter(out2.lines, 1, len("> "))
        assert out3 is not None
        self.assertEqual(out3.lines, ["> 1. Quoted item", ""])

    def test_cursor_before_marker_inserts_blank_line_above(self) -> None:
        lines = ["1. First item"]
        out = handle_enter(lines, 0, 0)
        assert out is not None
        self.assertEqual(out.lines, ["", "1. First item"])
        self.assertEqual(out.cursors, [(1, 0)])

    def test_soft_return_aligns_continuation(self) -> None:
        lines = ["1. First line"]
        out = handle_soft_return(lines, 0, len(lines[0]))
        assert out is not None
        self.assertEqual(out.lines, ["1. First line", "    "])
        self.assertEqual(out.cursors, [(1, 4)])

    def test_tab_and_shift_tab_roundtrip_with_renumbering(self) -> None:
        lines = ["1. A", "2. B", "3. C"]
        # Cursor at the END of `2. B` -> Tab indents to `    1. B`, and `3. C` becomes `2. C`
        out_in = handle_indent(lines, [((1, 4), (1, 4))], direction=1)
        assert out_in is not None
        self.assertEqual(out_in.lines, ["1. A", "    1. B", "2. C"])
        self.assertEqual(out_in.cursors, [(1, 8)])

        # Shift+Tab on `    1. B` restores `1. A`, `2. B`, `3. C`
        out_out = handle_indent(out_in.lines, [((1, 8), (1, 8))], direction=-1)
        assert out_out is not None
        self.assertEqual(out_out.lines, ["1. A", "2. B", "3. C"])
        self.assertEqual(out_out.cursors, [(1, 4)])

    def test_backspace_removes_whole_marker_and_renumbers(self) -> None:
        lines = ["    - [ ] Buy milk"]
        self.assertTrue(is_at_list_marker_end(lines[0], 10))
        self.assertFalse(is_at_list_marker_end(lines[0], 11))
        out = handle_backspace_at_marker(lines, 0, 10)
        assert out is not None
        self.assertEqual(out.lines, ["    Buy milk"])
        self.assertEqual(out.cursors, [(0, 4)])

        # Backspace on first ordered item renumbers remaining items from 1
        ordered = ["1. Intro", "2. Real one", "3. Real two"]
        out_ord = handle_backspace_at_marker(ordered, 0, 3)
        assert out_ord is not None
        self.assertEqual(out_ord.lines, ["Intro", "1. Real one", "2. Real two"])

    def test_fenced_code_block_inside_list_not_renumbered(self) -> None:
        lines = [
            "1. Step one",
            "    ```markdown",
            "    99. do not touch",
            "    ```",
            "5. Step two",
        ]
        renumber_range(lines, 0, len(lines) - 1)
        self.assertEqual(lines[2], "    99. do not touch")
        self.assertEqual(lines[4], "2. Step two")

    def test_second_sublist_backspace_renumbers_independently(self) -> None:
        lines = [
            "1. Parent A",
            "    1. Sub A1",
            "2. Parent B",
            "    1. Sub B1",
            "    2. Sub B2",
        ]
        out = handle_backspace_at_marker(lines, 3, len("    1. "))
        assert out is not None
        self.assertEqual(
            out.lines,
            [
                "1. Parent A",
                "    1. Sub A1",
                "2. Parent B",
                "    Sub B1",
                "    1. Sub B2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
