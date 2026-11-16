import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from build_platform import build


class FeatureTimingTests(unittest.TestCase):
    def test_late_historical_correction_cannot_change_features(self):
        try:
            import numpy as np

            from train_cost import cohort
        except ImportError:
            self.skipTest("Install NumPy for point-in-time checks")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.db"
            build(source, 100, 42)
            with closing(sqlite3.connect(source)) as db:
                original = cohort(db, 21)
                claim_id = db.execute(
                    "SELECT id FROM claim WHERE month_id=19 LIMIT 1"
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO payment_event VALUES (?,1,99,'2025-09-30','2025-09-30',999999)",
                    (claim_id,),
                )
                np.testing.assert_array_equal(original, cohort(db, 21))
                # An otherwise identical correction available before the cutoff must affect features.
                db.execute(
                    "UPDATE payment_event SET received_date='2025-08-31' WHERE claim_id=? AND version=99",
                    (claim_id,),
                )
                adjusted = cohort(db, 21)
                self.assertFalse(np.array_equal(original[:, 2:-1], adjusted[:, 2:-1]))
                np.testing.assert_array_equal(original[:, -1], adjusted[:, -1])
