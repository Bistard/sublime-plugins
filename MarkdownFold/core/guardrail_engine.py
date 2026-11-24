"""Strict boundary guardrail engine for editing around folded regions (pure Python).

Ensures that editing, inserting newlines, or deleting text between folded
regions never accidentally deletes hidden content or auto-unfolds adjacent
collapsed blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GuardDecision:
    """Result of evaluating a text command against active folded regions."""

    action: str  # "allow" | "block" | "safe_newline"
    reason: str = ""
    safe_newline_points: tuple[int, ...] = ()


# Read-only / navigation / fold management commands that never mutate buffer text
SAFE_COMMANDS: frozenset[str] = frozenset(
    {
        "copy",
        "move",
        "move_to",
        "expand_selection",
        "select_all",
        "select_lines",
        "single_selection",
        "split_selection_into_lines",
        "find_under_expand",
        "find_all_under",
        "scroll_lines",
        "show_at_center",
        "fold",
        "unfold",
        "fold_by_level",
        "unfold_all",
        "fold_unfold",
        "undo",
        "redo",
        "soft_undo",
        "soft_redo",
        "set_mark",
        "select_to_mark",
        "swap_with_mark",
        "clear_bookmarks",
        "toggle_bookmark",
        "next_bookmark",
        "prev_bookmark",
        "add_to_kill_ring",
        "context_menu",
        "drag_select",
        "auto_complete",
        "hide_auto_complete",
        "commit_completion",
        "markdown_fold_toggle_section",
        "markdown_fold_fold_level",
        "markdown_fold_fold_all",
        "markdown_fold_unfold_all",
        "markdown_fold_safe_newline",
        "markdown_fold_noop",
    }
)


def _line_start(text: str, pt: int) -> int:
    if pt <= 0:
        return 0
    idx = text.rfind("\n", 0, pt)
    return 0 if idx == -1 else idx + 1


def _line_end(text: str, pt: int) -> int:
    n = len(text)
    if pt >= n:
        return n
    idx = text.find("\n", pt)
    return n if idx == -1 else idx


def _normalize_folds(folds: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return sorted((min(a, b), max(a, b)) for a, b in folds if a != b)


def _selection_crosses_fold(
    text: str,
    s0: int,
    s1: int,
    folds: list[tuple[int, int]],
) -> bool:
    """Return True if a non-empty selection `[s0, s1]` intersects or breaches a fold."""
    for a, b in folds:
        # 1. Strictly overlaps the hidden folded region [a, b)
        if s0 < b and s1 > a:
            return True
        # 2. Spans across b (e.g. deletes the trailing newline right after [...])
        if s0 <= b < s1:
            return True
        # 3. Merges a folded heading line onto a non-empty preceding line
        f_line_start = _line_start(text, a)
        if f_line_start > 0:
            prev_nl = f_line_start - 1
            if s0 <= prev_nl < s1 and s0 > _line_start(text, s0):
                return True
        # 4. Selection starts inside visible heading text and spans past `a` (covered by #1)
    return False


def _point_inside_fold(pt: int, folds: list[tuple[int, int]]) -> bool:
    for a, b in folds:
        if a < pt < b:
            return True
    return False


def _fold_ending_at(pt: int, folds: list[tuple[int, int]]) -> tuple[int, int] | None:
    for a, b in folds:
        if pt == b:
            return (a, b)
    return None


def _fold_starting_at(pt: int, folds: list[tuple[int, int]]) -> tuple[int, int] | None:
    for a, b in folds:
        if pt == a:
            return (a, b)
    return None


def _fold_on_visible_line(text: str, pt: int, folds: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Return fold `(a, b)` if `pt` lies on the visible line hosting the fold (`[line_start(a) .. b]`)."""
    for a, b in folds:
        if _line_start(text, a) <= pt <= b:
            return (a, b)
    return None


def _macro_name(args: dict[str, Any] | None) -> str:
    if not args:
        return ""
    raw = str(args.get("file", ""))
    return raw.rsplit("/", 1)[-1].lower()


def _is_newline_insert(command: str, args: dict[str, Any] | None) -> bool:
    if command in ("markdown_flow_enter", "markdown_flow_soft_return"):
        return True
    if command == "insert" and args:
        chars = args.get("characters")
        return chars == "\n"
    return False


def _inserted_text(command: str, args: dict[str, Any] | None) -> str | None:
    if command == "insert" and args and isinstance(args.get("characters"), str):
        return args["characters"]
    if command == "insert_snippet" and args:
        contents = args.get("contents")
        if isinstance(contents, str):
            return contents
        return "\n"  # Conservative for external snippet files
    return None


def _eval_enter_at_caret(
    text: str,
    pt: int,
    folds: list[tuple[int, int]],
) -> str:
    """Evaluate pressing Enter at empty caret `pt`.

    Returns: "allow", "block", or "safe_newline".
    """
    if _point_inside_fold(pt, folds):
        return "block"

    if _fold_ending_at(pt, folds) is not None:
        # Caret is at `# Title [...]|` -> insert new line safely BELOW the fold
        return "safe_newline"

    # Check if caret is on the visible heading text of a folded block
    for a, _b in folds:
        f_line_start = _line_start(text, a)
        if f_line_start < pt <= a:
            # Inside or right at end of visible heading text: splitting would break the folded heading
            return "block"
        # Note: pt == f_line_start (col 0 before `# Title [...]`) cleanly inserts a blank line ABOVE!

    return "allow"


def _eval_left_delete_at_caret(
    text: str,
    pt: int,
    folds: list[tuple[int, int]],
    *,
    word_mode: bool = False,
) -> bool:
    """Return True if backward delete at `pt` should be BLOCKED."""
    if pt <= 0:
        return False
    if _point_inside_fold(pt, folds):
        return True
    if _fold_ending_at(pt, folds) is not None:
        # At `# Title [...]|` -> would delete into hidden body
        return True

    for a, b in folds:
        # Caret at col 0 of the line immediately following `# Title [...]`
        if pt == b + 1 and b < len(text) and text[b] == "\n":
            return True
        if word_mode and b < len(text) and text[b] == "\n" and pt > b + 1:
            # Ctrl+Backspace on whitespace-only prefix of the line right below fold can jump across \n
            if _line_start(text, pt) == b + 1 and text[b + 1 : pt].strip() == "":
                return True

        # Caret at col 0 of a folded heading line `# Section 2 [...]`
        f_line_start = _line_start(text, a)
        if pt == f_line_start and f_line_start > 0:
            prev_line_start = _line_start(text, f_line_start - 1)
            # Only allow if the preceding line is completely empty (deletes a blank line safely)
            if prev_line_start < f_line_start - 1:
                return True
        if word_mode and f_line_start > 0 and f_line_start < pt <= a:
            # Ctrl+Backspace on leading whitespace of a folded heading line could cross into previous line
            if text[f_line_start:pt].strip() == "":
                prev_line_start = _line_start(text, f_line_start - 1)
                if prev_line_start < f_line_start - 1:
                    return True

    return False


def _eval_right_delete_at_caret(
    text: str,
    pt: int,
    folds: list[tuple[int, int]],
    *,
    word_mode: bool = False,
) -> bool:
    """Return True if forward delete at `pt` should be BLOCKED."""
    n = len(text)
    if pt >= n:
        return False
    if _point_inside_fold(pt, folds):
        return True
    if _fold_starting_at(pt, folds) is not None:
        # At `# Title|[...]` -> ST4 right_delete destroys the entire hidden section!
        return True
    if _fold_ending_at(pt, folds) is not None:
        # At `# Title [...]|` -> would delete trailing \n and pull next line into fold boundary
        return True

    for a, _b in folds:
        f_line_start = _line_start(text, a)
        # Word-delete on whitespace right before `a` can jump across `a` into fold
        if word_mode and f_line_start <= pt < a and text[pt:a].strip() == "":
            return True

        # Caret at EOL of the line immediately above a folded heading `# Section 2 [...]`
        if f_line_start > 0 and pt == f_line_start - 1:
            cur_line_start = _line_start(text, pt)
            # Allow deleting an empty blank line above `# Section 2 [...]`, block if current line has text
            if pt > cur_line_start:
                return True
        if word_mode and f_line_start > 0 and pt < f_line_start - 1:
            if _line_end(text, pt) == f_line_start - 1 and text[pt : f_line_start - 1].strip() == "":
                cur_line_start = _line_start(text, pt)
                if cur_line_start < f_line_start - 1:
                    return True

    return False


def evaluate_command(
    command: str,
    args: dict[str, Any] | None,
    text: str,
    selections: list[tuple[int, int]],
    folds: list[tuple[int, int]],
    *,
    clipboard_text: str | None = None,
) -> GuardDecision:
    """Decide whether a Sublime Text command is allowed, blocked, or redirected.

    Parameters
    ----------
    command:
        Sublime Text command name from `on_text_command`.
    args:
        Command arguments dict (or None).
    text:
        Full buffer contents (normalized with `\\n`).
    selections:
        Current view selections as `(a, b)` pairs (unordered endpoints supported).
    folds:
        Active folded regions as `(a, b)` pairs.
    clipboard_text:
        Optional clipboard contents used when evaluating `paste` on a folded heading line.
    """
    norm_folds = _normalize_folds(folds)
    if not norm_folds or not selections:
        return GuardDecision("allow")

    if command in SAFE_COMMANDS:
        return GuardDecision("allow")

    norm_sels = [(min(a, b), max(a, b)) for a, b in selections]

    # ── 1. Non-empty selections: block ANY mutating command that touches a fold ──
    for s0, s1 in norm_sels:
        if s0 < s1 and _selection_crosses_fold(text, s0, s1, norm_folds):
            return GuardDecision("block", "Folded section is protected — unfold first")

    # ── 2. Built-in macros (`Ctrl+Shift+K`, `Ctrl+Enter`, `Delete to EOL/BOL`, etc.) ──
    if command == "run_macro_file":
        macro = _macro_name(args)
        if macro == "add line.sublime-macro":
            # Ctrl+Enter on a folded line -> safely insert new line below the fold!
            if all(s0 == s1 for s0, s1 in norm_sels):
                safe_pts: list[int] = []
                any_on_fold = False
                for pt, _ in norm_sels:
                    f = _fold_on_visible_line(text, pt, norm_folds)
                    if f is not None:
                        any_on_fold = True
                        safe_pts.append(f[1])
                    else:
                        safe_pts.append(_line_end(text, pt))
                if any_on_fold:
                    return GuardDecision("safe_newline", safe_newline_points=tuple(safe_pts))
            return GuardDecision("allow")

        if macro == "add line before.sublime-macro":
            # Ctrl+Shift+Enter inserts blank line above current line; only unsafe if caret is inside fold
            for s0, s1 in norm_sels:
                if _point_inside_fold(s0, norm_folds):
                    return GuardDecision("block", "Folded section is protected — unfold first")
            return GuardDecision("allow")

        if macro == "delete line.sublime-macro":
            for s0, s1 in norm_sels:
                # Deleting a line containing a fold would nuke the entire hidden section
                if _fold_on_visible_line(text, s0, norm_folds) is not None:
                    return GuardDecision("block", "Folded section is protected — unfold first")
                if s1 > s0 and _fold_on_visible_line(text, s1, norm_folds) is not None:
                    return GuardDecision("block", "Folded section is protected — unfold first")
                # Deleting an empty EOF line right after a fold (`b + 1 == len(text)`) deletes `text[b]`
                if s0 == s1 == len(text):
                    for _a, b in norm_folds:
                        if b + 1 == s0:
                            return GuardDecision("block", "Folded section is protected — unfold first")
            return GuardDecision("allow")

        if macro == "delete left right.sublime-macro":
            for s0, s1 in norm_sels:
                if s0 == s1 and (
                    _eval_left_delete_at_caret(text, s0, norm_folds)
                    or _eval_right_delete_at_caret(text, s0, norm_folds)
                ):
                    return GuardDecision("block", "Folded section is protected — unfold first")
            return GuardDecision("allow")

        if macro in ("delete to eol.sublime-macro", "delete to hard eol.sublime-macro"):
            for s0, s1 in norm_sels:
                if _fold_on_visible_line(text, s0, norm_folds) is not None:
                    return GuardDecision("block", "Folded section is protected — unfold first")
                if _eval_right_delete_at_caret(text, s0, norm_folds):
                    return GuardDecision("block", "Folded section is protected — unfold first")
            return GuardDecision("allow")

        if macro in ("delete to bol.sublime-macro", "delete to hard bol.sublime-macro"):
            for s0, s1 in norm_sels:
                if _point_inside_fold(s0, norm_folds) or _fold_ending_at(s0, norm_folds) is not None:
                    return GuardDecision("block", "Folded section is protected — unfold first")
                if _eval_left_delete_at_caret(text, s0, norm_folds):
                    return GuardDecision("block", "Folded section is protected — unfold first")
            return GuardDecision("allow")

        # Unknown macro on a folded line -> block conservatively
        for s0, s1 in norm_sels:
            if _fold_on_visible_line(text, s0, norm_folds) is not None:
                return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 3. Enter / Newline insertion ──
    if _is_newline_insert(command, args):
        if all(s0 == s1 for s0, s1 in norm_sels):
            decisions = [_eval_enter_at_caret(text, s0, norm_folds) for s0, _ in norm_sels]
            if "block" in decisions:
                return GuardDecision("block", "Folded section is protected — unfold first")
            if "safe_newline" in decisions:
                return GuardDecision(
                    "safe_newline",
                    safe_newline_points=tuple(s0 for s0, _ in norm_sels),
                )
            return GuardDecision("allow")
        # Non-empty selection: block if selection lies inside visible heading line
        for s0, s1 in norm_sels:
            for a, _b in norm_folds:
                f_line_start = _line_start(text, a)
                if f_line_start < s1 <= a:
                    return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 4. Backspace / Left delete ──
    if command in ("left_delete", "markdown_flow_backspace"):
        for s0, s1 in norm_sels:
            if s0 == s1 and _eval_left_delete_at_caret(text, s0, norm_folds):
                return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 5. Delete / Right delete ──
    if command == "right_delete":
        for s0, s1 in norm_sels:
            if s0 == s1 and _eval_right_delete_at_caret(text, s0, norm_folds):
                return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 6. Delete word (Ctrl+Backspace / Ctrl+Delete) ──
    if command == "delete_word":
        forward = bool((args or {}).get("forward", False))
        for s0, s1 in norm_sels:
            if s0 == s1:
                blocked = (
                    _eval_right_delete_at_caret(text, s0, norm_folds, word_mode=True)
                    if forward
                    else _eval_left_delete_at_caret(text, s0, norm_folds, word_mode=True)
                )
                if blocked:
                    return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 7. Cut (empty selection cuts whole line in Sublime Text!) ──
    if command == "cut":
        for s0, s1 in norm_sels:
            if s0 == s1:
                if _fold_on_visible_line(text, s0, norm_folds) is not None:
                    return GuardDecision("block", "Folded section is protected — unfold first")
                if s0 == len(text) and any(b + 1 == s0 for _a, b in norm_folds):
                    return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 8. Text insertion / Paste / Inline formatting ──
    if command in (
        "insert",
        "insert_snippet",
        "paste",
        "paste_and_indent",
        "paste_from_history",
        "yank",
        "markdown_flow_toggle_inline",
        "markdown_flow_insert_link",
        "markdown_flow_smart_paste",
    ):
        payload = _inserted_text(command, args)
        if command in ("paste", "paste_and_indent") and clipboard_text is not None:
            payload = clipboard_text
        has_newline = payload is not None and ("\n" in payload or "\r" in payload)

        for s0, s1 in norm_sels:
            if _point_inside_fold(s0, norm_folds) or _point_inside_fold(s1, norm_folds):
                return GuardDecision("block", "Folded section is protected — unfold first")
            # Caret sitting right after `[...]` (`pt == fold.b`) -> block typing/pasting
            if s0 == s1 and _fold_ending_at(s0, norm_folds) is not None:
                return GuardDecision("block", "Folded section is protected — unfold first")
            # Multi-line paste/insert inside a visible folded heading line would split it
            if has_newline or command in ("paste_from_history", "yank"):
                for a, _b in norm_folds:
                    f_line_start = _line_start(text, a)
                    if f_line_start < s0 <= a or (s0 == f_line_start and s1 > f_line_start):
                        return GuardDecision("block", "Folded section is protected — unfold first")
        return GuardDecision("allow")

    # ── 9. Line-structural mutating commands ──
    if command in (
        "join_lines",
        "swap_line_up",
        "swap_line_down",
        "duplicate_line",
        "indent",
        "unindent",
        "reindent",
        "transpose",
        "toggle_comment",
        "sort_lines",
        "permute_lines",
        "upper_case",
        "lower_case",
        "title_case",
        "swap_case",
        "delete_to_mark",
        "markdown_flow_indent",
        "markdown_flow_renumber",
    ):
        for s0, s1 in norm_sels:
            if _fold_on_visible_line(text, s0, norm_folds) is not None:
                return GuardDecision("block", "Folded section is protected — unfold first")
            if _fold_on_visible_line(text, s1, norm_folds) is not None:
                return GuardDecision("block", "Folded section is protected — unfold first")

            if command in ("join_lines", "swap_line_down"):
                # Line immediately above a folded heading cannot join/swap into it
                cur_eol = _line_end(text, s1)
                for a, _b in norm_folds:
                    f_line_start = _line_start(text, a)
                    if f_line_start > 0 and cur_eol == f_line_start - 1:
                        return GuardDecision("block", "Folded section is protected — unfold first")

            if command == "swap_line_up":
                # Line immediately below a folded block cannot swap across it
                cur_bol = _line_start(text, s0)
                for _a, b in norm_folds:
                    if b < len(text) and text[b] == "\n" and cur_bol == b + 1:
                        return GuardDecision("block", "Folded section is protected — unfold first")

            if command == "sort_lines":
                # Sorting whole file / multi-line span containing any fold would scramble folded blocks
                if s0 == s1 and norm_folds:
                    return GuardDecision("block", "Folded section is protected — unfold first")

        return GuardDecision("allow")

    # ── 10. Default fallback for any other unknown command ──
    # Do not break benign third-party commands unless selection strictly lies inside a fold
    for s0, s1 in norm_sels:
        if _point_inside_fold(s0, norm_folds) or _point_inside_fold(s1, norm_folds):
            return GuardDecision("block", "Folded section is protected — unfold first")
    return GuardDecision("allow")


def compute_safe_newline_edits(
    text: str,
    points: tuple[int, ...],
    folds: list[tuple[int, int]],
) -> tuple[list[tuple[int, str]], list[int]]:
    """Compute safe `(insert_pos, "\\n")` edits and resulting caret positions.

    For a caret sitting at `fold.b` (end of `# Section 1 [...]`):
    - If `text[fold.b] == "\\n"`, inserts `"\\n"` at `fold.b + 1` (the start of the
      next line!) so Sublime's folded region `(fold.a, fold.b)` is NEVER touched!
    - If `fold.b == len(text)` (EOF without trailing newline), inserts `"\\n"` at
      `fold.b` (caller should verify `(fold.a, fold.b)` remains folded).
    """
    norm_folds = _normalize_folds(folds)
    n = len(text)
    unique_pts = sorted(set(points))
    edits: list[tuple[int, str]] = []
    carets: list[int] = []
    shift = 0

    for pt in unique_pts:
        f = _fold_ending_at(pt, norm_folds)
        if f is not None:
            b = f[1]
            if b < n and text[b] == "\n":
                ins_pos = b + 1
                edits.append((ins_pos, "\n"))
                carets.append(ins_pos + shift)
            else:
                ins_pos = b
                edits.append((ins_pos, "\n"))
                carets.append(ins_pos + shift + 1)
        else:
            edits.append((pt, "\n"))
            carets.append(pt + shift + 1)
        shift += 1

    return edits, carets
