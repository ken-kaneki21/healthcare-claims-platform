import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path

from demo import SCHEMA, load_batch, run


class ClaimsTests(unittest.TestCase):
    def test_conflicting_delivery_rolls_back_batch(self):
        original = (1, 1, "SYN-000001", "2025-01-02", "2025-01-04", 0, 500)
        new = (2, *original[1:])
        conflict = (*original[:-1], 800)
        with closing(sqlite3.connect(":memory:")) as db:
            db.executescript(SCHEMA)
            self.assertEqual(load_batch(db, [], [original], 42, 2), 1)
            self.assertEqual(load_batch(db, [], [original], 42, 2), 0)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "conflicting payloads"):
                load_batch(db, [], [new, conflict], 42, 2)
            self.assertEqual(db.execute("SELECT * FROM feed").fetchall(), [original])

    def test_persistent_replay_and_as_of_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "claims.sqlite"
            initial = run(root / "initial", 1000, 42, "none", database=database)
            replay = run(root / "replay", 1000, 42, "none", database=database)
            later = run(root / "later", 1000, 42, "none", date(2025, 6, 30), database)
            self.assertTrue(initial["passed"] and replay["passed"] and later["passed"])
            self.assertEqual(initial["inserted_claim_versions"], 5238)
            self.assertEqual(replay["inserted_claim_versions"], 0)
            self.assertEqual(later["inserted_claim_versions"], 0)
            self.assertEqual(initial["actual_cents"], replay["actual_cents"])
            self.assertNotEqual(initial["actual_cents"], later["actual_cents"])
            with self.assertRaisesRegex(ValueError, "separate database"):
                run(root / "wrong-seed", 1000, 7, "none", database=database)

    def test_member_level_checks_detect_matching_total_faults(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for fault, mismatches in (("missing", 1), ("offsetting", 2)):
                with self.subTest(fault=fault):
                    result = run(root / fault, 1000, 42, fault)
                    self.assertFalse(result["passed"])
                    self.assertEqual(result["variance_cents"], 0)
                    self.assertEqual(result["mismatch_count"], mismatches)


if __name__ == "__main__":
    unittest.main()
