"""Publish a separate set of closes from committed journal deliveries."""

import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from time import perf_counter

from build_platform import materialize_closes


def rebuild(source: Path, journal: Path, output: Path):
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    start = perf_counter()
    with tempfile.TemporaryDirectory(dir=output.parent) as folder:
        work = Path(folder) / "close.sqlite"
        source_uri = source.resolve().as_uri() + "?mode=ro"
        journal_uri = journal.resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as original,
            closing(sqlite3.connect(work, uri=True)) as target,
        ):
            original.backup(target)
            target.execute("ATTACH DATABASE ? AS journal", (journal_uri,))
            target.executescript("""
                DROP VIEW restatement;
                DROP VIEW monthly_finance;
                DROP TABLE close_fact;
                DROP TABLE close_run;
                CREATE TEMP VIEW approved_delivery AS
                SELECT d.claim_id,d.line_no,d.version,d.received_date,d.replacement_cents
                FROM journal.delivery d
                JOIN journal.batch b USING(tenant,source,watermark)
                JOIN main.claim c ON c.id=d.claim_id AND c.client_id=d.tenant;
            """)
            checks = materialize_closes(target, from_journal=True)
            target.commit()
        work.rename(output)
    return {
        "close_source": "committed_journal",
        "closes": checks,
        "seconds": round(perf_counter() - start, 2),
    }
