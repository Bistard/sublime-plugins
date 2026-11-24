"""Cross-reopen fold state persistence & resilient anchor matching (pure Python).

Serializes active and nested-remembered folds as heading anchors `(level, title,
occurrence, row)` or fallback line ranges `(start_row, end_row, start_text)` so
folds restore cleanly even when a file has been lightly edited externally.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

from .section_engine import HeadingSection, parse_sections

SCHEMA_VERSION = 1
DEFAULT_MAX_FILES = 500


def normalize_file_key(path: str) -> str:
    """Canonicalize a file path as a stable dictionary key."""
    return os.path.normcase(os.path.abspath(path))


def _line_index_at(line_starts: list[int], pt: int) -> int:
    lo, hi = 0, len(line_starts) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if line_starts[mid] <= pt:
            lo = mid + 1
        else:
            hi = mid - 1
    return max(0, hi)


def _compute_line_starts(lines: list[str]) -> list[int]:
    starts: list[int] = []
    pos = 0
    for i, line in enumerate(lines):
        starts.append(pos)
        pos += len(line) + (1 if i < len(lines) - 1 else 0)
    return starts


def _occurrence_index(sections: list[HeadingSection], target: HeadingSection) -> int:
    occ = 0
    for sec in sections:
        if sec.row == target.row:
            return occ
        if sec.level == target.level and sec.title == target.title:
            occ += 1
    return occ


def serialize_fold_state(
    text: str,
    active_folds: list[tuple[int, int]],
    remembered_folds: list[tuple[int, int]] | None = None,
    *,
    keep_trailing_blank_lines: bool = True,
) -> dict[str, Any]:
    """Convert live buffer fold regions into portable JSON-serializable records."""
    sections = parse_sections(text, keep_trailing_blank_lines=keep_trailing_blank_lines)
    by_fold_start = {sec.fold_start: sec for sec in sections}
    lines = text.split("\n")
    line_starts = _compute_line_starts(lines)

    def encode_region(region: tuple[int, int]) -> dict[str, Any]:
        a, b = min(region[0], region[1]), max(region[0], region[1])
        sec = by_fold_start.get(a)
        if sec is not None:
            return {
                "kind": "heading",
                "level": sec.level,
                "title": sec.title,
                "occ": _occurrence_index(sections, sec),
                "row": sec.row,
            }
        start_row = _line_index_at(line_starts, a)
        end_row = _line_index_at(line_starts, max(a, b - 1))
        return {
            "kind": "range",
            "start_row": start_row,
            "end_row": end_row,
            "start_col": a - line_starts[start_row],
            "end_col": b - line_starts[end_row],
            "start_text": lines[start_row].strip() if start_row < len(lines) else "",
        }

    return {
        "updated_at": int(time.time()),
        "active": [encode_region(r) for r in active_folds if r[0] != r[1]],
        "remembered": [
            encode_region(r) for r in (remembered_folds or []) if r[0] != r[1]
        ],
    }


def resolve_saved_folds(
    entry: dict[str, Any],
    text: str,
    *,
    keep_trailing_blank_lines: bool = True,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Match a saved persistence entry against current file text.

    Returns `(active_regions, remembered_regions)` as `(a, b)` offset tuples.
    Unmatched or stale records are safely skipped.
    """
    if not text or not isinstance(entry, dict):
        return [], []

    sections = parse_sections(text, keep_trailing_blank_lines=keep_trailing_blank_lines)
    lines = text.split("\n")
    line_starts = _compute_line_starts(lines)

    # Group foldable sections by `(level, title)`
    by_key: dict[tuple[int, str], list[HeadingSection]] = {}
    for sec in sections:
        by_key.setdefault((sec.level, sec.title), []).append(sec)

    def decode_record(rec: dict[str, Any]) -> tuple[int, int] | None:
        if not isinstance(rec, dict):
            return None
        kind = rec.get("kind")
        if kind == "heading":
            level = rec.get("level")
            title = rec.get("title")
            if not isinstance(level, int) or not isinstance(title, str):
                return None
            candidates = by_key.get((level, title))
            if not candidates:
                return None
            occ = rec.get("occ", 0)
            saved_row = rec.get("row", 0)
            chosen: HeadingSection | None = None
            if isinstance(occ, int) and 0 <= occ < len(candidates):
                chosen = candidates[occ]
            else:
                chosen = min(candidates, key=lambda s: abs(s.row - int(saved_row or 0)))
            return chosen.fold_range if chosen and chosen.foldable else None

        if kind == "range":
            start_row = rec.get("start_row")
            end_row = rec.get("end_row")
            start_text = rec.get("start_text", "")
            if not isinstance(start_row, int) or not isinstance(end_row, int):
                return None
            if not (0 <= start_row < end_row < len(lines)):
                return None
            if lines[start_row].strip() != str(start_text).strip():
                return None
            start_col = rec.get("start_col")
            end_col = rec.get("end_col")
            line_a_len = len(lines[start_row])
            line_b_len = len(lines[end_row])
            col_a = start_col if isinstance(start_col, int) and 0 <= start_col <= line_a_len else line_a_len
            col_b = end_col if isinstance(end_col, int) and 0 <= end_col <= line_b_len else line_b_len
            a = line_starts[start_row] + col_a
            b = line_starts[end_row] + col_b
            return (a, b) if b > a else None

        return None

    active: list[tuple[int, int]] = []
    for rec in entry.get("active", []):
        resolved = decode_record(rec)
        if resolved is not None:
            active.append(resolved)

    remembered: list[tuple[int, int]] = []
    for rec in entry.get("remembered", []):
        resolved = decode_record(rec)
        if resolved is not None:
            remembered.append(resolved)

    return active, remembered


class FoldPersistenceStore:
    """JSON-backed LRU persistence store with atomic writes."""

    def __init__(self, store_path: str, *, max_files: int = DEFAULT_MAX_FILES) -> None:
        self.store_path = store_path
        self.max_files = max(1, max_files)
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def load(self) -> None:
        self._loaded = True
        if not os.path.exists(self.store_path):
            self._data = {}
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict) and raw.get("version") == SCHEMA_VERSION:
                files = raw.get("files")
                if isinstance(files, dict):
                    self._data = {
                        str(k): v for k, v in files.items() if isinstance(v, dict)
                    }
                    return
        except (OSError, ValueError, TypeError):
            pass
        self._data = {}

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get(self, file_path: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        return self._data.get(normalize_file_key(file_path))

    def set(self, file_path: str, entry: dict[str, Any]) -> None:
        self._ensure_loaded()
        key = normalize_file_key(file_path)
        has_any = bool(entry.get("active") or entry.get("remembered"))
        if not has_any:
            if key in self._data:
                del self._data[key]
                self.flush()
            return
        self._data[key] = entry
        self._prune()
        self.flush()

    def remove(self, file_path: str) -> None:
        self._ensure_loaded()
        key = normalize_file_key(file_path)
        if key in self._data:
            del self._data[key]
            self.flush()

    def _prune(self) -> None:
        if len(self._data) <= self.max_files:
            return
        ordered = sorted(
            self._data.items(),
            key=lambda kv: int(kv[1].get("updated_at", 0)),
            reverse=True,
        )
        self._data = dict(ordered[: self.max_files])

    def flush(self) -> None:
        parent = os.path.dirname(self.store_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        payload = {"version": SCHEMA_VERSION, "files": self._data}
        fd, tmp_path = tempfile.mkstemp(prefix="folds_", suffix=".tmp", dir=parent or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.store_path)
        except OSError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
