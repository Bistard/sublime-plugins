"""Pure-Python action dispatch and smart side-by-side toggle decisions."""

from __future__ import annotations

from dataclasses import dataclass

from .toolbar_engine import ACTION_COMMANDS

MISSING_GLANCE_MESSAGE = (
    "MarkdownGlance 尚未安装或尚未加载。\n\n"
    "请确认已安装 Package Control，并重启 Sublime Text 等待自动安装完成；\n"
    "或按 Ctrl+Shift+P 运行 \"Package Control: Install Package\" 手动安装 MarkdownGlance。"
)


@dataclass(frozen=True)
class WindowPreviewState:
    """Observed MarkdownGlance state in the current Sublime Text window."""

    glance_installed: bool
    source_group: int
    preview_group: int | None = None
    outline_open: bool = False
    source_is_active: bool = True

    @property
    def is_side_by_side_open(self) -> bool:
        return (
            self.preview_group is not None
            and self.source_group >= 0
            and self.preview_group != self.source_group
        )

    @property
    def is_full_screen_open(self) -> bool:
        return (
            self.preview_group is not None
            and self.source_group >= 0
            and self.preview_group == self.source_group
        )

    def active_actions(self) -> frozenset[str]:
        active: set[str] = set()
        if self.is_side_by_side_open:
            active.add("side_by_side")
        elif self.is_full_screen_open:
            active.add("full_screen")
        if self.outline_open:
            active.add("outline")
        return frozenset(active)


@dataclass(frozen=True)
class ActionPlan:
    """Decision returned to the Sublime Text command bridge."""

    kind: str  # "run_command" | "close_preview" | "missing_dependency" | "noop"
    command: str | None = None
    restore_source_focus: bool = False
    message: str | None = None


def decide_action(
    action: str,
    state: WindowPreviewState,
    *,
    toggle_side_by_side: bool = True,
    keep_source_focus: bool = True,
) -> ActionPlan:
    """Compute how to execute a toolbar or context-menu action."""
    if action not in ACTION_COMMANDS:
        return ActionPlan(kind="noop")

    if not state.glance_installed:
        return ActionPlan(
            kind="missing_dependency",
            message=MISSING_GLANCE_MESSAGE,
        )

    if action == "side_by_side":
        if toggle_side_by_side and state.is_side_by_side_open and state.source_is_active:
            return ActionPlan(kind="close_preview", restore_source_focus=True)
        return ActionPlan(
            kind="run_command",
            command=ACTION_COMMANDS["side_by_side"],
            restore_source_focus=keep_source_focus,
        )

    if action == "outline":
        return ActionPlan(
            kind="run_command",
            command=ACTION_COMMANDS["outline"],
            restore_source_focus=keep_source_focus,
        )

    if action == "full_screen":
        return ActionPlan(
            kind="run_command",
            command=ACTION_COMMANDS["full_screen"],
            restore_source_focus=False,
        )

    return ActionPlan(
        kind="run_command",
        command=ACTION_COMMANDS[action],
        restore_source_focus=False,
    )
