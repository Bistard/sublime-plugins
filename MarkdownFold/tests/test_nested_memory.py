import unittest

from core.nested_memory import (
    capture_absorbed_folds,
    diff_fold_transitions,
    pop_restorable_children,
    select_maximal_intervals,
)


class TestNestedMemory(unittest.TestCase):
    def test_two_level_remember_and_restore(self):
        h1 = (10, 100)
        h2 = (30, 60)

        # H2 is folded, then H1 is folded
        rem = capture_absorbed_folds(h1, prev_active=[h2], remembered=[])
        self.assertEqual(rem, [h2])

        # Unfold H1 -> restores H2
        to_refold, remaining = pop_restorable_children(h1, rem, current_active=[])
        self.assertEqual(to_refold, [h2])
        self.assertEqual(remaining, [])

    def test_three_level_nested_memory_restores_step_by_step(self):
        h1 = (10, 200)
        h2 = (30, 150)
        h3 = (60, 110)

        # 1. Fold H3 -> active=[h3], rem=[]
        # 2. Fold H2 -> active=[h2], rem=[h3]
        rem = capture_absorbed_folds(h2, prev_active=[h3], remembered=[])
        self.assertEqual(rem, [h3])

        # 3. Fold H1 -> active=[h1], rem=[h2, h3]
        rem = capture_absorbed_folds(h1, prev_active=[h2], remembered=rem)
        self.assertEqual(rem, [h2, h3])

        # 4. Unfold H1 -> restores ONLY maximal child [h2]; keeps [h3] remembered!
        to_refold, rem = pop_restorable_children(h1, rem, current_active=[])
        self.assertEqual(to_refold, [h2])
        self.assertEqual(rem, [h3])

        # 5. Unfold H2 -> restores [h3]; remembered becomes empty
        to_refold2, rem2 = pop_restorable_children(h2, rem, current_active=[])
        self.assertEqual(to_refold2, [h3])
        self.assertEqual(rem2, [])

    def test_multiple_sibling_children_restored_together(self):
        h1 = (10, 200)
        h2a = (30, 80)
        h2b = (100, 180)
        h3b = (120, 160)

        rem = capture_absorbed_folds(h2b, prev_active=[h3b], remembered=[])
        rem = capture_absorbed_folds(h1, prev_active=[h2a, h2b], remembered=rem)

        to_refold, remaining = pop_restorable_children(h1, rem, current_active=[])
        self.assertEqual(to_refold, [h2a, h2b])
        self.assertEqual(remaining, [h3b])

    def test_diff_transitions_ignores_title_rename_widening(self):
        # Editing visible heading text can widen tracked HIDDEN region (10, 52) while real fold is (12, 52)
        newly_folded, absorbed, newly_unfolded = diff_fold_transitions(
            prev_active=[(10, 52)],
            curr_active=[(12, 52)],
        )
        self.assertEqual(newly_folded, [])
        self.assertEqual(absorbed, [])
        self.assertEqual(newly_unfolded, [])

    def test_diff_transitions_detects_external_fold_and_unfold(self):
        # External fold absorbs inner fold
        newly_folded, absorbed, newly_unfolded = diff_fold_transitions(
            prev_active=[(30, 60)],
            curr_active=[(10, 100)],
        )
        self.assertEqual(newly_folded, [(10, 100)])
        self.assertEqual(absorbed, [(30, 60)])
        self.assertEqual(newly_unfolded, [])

        # External unfold
        newly_folded2, absorbed2, newly_unfolded2 = diff_fold_transitions(
            prev_active=[(10, 100), (120, 160)],
            curr_active=[(120, 160)],
        )
        self.assertEqual(newly_folded2, [])
        self.assertEqual(absorbed2, [])
        self.assertEqual(newly_unfolded2, [(10, 100)])

    def test_select_maximal_intervals(self):
        res = select_maximal_intervals([(10, 100), (20, 50), (30, 40), (110, 150), (120, 140)])
        self.assertEqual(res, [(10, 100), (110, 150)])


if __name__ == "__main__":
    unittest.main()
