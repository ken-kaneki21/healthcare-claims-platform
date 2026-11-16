import hashlib
import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace

from healthcare.ingest import CONTRACTS, Manifest, load


def fixture(rows, watermark=1, schema=2, tenant=3):
    payload = (",".join(CONTRACTS[schema]) + "\n" + "\n".join(rows) + "\n").encode()
    return Manifest(tenant, "claims", watermark, schema, "2025-12-01",
                    "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00",
                    len(rows), hashlib.sha256(payload).hexdigest()), payload


class IngestionTests(unittest.TestCase):
    def test_aliases_void_replay_and_interrupted_batch(self):
        with closing(sqlite3.connect(":memory:")) as db:
            first = fixture(["10,1,1,2026-01-01,900", "11,1,1,2026-01-01,200"])
            with self.assertRaisesRegex(RuntimeError, "interruption"):
                load(db, *first, interrupt_after=1)
            self.assertEqual(db.execute("SELECT count(*) FROM delivery").fetchone()[0], 0)
            self.assertEqual(load(db, *first), 2)
            self.assertEqual(load(db, *first), 0)
            self.assertEqual(load(db, *fixture(["10,1,2,2026-02-01,0"], watermark=2)), 1)
            self.assertEqual(db.execute("SELECT replacement_cents FROM delivery WHERE claim_id=10 "
                                        "ORDER BY version DESC LIMIT 1").fetchone()[0], 0)
            with self.assertRaisesRegex(ValueError, "conflicting payloads"):
                load(db, *fixture(["10,1,1,2026-01-01,999"], watermark=3))
            self.assertEqual(db.execute("SELECT max(watermark) FROM batch").fetchone()[0], 2)

    def test_bad_schema_counts_checksum_and_reference(self):
        with closing(sqlite3.connect(":memory:")) as db:
            manifest, payload = fixture(["10,1,1,2026-01-01,900"])
            with self.assertRaisesRegex(ValueError, "checksum"):
                load(db, manifest, payload + b"x")
            with self.assertRaisesRegex(ValueError, "columns"):
                load(db, replace(manifest, schema_version=1), payload)
            with self.assertRaisesRegex(ValueError, "Record count"):
                load(db, replace(manifest, records=2), payload)
            db.executescript("CREATE TABLE claim(id, client_id); INSERT INTO claim VALUES(10,1);")
            with self.assertRaisesRegex(ValueError, "outside the tenant"):
                load(db, manifest, payload, reference=db)
