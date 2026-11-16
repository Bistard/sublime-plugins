"""Pure-Python list and blockquote editing engine for MarkdownFlow.

Handles:
- Unordered lists (`-`, `*`, `+`), ordered lists (`1.`, `1)`), task lists (`- [ ]`, `- [x]`)
- Blockquotes (`>`, nested `> >`) and lists nested inside blockquotes (`> 1. item`)
- Enter continuation, mid-line split, empty-item outdent (step-by-step) and exit
- Shift+Enter soft continuation aligned with item content column
- Tab / Shift+Tab list item indentation (4 spaces per level by default)
- Single-keystroke Backspace removal of whole list markers
- Structure-aware ordered list sibling renumbering (preserving custom start numbers
  while skipping fenced code blocks)
"""

from __future__ import annotations

from dataclasses import dataclass
import re

DEFAULT_INDENT_SIZE = 4

_QUOTE_PREFIX_RE = re.compile(r"^(?P<quote>(?:[ ]{0,3}>[ ]?)+)")
_THEMATIC_BREAK_RE = re.compile(
    r"^[ \t]*(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$"
)
_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^[ ]{0,3}#{1,6}(?:[ \t]+|$)")
_LIST_ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)"
    r"(?P<marker>(?:[-*+])|(?:\d+[.)]))"
    r"(?P<space>[ \t]+)"
    r"(?:(?P<task>\[[ xX]\])(?P<task_space>[ \t]+|$))?"
    r"(?P<content>.*)$"
)


@dataclass(frozen=True)
class ParsedBlockLine:
    """Structured representation of a Markdown list item or blockquote line."""

    raw: str
    quote_raw: str
    quote_depth: int
    indent_raw: str
    indent_col: int
    is_list: bool
    bullet: str | None  # "-", "*", "+" for unordered lists
    number: int | None  # integer for ordered lists
    delimiter: str | None  # "." or ")" for ordered lists
    task: str | None  # "[ ]", "[x]", "[X]" if task item
    prefix_len: int  # char offset where content starts
    content: str

    @property
    def is_ordered(self) -> bool:
        return self.number is not None and self.delimiter is not None

    @property
    def is_empty_content(self) -> bool:
        return self.content.strip() == ""

    @property
    def marker_start_len(self) -> int:
        """Character offset where the list marker (`-`, `1.`) begins."""
        return len(self.quote_raw) + len(self.indent_raw)


@dataclass(frozen=True)
class EditOutcome:
    """Result of applying a list/blockquote editing operation to a line buffer."""

    lines: list[str]
    cursors: list[tuple[int, int]]  # list of (line_idx, col_offset) or single cursor
    selection_spans: list[tuple[tuple[int, int], tuple[int, int]]] | None = None


def expand_indent_col(indent_raw: str, indent_size: int = DEFAULT_INDENT_SIZE) -> int:
    return len(indent_raw.expandtabs(indent_size))


def normalize_quote_prefix(quote_raw: str) -> str:
    if not quote_raw:
        return ""
    if quote_raw.endswith(" "):
        return quote_raw
    return quote_raw + " "


def outdent_quote_prefix(quote_raw: str) -> str:
    if not quote_raw:
        return ""
    stripped = re.sub(r"[ ]{0,3}>[ ]?$", "", quote_raw)
    return normalize_quote_prefix(stripped) if stripped else ""


def parse_block_line(
    line: str, indent_size: int = DEFAULT_INDENT_SIZE
) -> ParsedBlockLine | None:
    """Parse a line as a Markdown list item (optionally quoted) or pure blockquote.

    Returns None if the line is neither a list item nor a blockquote.
    """
    qm = _QUOTE_PREFIX_RE.match(line)
    quote_raw = qm.group("quote") if qm else ""
    quote_depth = quote_raw.count(">")
    rest = line[len(quote_raw) :]

    if _THEMATIC_BREAK_RE.match(rest) or _FENCE_RE.match(rest) or _HEADING_RE.match(rest):
        if quote_depth > 0:
            return ParsedBlockLine(
                raw=line,
                quote_raw=quote_raw,
                quote_depth=quote_depth,
                indent_raw="",
                indent_col=0,
                is_list=False,
                bullet=None,
                number=None,
                delimiter=None,
                task=None,
                prefix_len=len(quote_raw),
                content=rest,
            )
        return None

    lm = _LIST_ITEM_RE.match(rest)
    if lm:
        indent_raw = lm.group("indent")
        marker = lm.group("marker")
        task = lm.group("task")
        content = lm.group("content")
        prefix_len = len(line) - len(content)

        if marker in ("-", "*", "+"):
            bullet: str | None = marker
            number: int | None = None
            delimiter: str | None = None
        else:
            bullet = None
            number = int(marker[:-1])
            delimiter = marker[-1]

        return ParsedBlockLine(
            raw=line,
            quote_raw=quote_raw,
            quote_depth=quote_depth,
            indent_raw=indent_raw,
            indent_col=expand_indent_col(indent_raw, indent_size),
            is_list=True,
            bullet=bullet,
            number=number,
            delimiter=delimiter,
            task=task,
            prefix_len=prefix_len,
            content=content,
        )

    if quote_depth > 0:
        return ParsedBlockLine(
            raw=line,
            quote_raw=quote_raw,
            quote_depth=quote_depth,
            indent_raw="",
            indent_col=0,
            is_list=False,
            bullet=None,
            number=None,
            delimiter=None,
            task=None,
            prefix_len=len(quote_raw),
            content=rest,
        )

    return None


def build_list_prefix(
    *,
    quote_raw: str = "",
    indent_col: int = 0,
    bullet: str | None = None,
    number: int | None = None,
    delimiter: str | None = None,
    has_task: bool = False,
    task_checked: bool = False,
) -> str:
    """Format a normalized Markdown list item prefix."""
    q = normalize_quote_prefix(quote_raw)
    indent = " " * max(0, indent_col)
    if bullet is not None:
        head = bullet
    else:
        num = 1 if number is None else number
        delim = "." if delimiter is None else delimiter
        head = f"{num}{delim}"

    if has_task:
        box = "[x]" if task_checked else "[ ]"
        return f"{q}{indent}{head} {box} "
    return f"{q}{indent}{head} "


def _strip_quote(line: str, expected_quote_depth: int) -> tuple[bool, str]:
    """Check if line matches the expected quote depth and return (matches, rest)."""
    qm = _QUOTE_PREFIX_RE.match(line)
    quote_raw = qm.group("quote") if qm else ""
    depth = quote_raw.count(">")
    if depth != expected_quote_depth:
        return False, ""
    return True, line[len(quote_raw) :]


def find_list_block_bounds(
    lines: list[str],
    center_idx: int,
    quote_depth: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> tuple[int, int]:
    """Find inclusive (start_idx, end_idx) of the contiguous list block around center_idx."""
    n = len(lines)
    if n == 0:
        return 0, 0
    center_idx = max(0, min(center_idx, n - 1))

    def is_structural_break(rest: str) -> bool:
        return bool(_HEADING_RE.match(rest) or _THEMATIC_BREAK_RE.match(rest))

    # Scan upwards
    start = center_idx
    in_fence: str | None = None
    i = center_idx - 1
    while i >= 0:
        ok, rest = _strip_quote(lines[i], quote_depth)
        if not ok:
            break
        fm = _FENCE_RE.match(rest)
        if fm:
            token = fm.group("fence")
            if in_fence is None:
                in_fence = token[0]
            elif token[0] == in_fence:
                in_fence = None
            start = i
            i -= 1
            continue
        if in_fence is not None:
            start = i
            i -= 1
            continue
        if rest.strip() == "":
            # Allow at most 1 blank line if preceded by a list item or indented continuation
            if i - 1 >= 0:
                ok_prev, rest_prev = _strip_quote(lines[i - 1], quote_depth)
                if ok_prev and rest_prev.strip() != "" and not is_structural_break(rest_prev):
                    prev_parsed = parse_block_line(lines[i - 1], indent_size)
                    if (prev_parsed and prev_parsed.is_list) or rest_prev.startswith((" ", "\t")):
                        start = i - 1
                        i -= 2
                        continue
            break
        if is_structural_break(rest):
            break
        parsed = parse_block_line(lines[i], indent_size)
        if parsed and parsed.is_list:
            start = i
            i -= 1
            continue
        if rest.startswith((" ", "\t")):
            start = i
            i -= 1
            continue
        # Unindented plain paragraph: only part of block if lazy continuation of an item above
        if i - 1 >= 0:
            prev_parsed = parse_block_line(lines[i - 1], indent_size)
            if prev_parsed and prev_parsed.is_list and prev_parsed.quote_depth == quote_depth:
                start = i - 1
                i -= 2
                continue
        break

    # Scan downwards
    end = center_idx
    in_fence = None
    i = center_idx + 1
    while i < n:
        ok, rest = _strip_quote(lines[i], quote_depth)
        if not ok:
            break
        fm = _FENCE_RE.match(rest)
        if fm:
            token = fm.group("fence")
            if in_fence is None:
                in_fence = token[0]
                # Unindented code fence at col 0 closes top-level list
                if not rest.startswith((" ", "\t")):
                    break
            elif token[0] == in_fence:
                in_fence = None
            end = i
            i += 1
            continue
        if in_fence is not None:
            end = i
            i += 1
            continue
        if rest.strip() == "":
            # Allow single blank line if followed by a list item or indented block
            if i + 1 < n:
                ok_next, rest_next = _strip_quote(lines[i + 1], quote_depth)
                if ok_next and rest_next.strip() != "" and not is_structural_break(rest_next):
                    next_parsed = parse_block_line(lines[i + 1], indent_size)
                    if (next_parsed and next_parsed.is_list) or rest_next.startswith((" ", "\t")):
                        end = i + 1
                        i += 2
                        continue
            break
        if is_structural_break(rest):
            break
        parsed = parse_block_line(lines[i], indent_size)
        if parsed and parsed.is_list:
            end = i
            i += 1
            continue
        if rest.startswith((" ", "\t")):
            end = i
            i += 1
            continue
        # Unindented plain line immediately following a list line = lazy continuation
        prev_ok, prev_rest = _strip_quote(lines[i - 1], quote_depth)
        if prev_ok and prev_rest.strip() != "":
            end = i
            i += 1
            continue
        break

    return start, end


def snapshot_start_numbers(
    lines: list[str],
    start: int,
    end: int,
    quote_depth: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> dict[tuple[int, int, str], int]:
    """Capture initial starting numbers keyed by `(parent_line_idx, indent_col, delimiter)`."""
    starts: dict[tuple[int, int, str], int] = {}
    active_runs: dict[int, tuple[int, str]] = {}  # col -> (parent_idx, delim)
    last_item_at_col: dict[int, int] = {}
    in_fence: tuple[str, int] | None = None

    for idx in range(start, min(end + 1, len(lines))):
        ok, rest = _strip_quote(lines[idx], quote_depth)
        if not ok:
            continue
        fm = _FENCE_RE.match(rest)
        if fm:
            f = fm.group("fence")
            if in_fence is None:
                in_fence = (f[0], len(f))
            elif f[0] == in_fence[0] and len(f) >= in_fence[1]:
                in_fence = None
            continue
        if in_fence is not None:
            continue

        parsed = parse_block_line(lines[idx], indent_size)
        if not parsed or not parsed.is_list:
            continue
        col = parsed.indent_col
        for deeper in [k for k in active_runs if k > col]:
            del active_runs[deeper]
        for deeper in [k for k in last_item_at_col if k > col]:
            del last_item_at_col[deeper]

        parent_idx = max(
            (line_i for k, line_i in last_item_at_col.items() if k < col),
            default=-1,
        )
        last_item_at_col[col] = idx

        if not parsed.is_ordered:
            active_runs.pop(col, None)
            continue

        assert parsed.delimiter is not None and parsed.number is not None
        delim = parsed.delimiter
        if active_runs.get(col) != (parent_idx, delim):
            active_runs[col] = (parent_idx, delim)
            key = (parent_idx, col, delim)
            if key not in starts:
                starts[key] = parsed.number
    return starts


def renumber_range(
    lines: list[str],
    start: int,
    end: int,
    quote_depth: int | None = None,
    indent_size: int = DEFAULT_INDENT_SIZE,
    preserved_starts: dict[tuple[int, int, str], int] | None = None,
) -> dict[int, int]:
    """Renumber ordered lists in lines[start : end + 1] in place.

    Returns a mapping `{line_idx: prefix_len_delta}` for lines whose prefix length changed,
    allowing callers to keep cursor columns anchored accurately.
    """
    deltas: dict[int, int] = {}
    # Keyed by quote_depth -> {indent_col: (delimiter, next_num)}
    counters_by_quote: dict[int, dict[int, tuple[str, int]]] = {}
    last_item_by_quote: dict[int, dict[int, int]] = {}
    used_preserved: set[tuple[int, int, str]] = set()
    in_fence: tuple[str, int] | None = None
    consecutive_blanks = 0

    for idx in range(max(0, start), min(end + 1, len(lines))):
        line = lines[idx]
        qm = _QUOTE_PREFIX_RE.match(line)
        q_raw = qm.group("quote") if qm else ""
        q_depth = q_raw.count(">")
        rest = line[len(q_raw) :]

        fm = _FENCE_RE.match(rest)
        if fm:
            f = fm.group("fence")
            if in_fence is None:
                in_fence = (f[0], len(f))
                if not rest.startswith((" ", "\t")):
                    counters_by_quote.pop(q_depth, None)
                    last_item_by_quote.pop(q_depth, None)
            elif f[0] == in_fence[0] and len(f) >= in_fence[1]:
                in_fence = None
            continue
        if in_fence is not None:
            continue

        if quote_depth is not None and q_depth != quote_depth:
            for d in list(counters_by_quote.keys()):
                if d > q_depth:
                    counters_by_quote.pop(d, None)
                    last_item_by_quote.pop(d, None)
            continue

        for d in list(counters_by_quote.keys()):
            if d > q_depth:
                counters_by_quote.pop(d, None)
                last_item_by_quote.pop(d, None)

        if rest.strip() == "":
            consecutive_blanks += 1
            if consecutive_blanks >= 2:
                counters_by_quote.pop(q_depth, None)
                last_item_by_quote.pop(q_depth, None)
            continue

        if _HEADING_RE.match(rest) or _THEMATIC_BREAK_RE.match(rest):
            consecutive_blanks = 0
            counters_by_quote.pop(q_depth, None)
            last_item_by_quote.pop(q_depth, None)
            continue

        parsed = parse_block_line(line, indent_size)
        if parsed and parsed.is_list:
            consecutive_blanks = 0
            counters = counters_by_quote.setdefault(q_depth, {})
            last_items = last_item_by_quote.setdefault(q_depth, {})
            col = parsed.indent_col

            # Pop any deeper sublist counters once we return to a shallower/equal level
            for deeper in [k for k in counters if k > col]:
                del counters[deeper]
            for deeper in [k for k in last_items if k > col]:
                del last_items[deeper]

            parent_idx = max(
                (line_i for k, line_i in last_items.items() if k < col),
                default=-1,
            )
            last_items[col] = idx

            if not parsed.is_ordered:
                # Switching to unordered at the same indent closes any ordered run at `col`
                counters.pop(col, None)
                continue

            assert parsed.delimiter is not None and parsed.number is not None
            delim = parsed.delimiter
            existing_entry = counters.get(col)
            if existing_entry is not None and existing_entry[0] == delim:
                expected = existing_entry[1]
            else:
                key = (parent_idx, col, delim)
                if (
                    preserved_starts is not None
                    and key in preserved_starts
                    and key not in used_preserved
                ):
                    expected = preserved_starts[key]
                    used_preserved.add(key)
                else:
                    expected = parsed.number
            counters[col] = (delim, expected + 1)

            if expected != parsed.number:
                # Replace just the digits before delimiter while keeping exact quote/indent/task
                old_num_str = str(parsed.number)
                new_num_str = str(expected)
                marker_pos = parsed.marker_start_len
                lines[idx] = (
                    line[:marker_pos]
                    + new_num_str
                    + line[marker_pos + len(old_num_str) :]
                )
                deltas[idx] = len(new_num_str) - len(old_num_str)
        else:
            # Plain non-indented paragraph after a blank line closes the list
            if consecutive_blanks >= 1 and not rest.startswith((" ", "\t")):
                counters_by_quote.pop(q_depth, None)
                last_item_by_quote.pop(q_depth, None)
            consecutive_blanks = 0

    return deltas


def _find_parent_style(
    lines: list[str],
    before_idx: int,
    block_start: int,
    target_indent_col: int,
    quote_depth: int,
    indent_size: int,
) -> ParsedBlockLine | None:
    """Find the nearest preceding list item at `target_indent_col` in the same block."""
    for idx in range(before_idx - 1, block_start - 1, -1):
        parsed = parse_block_line(lines[idx], indent_size)
        if not parsed or parsed.quote_depth != quote_depth or not parsed.is_list:
            continue
        if parsed.indent_col < target_indent_col:
            return None
        if parsed.indent_col == target_indent_col:
            return parsed
    return None


def can_handle_enter(line: str, indent_size: int = DEFAULT_INDENT_SIZE) -> bool:
    return parse_block_line(line, indent_size) is not None


def handle_enter(
    lines: list[str],
    line_idx: int,
    col: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> EditOutcome | None:
    """Process `Enter` at `(line_idx, col)` on a list or blockquote line."""
    if not (0 <= line_idx < len(lines)):
        return None
    line = lines[line_idx]
    parsed = parse_block_line(line, indent_size)
    if parsed is None:
        return None

    new_lines = list(lines)

    # Case 1: Pure blockquote line (not a list item)
    if not parsed.is_list:
        if parsed.is_empty_content:
            outdented = outdent_quote_prefix(parsed.quote_raw)
            new_lines[line_idx] = outdented
            return EditOutcome(lines=new_lines, cursors=[(line_idx, len(outdented))])

        if col < len(parsed.quote_raw):
            # Cursor inside or before `> `: insert new quote line above
            q_norm = normalize_quote_prefix(parsed.quote_raw).rstrip()
            new_lines.insert(line_idx, q_norm)
            return EditOutcome(lines=new_lines, cursors=[(line_idx + 1, col)])

        q_norm = normalize_quote_prefix(parsed.quote_raw)
        head = line[:col]
        tail = line[col:]
        new_lines[line_idx] = head
        new_lines.insert(line_idx + 1, q_norm + tail)
        return EditOutcome(lines=new_lines, cursors=[(line_idx + 1, len(q_norm))])

    # Case 2: List item (optionally inside a blockquote)
    b_start, b_end = find_list_block_bounds(
        new_lines, line_idx, parsed.quote_depth, indent_size
    )
    starts = snapshot_start_numbers(
        new_lines, b_start, b_end, parsed.quote_depth, indent_size
    )

    # Subcase 2a: Empty list item -> step-by-step outdent, then exit
    if parsed.is_empty_content:
        if parsed.indent_col > 0:
            new_indent = max(0, parsed.indent_col - indent_size)
            parent = _find_parent_style(
                new_lines, line_idx, b_start, new_indent, parsed.quote_depth, indent_size
            )
            if parent is not None:
                replacement = build_list_prefix(
                    quote_raw=parsed.quote_raw,
                    indent_col=new_indent,
                    bullet=parent.bullet,
                    number=(parent.number + 1) if parent.number is not None else None,
                    delimiter=parent.delimiter,
                    has_task=parent.task is not None,
                    task_checked=False,
                )
            else:
                replacement = build_list_prefix(
                    quote_raw=parsed.quote_raw,
                    indent_col=new_indent,
                    bullet=parsed.bullet,
                    number=1 if parsed.is_ordered else None,
                    delimiter=parsed.delimiter,
                    has_task=parsed.task is not None,
                    task_checked=False,
                )
            new_lines[line_idx] = replacement
            deltas = renumber_range(
                new_lines,
                b_start,
                b_end,
                quote_depth=parsed.quote_depth,
                indent_size=indent_size,
                preserved_starts=starts,
            )
            cursor_col = len(replacement) + deltas.get(line_idx, 0)
            return EditOutcome(lines=new_lines, cursors=[(line_idx, cursor_col)])

        # At top indent level (indent_col == 0)
        if parsed.quote_depth > 0:
            # Outdent from quoted list item back to plain blockquote line `> `
            q_norm = normalize_quote_prefix(parsed.quote_raw)
            new_lines[line_idx] = q_norm
            renumber_range(
                new_lines,
                b_start,
                b_end,
                quote_depth=parsed.quote_depth,
                indent_size=indent_size,
                preserved_starts=starts,
            )
            return EditOutcome(lines=new_lines, cursors=[(line_idx, len(q_norm))])

        # Clear line completely to exit the list
        new_lines[line_idx] = ""
        renumber_range(
            new_lines,
            b_start,
            b_end,
            quote_depth=0,
            indent_size=indent_size,
            preserved_starts=starts,
        )
        return EditOutcome(lines=new_lines, cursors=[(line_idx, 0)])

    # Subcase 2b: Non-empty list item, cursor BEFORE the list marker -> insert blank line above
    if col <= parsed.marker_start_len:
        blank_above = normalize_quote_prefix(parsed.quote_raw).rstrip()
        new_lines.insert(line_idx, blank_above)
        return EditOutcome(lines=new_lines, cursors=[(line_idx + 1, col)])

    # Subcase 2c: Non-empty list item, split or continue at cursor
    split_col = max(col, parsed.prefix_len)
    head = line[:split_col]
    tail = line[split_col:]

    next_prefix = build_list_prefix(
        quote_raw=parsed.quote_raw,
        indent_col=parsed.indent_col,
        bullet=parsed.bullet,
        number=(parsed.number + 1) if parsed.number is not None else None,
        delimiter=parsed.delimiter,
        has_task=parsed.task is not None,
        task_checked=False,  # Completed `[x]` items always spawn fresh `[ ]` items
    )

    new_lines[line_idx] = head
    new_lines.insert(line_idx + 1, next_prefix + tail)
    deltas = renumber_range(
        new_lines,
        b_start,
        b_end + 1,
        quote_depth=parsed.quote_depth,
        indent_size=indent_size,
        preserved_starts=starts,
    )
    new_cursor_col = len(next_prefix) + deltas.get(line_idx + 1, 0)
    return EditOutcome(lines=new_lines, cursors=[(line_idx + 1, new_cursor_col)])


def handle_soft_return(
    lines: list[str],
    line_idx: int,
    col: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> EditOutcome | None:
    """Process `Shift+Enter`: insert an aligned continuation line without a new marker."""
    if not (0 <= line_idx < len(lines)):
        return None
    line = lines[line_idx]
    parsed = parse_block_line(line, indent_size)
    if parsed is None:
        return None

    new_lines = list(lines)
    split_col = max(col, parsed.prefix_len)
    head = line[:split_col]
    tail = line[split_col:]

    if parsed.is_list:
        q_norm = normalize_quote_prefix(parsed.quote_raw)
        # Align continuation content column with current item's content start
        content_offset = parsed.prefix_len - len(parsed.quote_raw)
        continuation_prefix = q_norm + (" " * max(indent_size, content_offset))
    else:
        continuation_prefix = normalize_quote_prefix(parsed.quote_raw)

    new_lines[line_idx] = head
    new_lines.insert(line_idx + 1, continuation_prefix + tail)
    return EditOutcome(
        lines=new_lines, cursors=[(line_idx + 1, len(continuation_prefix))]
    )


def is_at_list_marker_end(
    line: str, col: int, indent_size: int = DEFAULT_INDENT_SIZE
) -> bool:
    """Return True if `col` sits immediately after the list marker (and optional checkbox)."""
    parsed = parse_block_line(line, indent_size)
    if parsed is None or not parsed.is_list:
        return False
    return col == parsed.prefix_len


def handle_backspace_at_marker(
    lines: list[str],
    line_idx: int,
    col: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> EditOutcome | None:
    """Remove the entire list marker in one keystroke while keeping indentation."""
    if not (0 <= line_idx < len(lines)):
        return None
    line = lines[line_idx]
    parsed = parse_block_line(line, indent_size)
    if parsed is None or not parsed.is_list or col != parsed.prefix_len:
        return None

    new_lines = list(lines)
    b_start, b_end = find_list_block_bounds(
        new_lines, line_idx, parsed.quote_depth, indent_size
    )
    starts = snapshot_start_numbers(
        new_lines, b_start, b_end, parsed.quote_depth, indent_size
    )

    kept_prefix = parsed.quote_raw + (" " * parsed.indent_col)
    new_lines[line_idx] = kept_prefix + parsed.content

    renumber_range(
        new_lines,
        b_start,
        b_end,
        quote_depth=parsed.quote_depth,
        indent_size=indent_size,
        preserved_starts=starts,
    )
    return EditOutcome(lines=new_lines, cursors=[(line_idx, len(kept_prefix))])


def can_indent_lines(
    lines: list[str],
    target_line_indices: list[int],
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> bool:
    """Return True if all targeted lines are Markdown list items."""
    if not target_line_indices:
        return False
    for idx in target_line_indices:
        if not (0 <= idx < len(lines)):
            return False
        parsed = parse_block_line(lines[idx], indent_size)
        if parsed is None or not parsed.is_list:
            return False
    return True


def handle_indent(
    lines: list[str],
    selections: list[tuple[tuple[int, int], tuple[int, int]]],
    direction: int,
    indent_size: int = DEFAULT_INDENT_SIZE,
) -> EditOutcome | None:
    """Indent (`direction=+1`) or outdent (`direction=-1`) list items covered by selections.

    Preserves exact cursor/selection character offsets relative to item content and
    renumbers affected ordered list blocks.
    """
    if direction not in (1, -1) or not selections:
        return None

    affected_indices: list[int] = []
    seen: set[int] = set()
    for (r1, _c1), (r2, c2) in selections:
        lo, hi = (r1, r2) if (r1, _c1) <= (r2, c2) else (r2, r1)
        # If multi-line selection ends at column 0 of `hi` and `hi > lo`, exclude `hi`
        end_col = c2 if r2 >= r1 else _c1
        if hi > lo and end_col == 0:
            hi -= 1
        for r in range(lo, hi + 1):
            if r not in seen:
                seen.add(r)
                affected_indices.append(r)

    if not can_indent_lines(lines, affected_indices, indent_size):
        return None

    new_lines = list(lines)

    # Snapshot block bounds and starting numbers before mutating indentation
    blocks: list[tuple[int, int, int, dict[tuple[int, str], int]]] = []
    covered_upto = -1
    for idx in sorted(affected_indices):
        if idx <= covered_upto:
            continue
        parsed = parse_block_line(new_lines[idx], indent_size)
        assert parsed is not None
        b_start, b_end = find_list_block_bounds(
            new_lines, idx, parsed.quote_depth, indent_size
        )
        starts = snapshot_start_numbers(
            new_lines, b_start, b_end, parsed.quote_depth, indent_size
        )
        blocks.append((b_start, b_end, parsed.quote_depth, starts))
        covered_upto = b_end

    line_shift: dict[int, int] = {}
    for idx in affected_indices:
        line = new_lines[idx]
        parsed = parse_block_line(line, indent_size)
        assert parsed is not None and parsed.is_list

        new_indent_col = max(0, parsed.indent_col + direction * indent_size)
        if new_indent_col == parsed.indent_col:
            line_shift[idx] = 0
            continue

        # When indenting an ordered item deeper, reset number to 1 so a new sublist starts at 1
        reset_num = 1 if (direction > 0 and parsed.is_ordered) else parsed.number

        new_prefix = build_list_prefix(
            quote_raw=parsed.quote_raw,
            indent_col=new_indent_col,
            bullet=parsed.bullet,
            number=reset_num,
            delimiter=parsed.delimiter,
            has_task=parsed.task is not None,
            task_checked=parsed.task in ("[x]", "[X]"),
        )
        old_prefix_len = parsed.prefix_len
        new_lines[idx] = new_prefix + parsed.content
        line_shift[idx] = len(new_prefix) - old_prefix_len

    for b_start, b_end, q_depth, starts in blocks:
        deltas = renumber_range(
            new_lines,
            b_start,
            b_end,
            quote_depth=q_depth,
            indent_size=indent_size,
            preserved_starts=starts,
        )
        for r, d in deltas.items():
            line_shift[r] = line_shift.get(r, 0) + d

    def shift_pt(pt: tuple[int, int]) -> tuple[int, int]:
        r, c = pt
        delta = line_shift.get(r, 0)
        if delta == 0:
            return r, c
        max_col = len(new_lines[r])
        return r, max(0, min(max_col, c + delta))

    new_spans = [(shift_pt(a), shift_pt(b)) for a, b in selections]
    new_cursors = [b for _a, b in new_spans]
    return EditOutcome(
        lines=new_lines, cursors=new_cursors, selection_spans=new_spans
    )
