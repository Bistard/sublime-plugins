from __future__ import annotations

import unittest

from core.dispatch_engine import (
    MISSING_GLANCE_MESSAGE,
    ActionPlan,
    WindowPreviewState,
    decide_action,
)


class TestWindowPreviewState(unittest.TestCase):
    def test_no_preview_open(self) -> None:
        state = WindowPreviewState(glance_installed=True, source_group=0)
        self.assertFalse(state.is_side_by_side_open)
        self.assertFalse(state.is_full_screen_open)
        self.assertEqual(state.active_actions(), frozenset())

    def test_side_by_side_open_when_preview_in_other_group(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=1,
            outline_open=True,
        )
        self.assertTrue(state.is_side_by_side_open)
        self.assertFalse(state.is_full_screen_open)
        self.assertEqual(state.active_actions(), frozenset({"side_by_side", "outline"}))

    def test_full_screen_open_when_preview_in_same_group(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=0,
            outline_open=False,
        )
        self.assertFalse(state.is_side_by_side_open)
        self.assertTrue(state.is_full_screen_open)
        self.assertEqual(state.active_actions(), frozenset({"full_screen"}))


class TestDecideAction(unittest.TestCase):
    def test_unknown_action_returns_noop(self) -> None:
        state = WindowPreviewState(glance_installed=True, source_group=0)
        self.assertEqual(decide_action("invalid", state), ActionPlan(kind="noop"))

    def test_missing_dependency_returns_guidance_message(self) -> None:
        state = WindowPreviewState(glance_installed=False, source_group=0)
        plan = decide_action("side_by_side", state)
        self.assertEqual(plan.kind, "missing_dependency")
        self.assertEqual(plan.message, MISSING_GLANCE_MESSAGE)

    def test_side_by_side_opens_and_keeps_source_focus(self) -> None:
        state = WindowPreviewState(glance_installed=True, source_group=0)
        plan = decide_action(
            "side_by_side",
            state,
            toggle_side_by_side=True,
            keep_source_focus=True,
        )
        self.assertEqual(
            plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_open_side_by_side",
                restore_source_focus=True,
            ),
        )

    def test_side_by_side_second_click_closes_preview_when_toggle_enabled(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=1,
        )
        plan = decide_action(
            "side_by_side",
            state,
            toggle_side_by_side=True,
            keep_source_focus=False,
        )
        self.assertEqual(
            plan,
            ActionPlan(kind="close_preview", restore_source_focus=True),
        )

    def test_side_by_side_when_toggle_disabled_runs_native_command(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=1,
        )
        plan = decide_action(
            "side_by_side",
            state,
            toggle_side_by_side=False,
            keep_source_focus=False,
        )
        self.assertEqual(
            plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_open_side_by_side",
                restore_source_focus=False,
            ),
        )

    def test_side_by_side_switches_from_full_screen_instead_of_closing(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=0,
        )
        plan = decide_action(
            "side_by_side",
            state,
            toggle_side_by_side=True,
            keep_source_focus=True,
        )
        self.assertEqual(
            plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_open_side_by_side",
                restore_source_focus=True,
            ),
        )

    def test_side_by_side_on_inactive_background_tab_opens_instead_of_closing(self) -> None:
        state = WindowPreviewState(
            glance_installed=True,
            source_group=0,
            preview_group=1,
            source_is_active=False,
        )
        plan = decide_action(
            "side_by_side",
            state,
            toggle_side_by_side=True,
            keep_source_focus=True,
        )
        self.assertEqual(
            plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_open_side_by_side",
                restore_source_focus=True,
            ),
        )

    def test_outline_honors_keep_source_focus(self) -> None:
        state = WindowPreviewState(glance_installed=True, source_group=0)
        plan_keep = decide_action("outline", state, keep_source_focus=True)
        plan_focus = decide_action("outline", state, keep_source_focus=False)
        self.assertEqual(plan_keep.command, "mdglance_toggle_outline")
        self.assertTrue(plan_keep.restore_source_focus)
        self.assertFalse(plan_focus.restore_source_focus)

    def test_full_screen_and_browser_never_restore_source_focus(self) -> None:
        state = WindowPreviewState(glance_installed=True, source_group=0)
        fs_plan = decide_action("full_screen", state, keep_source_focus=True)
        br_plan = decide_action("browser", state, keep_source_focus=True)
        self.assertEqual(
            fs_plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_toggle_full_screen",
                restore_source_focus=False,
            ),
        )
        self.assertEqual(
            br_plan,
            ActionPlan(
                kind="run_command",
                command="mdglance_open_in_browser",
                restore_source_focus=False,
            ),
        )


if __name__ == "__main__":
    unittest.main()
