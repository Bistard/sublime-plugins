"""Sublime Text 4 entrypoint for MarkdownFold.

Provides:
1. Clickable inline Phantom arrows (`▾` / `▸`) to the left of Markdown headings
   for true hierarchical section folding (including nested subheadings).
2. Strict boundary guardrail protecting all folded regions in Markdown views
   against accidental edits, deletions, and unintended auto-unfolding.
3. Nested fold memory (restores folded inner subheadings on outer unfold).
4. Cross-reopen fold persistence stored inside Sublime Text's Cache directory.
5. Command Palette actions for toggling, level-folding (H1-H6), and unfolding.
"""

from __future__ import annotations

import html
import os
from typing import Any

import sublime
import sublime_plugin

from .core.guardrail_engine import (
    SAFE_COMMANDS,
    compute_safe_newline_edits,
    evaluate_command,
)
from .core.nested_memory import (
    capture_absorbed_folds,
    diff_fold_transitions,
    normalize_intervals,
    pop_restorable_children,
    select_maximal_intervals,
)
from .core.persistence import (
    DEFAULT_MAX_FILES,
    FoldPersistenceStore,
    resolve_saved_folds,
    serialize_fold_state,
)
from .core.section_engine import (
    HeadingSection,
    find_active_fold_for_section,
    find_enclosing_section,
    is_section_hidden_inside_fold,
    parse_sections,
)

SETTINGS_FILE = "MarkdownFold.sublime-settings"
MARKDOWN_SELECTOR = "text.html.markdown"

PHANTOM_SET_KEY = "markdown_fold.heading_arrows"
REGION_KEY_PREV_ACTIVE = "markdown_fold.prev_active"
REGION_KEY_REM_PREFIX = "markdown_fold.rem."
MAX_REM_DEPTH_BUCKETS = 12
REFRESH_DEBOUNCE_MS = 40
CLIPBOARD_INSPECT_LIMIT = 4096

# Per-view runtime state keyed by `view.id()`
_phantom_sets: dict[int, sublime.PhantomSet] = {}
_last_phantom_sig: dict[int, tuple[Any, ...]] = {}
_pending_refresh_seq: dict[int, int] = {}
_rem_bucket_counts: dict[int, int] = {}
_fade_managed_views: set[int] = set()
_internal_fold_views: set[int] = set()
_clearing_all_views: set[int] = set()
_restored_views: set[int] = set()

_store: FoldPersistenceStore | None = None


# ── Settings & Store Helpers ────────────────────────────────────────────────


def _settings() -> sublime.Settings:
    return sublime.load_settings(SETTINGS_FILE)


def _get_store() -> FoldPersistenceStore:
    global _store
    max_files = _settings().get("persist_max_files", DEFAULT_MAX_FILES)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = DEFAULT_MAX_FILES
    if _store is None:
        cache_dir = os.path.join(sublime.cache_path(), "MarkdownFold")
        _store = FoldPersistenceStore(
            os.path.join(cache_dir, "folds_v1.json"),
            max_files=max_files,
        )
    else:
        _store.max_files = max_files
    return _store


def _is_enabled(view: sublime.View) -> bool:
    view_flag = view.settings().get("markdown_fold_enabled")
    if view_flag is not None:
        return bool(view_flag)
    return bool(_settings().get("enabled", True))


def _is_markdown_view(view: sublime.View) -> bool:
    if not view or not view.is_valid():
        return False
    if view.element() is not None:
        return False
    if view.size() == 0:
        syn = view.syntax()
        return bool(syn and syn.scope.startswith(MARKDOWN_SELECTOR))
    return bool(view.match_selector(0, MARKDOWN_SELECTOR))


def _is_active_view(view: sublime.View) -> bool:
    return _is_markdown_view(view) and _is_enabled(view)


def _keep_trailing_blanks() -> bool:
    return bool(_settings().get("keep_trailing_blank_lines", True))


def _guard_enabled() -> bool:
    return bool(_settings().get("guard_folded_regions", True))


def _nested_memory_enabled() -> bool:
    return bool(_settings().get("remember_nested_folds", True))


def _persistence_enabled() -> bool:
    return bool(_settings().get("persist_folds", True))


def _show_arrows_enabled() -> bool:
    return bool(_settings().get("show_heading_arrows", True))


def _max_arrow_file_size() -> int:
    val = _settings().get("max_arrow_file_size", 500000)
    return val if isinstance(val, int) and val > 0 else 500000


def _arrow_glyphs() -> tuple[str, str]:
    exp = _settings().get("arrow_expanded", "▾")
    col = _settings().get("arrow_collapsed", "▸")
    return (
        exp if isinstance(exp, str) and exp else "▾",
        col if isinstance(col, str) and col else "▸",
    )


def _status_hint(view: sublime.View, message: str) -> None:
    win = view.window()
    full = f"MarkdownFold: {message}"
    if win is not None:
        win.status_message(full)
    else:
        sublime.status_message(full)


# ── Buffer & Region Helpers ─────────────────────────────────────────────────


def _full_text(view: sublime.View) -> str:
    return view.substr(sublime.Region(0, view.size()))


def _active_fold_intervals(view: sublime.View) -> list[tuple[int, int]]:
    return normalize_intervals([(r.a, r.b) for r in view.folded_regions() if r.a < r.b])


def _get_prev_active(view: sublime.View) -> list[tuple[int, int]]:
    return normalize_intervals(
        [(r.a, r.b) for r in view.get_regions(REGION_KEY_PREV_ACTIVE) if r.a < r.b]
    )


def _set_prev_active(view: sublime.View, intervals: list[tuple[int, int]]) -> None:
    norm = normalize_intervals(intervals)
    if norm:
        view.add_regions(
            REGION_KEY_PREV_ACTIVE,
            [sublime.Region(a, b) for a, b in norm],
            flags=sublime.HIDDEN,
        )
    else:
        view.erase_regions(REGION_KEY_PREV_ACTIVE)


def _get_remembered(view: sublime.View) -> list[tuple[int, int]]:
    vid = view.id()
    buckets = _rem_bucket_counts.get(vid, MAX_REM_DEPTH_BUCKETS)
    collected: list[tuple[int, int]] = []
    for depth in range(buckets):
        for r in view.get_regions(f"{REGION_KEY_REM_PREFIX}{depth}"):
            if r.a < r.b:
                collected.append((r.a, r.b))
    return normalize_intervals(collected)


def _set_remembered(view: sublime.View, intervals: list[tuple[int, int]]) -> None:
    """Store potentially nested intervals in depth-bucketed `HIDDEN` regions.

    Each depth bucket holds pairwise non-overlapping intervals so Sublime Text
    never merges nested intervals together, while still auto-shifting every
    interval across edits elsewhere in the buffer.
    """
    vid = view.id()
    remaining = normalize_intervals(intervals)
    depth = 0
    while remaining and depth < MAX_REM_DEPTH_BUCKETS:
        layer = select_maximal_intervals(remaining)
        layer_set = set(layer)
        view.add_regions(
            f"{REGION_KEY_REM_PREFIX}{depth}",
            [sublime.Region(a, b) for a, b in layer],
            flags=sublime.HIDDEN,
        )
        remaining = [r for r in remaining if r not in layer_set]
        depth += 1

    prev_buckets = _rem_bucket_counts.get(vid, MAX_REM_DEPTH_BUCKETS)
    for stale in range(depth, prev_buckets):
        view.erase_regions(f"{REGION_KEY_REM_PREFIX}{stale}")
    _rem_bucket_counts[vid] = depth


def _clear_remembered(view: sublime.View) -> None:
    _set_remembered(view, [])


def _apply_gutter_fade_setting(view: sublime.View) -> None:
    vid = view.id()
    want_always = _is_active_view(view) and bool(
        _settings().get("always_show_gutter_fold_buttons", True)
    )
    if want_always:
        if view.settings().get("fade_fold_buttons") is not False:
            view.settings().set("fade_fold_buttons", False)
            _fade_managed_views.add(vid)
    elif vid in _fade_managed_views:
        view.settings().erase("fade_fold_buttons")
        _fade_managed_views.discard(vid)


# ── Core Fold / Unfold Operations (with Nested Memory) ──────────────────────


def _evict_trapped_selections(view: sublime.View, fold_a: int, fold_b: int) -> None:
    """Move any selection trapped inside `[fold_a, fold_b]` out to the heading line."""
    changed = False
    new_sels: list[sublime.Region] = []
    heading_start = view.line(fold_a).begin()
    for sel in view.sel():
        s0, s1 = min(sel.a, sel.b), max(sel.a, sel.b)
        if s0 == s1 and fold_a < s0 < fold_b:
            new_sels.append(sublime.Region(heading_start, heading_start))
            changed = True
        elif s0 < fold_b and s1 > fold_a:
            new_sels.append(sublime.Region(heading_start, heading_start))
            changed = True
        else:
            new_sels.append(sel)
    if changed:
        view.sel().clear()
        for r in new_sels:
            view.sel().add(r)


def _fold_interval(view: sublime.View, interval: tuple[int, int]) -> bool:
    """Fold `(a, b)` cleanly, capturing any absorbed inner folds into nested memory."""
    a, b = min(interval[0], interval[1]), max(interval[0], interval[1])
    if b <= a or b > view.size():
        return False

    vid = view.id()
    prev_active = _active_fold_intervals(view)
    if _nested_memory_enabled():
        remembered = _get_remembered(view)
        updated_rem = capture_absorbed_folds((a, b), prev_active, remembered)
        _set_remembered(view, updated_rem)

    _internal_fold_views.add(vid)
    try:
        _evict_trapped_selections(view, a, b)
        folded = bool(view.fold(sublime.Region(a, b)))
        _set_prev_active(view, _active_fold_intervals(view))
    finally:
        _internal_fold_views.discard(vid)

    _refresh_phantoms_now(view)
    return folded


def _unfold_interval(view: sublime.View, interval: tuple[int, int]) -> bool:
    """Unfold `(a, b)` and restore maximal remembered inner folds (if enabled)."""
    a, b = min(interval[0], interval[1]), max(interval[0], interval[1])
    if b <= a:
        return False

    vid = view.id()
    _internal_fold_views.add(vid)
    try:
        unfolded_regions = view.unfold(sublime.Region(a, b))
        if not unfolded_regions:
            return False

        if _nested_memory_enabled():
            remembered = _get_remembered(view)
            curr_active = _active_fold_intervals(view)
            to_refold, remaining = pop_restorable_children((a, b), remembered, curr_active)
            _set_remembered(view, remaining)
            if to_refold:
                view.fold([sublime.Region(ra, rb) for ra, rb in to_refold])

        _set_prev_active(view, _active_fold_intervals(view))
    finally:
        _internal_fold_views.discard(vid)

    _refresh_phantoms_now(view)
    return True


def _unfold_all(view: sublime.View) -> None:
    vid = view.id()
    _internal_fold_views.add(vid)
    try:
        _clear_remembered(view)
        view.unfold(sublime.Region(0, view.size()))
        _set_prev_active(view, [])
    finally:
        _internal_fold_views.discard(vid)
    _refresh_phantoms_now(view)


def _sync_external_fold_changes(view: sublime.View) -> None:
    """Synchronize nested memory when folds change outside our commands (e.g. clicking `[...]`)."""
    vid = view.id()
    if vid in _internal_fold_views or not _is_active_view(view):
        return

    curr_active = _active_fold_intervals(view)

    if vid in _clearing_all_views:
        _clearing_all_views.discard(vid)
        _clear_remembered(view)
        _set_prev_active(view, curr_active)
        return

    prev_active = _get_prev_active(view)
    if not _nested_memory_enabled():
        _set_prev_active(view, curr_active)
        return

    newly_folded, absorbed_prev, newly_unfolded = diff_fold_transitions(
        prev_active, curr_active
    )

    remembered = _get_remembered(view)
    rem_changed = False

    # Record inner folds absorbed by an external fold (e.g. Ctrl+Shift+[)
    if newly_folded and absorbed_prev:
        for outer in newly_folded:
            remembered = capture_absorbed_folds(outer, absorbed_prev, remembered)
        rem_changed = True

    # Restore maximal remembered children when an outer fold was unfolded externally
    if newly_unfolded and remembered:
        to_refold_all: list[tuple[int, int]] = []
        active_now = list(curr_active)
        for uf in newly_unfolded:
            to_refold, remembered = pop_restorable_children(uf, remembered, active_now)
            if to_refold:
                to_refold_all.extend(to_refold)
                active_now.extend(to_refold)
                rem_changed = True

        if to_refold_all:
            _internal_fold_views.add(vid)
            try:
                view.fold([sublime.Region(a, b) for a, b in to_refold_all])
            finally:
                _internal_fold_views.discard(vid)
            curr_active = _active_fold_intervals(view)

    if rem_changed:
        _set_remembered(view, remembered)
    _set_prev_active(view, curr_active)


# ── Inline Heading Arrow Phantoms ───────────────────────────────────────────


def _build_arrow_html(
    row: int,
    *,
    collapsed: bool,
    hidden_lines: int,
    glyph_expanded: str,
    glyph_collapsed: str,
) -> str:
    glyph = html.escape(glyph_collapsed if collapsed else glyph_expanded)
    cls = "collapsed" if collapsed else "expanded"
    if collapsed:
        tooltip = f"Unfold section ({hidden_lines} lines)" if hidden_lines else "Unfold section"
    else:
        tooltip = f"Fold section ({hidden_lines} lines)" if hidden_lines else "Fold section"
    return (
        '<body id="markdown-fold-arrow">'
        "<style>"
        "html, body { margin: 0; padding: 0; background-color: transparent; }"
        "a { text-decoration: none; padding-right: 4px; }"
        "a.expanded { color: color(var(--foreground) alpha(0.45)); }"
        "a.collapsed { color: var(--accent); }"
        "</style>"
        f'<a class="{cls}" href="toggle:{row}" title="{html.escape(tooltip)}">{glyph}</a>'
        "</body>"
    )


def _clear_phantoms(view: sublime.View) -> None:
    vid = view.id()
    pset = _phantom_sets.pop(vid, None)
    if pset is not None:
        pset.update([])
    _last_phantom_sig.pop(vid, None)


def _on_arrow_click(view: sublime.View, href: str) -> None:
    if not view.is_valid() or not _is_active_view(view):
        return
    if not href.startswith("toggle:"):
        return
    try:
        row = int(href.split(":", 1)[1])
    except ValueError:
        return
    _toggle_heading_at_row(view, row)


def _toggle_heading_at_row(view: sublime.View, row: int) -> None:
    text = _full_text(view)
    sections = parse_sections(text, keep_trailing_blank_lines=_keep_trailing_blanks())
    target: HeadingSection | None = None
    for sec in sections:
        if sec.row == row:
            target = sec
            break
    if target is None:
        return

    active_folds = _active_fold_intervals(view)
    existing = find_active_fold_for_section(target, active_folds)
    if existing is not None:
        _unfold_interval(view, existing)
    elif target.fold_range is not None:
        _fold_interval(view, target.fold_range)


def _refresh_phantoms_now(view: sublime.View) -> None:
    if not view or not view.is_valid():
        return
    if not _is_active_view(view) or not _show_arrows_enabled():
        _clear_phantoms(view)
        return
    if view.size() > _max_arrow_file_size():
        _clear_phantoms(view)
        return

    text = _full_text(view)
    sections = parse_sections(text, keep_trailing_blank_lines=_keep_trailing_blanks())
    active_folds = _active_fold_intervals(view)
    glyph_exp, glyph_col = _arrow_glyphs()

    entries: list[tuple[int, int, bool, int]] = []
    # (line_start, row, collapsed, hidden_lines)
    for sec in sections:
        if is_section_hidden_inside_fold(sec, active_folds):
            continue
        existing = find_active_fold_for_section(sec, active_folds)
        if existing is not None:
            # Count lines inside the active fold itself
            fold_lines = text.count("\n", existing[0], existing[1])
            entries.append((sec.line_start, sec.row, True, fold_lines))
        elif sec.foldable:
            entries.append((sec.line_start, sec.row, False, sec.hidden_line_count))

    sig = (glyph_exp, glyph_col, tuple(entries))
    vid = view.id()
    if _last_phantom_sig.get(vid) == sig:
        return

    _last_phantom_sig[vid] = sig
    pset = _phantom_sets.get(vid)
    if pset is None:
        pset = sublime.PhantomSet(view, PHANTOM_SET_KEY)
        _phantom_sets[vid] = pset

    phantoms = [
        sublime.Phantom(
            sublime.Region(line_start, line_start),
            _build_arrow_html(
                row,
                collapsed=collapsed,
                hidden_lines=hidden_lines,
                glyph_expanded=glyph_exp,
                glyph_collapsed=glyph_col,
            ),
            sublime.LAYOUT_INLINE,
            lambda href, v=view: _on_arrow_click(v, href),
        )
        for line_start, row, collapsed, hidden_lines in entries
    ]
    pset.update(phantoms)


def _schedule_refresh(view: sublime.View, *, delay_ms: int = REFRESH_DEBOUNCE_MS) -> None:
    if not view or not view.is_valid():
        return
    vid = view.id()
    seq = _pending_refresh_seq.get(vid, 0) + 1
    _pending_refresh_seq[vid] = seq

    def _run() -> None:
        if _pending_refresh_seq.get(vid) != seq:
            return
        if not view.is_valid():
            return
        _apply_gutter_fade_setting(view)
        _sync_external_fold_changes(view)
        _refresh_phantoms_now(view)

    sublime.set_timeout(_run, delay_ms)


# ── Persistence Helpers ─────────────────────────────────────────────────────


def _save_view_folds(view: sublime.View) -> None:
    if not _persistence_enabled() or not _is_active_view(view):
        return
    path = view.file_name()
    if not path:
        return
    active = _active_fold_intervals(view)
    remembered = _get_remembered(view) if _nested_memory_enabled() else []
    entry = serialize_fold_state(
        _full_text(view),
        active,
        remembered,
        keep_trailing_blank_lines=_keep_trailing_blanks(),
    )
    _get_store().set(path, entry)


def _restore_view_folds(view: sublime.View) -> None:
    if not _persistence_enabled() or not _is_active_view(view):
        return
    vid = view.id()
    if vid in _restored_views:
        return
    _restored_views.add(vid)

    path = view.file_name()
    if not path:
        return

    entry = _get_store().get(path)
    existing_active = _active_fold_intervals(view)
    if not entry:
        if existing_active:
            _set_prev_active(view, existing_active)
        return

    active, remembered = resolve_saved_folds(
        entry,
        _full_text(view),
        keep_trailing_blank_lines=_keep_trailing_blanks(),
    )

    # Respect Sublime Text's native hot_exit/session active folds if already present,
    # while still rehydrating remembered nested folds inside those active folds!
    if existing_active:
        if _nested_memory_enabled() and remembered:
            valid_rem = [
                r
                for r in remembered
                if any(a <= r[0] and r[1] <= b and r != (a, b) for a, b in existing_active)
            ]
            if valid_rem:
                _set_remembered(view, valid_rem)
        _set_prev_active(view, existing_active)
        _refresh_phantoms_now(view)
        return

    if not active and not remembered:
        return

    _internal_fold_views.add(vid)
    try:
        if _nested_memory_enabled() and remembered:
            _set_remembered(view, remembered)
        if active:
            outermost = select_maximal_intervals(active)
            # Any non-outermost saved active fold goes into nested memory
            outer_set = set(outermost)
            extra_rem = [r for r in active if r not in outer_set]
            if _nested_memory_enabled() and extra_rem:
                _set_remembered(view, normalize_intervals(remembered + extra_rem))
            view.fold([sublime.Region(a, b) for a, b in outermost])
        _set_prev_active(view, _active_fold_intervals(view))
    finally:
        _internal_fold_views.discard(vid)

    _refresh_phantoms_now(view)


# ── Event Listener ──────────────────────────────────────────────────────────


class MarkdownFoldEventListener(sublime_plugin.EventListener):
    def on_text_command(
        self,
        view: sublime.View,
        command_name: str,
        args: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any] | None] | None:
        if not _is_active_view(view):
            return None

        if command_name == "unfold_all":
            _clearing_all_views.add(view.id())
            return None

        if command_name in SAFE_COMMANDS or not _guard_enabled():
            return None

        folds = _active_fold_intervals(view)
        if not folds:
            return None

        sels = [(s.a, s.b) for s in view.sel()]
        if not sels:
            return None

        clipboard_text: str | None = None
        if command_name in ("paste", "paste_and_indent"):
            clipboard_text = sublime.get_clipboard(CLIPBOARD_INSPECT_LIMIT)

        decision = evaluate_command(
            command_name,
            args,
            _full_text(view),
            sels,
            folds,
            clipboard_text=clipboard_text,
        )

        if decision.action == "block":
            _status_hint(view, decision.reason or "Folded section is protected — unfold first")
            return ("markdown_fold_noop", None)

        if decision.action == "safe_newline":
            return (
                "markdown_fold_safe_newline",
                {"points": list(decision.safe_newline_points)},
            )

        return None

    def on_post_text_command(
        self,
        view: sublime.View,
        command_name: str,
        args: dict[str, Any] | None,
    ) -> None:
        if not _is_active_view(view):
            return
        if command_name in (
            "fold",
            "unfold",
            "fold_by_level",
            "unfold_all",
            "fold_unfold",
            "undo",
            "redo",
        ):
            _schedule_refresh(view, delay_ms=10)

    def on_modified_async(self, view: sublime.View) -> None:
        if _is_markdown_view(view):
            _schedule_refresh(view)

    def on_selection_modified_async(self, view: sublime.View) -> None:
        if _is_active_view(view):
            _schedule_refresh(view, delay_ms=25)

    def on_activated_async(self, view: sublime.View) -> None:
        if _is_markdown_view(view):
            _schedule_refresh(view, delay_ms=20)
        elif view.id() in _phantom_sets or view.id() in _fade_managed_views:
            _clear_phantoms(view)
            _apply_gutter_fade_setting(view)

    def on_load(self, view: sublime.View) -> None:
        if not _is_active_view(view):
            return
        _apply_gutter_fade_setting(view)
        # Run slightly deferred so Sublime finishes initializing syntax & hot_exit state
        sublime.set_timeout(lambda: self._on_load_ready(view), 30)

    def _on_load_ready(self, view: sublime.View) -> None:
        if not view.is_valid() or not _is_active_view(view):
            return
        _restore_view_folds(view)
        _refresh_phantoms_now(view)

    def on_post_save_async(self, view: sublime.View) -> None:
        if _is_active_view(view):
            _save_view_folds(view)

    def on_pre_close(self, view: sublime.View) -> None:
        if _is_active_view(view):
            _save_view_folds(view)

    def on_close(self, view: sublime.View) -> None:
        vid = view.id()
        _phantom_sets.pop(vid, None)
        _last_phantom_sig.pop(vid, None)
        _pending_refresh_seq.pop(vid, None)
        _rem_bucket_counts.pop(vid, None)
        _fade_managed_views.discard(vid)
        _internal_fold_views.discard(vid)
        _clearing_all_views.discard(vid)
        _restored_views.discard(vid)


# ── Text Commands ───────────────────────────────────────────────────────────


class MarkdownFoldNoopCommand(sublime_plugin.TextCommand):
    """Sentinel command used by the guardrail to cleanly cancel a blocked edit."""

    def run(self, edit: sublime.Edit) -> None:
        pass


class MarkdownFoldSafeNewlineCommand(sublime_plugin.TextCommand):
    """Insert a new line safely below a folded block without unfolding it."""

    def run(self, edit: sublime.Edit, points: list[int] | None = None) -> None:
        view = self.view
        folds = _active_fold_intervals(view)
        pts = tuple(points) if points is not None else tuple(s.end() for s in view.sel())
        if not pts:
            return

        text = _full_text(view)
        edits, carets = compute_safe_newline_edits(text, pts, folds)
        if not edits:
            return

        # Snapshot folds that must stay collapsed (guards EOF fold where b == len(text))
        eof_folds = [(a, b) for a, b in folds if b == len(text)]

        vid = view.id()
        _internal_fold_views.add(vid)
        try:
            for pos, ch in reversed(edits):
                view.insert(edit, pos, ch)

            for a, b in eof_folds:
                reg = sublime.Region(a, b)
                if not view.is_folded(reg):
                    view.fold(reg)

            view.sel().clear()
            for c in carets:
                view.sel().add(sublime.Region(c, c))
            if carets:
                view.show(carets[-1])

            _set_prev_active(view, _active_fold_intervals(view))
        finally:
            _internal_fold_views.discard(vid)

        _refresh_phantoms_now(view)


class MarkdownFoldToggleSectionCommand(sublime_plugin.TextCommand):
    """Toggle folding for the Markdown heading section enclosing each cursor."""

    def is_enabled(self) -> bool:
        return _is_active_view(self.view)

    def run(self, edit: sublime.Edit) -> None:
        view = self.view
        text = _full_text(view)
        sections = parse_sections(text, keep_trailing_blank_lines=_keep_trailing_blanks())
        if not sections:
            return

        seen_rows: set[int] = set()
        for sel in list(view.sel()):
            row = view.rowcol(sel.begin())[0]
            sec = find_enclosing_section(sections, row)
            if sec is None or sec.row in seen_rows:
                continue
            seen_rows.add(sec.row)
            active = _active_fold_intervals(view)
            existing = find_active_fold_for_section(sec, active)
            if existing is not None:
                _unfold_interval(view, existing)
            elif sec.fold_range is not None:
                _fold_interval(view, sec.fold_range)


class MarkdownFoldFoldLevelCommand(sublime_plugin.TextCommand):
    """Fold all Markdown headings at the specified heading level (1-6)."""

    def is_enabled(self) -> bool:
        return _is_active_view(self.view)

    def run(self, edit: sublime.Edit, level: int = 1) -> None:
        if not isinstance(level, int) or not (1 <= level <= 6):
            return
        view = self.view
        text = _full_text(view)
        sections = parse_sections(text, keep_trailing_blank_lines=_keep_trailing_blanks())
        targets = [
            sec.fold_range
            for sec in sections
            if sec.level == level and sec.fold_range is not None
        ]

        vid = view.id()
        _internal_fold_views.add(vid)
        try:
            _clear_remembered(view)
            view.unfold(sublime.Region(0, view.size()))
            if targets:
                outermost = select_maximal_intervals(targets)
                for a, b in outermost:
                    _evict_trapped_selections(view, a, b)
                view.fold([sublime.Region(a, b) for a, b in outermost])
            _set_prev_active(view, _active_fold_intervals(view))
        finally:
            _internal_fold_views.discard(vid)

        _refresh_phantoms_now(view)


class MarkdownFoldFoldAllCommand(sublime_plugin.TextCommand):
    """Fold all top-level Markdown heading sections."""

    def is_enabled(self) -> bool:
        return _is_active_view(self.view)

    def run(self, edit: sublime.Edit) -> None:
        view = self.view
        text = _full_text(view)
        sections = parse_sections(text, keep_trailing_blank_lines=_keep_trailing_blanks())
        all_ranges = [sec.fold_range for sec in sections if sec.fold_range is not None]
        if not all_ranges:
            return

        outermost = select_maximal_intervals(all_ranges)
        vid = view.id()
        prev_active = _active_fold_intervals(view)
        if _nested_memory_enabled():
            rem = _get_remembered(view)
            for outer in outermost:
                rem = capture_absorbed_folds(outer, prev_active, rem)
            _set_remembered(view, rem)

        _internal_fold_views.add(vid)
        try:
            for a, b in outermost:
                _evict_trapped_selections(view, a, b)
            view.fold([sublime.Region(a, b) for a, b in outermost])
            _set_prev_active(view, _active_fold_intervals(view))
        finally:
            _internal_fold_views.discard(vid)

        _refresh_phantoms_now(view)


class MarkdownFoldUnfoldAllCommand(sublime_plugin.TextCommand):
    """Unfold everything in the view and clear nested fold memory."""

    def is_enabled(self) -> bool:
        return _is_active_view(self.view)

    def run(self, edit: sublime.Edit) -> None:
        _unfold_all(self.view)


# ── Plugin Lifecycle ────────────────────────────────────────────────────────


def _on_settings_changed() -> None:
    for win in sublime.windows():
        for view in win.views():
            if _is_markdown_view(view):
                _apply_gutter_fade_setting(view)
                _last_phantom_sig.pop(view.id(), None)
                _refresh_phantoms_now(view)


def plugin_loaded() -> None:
    _settings().add_on_change("markdown_fold_reload", _on_settings_changed)
    for win in sublime.windows():
        for view in win.views():
            if _is_active_view(view):
                _apply_gutter_fade_setting(view)
                _set_prev_active(view, _active_fold_intervals(view))
                _refresh_phantoms_now(view)


def plugin_unloaded() -> None:
    _settings().clear_on_change("markdown_fold_reload")
    for win in sublime.windows():
        for view in win.views():
            vid = view.id()
            if vid in _fade_managed_views:
                view.settings().erase("fade_fold_buttons")
            _clear_phantoms(view)
            view.erase_regions(REGION_KEY_PREV_ACTIVE)
            for depth in range(MAX_REM_DEPTH_BUCKETS):
                view.erase_regions(f"{REGION_KEY_REM_PREFIX}{depth}")
    _phantom_sets.clear()
    _last_phantom_sig.clear()
    _pending_refresh_seq.clear()
    _rem_bucket_counts.clear()
    _fade_managed_views.clear()
    _internal_fold_views.clear()
    _clearing_all_views.clear()
    _restored_views.clear()
