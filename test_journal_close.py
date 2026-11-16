import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from build_platform import build
from healthcare.ingest import load, replay_feed
from healthcare.journal_close import rebuild
from test_v2_ingest import fixture


class JournalCloseTests(unittest.TestCase):
    def test_replay_reproduces_two_frozen_closes_and_incomplete_feed_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, journal, output = (
                root / name for name in ("source.db", "journal.db", "close.db")
            )
            baseline = build(source, 100, 42, tenants=3)
            replay_feed(source, journal, 1, 200)
            with self.assertRaisesRegex(RuntimeError, "ledger"):
                rebuild(source, journal, output)
            self.assertFalse(output.exists())
            replay_feed(source, journal, 2, 200)
            replay_feed(source, journal, 3, 200)
            with closing(sqlite3.connect(journal)) as db:
                self.assertIn(
                    '"schema_version": 2',
                    db.execute("SELECT manifest FROM batch WHERE tenant=3").fetchone()[
                        0
                    ],
                )
            self.assertEqual(
                replay_feed(source, journal, 1, 200)["inserted_versions"], 0
            )
            results = rebuild(source, journal, output)["closes"]
            self.assertEqual(
                [row["paid_cents"] for row in results],
                [row["paid_cents"] for row in baseline["closes"]],
            )
            with closing(sqlite3.connect(output)) as db:
                db.execute("ATTACH DATABASE ? AS baseline", (str(source),))
                for left, right in (("main", "baseline"), ("baseline", "main")):
                    self.assertIsNone(
                        db.execute(
                            f"SELECT * FROM {left}.close_fact EXCEPT SELECT * FROM {right}.close_fact"
                        ).fetchone()
                    )

    def test_quarantine_survives_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "journal.db"
            with closing(sqlite3.connect(journal)) as db, self.assertRaises(ValueError):
                load(db, *fixture(["10,1,1,2026-01-01,100", "11,1,1,2026-01-01,-1"]))
            with closing(sqlite3.connect(journal)) as db:
                self.assertEqual(
                    db.execute("SELECT reason FROM quarantine").fetchone()[0],
                    "Invalid claim key or replacement amount",
                )
                self.assertEqual(
                    db.execute("SELECT count(*) FROM delivery").fetchone()[0], 0
                )
