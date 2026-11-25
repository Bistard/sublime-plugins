"""Sublime Text 4 entrypoint for MarkdownGlanceBar.

Provides ergonomic, Markdown-only entry points for MarkdownGlance:
1. A compact top-right editor annotation toolbar (`分屏预览 · 全屏 · 目录`)
   anchored at line 1 without colliding with MarkdownFold arrows.
2. Markdown-only editor right-click context menu entries.
3. Smart side-by-side toggle (clicking again closes the split preview) with
   optional source-editor focus retention.
"""

from __future__ import annotations

from typing import Any

import sublime
import sublime_plugin

from .core.dispatch_engine import WindowPreviewState, decide_action
from .core.toolbar_engine import (
    DEFAULT_ANNOTATION_COLOR,
    DEFAULT_SEPARATOR,
    build_toolbar_html,
    compute_toolbar_signature,
    normalize_buttons,
    parse_action_href,
)

SETTINGS_FILE = "MarkdownGlanceBar.sublime-settings"
SETTINGS_CHANGE_KEY = "markdown_glance_bar.settings"
REGION_KEY = "markdown_glance_bar.toolbar"
MARKDOWN_SELECTOR = "text.html.markdown"
GLANCE_ROLE_KEY = "mdglance.role"
GLANCE_SETTINGS_RESOURCE = "MarkdownGlance.sublime-settings"

FOCUS_RESTORE_DELAY_MS = 35
WINDOW_REFRESH_DELAY_MS = 90

_last_toolbar_sig: dict[int, tuple[Any, ...]] = {}
_pending_window_refresh: dict[int, int] = {}


# ── Settings Helpers ────────────────────────────────────────────────────────


def _settings() -> sublime.Settings:
    return sublime.load_settings(SETTINGS_FILE)


def _is_enabled(view: sublime.View) -> bool:
    view_flag = view.settings().get("markdown_glance_bar_enabled")
    if view_flag is not None:
        return bool(view_flag)
    return bool(_settings().get("enabled", True))


def _show_toolbar(view: sublime.View) -> bool:
    view_flag = view.settings().get("markdown_glance_bar_show_toolbar")
    if view_flag is not None:
        return bool(view_flag)
    return bool(_settings().get("show_toolbar", True))


def _toggle_side_by_side() -> bool:
    return bool(_settings().get("toggle_side_by_side", True))


def _keep_source_focus() -> bool:
    return bool(_settings().get("keep_source_focus", True))


def _toolbar_separator() -> str:
    raw = _settings().get("toolbar_separator", DEFAULT_SEPARATOR)
    return raw if isinstance(raw, str) else DEFAULT_SEPARATOR


def _annotation_color() -> str:
    raw = _settings().get("annotation_color", DEFAULT_ANNOTATION_COLOR)
    return raw if isinstance(raw, str) and raw.strip() else DEFAULT_ANNOTATION_COLOR


def _configured_buttons():
    return normalize_buttons(_settings().get("buttons"))


# ── View & MarkdownGlance State Inspection ──────────────────────────────────


def _is_markdown_source_view(view: sublime.View | None) -> bool:
    if not view or not view.is_valid():
        return False
    if view.element() is not None:
        return False
    view_settings = view.settings()
    if view_settings.get("is_widget") or view_settings.get(GLANCE_ROLE_KEY):
        return False
    if view.size() == 0:
        syn = view.syntax()
        return bool(syn and syn.scope.startswith(MARKDOWN_SELECTOR))
    return bool(view.match_selector(0, MARKDOWN_SELECTOR))


def _is_glance_installed() -> bool:
    return bool(sublime.find_resources(GLANCE_SETTINGS_RESOURCE))


def _find_glance_view(window: sublime.Window, role: str) -> sublime.View | None:
    for view in window.views():
        if view.is_valid() and view.settings().get(GLANCE_ROLE_KEY) == role:
            return view
    return None


def _inspect_window_state(
    window: sublime.Window | None,
    source_view: sublime.View | None,
) -> WindowPreviewState:
    source_group = -1
    preview_group: int | None = None
    outline_open = False

    source_is_active = True
    if window is not None:
        if source_view is not None and source_view.is_valid():
            group, _ = window.get_view_index(source_view)
            source_group = group
            active_in_group = window.active_view_in_group(group) if group >= 0 else None
            source_is_active = active_in_group == source_view

        for view in window.views():
            if not view.is_valid():
                continue
            role = view.settings().get(GLANCE_ROLE_KEY)
            if role == "preview" and preview_group is None:
                group, _ = window.get_view_index(view)
                if group >= 0:
                    preview_group = group
            elif role == "outline":
                outline_open = True

    return WindowPreviewState(
        glance_installed=_is_glance_installed(),
        source_group=source_group,
        preview_group=preview_group,
        outline_open=outline_open,
        source_is_active=source_is_active,
    )


# ── Annotation Toolbar Rendering ────────────────────────────────────────────


def _clear_toolbar(view: sublime.View) -> None:
    vid = view.id()
    _last_toolbar_sig.pop(vid, None)
    if view.is_valid():
        view.erase_regions(REGION_KEY)


def _is_anchored_on_first_line(view: sublime.View) -> bool:
    regions = view.get_regions(REGION_KEY)
    if len(regions) != 1:
        return False
    row, _ = view.rowcol(regions[0].a)
    return row == 0


def _refresh_view(view: sublime.View | None, *, force: bool = False) -> None:
    if not view or not view.is_valid():
        return

    if not _is_markdown_source_view(view):
        _clear_toolbar(view)
        return

    enabled = _is_enabled(view)
    show_toolbar = _show_toolbar(view)
    if not enabled or not show_toolbar:
        _clear_toolbar(view)
        return

    buttons = _configured_buttons()
    if not buttons:
        _clear_toolbar(view)
        return

    state = _inspect_window_state(view.window(), view)
    separator = _toolbar_separator()
    color = _annotation_color()
    active_actions = state.active_actions()

    sig = compute_toolbar_signature(
        enabled=enabled,
        show_toolbar=show_toolbar,
        buttons=buttons,
        active_actions=active_actions,
        separator=separator,
        annotation_color=color,
    )

    vid = view.id()
    if not force and _last_toolbar_sig.get(vid) == sig and _is_anchored_on_first_line(view):
        return

    html_body = build_toolbar_html(
        buttons,
        active_actions=active_actions,
        separator=separator,
    )
    if not html_body:
        _clear_toolbar(view)
        return

    view.add_regions(
        REGION_KEY,
        [sublime.Region(0, 0)],
        scope="",
        flags=sublime.RegionFlags.HIDE_ON_MINIMAP | sublime.RegionFlags.NO_UNDO,
        annotations=[html_body],
        annotation_color=color,
        on_navigate=lambda href, target_view=view: _on_toolbar_navigate(
            target_view, href
        ),
    )
    _last_toolbar_sig[vid] = sig


def _refresh_window(window: sublime.Window | None, *, force: bool = False) -> None:
    if window is None or not window.is_valid():
        return
    for view in window.views():
        _refresh_view(view, force=force)


def _refresh_all_views(*, force: bool = False) -> None:
    for window in sublime.windows():
        _refresh_window(window, force=force)


def _schedule_window_refresh(
    window: sublime.Window | None,
    *,
    delay_ms: int = WINDOW_REFRESH_DELAY_MS,
) -> None:
    if window is None or not window.is_valid():
        return
    wid = window.id()
    seq = _pending_window_refresh.get(wid, 0) + 1
    _pending_window_refresh[wid] = seq

    def _run() -> None:
        if _pending_window_refresh.get(wid) != seq:
            return
        _pending_window_refresh.pop(wid, None)
        if window.is_valid():
            _refresh_window(window)

    sublime.set_timeout(_run, delay_ms)


# ── Action Dispatch ─────────────────────────────────────────────────────────


def _restore_source_focus(
    window: sublime.Window,
    source_view: sublime.View,
) -> None:
    if window.is_valid() and source_view.is_valid():
        window.focus_view(source_view)


def _execute_action(
    window: sublime.Window | None,
    source_view: sublime.View | None,
    action: str,
) -> None:
    if window is None or not window.is_valid():
        return
    if not _is_markdown_source_view(source_view):
        return
    assert source_view is not None

    state = _inspect_window_state(window, source_view)
    plan = decide_action(
        action,
        state,
        toggle_side_by_side=_toggle_side_by_side(),
        keep_source_focus=_keep_source_focus(),
    )

    if plan.kind == "noop":
        return

    if plan.kind == "missing_dependency":
        sublime.error_message(plan.message or "MarkdownGlance 未安装。")
        return

    if plan.kind == "close_preview":
        preview_view = _find_glance_view(window, "preview")
        if preview_view is not None and preview_view.is_valid():
            preview_view.close()
        if plan.restore_source_focus:
            sublime.set_timeout(
                lambda: _restore_source_focus(window, source_view),
                FOCUS_RESTORE_DELAY_MS,
            )
        _schedule_window_refresh(window, delay_ms=WINDOW_REFRESH_DELAY_MS)
        return

    if plan.kind == "run_command" and plan.command:
        # Ensure the clicked Markdown view is active so MarkdownGlance targets it.
        if window.active_view() != source_view:
            window.focus_view(source_view)
        window.run_command(plan.command)
        if plan.restore_source_focus:
            sublime.set_timeout(
                lambda: _restore_source_focus(window, source_view),
                FOCUS_RESTORE_DELAY_MS,
            )
        _schedule_window_refresh(window, delay_ms=WINDOW_REFRESH_DELAY_MS)


def _on_toolbar_navigate(view: sublime.View, href: str) -> None:
    action = parse_action_href(href)
    if action is None or not view.is_valid():
        return
    _execute_action(view.window(), view, action)


# ── Sublime Commands & Event Listeners ──────────────────────────────────────


def _resolve_target_view(
    window: sublime.Window,
    group: int = -1,
    index: int = -1,
) -> sublime.View | None:
    if group >= 0 and index >= 0:
        sheets = window.sheets_in_group(group)
        if 0 <= index < len(sheets):
            return sheets[index].view()
        return None
    return window.active_view()


class MarkdownGlanceBarActionCommand(sublime_plugin.WindowCommand):
    """Run a MarkdownGlance action from menus, tab context, or command palette."""

    def run(
        self,
        action: str = "side_by_side",
        group: int = -1,
        index: int = -1,
    ) -> None:
        source_view = _resolve_target_view(self.window, group=group, index=index)
        _execute_action(self.window, source_view, action)

    def is_visible(
        self,
        action: str = "side_by_side",
        group: int = -1,
        index: int = -1,
    ) -> bool:
        view = _resolve_target_view(self.window, group=group, index=index)
        if not _is_markdown_source_view(view):
            return False
        assert view is not None
        return _is_enabled(view)

    def is_enabled(
        self,
        action: str = "side_by_side",
        group: int = -1,
        index: int = -1,
    ) -> bool:
        return self.is_visible(action=action, group=group, index=index)


class MarkdownGlanceBarToggleToolbarCommand(sublime_plugin.WindowCommand):
    """Toggle the top-right MarkdownGlanceBar annotation toolbar globally."""

    def run(self) -> None:
        settings = _settings()
        current = bool(settings.get("show_toolbar", True))
        settings.set("show_toolbar", not current)
        sublime.save_settings(SETTINGS_FILE)
        _refresh_all_views(force=True)
        status = "已开启" if not current else "已隐藏"
        sublime.status_message(f"MarkdownGlanceBar: 右上角工具栏{status}")


class MarkdownGlanceBarListener(sublime_plugin.EventListener):
    def on_new_async(self, view: sublime.View) -> None:
        _refresh_view(view)

    def on_load_async(self, view: sublime.View) -> None:
        _refresh_view(view)

    def on_activated_async(self, view: sublime.View) -> None:
        _refresh_view(view)
        if view.is_valid() and view.settings().get(GLANCE_ROLE_KEY):
            _schedule_window_refresh(view.window(), delay_ms=50)

    def on_modified_async(self, view: sublime.View) -> None:
        if not view.is_valid():
            return
        if view.id() not in _last_toolbar_sig:
            return
        if not _is_anchored_on_first_line(view):
            _refresh_view(view, force=True)

    def on_close(self, view: sublime.View) -> None:
        _last_toolbar_sig.pop(view.id(), None)
        if view.settings().get(GLANCE_ROLE_KEY):
            _schedule_window_refresh(view.window(), delay_ms=WINDOW_REFRESH_DELAY_MS)

    def on_post_window_command(
        self,
        window: sublime.Window,
        command_name: str,
        args: Any,
    ) -> None:
        if (
            command_name.startswith("mdglance_")
            or command_name in {"set_file_type", "close", "close_by_index", "close_pane"}
        ):
            _schedule_window_refresh(window, delay_ms=WINDOW_REFRESH_DELAY_MS)

    def on_post_text_command(
        self,
        view: sublime.View,
        command_name: str,
        args: Any,
    ) -> None:
        if command_name == "set_file_type":
            _refresh_view(view, force=True)


# ── Plugin Lifecycle ────────────────────────────────────────────────────────


def _on_settings_changed() -> None:
    _refresh_all_views(force=True)


def plugin_loaded() -> None:
    _settings().add_on_change(SETTINGS_CHANGE_KEY, _on_settings_changed)
    sublime.set_timeout(lambda: _refresh_all_views(force=True), 50)


def plugin_unloaded() -> None:
    _settings().clear_on_change(SETTINGS_CHANGE_KEY)
    _pending_window_refresh.clear()
    for window in sublime.windows():
        for view in window.views():
            _clear_toolbar(view)
    _last_toolbar_sig.clear()
