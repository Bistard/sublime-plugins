import unittest

from core.guardrail_engine import compute_safe_newline_edits, evaluate_command


class TestGuardrailEngine(unittest.TestCase):
    def setUp(self):
        # Doc with two folded H1 sections and an editable gap with ## new_title
        # Row 0: "# Section 1"          (0..11)
        # Row 1: "body 1"               (12..18)
        # Row 2: ""                     (19..19)  <- blank line
        # Row 3: "## new_title"         (20..32)
        # Row 4: "typing here"          (33..44)
        # Row 5: ""                     (45..45)  <- blank line
        # Row 6: "# Section 2"          (46..57)
        # Row 7: "body 2"               (58..64)
        self.doc = (
            "# Section 1\n"
            "body 1\n"
            "\n"
            "## new_title\n"
            "typing here\n"
            "\n"
            "# Section 2\n"
            "body 2"
        )
        self.f1 = (11, 18)  # "\nbody 1"
        self.f2 = (57, 64)  # "\nbody 2"
        self.folds = [self.f1, self.f2]

    def test_free_editing_in_gap_is_allowed(self):
        # Typing in gap
        self.assertEqual(
            evaluate_command("insert", {"characters": "hello"}, self.doc, [(35, 35)], self.folds).action,
            "allow",
        )
        # Pressing Enter in gap
        self.assertEqual(
            evaluate_command("insert", {"characters": "\n"}, self.doc, [(44, 44)], self.folds).action,
            "allow",
        )
        # Backspace inside gap (row 3 col 0 deletes blank line at row 2 — safe!)
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(20, 20)], self.folds).action,
            "allow",
        )
        # Delete on blank line above Section 2 (row 5 col 0 deletes blank line — safe!)
        self.assertEqual(
            evaluate_command("right_delete", None, self.doc, [(45, 45)], self.folds).action,
            "allow",
        )
        # Backspace at col 0 of Section 2 when preceded by blank line (deletes blank line — safe!)
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(46, 46)], self.folds).action,
            "allow",
        )
        # Selecting and deleting whole gap content "## new_title\ntyping here\n"
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(20, 45)], self.folds).action,
            "allow",
        )
        # Delete Line (Ctrl+Shift+K) on a normal line in the gap
        self.assertEqual(
            evaluate_command(
                "run_macro_file",
                {"file": "res://Packages/Default/Delete Line.sublime-macro"},
                self.doc,
                [(25, 25)],
                self.folds,
            ).action,
            "allow",
        )

    def test_boundary_backspace_and_delete_are_blocked(self):
        # Backspace at col 0 of the line immediately after fold1 (pt == f1.b + 1 == 19)
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(19, 19)], self.folds).action,
            "block",
        )
        # Backspace right after [...] (pt == f1.b == 18)
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(18, 18)], self.folds).action,
            "block",
        )
        # Delete right before [...] (pt == f1.a == 11) — would nuke whole section!
        self.assertEqual(
            evaluate_command("right_delete", None, self.doc, [(11, 11)], self.folds).action,
            "block",
        )
        # Delete right after [...] (pt == f1.b == 18)
        self.assertEqual(
            evaluate_command("right_delete", None, self.doc, [(18, 18)], self.folds).action,
            "block",
        )

        # Compact doc without blank line above Section 2:
        compact = "# Section 1\nbody 1\ntyping here\n# Section 2\nbody 2"
        folds = [(11, 18), (42, 49)]
        # Delete at EOL of "typing here" (pt == 30, line_start == 19) -> would merge # Section 2!
        self.assertEqual(
            evaluate_command("right_delete", None, compact, [(30, 30)], folds).action,
            "block",
        )
        # Backspace at col 0 of "# Section 2" (pt == 31) when line above has text -> block!
        self.assertEqual(
            evaluate_command("left_delete", None, compact, [(31, 31)], folds).action,
            "block",
        )

    def test_enter_at_fold_end_redirects_to_safe_newline(self):
        # Caret at `# Section 1 [...]|` (pt == 18)
        res = evaluate_command("insert", {"characters": "\n"}, self.doc, [(18, 18)], self.folds)
        self.assertEqual(res.action, "safe_newline")
        self.assertEqual(res.safe_newline_points, (18,))

        edits, carets = compute_safe_newline_edits(self.doc, res.safe_newline_points, self.folds)
        # Inserts at 19 (b + 1), never touching fold.b (18)!
        self.assertEqual(edits, [(19, "\n")])
        self.assertEqual(carets, [19])

        # Also works for MarkdownFlow Enter and Ctrl+Enter macro
        res_mf = evaluate_command("markdown_flow_enter", None, self.doc, [(18, 18)], self.folds)
        self.assertEqual(res_mf.action, "safe_newline")

        res_ctrl_enter = evaluate_command(
            "run_macro_file",
            {"file": "res://Packages/Default/Add Line.sublime-macro"},
            self.doc,
            [(4, 4)],  # caret inside visible heading text of folded Section 1
            self.folds,
        )
        self.assertEqual(res_ctrl_enter.action, "safe_newline")
        self.assertEqual(res_ctrl_enter.safe_newline_points, (18,))

    def test_safe_newline_at_eof_fold_without_trailing_newline(self):
        # Caret at `# Section 2 [...]|` where f2.b == len(doc) == 64
        edits, carets = compute_safe_newline_edits(self.doc, (64,), self.folds)
        self.assertEqual(edits, [(64, "\n")])
        self.assertEqual(carets, [65])

    def test_visible_heading_title_editing_vs_splitting(self):
        # Typing inside visible title `# Sec|tion 1 [...]` -> ALLOWED
        self.assertEqual(
            evaluate_command("insert", {"characters": "X"}, self.doc, [(5, 5)], self.folds).action,
            "allow",
        )
        # Typing at end of visible title `# Section 1|[...]` (pt == 11) -> ALLOWED
        self.assertEqual(
            evaluate_command("insert", {"characters": "2"}, self.doc, [(11, 11)], self.folds).action,
            "allow",
        )
        # Backspace at end of visible title `# Section 1|[...]` (pt == 11) -> ALLOWED
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(11, 11)], self.folds).action,
            "allow",
        )
        # Replacing selected visible title text "Section 1" -> ALLOWED
        self.assertEqual(
            evaluate_command("insert", {"characters": "Renamed"}, self.doc, [(2, 11)], self.folds).action,
            "allow",
        )
        # Enter inside visible title (would split heading) -> BLOCKED
        self.assertEqual(
            evaluate_command("insert", {"characters": "\n"}, self.doc, [(5, 5)], self.folds).action,
            "block",
        )
        # Enter at col 0 before `# Section 2 [...]` (inserts blank line above) -> ALLOWED
        self.assertEqual(
            evaluate_command("insert", {"characters": "\n"}, self.doc, [(46, 46)], self.folds).action,
            "allow",
        )
        # Multi-line paste inside visible title -> BLOCKED
        self.assertEqual(
            evaluate_command(
                "paste", None, self.doc, [(5, 5)], self.folds, clipboard_text="line1\nline2"
            ).action,
            "block",
        )
        # Single-line paste inside visible title -> ALLOWED
        self.assertEqual(
            evaluate_command(
                "paste", None, self.doc, [(5, 5)], self.folds, clipboard_text="Updated"
            ).action,
            "allow",
        )
        # Typing right AFTER `[...]` (`# Section 1 [...]|`, pt == 18) -> BLOCKED
        self.assertEqual(
            evaluate_command("insert", {"characters": "a"}, self.doc, [(18, 18)], self.folds).action,
            "block",
        )

    def test_bulk_destructive_commands_and_copy(self):
        # Selection crossing into fold1 -> BLOCKED for delete, cut, paste, insert
        for cmd, args in [
            ("left_delete", None),
            ("right_delete", None),
            ("cut", None),
            ("paste", None),
            ("insert", {"characters": "x"}),
        ]:
            self.assertEqual(
                evaluate_command(cmd, args, self.doc, [(5, 22)], self.folds).action,
                "block",
                msg=f"Expected {cmd} to be blocked",
            )

        # Read-only copy across folded section -> ALLOWED
        self.assertEqual(
            evaluate_command("copy", None, self.doc, [(0, 25)], self.folds).action,
            "allow",
        )

        # Empty-selection Ctrl+X on folded heading line -> BLOCKED
        self.assertEqual(
            evaluate_command("cut", None, self.doc, [(4, 4)], self.folds).action,
            "block",
        )

        # Ctrl+Shift+K (Delete Line) on folded heading line -> BLOCKED
        self.assertEqual(
            evaluate_command(
                "run_macro_file",
                {"file": "res://Packages/Default/Delete Line.sublime-macro"},
                self.doc,
                [(4, 4)],
                self.folds,
            ).action,
            "block",
        )

        # Ctrl+K Ctrl+K (Delete to EOL) inside folded heading line -> BLOCKED
        self.assertEqual(
            evaluate_command(
                "run_macro_file",
                {"file": "res://Packages/Default/Delete to EOL.sublime-macro"},
                self.doc,
                [(4, 4)],
                self.folds,
            ).action,
            "block",
        )

        # Selection that merges non-empty line onto folded Section 2 -> BLOCKED
        compact = "# Section 1\nbody 1\ntyping here\n# Section 2\nbody 2"
        folds = [(11, 18), (42, 49)]
        self.assertEqual(
            evaluate_command("left_delete", None, compact, [(25, 31)], folds).action,
            "block",
        )

    def test_line_swap_and_join_boundaries(self):
        compact = "# Section 1\nbody 1\ngap line\n# Section 2\nbody 2"
        folds = [(11, 18), (39, 46)]
        # swap_line_up on line right below fold1 -> BLOCKED
        self.assertEqual(
            evaluate_command("swap_line_up", None, compact, [(20, 20)], folds).action,
            "block",
        )
        # swap_line_down on line right above fold2 -> BLOCKED
        self.assertEqual(
            evaluate_command("swap_line_down", None, compact, [(20, 20)], folds).action,
            "block",
        )
        # join_lines on line right above fold2 -> BLOCKED
        self.assertEqual(
            evaluate_command("join_lines", None, compact, [(20, 20)], folds).action,
            "block",
        )

    def test_multi_cursor_blocks_if_any_cursor_unsafe(self):
        # One safe cursor in gap (35), one unsafe cursor at fold1.b + 1 (19)
        self.assertEqual(
            evaluate_command("left_delete", None, self.doc, [(35, 35), (19, 19)], self.folds).action,
            "block",
        )


if __name__ == "__main__":
    unittest.main()
