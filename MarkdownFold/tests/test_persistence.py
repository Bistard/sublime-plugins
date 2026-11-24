import os
import tempfile
import unittest

from core.persistence import (
    FoldPersistenceStore,
    resolve_saved_folds,
    serialize_fold_state,
)
from core.section_engine import parse_sections


class TestPersistence(unittest.TestCase):
    def test_roundtrip_headings_and_nested_memory_after_external_insert(self):
        original = (
            "# Intro\n"
            "hello\n"
            "\n"
            "## Notes\n"
            "first notes\n"
            "\n"
            "# Work\n"
            "work intro\n"
            "\n"
            "## Notes\n"
            "second notes\n"
            "\n"
            "```python\n"
            "x = 1\n"
            "y = 2\n"
            "```\n"
        )
        sections = parse_sections(original)
        intro = sections[0]
        notes1 = sections[1]
        work = sections[2]
        notes2 = sections[3]

        # Fold Intro (with Notes#0 remembered) and Notes#1
        entry = serialize_fold_state(
            original,
            active_folds=[intro.fold_range, notes2.fold_range],  # type: ignore[list-item]
            remembered_folds=[notes1.fold_range],  # type: ignore[list-item]
        )

        # Simulate external edit: 3 lines prepended at top of file + extra text inside Work
        edited = (
            "Preamble line 1\n"
            "Preamble line 2\n"
            "\n"
            + original.replace("work intro\n", "work intro updated\nextra line\n")
        )
        active, remembered = resolve_saved_folds(entry, edited)
        edited_sections = parse_sections(edited)
        self.assertEqual(len(active), 2)
        self.assertEqual(len(remembered), 1)
        # First active fold matches Intro; second matches second "## Notes" (occ=1)
        self.assertEqual(active[0], edited_sections[0].fold_range)
        self.assertEqual(active[1], edited_sections[3].fold_range)
        # Remembered fold matches first "## Notes" (occ=0)
        self.assertEqual(remembered[0], edited_sections[1].fold_range)

    def test_non_heading_range_roundtrip_and_stale_guard(self):
        doc = (
            "# Title\n"
            "```python\n"
            "a = 1\n"
            "b = 2\n"
            "```\n"
        )
        fence_start = doc.index("```python") + len("```python")
        fence_end = doc.index("```\n") + 3
        entry = serialize_fold_state(doc, active_folds=[(fence_start, fence_end)])

        # Exact match restores cleanly
        active, _ = resolve_saved_folds(entry, doc)
        self.assertEqual(active, [(fence_start, fence_end)])

        # If line at start_row changed externally, stale range is safely skipped
        changed = "# Title\nnot a fence anymore\na = 1\nb = 2\n```\n"
        active2, _ = resolve_saved_folds(entry, changed)
        self.assertEqual(active2, [])

    def test_store_atomic_write_reload_and_lru_eviction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "folds_v1.json")
            store = FoldPersistenceStore(path, max_files=2)
            store.set(r"C:\docs\a.md", {"updated_at": 100, "active": [{"kind": "heading"}], "remembered": []})
            store.set(r"C:\docs\b.md", {"updated_at": 200, "active": [{"kind": "heading"}], "remembered": []})
            store.set(r"C:\docs\c.md", {"updated_at": 300, "active": [{"kind": "heading"}], "remembered": []})

            # Reload from disk in fresh instance
            reloaded = FoldPersistenceStore(path, max_files=2)
            self.assertIsNone(reloaded.get(r"C:\docs\a.md"))  # Evicted (oldest)
            self.assertIsNotNone(reloaded.get(r"C:\docs\b.md"))
            self.assertIsNotNone(reloaded.get(r"C:\docs\c.md"))

            # Setting empty active + remembered removes entry
            reloaded.set(r"C:\docs\b.md", {"updated_at": 400, "active": [], "remembered": []})
            reloaded2 = FoldPersistenceStore(path, max_files=2)
            self.assertIsNone(reloaded2.get(r"C:\docs\b.md"))

    def test_store_corrupt_json_recovers_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "folds_v1.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{corrupt json")
            store = FoldPersistenceStore(path)
            self.assertIsNone(store.get(r"C:\docs\x.md"))


if __name__ == "__main__":
    unittest.main()
