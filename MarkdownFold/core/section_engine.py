"""Markdown heading & hierarchical section parser (pure Python).

Parses ATX headings (H1-H6) and Setext headings (H1-H2) while ignoring fenced
code blocks, YAML/TOML frontmatter, HTML comments, blockquotes, and lists.
Computes exact character-offset fold ranges for each heading including all
nested subheadings, optionally preserving trailing blank lines outside the fold.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_ATX_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_ATX_TRAILING_HASH_RE = re.compile(r"(?:^|[ \t]+)#+$")
_SETEXT_UNDERLINE_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_LIST_OR_QUOTE_RE = re.compile(r"^ {0,3}(?:>|[-+*](?:[ \t]+|$)|\d{1,9}[.)](?:[ \t]+|$))")


@dataclass(frozen=True)
class HeadingSection:
    """A Markdown heading and its hierarchical foldable section."""

    row: int
    header_end_row: int
    level: int
    title: str
    is_setext: bool
    line_start: int
    fold_start: int
    fold_end: int | None  # None when section has no non-blank body to fold
    end_row: int  # Last row included in the folded body (== header_end_row if empty)

    @property
    def foldable(self) -> bool:
        return self.fold_end is not None and self.fold_end > self.fold_start

    @property
    def fold_range(self) -> tuple[int, int] | None:
        if not self.foldable or self.fold_end is None:
            return None
        return (self.fold_start, self.fold_end)

    @property
    def hidden_line_count(self) -> int:
        if not self.foldable:
            return 0
        return max(0, self.end_row - self.header_end_row)


def _compute_line_offsets(lines: list[str]) -> tuple[list[int], list[int]]:
    """Return `(line_starts, line_ends)` where `line_ends[i]` is before `\\n`."""
    starts: list[int] = []
    ends: list[int] = []
    pos = 0
    for i, line in enumerate(lines):
        starts.append(pos)
        end = pos + len(line)
        ends.append(end)
        pos = end + (1 if i < len(lines) - 1 else 0)
    return starts, ends


def _clean_atx_title(raw: str | None) -> str:
    if not raw:
        return ""
    stripped = raw.strip()
    # CommonMark optional closing hash sequence preceded by space/tab (or whole string of #)
    cleaned = _ATX_TRAILING_HASH_RE.sub("", stripped).strip()
    return cleaned


def _detect_frontmatter_end(lines: list[str]) -> int:
    """If lines start with YAML (`---`) or TOML (`+++`) frontmatter, return its closing row.

    Returns -1 when no valid frontmatter block exists.
    """
    if not lines:
        return -1
    first = lines[0].rstrip(" \t")
    if first == "---":
        closers = ("---", "...")
    elif first == "+++":
        closers = ("+++",)
    else:
        return -1

    for idx in range(1, len(lines)):
        if lines[idx].rstrip(" \t") in closers:
            return idx
    return -1


def _can_be_setext_text(line: str) -> bool:
    if not line.strip():
        return False
    # 4+ leading spaces or leading tab = indented code block
    if line.startswith("\t") or line.startswith("    "):
        return False
    if _ATX_HEADING_RE.match(line):
        return False
    if _LIST_OR_QUOTE_RE.match(line):
        return False
    if _THEMATIC_BREAK_RE.match(line):
        return False
    if _FENCE_OPEN_RE.match(line):
        return False
    return True


def parse_sections(
    text: str,
    *,
    keep_trailing_blank_lines: bool = True,
) -> list[HeadingSection]:
    """Parse Markdown text and return all headings with their hierarchical fold ranges."""
    if not text:
        return []

    lines = text.split("\n")
    line_starts, line_ends = _compute_line_offsets(lines)
    total_lines = len(lines)

    raw_headings: list[tuple[int, int, int, str, bool]] = []
    # Each entry: (row, header_end_row, level, title, is_setext)

    fm_end = _detect_frontmatter_end(lines)
    i = fm_end + 1 if fm_end >= 0 else 0

    fence_char: str | None = None
    fence_len = 0
    in_html_comment = False

    while i < total_lines:
        line = lines[i]

        # 1. Inside fenced code block
        if fence_char is not None:
            m_close = re.match(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$", line)
            if m_close:
                fence_char = None
                fence_len = 0
            i += 1
            continue

        # 2. Inside multi-line HTML comment
        if in_html_comment:
            if "-->" in line:
                in_html_comment = False
            i += 1
            continue

        # 3. Check opening HTML comment on non-heading line
        stripped = line.lstrip(" ")
        leading_spaces = len(line) - len(stripped)
        if leading_spaces <= 3 and stripped.startswith("<!--"):
            if "-->" not in stripped[4:]:
                in_html_comment = True
            i += 1
            continue

        # 4. Check opening fenced code block
        m_fence = _FENCE_OPEN_RE.match(line)
        if m_fence:
            marker = m_fence.group(1)
            info = m_fence.group(2)
            # CommonMark: backtick fence info string cannot contain backticks
            if marker[0] == "~" or "`" not in info:
                fence_char = marker[0]
                fence_len = len(marker)
                i += 1
                continue

        # 5. ATX Heading
        if not line.startswith("\t") and not line.startswith("    "):
            m_atx = _ATX_HEADING_RE.match(line)
            if m_atx:
                hashes = m_atx.group(1)
                raw_rest = m_atx.group(2)
                # Ensure `#foo` (no space after hashes unless EOL) is NOT matched:
                # _ATX_HEADING_RE already requires [ \t]+ or EOL after hashes!
                level = len(hashes)
                title = _clean_atx_title(raw_rest)
                raw_headings.append((i, i, level, title, False))
                i += 1
                continue

            # 6. Setext Heading (lookahead next line)
            if i + 1 < total_lines and _can_be_setext_text(line):
                m_setext = _SETEXT_UNDERLINE_RE.match(lines[i + 1])
                if m_setext:
                    underline = m_setext.group(1)
                    level = 1 if underline[0] == "=" else 2
                    title = line.strip()
                    raw_headings.append((i, i + 1, level, title, True))
                    i += 2
                    continue

        i += 1

    # Compute hierarchical fold ranges for each heading
    sections: list[HeadingSection] = []
    count = len(raw_headings)

    for idx, (row, header_end_row, level, title, is_setext) in enumerate(raw_headings):
        # Next heading with level <= current level terminates this section
        raw_end_row = total_lines - 1
        for next_idx in range(idx + 1, count):
            next_row, _, next_level, _, _ = raw_headings[next_idx]
            if next_level <= level:
                raw_end_row = next_row - 1
                break

        end_row = raw_end_row
        if keep_trailing_blank_lines:
            while end_row > header_end_row and lines[end_row].strip() == "":
                end_row -= 1

        fold_start = line_ends[header_end_row]
        if end_row > header_end_row:
            fold_end: int | None = line_ends[end_row]
        else:
            fold_end = None
            end_row = header_end_row

        sections.append(
            HeadingSection(
                row=row,
                header_end_row=header_end_row,
                level=level,
                title=title,
                is_setext=is_setext,
                line_start=line_starts[row],
                fold_start=fold_start,
                fold_end=fold_end,
                end_row=end_row,
            )
        )

    return sections


def find_enclosing_section(
    sections: list[HeadingSection],
    row: int,
) -> HeadingSection | None:
    """Return the innermost heading section covering `row` (heading line or body).

    If `row` is directly on a heading line, returns that heading (even if not
    foldable, so callers can decide whether to no-op). Otherwise returns the
    deepest heading whose `[row .. end_row]` (or raw extent up to the next
    equal/higher heading) encloses `row`.
    """
    if not sections:
        return None

    # Exact match on a heading's own lines
    for sec in sections:
        if sec.row <= row <= sec.header_end_row:
            return sec

    # Find last heading starting before `row`
    candidate: HeadingSection | None = None
    for sec in sections:
        if sec.row > row:
            break
        if sec.foldable and sec.row <= row <= sec.end_row:
            # Prefer the innermost (most recent / highest row) enclosing foldable section
            candidate = sec

    if candidate is not None:
        return candidate

    # Fallback: if row is on a trailing blank line right after a section's last non-blank line,
    # still find the nearest preceding foldable section before any equal/higher boundary.
    preceding = [s for s in sections if s.row < row]
    if not preceding:
        return None
    for sec in reversed(preceding):
        if sec.foldable:
            # Verify no heading of level <= sec.level occurred between sec.row and row
            blocked = any(
                other.row > sec.row and other.row <= row and other.level <= sec.level
                for other in sections
            )
            if not blocked:
                return sec
    return None


def find_active_fold_for_section(
    section: HeadingSection,
    active_folds: list[tuple[int, int]],
) -> tuple[int, int] | None:
    """Return the active folded range `(a, b)` that collapses `section`, if any.

    Matches by `a == section.fold_start` rather than exact `(fold_start, fold_end)`
    so that typing new headings or prose AFTER a folded section keeps the folded
    section recognized as collapsed!
    """
    target_start = section.fold_start
    for a, b in active_folds:
        if a == target_start and b > a:
            return (a, b)
    return None


def is_section_hidden_inside_fold(
    section: HeadingSection,
    active_folds: list[tuple[int, int]],
) -> bool:
    """Return True if `section`'s heading line itself lies inside an active fold."""
    pt = section.line_start
    for a, b in active_folds:
        if a < pt < b:
            return True
    return False
