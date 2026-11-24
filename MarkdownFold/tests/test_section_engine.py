import unittest

from core.section_engine import (
    find_active_fold_for_section,
    find_enclosing_section,
    is_section_hidden_inside_fold,
    parse_sections,
)


class TestSectionEngine(unittest.TestCase):
    def test_hierarchical_multi_level_folding_with_subheadings(self):
        doc = (
            "# H1 Alpha\n"
            "intro alpha\n"
            "\n"
            "## H2 One\n"
            "body one\n"
            "\n"
            "### H3 Deep\n"
            "body deep\n"
            "\n"
            "#### H4 Deeper\n"
            "body deeper\n"
            "\n"
            "## H2 Two\n"
            "body two\n"
            "\n"
            "# H1 Beta\n"
            "intro beta\n"
        )
        sections = parse_sections(doc, keep_trailing_blank_lines=True)
        by_title = {s.title: s for s in sections}

        # H1 Alpha folds all the way through body two (excluding blank line before H1 Beta)
        h1 = by_title["H1 Alpha"]
        self.assertEqual(h1.level, 1)
        self.assertTrue(h1.foldable)
        self.assertEqual(
            doc[h1.fold_start : h1.fold_end],
            "\nintro alpha\n\n## H2 One\nbody one\n\n### H3 Deep\nbody deep\n\n#### H4 Deeper\nbody deeper\n\n## H2 Two\nbody two",
        )

        # H2 One folds through H3 Deep and H4 Deeper, stopping before H2 Two
        h2_one = by_title["H2 One"]
        self.assertEqual(
            doc[h2_one.fold_start : h2_one.fold_end],
            "\nbody one\n\n### H3 Deep\nbody deep\n\n#### H4 Deeper\nbody deeper",
        )

        # H3 Deep folds H4 Deeper too
        h3 = by_title["H3 Deep"]
        self.assertEqual(
            doc[h3.fold_start : h3.fold_end],
            "\nbody deep\n\n#### H4 Deeper\nbody deeper",
        )

        # H4 Deeper stops before H2 Two (jumping UP 2 levels)
        h4 = by_title["H4 Deeper"]
        self.assertEqual(doc[h4.fold_start : h4.fold_end], "\nbody deeper")

        # H2 Two stops before H1 Beta (jumping UP 1 level)
        h2_two = by_title["H2 Two"]
        self.assertEqual(doc[h2_two.fold_start : h2_two.fold_end], "\nbody two")

        # H1 Beta folds to EOF (excluding final trailing blank line from trailing \n)
        h1_beta = by_title["H1 Beta"]
        self.assertEqual(doc[h1_beta.fold_start : h1_beta.fold_end], "\nintro beta")

    def test_h1_directly_followed_by_h2_without_intro_is_foldable(self):
        doc = "# Chapter 1\n\n## Section 1.1\ncontent\n\n# Chapter 2\nmore"
        sections = parse_sections(doc)
        c1 = sections[0]
        self.assertEqual(c1.title, "Chapter 1")
        self.assertTrue(c1.foldable)
        self.assertEqual(doc[c1.fold_start : c1.fold_end], "\n\n## Section 1.1\ncontent")

    def test_keep_trailing_blank_lines_false(self):
        doc = "# A\nbody\n\n\n# B\nend"
        sections = parse_sections(doc, keep_trailing_blank_lines=False)
        a = sections[0]
        self.assertEqual(doc[a.fold_start : a.fold_end], "\nbody\n\n")

    def test_empty_heading_is_not_foldable(self):
        doc = "# Empty\n\n# Next\nbody\n# TailEmpty"
        sections = parse_sections(doc)
        self.assertFalse(sections[0].foldable)
        self.assertIsNone(sections[0].fold_range)
        self.assertTrue(sections[1].foldable)
        self.assertFalse(sections[2].foldable)

    def test_ignores_code_fences_frontmatter_comments_quotes_lists(self):
        doc = (
            "---\n"
            "title: Doc\n"
            "# yaml comment\n"
            "---\n"
            "# Real H1\n"
            "```python\n"
            "# python comment\n"
            "## another comment\n"
            "```\n"
            "~~~\n"
            "# tilde fence heading\n"
            "~~~\n"
            "<!--\n"
            "# commented heading\n"
            "-->\n"
            "> # quoted heading\n"
            "- # list heading\n"
            "    # indented code\n"
            "#nospace\n"
            "real body\n"
            "## Real H2 ##\n"
            "h2 body\n"
        )
        sections = parse_sections(doc)
        self.assertEqual([(s.level, s.title) for s in sections], [(1, "Real H1"), (2, "Real H2")])
        self.assertIn("# python comment", doc[sections[0].fold_start : sections[0].fold_end])
        self.assertIn("h2 body", doc[sections[0].fold_start : sections[0].fold_end])

    def test_setext_headings_and_thematic_break(self):
        doc = (
            "Setext One\n"
            "==========\n"
            "body 1\n"
            "\n"
            "Setext Two\n"
            "----------\n"
            "body 2\n"
            "\n"
            "---\n"
            "after hr\n"
        )
        sections = parse_sections(doc)
        self.assertEqual(
            [(s.level, s.title, s.is_setext, s.row, s.header_end_row) for s in sections],
            [
                (1, "Setext One", True, 0, 1),
                (2, "Setext Two", True, 4, 5),
            ],
        )
        self.assertIn("after hr", doc[sections[0].fold_start : sections[0].fold_end])
        self.assertIn("after hr", doc[sections[1].fold_start : sections[1].fold_end])

    def test_editing_new_subheading_between_two_folded_h1_sections(self):
        # User's exact scenario:
        # # Section 1 (folded)
        #
        # ## new_title
        # human typing...
        #
        # # Section 2 (folded)
        doc = (
            "# Section 1\n"
            "old body\n"
            "## Sub 1.1\n"
            "sub body\n"
            "\n"
            "## new_title\n"
            "human typing here\n"
            "\n"
            "# Section 2\n"
            "sec2 body\n"
        )
        sections = parse_sections(doc)
        by_title = {s.title: s for s in sections}

        # Active fold for Section 1 only covers up to "sub body" (before new_title was added)
        sub_body_end = doc.index("sub body") + len("sub body")
        sec1_active = (by_title["Section 1"].fold_start, sub_body_end)
        sec2_active = by_title["Section 2"].fold_range
        assert sec2_active is not None
        active = [sec1_active, sec2_active]

        # Section 1 is STILL recognized as collapsed via fold_start matching!
        self.assertEqual(find_active_fold_for_section(by_title["Section 1"], active), sec1_active)
        # Sub 1.1 is hidden inside Section 1's active fold
        self.assertTrue(is_section_hidden_inside_fold(by_title["Sub 1.1"], active))
        # new_title is NOT hidden and NOT collapsed
        self.assertFalse(is_section_hidden_inside_fold(by_title["new_title"], active))
        self.assertIsNone(find_active_fold_for_section(by_title["new_title"], active))
        # Enclosing section of "human typing here" (row 6) is new_title
        enclosing = find_enclosing_section(sections, 6)
        self.assertIsNotNone(enclosing)
        self.assertEqual(enclosing.title, "new_title")
        # Folding new_title stops cleanly before Section 2 (preserving blank line)
        nt = by_title["new_title"]
        self.assertEqual(doc[nt.fold_start : nt.fold_end], "\nhuman typing here")


if __name__ == "__main__":
    unittest.main()
