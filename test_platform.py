import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from build_platform import build
from financial_tools import answer, evaluate


class PlatformTests(unittest.TestCase):
    def test_two_closes_and_scoped_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / "platform.sqlite"
            evidence = build(database, 100, 42)
            original, revised = evidence["closes"]
            self.assertEqual(original["rows"], evidence["rows"]["member_month"])
            self.assertEqual(revised["rows"], original["rows"])
            self.assertEqual((original["ledger_differences"], revised["ledger_differences"]), (0,0))
            self.assertNotEqual(original["paid_cents"], revised["paid_cents"])
            with self.assertRaises(FileExistsError):
                build(database, 100, 42)
            with closing(sqlite3.connect(database)) as db:
                self.assertGreater(evaluate(db)["financial_cases"], 0)
                self.assertEqual(answer(db, 3, "close", "2025-12-01")["status"], "no_evidence")
                north = answer(db, 1, "close", "2025-12-01")
                south = answer(db, 2, "close", "2025-12-01")
                self.assertEqual(north["evidence"]["client_id"], 1)
                self.assertNotEqual(north["values"], south["values"])


if __name__ == "__main__":
    unittest.main()
