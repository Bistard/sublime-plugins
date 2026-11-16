"""Sublime Text entrypoint for MarkdownFlow.

Bridges Sublime Text's `View` / `Edit` / `EventListener` APIs to the pure-Python
engines in `.core.list_engine` and `.core.inline_engine`.
"""

from __future__ import annotations

import sublime
import sublime_plugin

from .core.inline_engine import (
    apply_insert_link,
    apply_smart_paste_url,
    can_smart_paste_url,
    toggle_inline_span,
)
from .core.list_engine import (
    DEFAULT_INDENT_SIZE,
    EditOutcome,
    can_handle_enter,
    can_indent_lines,
    handle_backspace_at_marker,
    handle_enter,
    handle_indent,
    handle_soft_return,
    is_at_list_marker_end,
    renumber_range,
)

SETTINGS_FILE = "MarkdownFlow.sublime-settings"

PROSE_SELECTOR = (
    "text.html.markdown"
    " - meta.code-fence"
    " - markup.raw.code-fence"
    " - meta.frontmatter"
    " - comment.block.html"
    " - text.tex"
)
SMART_PASTE_SELECTOR = PROSE_SELECTOR + " - markup.raw"
CLIPBOARD_MAX_BYTES = 8192


def _plugin_settings() -> sublime.Settings:
    return sublime.load_settings(SETTINGS_FILE)


def _is_enabled(view: sublime.View) -> bool:
    view_flag = view.settings().get("markdown_flow_enabled")
    if view_flag is not None:
        return bool(view_flag)
    return bool(_plugin_settings().get("enabled", True))


def _get_indent_size(view: sublime.View) -> int:
    override = view.settings().get("markdown_flow_list_indent_size")
    if isinstance(override, int) and override > 0:
        return override
    val = _plugin_settings().get("list_indent_size", DEFAULT_INDENT_SIZE)
    return val if isinstance(val, int) and val > 0 else DEFAULT_INDENT_SIZE


def _all_selections_match_selector(view: sublime.View, selector: str) -> bool:
    sels = view.sel()
    if len(sels) == 0:
        return False
    for reg in sels:
        if not view.match_selector(reg.begin(), selector):
            return False
        if not reg.empty() and not view.match_selector(max(reg.begin(), reg.end() - 1), selector):
            return False
    return True


def _extract_local_window(
    view: sublime.View, min_row: int, max_row: int, margin: int = 120
) -> tuple[int, int, list[str]]:
    """Extract a local line window `[win_start_row .. win_end_row]` around target rows.

    Expands beyond `margin` if needed until two consecutive blank lines (outside fences)
    or buffer boundaries are reached, keeping list operations O(list_size) even on huge files.
    """
    total_rows = view.rowcol(view.size())[0] + 1
    win_start = max(0, min_row - margin)
    win_end = min(total_rows - 1, max_row + margin)

    # Expand upwards until 2 consecutive blank lines or start of buffer
    blanks = 0
    while win_start > 0:
        pt = view.text_point(win_start, 0)
        text = view.substr(view.line(pt))
        if text.strip() == "":
            blanks += 1
            if blanks >= 2:
                break
        else:
            blanks = 0
        win_start -= 1

    # Expand downwards until 2 consecutive blank lines or end of buffer
    blanks = 0
    while win_end < total_rows - 1:
        pt = view.text_point(win_end, 0)
        text = view.substr(view.line(pt))
        if text.strip() == "":
            blanks += 1
            if blanks >= 2:
                break
        else:
            blanks = 0
        win_end += 1

    start_pt = view.text_point(win_start, 0)
    end_pt = view.line(view.text_point(win_end, 0)).end()
    raw = view.substr(sublime.Region(start_pt, end_pt))
    return win_start, win_end, raw.split("\n")


def _apply_window_outcome(
    view: sublime.View,
    edit: sublime.Edit,
    win_start_row: int,
    old_lines: list[str],
    outcome: EditOutcome,
) -> None:
    """Patch only the minimal changed line range inside `[win_start_row ..]` and update cursors."""
    new_lines = outcome.lines
    if old_lines != new_lines:
        m, k = len(old_lines), len(new_lines)
        lo = 0
        while lo < m - 1 and lo < k - 1 and old_lines[lo] == new_lines[lo]:
            lo += 1
        hi_old, hi_new = m - 1, k - 1
        while (
            hi_old > lo
            and hi_new > lo
            and old_lines[hi_old] == new_lines[hi_new]
        ):
            hi_old -= 1
            hi_new -= 1

        rep_start = view.text_point(win_start_row + lo, 0)
        rep_end = view.line(view.text_point(win_start_row + hi_old, 0)).end()
        replacement = "\n".join(new_lines[lo : hi_new + 1])
        view.replace(edit, sublime.Region(rep_start, rep_end), replacement)

    sels = view.sel()
    sels.clear()
    if outcome.selection_spans is not None:
        for (r1, c1), (r2, c2) in outcome.selection_spans:
            p1 = view.text_point(win_start_row + r1, c1)
            p2 = view.text_point(win_start_row + r2, c2)
            sels.add(sublime.Region(p1, p2))
    else:
        for r, c in outcome.cursors:
            pt = view.text_point(win_start_row + r, c)
            sels.add(sublime.Region(pt, pt))

    if len(sels) > 0:
        view.show(sels[-1], show_surrounds=False)


class MarkdownFlowEnterCommand(sublime_plugin.TextCommand):
    """Continue, split, step-by-step outdent, or exit Markdown lists and blockquotes."""

    def run(self, edit: sublime.Edit) -> None:
        sels = self.view.sel()
        if len(sels) != 1:
            return
        reg = sels[0]
        r_begin, c_begin = self.view.rowcol(reg.begin())
        r_end, _ = self.view.rowcol(reg.end())
        if r_begin != r_end:
            return

        if not reg.empty():
            self.view.erase(edit, reg)

        win_start, _, lines = _extract_local_window(self.view, r_begin, r_begin)
        local_idx = r_begin - win_start
        indent_size = _get_indent_size(self.view)
        outcome = handle_enter(lines, local_idx, c_begin, indent_size=indent_size)
        if outcome is None:
            self.view.run_command("insert", {"characters": "\n"})
            return
        _apply_window_outcome(self.view, edit, win_start, lines, outcome)


class MarkdownFlowSoftReturnCommand(sublime_plugin.TextCommand):
    """Insert an indented continuation line inside a list item or blockquote."""

    def run(self, edit: sublime.Edit) -> None:
        sels = self.view.sel()
        if len(sels) != 1:
            return
        reg = sels[0]
        r_begin, c_begin = self.view.rowcol(reg.begin())
        r_end, _ = self.view.rowcol(reg.end())
        if r_begin != r_end:
            return

        if not reg.empty():
            self.view.erase(edit, reg)

        win_start, _, lines = _extract_local_window(self.view, r_begin, r_begin)
        local_idx = r_begin - win_start
        indent_size = _get_indent_size(self.view)
        outcome = handle_soft_return(lines, local_idx, c_begin, indent_size=indent_size)
        if outcome is None:
            self.view.run_command("insert", {"characters": "\n"})
            return
        _apply_window_outcome(self.view, edit, win_start, lines, outcome)


class MarkdownFlowIndentCommand(sublime_plugin.TextCommand):
    """Indent (`direction=1`) or outdent (`direction=-1`) Markdown list items."""

    def run(self, edit: sublime.Edit, direction: int = 1) -> None:
        sels = list(self.view.sel())
        if not sels:
            return
        min_row = self.view.rowcol(min(r.begin() for r in sels))[0]
        max_row = self.view.rowcol(max(r.end() for r in sels))[0]

        win_start, _, lines = _extract_local_window(self.view, min_row, max_row)
        local_sels: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for r in sels:
            ra, ca = self.view.rowcol(r.a)
            rb, cb = self.view.rowcol(r.b)
            local_sels.append(((ra - win_start, ca), (rb - win_start, cb)))

        indent_size = _get_indent_size(self.view)
        outcome = handle_indent(
            lines, local_sels, direction=direction, indent_size=indent_size
        )
        if outcome is None:
            return
        _apply_window_outcome(self.view, edit, win_start, lines, outcome)


class MarkdownFlowBackspaceCommand(sublime_plugin.TextCommand):
    """Remove entire Markdown list marker (`- `, `12. `, `- [ ] `) in a single Backspace."""

    def run(self, edit: sublime.Edit) -> None:
        sels = list(self.view.sel())
        if len(sels) != 1 or not sels[0].empty():
            self.view.run_command("left_delete")
            return
        row, col = self.view.rowcol(sels[0].begin())
        win_start, _, lines = _extract_local_window(self.view, row, row)
        indent_size = _get_indent_size(self.view)
        outcome = handle_backspace_at_marker(
            lines, row - win_start, col, indent_size=indent_size
        )
        if outcome is None:
            self.view.run_command("left_delete")
            return
        _apply_window_outcome(self.view, edit, win_start, lines, outcome)


class MarkdownFlowRenumberCommand(sublime_plugin.TextCommand):
    """Command Palette utility: renumber ordered lists in selection or whole document."""

    def run(self, edit: sublime.Edit) -> None:
        indent_size = _get_indent_size(self.view)
        sels = list(self.view.sel())
        has_non_empty = any(not r.empty() for r in sels)
        total_rows = self.view.rowcol(self.view.size())[0] + 1

        if has_non_empty:
            min_row = self.view.rowcol(min(r.begin() for r in sels if not r.empty()))[0]
            max_row = self.view.rowcol(max(r.end() for r in sels if not r.empty()))[0]
        else:
            min_row, max_row = 0, total_rows - 1

        start_pt = self.view.text_point(min_row, 0)
        end_pt = self.view.line(self.view.text_point(max_row, 0)).end()
        old_lines = self.view.substr(sublime.Region(start_pt, end_pt)).split("\n")
        new_lines = list(old_lines)
        renumber_range(new_lines, 0, len(new_lines) - 1, indent_size=indent_size)
        if new_lines != old_lines:
            outcome = EditOutcome(
                lines=new_lines,
                cursors=[
                    (self.view.rowcol(r.b)[0] - min_row, self.view.rowcol(r.b)[1])
                    for r in sels
                ],
            )
            _apply_window_outcome(self.view, edit, min_row, old_lines, outcome)

    def is_enabled(self) -> bool:
        return self.view.match_selector(0, "text.html.markdown")


def _run_per_line_selection_transform(
    view: sublime.View,
    edit: sublime.Edit,
    transform_fn,
) -> None:
    """Apply a single-line `(line, a, b) -> (new_line, new_a, new_b)` across multi-cursors.

    Correctly handles multiple cursors even when several selections sit on the SAME line
    (e.g. via `Ctrl+D`).
    """
    sels = list(view.sel())
    if not sels:
        return

    # Group selections by line index; skip multi-line selections cleanly
    by_row: dict[int, list[tuple[int, int, int, bool]]] = {}
    passthrough_regions: list[sublime.Region] = []
    for idx, reg in enumerate(sels):
        r_start, c_start = view.rowcol(reg.begin())
        r_end, c_end = view.rowcol(reg.end())
        if r_start != r_end:
            passthrough_regions.append(reg)
            continue
        reversed_dir = reg.a > reg.b
        by_row.setdefault(r_start, []).append((idx, c_start, c_end, reversed_dir))

    result_regions: list[sublime.Region] = list(passthrough_regions)

    # Process rows bottom-to-top so buffer point offsets on earlier rows stay valid
    for row in sorted(by_row.keys(), reverse=True):
        line_pt = view.text_point(row, 0)
        line_reg = view.line(line_pt)
        line_text = view.substr(line_reg)

        # Sort selections on this line right-to-left
        items = sorted(by_row[row], key=lambda it: (it[1], it[2]), reverse=True)
        computed_spans: list[tuple[int, int, bool]] = []  # (a, b, reversed_dir)

        for _idx, a, b, rev in items:
            old_len = len(line_text)
            res = transform_fn(line_text, a, b)
            if res is None:
                computed_spans.append((a, b, rev))
                continue
            new_line_text, new_a, new_b = res
            delta = len(new_line_text) - old_len
            line_text = new_line_text
            # Shift any already-computed spans strictly to the right on this same line
            computed_spans = [
                (sa + delta, sb + delta, srev) for sa, sb, srev in computed_spans
            ]
            computed_spans.append((new_a, new_b, rev))

        if line_text != view.substr(line_reg):
            view.replace(edit, line_reg, line_text)

        for sa, sb, rev in reversed(computed_spans):
            pa = line_pt + sa
            pb = line_pt + sb
            result_regions.append(sublime.Region(pb, pa) if rev else sublime.Region(pa, pb))

    view.sel().clear()
    for reg in result_regions:
        view.sel().add(reg)


class MarkdownFlowToggleInlineCommand(sublime_plugin.TextCommand):
    """Toggle `**`, `*`, `` ` ``, or `~~` inline Markdown spans."""

    def run(self, edit: sublime.Edit, marker: str = "**") -> None:
        _run_per_line_selection_transform(
            self.view,
            edit,
            lambda line, a, b: toggle_inline_span(line, a, b, marker),
        )


class MarkdownFlowInsertLinkCommand(sublime_plugin.TextCommand):
    """Insert `[text](url)` or step through link fields."""

    def run(self, edit: sublime.Edit) -> None:
        _run_per_line_selection_transform(
            self.view,
            edit,
            apply_insert_link,
        )


class MarkdownFlowSmartPasteCommand(sublime_plugin.TextCommand):
    """Paste URL over selected text as `[selected](url)`."""

    def run(self, edit: sublime.Edit) -> None:
        clipboard = sublime.get_clipboard(CLIPBOARD_MAX_BYTES)
        _run_per_line_selection_transform(
            self.view,
            edit,
            lambda line, a, b: apply_smart_paste_url(line, a, b, clipboard),
        )


class MarkdownFlowContextListener(sublime_plugin.EventListener):
    """Evaluates fine-grained keybinding contexts so native Sublime keys stay untouched."""

    def on_query_context(
        self,
        view: sublime.View,
        key: str,
        operator: int,
        operand: object,
        match_all: bool,
    ) -> bool | None:
        if not key.startswith("md_flow."):
            return None

        result = self._evaluate(view, key)
        if operator == sublime.OP_EQUAL:
            return result == operand
        if operator == sublime.OP_NOT_EQUAL:
            return result != operand
        return None

    def _evaluate(self, view: sublime.View, key: str) -> bool:
        if not _is_enabled(view):
            return False

        sels = view.sel()
        if len(sels) == 0:
            return False

        indent_size = _get_indent_size(view)

        if key in ("md_flow.can_enter", "md_flow.can_soft_return"):
            if len(sels) != 1:
                return False
            reg = sels[0]
            if not view.match_selector(reg.begin(), PROSE_SELECTOR):
                return False
            r1, _ = view.rowcol(reg.begin())
            r2, _ = view.rowcol(reg.end())
            if r1 != r2:
                return False
            line = view.substr(view.line(reg.begin()))
            return can_handle_enter(line, indent_size=indent_size)

        if key == "md_flow.can_indent":
            if not _all_selections_match_selector(view, PROSE_SELECTOR):
                return False
            lines: list[str] = []
            indices: list[int] = []
            for reg in sels:
                r1, c1 = view.rowcol(reg.begin())
                r2, c2 = view.rowcol(reg.end())
                if r2 > r1 and c2 == 0:
                    r2 -= 1
                for r in range(r1, r2 + 1):
                    line_str = view.substr(view.line(view.text_point(r, 0)))
                    indices.append(len(lines))
                    lines.append(line_str)
            return can_indent_lines(lines, indices, indent_size=indent_size)

        if key == "md_flow.can_backspace_marker":
            if len(sels) != 1 or not sels[0].empty():
                return False
            pt = sels[0].begin()
            if not view.match_selector(pt, PROSE_SELECTOR):
                return False
            _, col = view.rowcol(pt)
            line = view.substr(view.line(pt))
            return is_at_list_marker_end(line, col, indent_size=indent_size)

        if key == "md_flow.can_smart_paste":
            if not bool(_plugin_settings().get("smart_paste_url", True)):
                return False
            if not _all_selections_match_selector(view, SMART_PASTE_SELECTOR):
                return False
            clipboard = sublime.get_clipboard(CLIPBOARD_MAX_BYTES)
            if not clipboard:
                return False
            for reg in sels:
                if reg.empty():
                    return False
                r1, c1 = view.rowcol(reg.begin())
                r2, c2 = view.rowcol(reg.end())
                if r1 != r2:
                    return False
                line = view.substr(view.line(reg.begin()))
                if not can_smart_paste_url(line, c1, c2, clipboard):
                    return False
            return True

        return False
