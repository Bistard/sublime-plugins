"""Pure-Python inline formatting, link insertion, and smart URL paste engine.

Designed specifically for smooth CJK + English Markdown authoring:
- Streaming pair input on empty selection (`**|**` -> type -> press again to jump out,
  or press immediately on empty pair to remove)
- 2-bit XOR state machine for `*` (italic = 1), `**` (bold = 2), and `***` (bold+italic = 3)
- Cursor-inside-span unwrap when placed inside existing formatted text (`**文|字**` -> `文|字`)
- List-bullet and inline-code awareness so `* item` or `` `a*b` `` never misparse as italic
- Smart URL paste with guards against code spans, URLs replacing URLs, and `[...](...)` slots
"""

from __future__ import annotations

import re

_URL_RE = re.compile(r"^(?:https?://|mailto:)[^\s<>]+$", re.IGNORECASE)
_LINE_LIST_PREFIX_RE = re.compile(
    r"^(?:[ ]{0,3}>[ ]?)*(?:[ \t]*(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?)"
)


def is_single_url(text: str) -> str | None:
    """Return stripped URL if `text` is a single HTTP(S) or mailto URL, else None."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped or any(ch.isspace() for ch in stripped):
        return None
    if _URL_RE.match(stripped):
        return stripped
    return None


def _prose_start_offset(line: str) -> int:
    """Return index after any blockquote + list marker so `* item` bullet is skipped."""
    m = _LINE_LIST_PREFIX_RE.match(line)
    if m:
        return m.end()
    qm = re.match(r"^(?:[ ]{0,3}>[ ]?)+", line)
    return qm.end() if qm else 0


def find_code_spans(line: str, start_at: int = 0) -> list[tuple[int, int, int, int]]:
    """Find matched backtick inline code spans `(open_s, inner_s, inner_e, close_e)`."""
    spans: list[tuple[int, int, int, int]] = []
    n = len(line)
    i = start_at
    while i < n:
        if line[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if line[i] == "`":
            j = i
            while j < n and line[j] == "`":
                j += 1
            ticks = j - i
            # Find matching run of exact `ticks` backticks
            k = j
            matched = False
            while k < n:
                if line[k] == "`":
                    m = k
                    while m < n and line[m] == "`":
                        m += 1
                    if m - k == ticks:
                        spans.append((i, j, k, m))
                        i = m
                        matched = True
                        break
                    k = m
                else:
                    k += 1
            if not matched:
                i = j
        else:
            i += 1
    return spans


def _in_any_code_span(
    idx: int, code_spans: list[tuple[int, int, int, int]]
) -> bool:
    return any(open_s <= idx < close_e for open_s, _, _, close_e in code_spans)


def _find_symmetric_marker_spans(
    line: str,
    delim_char: str,
    min_len: int,
    max_len: int,
    start_at: int,
    code_spans: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int, int]]:
    """Find matched delimiter spans `(open_s, inner_s, inner_e, close_e, run_len)`."""
    runs: list[tuple[int, int]] = []  # (pos, length)
    n = len(line)
    i = start_at
    while i < n:
        if _in_any_code_span(i, code_spans):
            i += 1
            continue
        if line[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if line[i] == delim_char:
            j = i
            while j < n and line[j] == delim_char and not _in_any_code_span(j, code_spans):
                j += 1
            run_len = j - i
            if min_len <= run_len <= max_len:
                runs.append((i, run_len))
            i = j
        else:
            i += 1

    # Pair matching runs using a simple stack (handles nested `*` inside `**` or exact matches)
    stack: list[tuple[int, int]] = []
    spans: list[tuple[int, int, int, int, int]] = []
    for pos, length in runs:
        # Look for matching length on stack top-down
        match_idx: int | None = None
        for s_idx in range(len(stack) - 1, -1, -1):
            open_pos, open_len = stack[s_idx]
            if open_len == length and pos > open_pos + open_len:
                # Markdown emphasis cannot have space immediately inside both edges
                inner = line[open_pos + open_len : pos]
                if inner and not (inner[0].isspace() and inner[-1].isspace()):
                    match_idx = s_idx
                    break
        if match_idx is not None:
            open_pos, open_len = stack[match_idx]
            del stack[match_idx:]
            spans.append((open_pos, open_pos + open_len, pos, pos + length, length))
        else:
            stack.append((pos, length))
    return spans


def _toggle_backtick(line: str, a: int, b: int) -> tuple[str, int, int]:
    prose_start = _prose_start_offset(line)
    code_spans = find_code_spans(line, prose_start)

    if a < b:
        selected = line[a:b]
        # Case 1: Selection itself starts and ends with matching backticks
        m_in = re.match(r"^(`+)(.*?)\1$", selected)
        if m_in and m_in.group(2) != "":
            ticks_len = len(m_in.group(1))
            core = m_in.group(2)
            if core.startswith(" ") and core.endswith(" ") and len(core) >= 2 and "`" in core:
                core = core[1:-1]
            new_line = line[:a] + core + line[b:]
            return new_line, a, a + len(core)

        # Case 2: Selection is immediately wrapped by backticks outside [a, b]
        left_ticks = len(line[:a]) - len(line[:a].rstrip("`"))
        right_ticks = len(line[b:]) - len(line[b:].lstrip("`"))
        pair_ticks = min(left_ticks, right_ticks)
        if pair_ticks > 0 and left_ticks == right_ticks:
            outer_a = a - pair_ticks
            outer_b = b + pair_ticks
            new_line = line[:outer_a] + selected + line[outer_b:]
            return new_line, outer_a, outer_a + len(selected)

        # Wrap selection (if selection contains backticks, use a longer backtick fence)
        max_run = max((len(m.group(0)) for m in re.finditer(r"`+", selected)), default=0)
        fence = "`" * (max_run + 1)
        pad = " " if (selected.startswith("`") or selected.endswith("`")) else ""
        wrapped = f"{fence}{pad}{selected}{pad}{fence}"
        new_line = line[:a] + wrapped + line[b:]
        core_a = a + len(fence) + len(pad)
        return new_line, core_a, core_a + len(selected)

    # Empty selection (a == b)
    pos = a
    left_ticks = len(line[:pos]) - len(line[:pos].rstrip("`"))
    right_ticks = len(line[pos:]) - len(line[pos:].lstrip("`"))
    if left_ticks > 0 and left_ticks == right_ticks:
        # Inside empty `` `|` `` -> remove empty pair
        new_line = line[: pos - left_ticks] + line[pos + right_ticks :]
        new_pos = pos - left_ticks
        return new_line, new_pos, new_pos

    for open_s, inner_s, inner_e, close_e in code_spans:
        if inner_s <= pos <= inner_e:
            if pos == inner_e and inner_s < inner_e:
                # At end of span right before closing backtick -> jump out
                return line, close_e, close_e
            # Inside existing code span -> unwrap
            core = line[inner_s:inner_e]
            new_line = line[:open_s] + core + line[close_e:]
            new_pos = pos - (inner_s - open_s)
            return new_line, new_pos, new_pos

    new_line = line[:pos] + "``" + line[pos:]
    return new_line, pos + 1, pos + 1


def _toggle_strikethrough(line: str, a: int, b: int) -> tuple[str, int, int]:
    prose_start = _prose_start_offset(line)
    code_spans = find_code_spans(line, prose_start)

    if a < b:
        selected = line[a:b]
        if selected.startswith("~~") and selected.endswith("~~") and len(selected) > 4:
            core = selected[2:-2]
            new_line = line[:a] + core + line[b:]
            return new_line, a, a + len(core)
        if a >= 2 and line[a - 2 : a] == "~~" and line[b : b + 2] == "~~":
            new_line = line[: a - 2] + selected + line[b + 2 :]
            return new_line, a - 2, a - 2 + len(selected)

        new_line = line[:a] + f"~~{selected}~~" + line[b:]
        return new_line, a + 2, b + 2

    pos = a
    if pos >= 2 and line[pos - 2 : pos] == "~~" and line[pos : pos + 2] == "~~":
        new_line = line[: pos - 2] + line[pos + 2 :]
        return new_line, pos - 2, pos - 2

    spans = _find_symmetric_marker_spans(line, "~", 2, 2, prose_start, code_spans)
    for open_s, inner_s, inner_e, close_e, _ in spans:
        if inner_s <= pos <= inner_e:
            if pos == inner_e and inner_s < inner_e:
                return line, close_e, close_e
            core = line[inner_s:inner_e]
            new_line = line[:open_s] + core + line[close_e:]
            new_pos = pos - 2
            return new_line, new_pos, new_pos

    new_line = line[:pos] + "~~~~" + line[pos:]
    return new_line, pos + 2, pos + 2


def _toggle_asterisks(line: str, a: int, b: int, bit: int) -> tuple[str, int, int]:
    """Toggle italic (`bit=1`) or bold (`bit=2`) using 2-bit XOR on `*`..`***`."""
    prose_start = _prose_start_offset(line)
    code_spans = find_code_spans(line, prose_start)

    if a < b:
        # Peel symmetric `*` inside [a, b]
        sel = line[a:b]
        l_in = len(sel) - len(sel.lstrip("*"))
        r_in = len(sel) - len(sel.rstrip("*"))
        in_pair = min(3, l_in, r_in) if len(sel) > 2 * min(l_in, r_in) else 0
        core_a = a + in_pair
        core_b = b - in_pair

        # Peel symmetric `*` immediately outside [core_a, core_b] (but not into list bullet!)
        left_slice = line[prose_start:core_a]
        l_out = len(left_slice) - len(left_slice.rstrip("*"))
        r_out = len(line[core_b:]) - len(line[core_b:].lstrip("*"))
        out_pair = min(3 - in_pair, l_out, r_out)

        outer_a = core_a - out_pair
        outer_b = core_b + out_pair
        stars = min(3, in_pair + out_pair)
        new_stars = stars ^ bit
        core = line[core_a:core_b]
        wrap = "*" * new_stars
        new_line = line[:outer_a] + wrap + core + wrap + line[outer_b:]
        new_core_a = outer_a + new_stars
        return new_line, new_core_a, new_core_a + len(core)

    # Empty selection (a == b)
    pos = a
    left_slice = line[prose_start:pos]
    l_stars = len(left_slice) - len(left_slice.rstrip("*"))
    r_stars = len(line[pos:]) - len(line[pos:].lstrip("*"))
    if 1 <= l_stars <= 3 and l_stars == r_stars:
        # Cursor sits right inside an empty `*|*` / `**|**` / `***|***` pair
        new_stars = l_stars ^ bit
        outer_a = pos - l_stars
        outer_b = pos + r_stars
        wrap = "*" * new_stars
        new_line = line[:outer_a] + wrap + wrap + line[outer_b:]
        new_pos = outer_a + new_stars
        return new_line, new_pos, new_pos

    spans = _find_symmetric_marker_spans(line, "*", 1, 3, prose_start, code_spans)
    # Find the innermost enclosing span whose star-count either has `bit` set or matches
    enclosing = [
        sp for sp in spans if sp[1] <= pos <= sp[2] and (sp[4] & bit) != 0
    ]
    if enclosing:
        # Innermost span has largest inner_s
        open_s, inner_s, inner_e, close_e, stars = max(enclosing, key=lambda sp: sp[1])
        if pos == inner_e and inner_s < inner_e:
            # Streaming exit: jump past the `bit` closing stars (or all closing stars if equal)
            jump = bit if stars != bit else stars
            return line, pos + jump, pos + jump

        new_stars = stars ^ bit
        wrap = "*" * new_stars
        core = line[inner_s:inner_e]
        new_line = line[:open_s] + wrap + core + wrap + line[close_e:]
        new_pos = pos - (stars - new_stars)
        return new_line, new_pos, new_pos

    wrap = "*" * bit
    new_line = line[:pos] + wrap + wrap + line[pos:]
    return new_line, pos + bit, pos + bit


def toggle_inline_span(
    line: str, sel_start: int, sel_end: int, marker: str
) -> tuple[str, int, int]:
    """Toggle `marker` (`**`, `*`, `` ` ``, `~~`) on `line` for `[sel_start, sel_end]`."""
    a, b = (sel_start, sel_end) if sel_start <= sel_end else (sel_end, sel_start)
    a = max(0, min(a, len(line)))
    b = max(0, min(b, len(line)))

    if marker == "`":
        return _toggle_backtick(line, a, b)
    if marker == "~~":
        return _toggle_strikethrough(line, a, b)
    if marker == "**":
        return _toggle_asterisks(line, a, b, bit=2)
    if marker == "*":
        return _toggle_asterisks(line, a, b, bit=1)
    raise ValueError(f"Unsupported inline marker: {marker!r}")


def is_inside_link_destination(line: str, a: int, b: int) -> bool:
    """Return True if `[a, b]` lies inside `[...](...)` URL parentheses or `<...>` autolink."""
    for m in re.finditer(r"\]\(([^)\s]*)\)", line):
        dest_start, dest_end = m.start(1) - 1, m.end(1) + 1  # include `(` and `)`
        if dest_start < a and b < dest_end:
            return True
        if m.start(1) <= a and b <= m.end(1):
            return True
    for m in re.finditer(r"<(?:https?://|mailto:)[^>]*>", line):
        if m.start() <= a and b <= m.end():
            return True
    return False


def can_smart_paste_url(line: str, a: int, b: int, clipboard: str) -> bool:
    """Check whether pasting `clipboard` over `line[a:b]` should create `[text](url)`."""
    lo, hi = (a, b) if a <= b else (b, a)
    if lo == hi:
        return False
    if is_single_url(clipboard) is None:
        return False
    selected = line[lo:hi]
    if not selected or "\n" in selected or "\r" in selected:
        return False
    if is_single_url(selected) is not None:
        return False
    code_spans = find_code_spans(line, _prose_start_offset(line))
    if any(open_s <= lo < close_e or open_s < hi <= close_e for open_s, _, _, close_e in code_spans):
        return False
    if is_inside_link_destination(line, lo, hi):
        return False
    return True


def apply_smart_paste_url(
    line: str, a: int, b: int, clipboard: str
) -> tuple[str, int, int] | None:
    """Format `line[a:b]` + URL clipboard into `[text](url)` and place cursor after `)`."""
    lo, hi = (a, b) if a <= b else (b, a)
    if not can_smart_paste_url(line, lo, hi, clipboard):
        return None
    url = is_single_url(clipboard)
    assert url is not None
    selected = line[lo:hi]
    replacement = f"[{selected}]({url})"
    new_line = line[:lo] + replacement + line[hi:]
    end_pos = lo + len(replacement)
    return new_line, end_pos, end_pos


def apply_insert_link(line: str, a: int, b: int) -> tuple[str, int, int]:
    """Insert or navigate `[text](url)` at `[a, b]` on `line`."""
    lo, hi = (a, b) if a <= b else (b, a)
    lo = max(0, min(lo, len(line)))
    hi = max(0, min(hi, len(line)))

    if lo == hi:
        pos = lo
        # Ergonomic step-through: if cursor is inside `[text|]()`, jump into `(|)`!
        m_text = re.search(r"\[[^\]]*\]\(\)", line)
        if m_text:
            close_bracket = line.find("](", m_text.start())
            if m_text.start() < pos <= close_bracket:
                paren_pos = close_bracket + 2
                return line, paren_pos, paren_pos
        # If cursor is right before closing `)` of `[text](url|)`, jump past `)`!
        if pos < len(line) and line[pos] == ")":
            before = line[:pos]
            if "](" in before and ")" not in before[before.rfind("](") :]:
                return line, pos + 1, pos + 1

        new_line = line[:pos] + "[]()" + line[pos:]
        return new_line, pos + 1, pos + 1

    selected = line[lo:hi]
    url = is_single_url(selected)
    if url is not None:
        replacement = f"[]({url})"
        new_line = line[:lo] + replacement + line[hi:]
        return new_line, lo + 1, lo + 1

    replacement = f"[{selected}]()"
    new_line = line[:lo] + replacement + line[hi:]
    url_cursor = lo + len(selected) + 3  # inside `(|)`
    return new_line, url_cursor, url_cursor
