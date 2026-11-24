"""Nested fold memory engine (pure Python).

Tracks inner folded regions absorbed when an outer heading section is folded,
and computes which maximal inner regions should be restored when the outer
section is later unfolded — supporting arbitrary nesting depth (H1 -> H2 -> ...
-> H6 + code blocks).
"""

from __future__ import annotations

Interval = tuple[int, int]


def normalize_intervals(intervals: list[Interval]) -> list[Interval]:
    """Return sorted, deduplicated non-empty `(a, b)` intervals with `a < b`."""
    cleaned = {(min(a, b), max(a, b)) for a, b in intervals if a != b}
    return sorted(cleaned, key=lambda r: (r[0], -r[1]))


def strictly_contained(inner: Interval, outer: Interval) -> bool:
    """Return True if `inner` lies inside `outer` and is not identical to `outer`."""
    ia, ib = inner
    oa, ob = outer
    return oa <= ia and ib <= ob and inner != outer


def select_maximal_intervals(intervals: list[Interval]) -> list[Interval]:
    """Keep only outermost intervals that are not strictly contained in another."""
    ordered = normalize_intervals(intervals)
    maximal: list[Interval] = []
    for candidate in ordered:
        if any(strictly_contained(candidate, kept) for kept in maximal):
            continue
        maximal.append(candidate)
    return maximal


def capture_absorbed_folds(
    outer: Interval,
    prev_active: list[Interval],
    remembered: list[Interval],
) -> list[Interval]:
    """Update remembered nested folds when `outer` is newly folded.

    Any previously active fold strictly contained within `outer` is added to
    the remembered pool (while keeping any even deeper already-remembered folds).
    """
    oa, ob = min(outer[0], outer[1]), max(outer[0], outer[1])
    outer_norm = (oa, ob)
    pool = set(normalize_intervals(remembered))
    # Remove any remembered entry equal to outer itself (since outer is now active)
    pool.discard(outer_norm)

    for prev in normalize_intervals(prev_active):
        if strictly_contained(prev, outer_norm):
            pool.add(prev)

    return normalize_intervals(list(pool))


def pop_restorable_children(
    unfolded: Interval,
    remembered: list[Interval],
    current_active: list[Interval],
) -> tuple[list[Interval], list[Interval]]:
    """Compute `(to_refold, remaining_remembered)` when `unfolded` expands.

    - Finds all remembered intervals strictly contained inside `unfolded` that
      are not already contained in some still-active fold.
    - Returns the maximal (outermost) subset as `to_refold` so direct folded
      children are restored while deeper grandchildren remain in
      `remaining_remembered` for when those children are later unfolded.
    """
    ua, ub = min(unfolded[0], unfolded[1]), max(unfolded[0], unfolded[1])
    unfolded_norm = (ua, ub)
    active_norm = normalize_intervals(current_active)
    rem_norm = normalize_intervals(remembered)

    candidates: list[Interval] = []
    others: list[Interval] = []

    for r in rem_norm:
        if r == unfolded_norm:
            continue
        if strictly_contained(r, unfolded_norm):
            # Ignore if already hidden inside another still-active fold
            if any(a <= r[0] and r[1] <= b for a, b in active_norm):
                others.append(r)
            else:
                candidates.append(r)
        else:
            others.append(r)

    to_refold = select_maximal_intervals(candidates)
    refold_set = set(to_refold)

    # Deeper grandchildren stay remembered for subsequent unfolds
    remaining = others + [r for r in candidates if r not in refold_set]
    return to_refold, normalize_intervals(remaining)


def _overlaps(r1: Interval, r2: Interval) -> bool:
    return r1[0] < r2[1] and r2[0] < r1[1]


def diff_fold_transitions(
    prev_active: list[Interval],
    curr_active: list[Interval],
) -> tuple[list[Interval], list[Interval], list[Interval]]:
    """Return `(newly_folded, absorbed_prev, newly_unfolded)` between fold snapshots.

    Uses overlap detection so that editing a folded heading's visible title
    (which can cause Sublime's tracked `HIDDEN` region to widen slightly at its
    start while the real fold shifts right) is NOT misclassified as an unfold.
    """
    prev_norm = normalize_intervals(prev_active)
    curr_norm = normalize_intervals(curr_active)

    newly_folded: list[Interval] = []
    absorbed_prev: list[Interval] = []
    newly_unfolded: list[Interval] = []

    for c in curr_norm:
        # Newly folded if it wasn't identical to a previous fold and strictly contains
        # at least one previous fold or didn't overlap any previous fold
        if not any(_overlaps(c, p) for p in prev_norm) or any(
            strictly_contained(p, c) for p in prev_norm
        ):
            newly_folded.append(c)

    for p in prev_norm:
        if any(strictly_contained(p, c) for c in curr_norm):
            absorbed_prev.append(p)
        elif not any(_overlaps(p, c) for c in curr_norm):
            newly_unfolded.append(p)

    return (
        normalize_intervals(newly_folded),
        normalize_intervals(absorbed_prev),
        normalize_intervals(newly_unfolded),
    )
