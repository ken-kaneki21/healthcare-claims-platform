import sqlite3
import unittest
from contextlib import closing

from healthcare.registry import load_bundle, register, transition


class RegistryTests(unittest.TestCase):
    def test_promotion_rejection_signature_and_rollback(self):
        key = "test-fixture-signing-key-only-12345"
        bundle = {
            "features": ["history"],
            "training_sha256": "a" * 64,
            "validation_sha256": "b" * 64,
            "baseline_validation_mae_usd": 20,
            "artifact": {
                "mean": [10],
                "scale": [1],
                "coefficients": [1],
                "intercept": 10,
            },
        }
        with closing(sqlite3.connect(":memory:")) as db:
            for name, score in (("v1", 15), ("v2", 13), ("bad", 24), ("worse", 14)):
                register(db, name, {**bundle, "validation_mae_usd": score}, key)
            self.assertEqual(transition(db, key, "v1")["version"], "v1")
            self.assertEqual(transition(db, key, "v2")["version"], "v2")
            for rejected in ("bad", "worse"):
                with self.assertRaisesRegex(ValueError, "did not beat"):
                    transition(db, key, rejected)
            self.assertEqual(
                transition(db, key), {"version": "v1", "action": "rollback"}
            )
            with db:
                db.execute("UPDATE model SET payload='tampered' WHERE version='v1'")
            with self.assertRaisesRegex(ValueError, "signature mismatch"):
                load_bundle(db, "v1", key)
