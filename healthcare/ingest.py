"""Atomic manifest-driven delivery loading into a local append-only journal."""

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

FIELDS = ("claim_id", "line_no", "version", "received_date", "replacement_cents")
CONTRACTS = {
    1: FIELDS,
    2: (
        "claim_ref",
        "service_line",
        "revision_number",
        "arrival_day",
        "net_paid_cents",
    ),
}
DDL = """
CREATE TABLE IF NOT EXISTS batch(
    tenant INTEGER, source TEXT, watermark INTEGER, manifest TEXT NOT NULL,
    PRIMARY KEY(tenant,source,watermark)
);
CREATE TABLE IF NOT EXISTS delivery(
    tenant INTEGER, claim_id INTEGER, line_no INTEGER, version INTEGER,
    received_date TEXT NOT NULL, replacement_cents INTEGER NOT NULL,
    source TEXT NOT NULL, watermark INTEGER NOT NULL,
    PRIMARY KEY(tenant,claim_id,line_no,version)
);
"""


@dataclass(frozen=True)
class Manifest:
    tenant: int
    source: str
    watermark: int
    schema_version: int
    period: str
    effective_at: str
    received_at: str
    records: int
    sha256: str


def load(
    db,
    manifest: Manifest,
    payload: bytes,
    *,
    reference: sqlite3.Connection | None = None,
    interrupt_after: int | None = None,
):
    if manifest.tenant < 1 or not manifest.source.strip() or manifest.watermark < 1:
        raise ValueError("Invalid tenant, source, or watermark")
    columns = CONTRACTS.get(manifest.schema_version)
    if columns is None:
        raise ValueError("Unknown source schema version")
    if hashlib.sha256(payload).hexdigest() != manifest.sha256:
        raise ValueError("Payload checksum mismatch")
    if date.fromisoformat(manifest.period).day != 1:
        raise ValueError("Period must be the first day of a month")
    effective, arrived = (
        datetime.fromisoformat(value)
        for value in (manifest.effective_at, manifest.received_at)
    )
    if effective.tzinfo is None or arrived.tzinfo is None or effective > arrived:
        raise ValueError("Manifest timestamps must be ordered and timezone-aware")
    rows = csv.reader(io.StringIO(payload.decode("utf-8"), newline=""), strict=True)
    if tuple(next(rows, ())) != columns:
        raise ValueError("Unexpected source columns")
    db.executescript(DDL)
    key = (manifest.tenant, manifest.source, manifest.watermark)
    serialized = json.dumps(asdict(manifest), sort_keys=True)
    with db:
        db.execute("BEGIN IMMEDIATE")
        stored = db.execute(
            "SELECT manifest FROM batch WHERE tenant=? AND source=? AND watermark=?",
            key,
        ).fetchone()
        if stored:
            if stored[0] != serialized:
                raise ValueError("Replay manifest differs from committed batch")
            return 0
        previous = db.execute(
            "SELECT coalesce(max(watermark),0) FROM batch WHERE tenant=? AND source=?",
            key[:2],
        ).fetchone()[0]
        if manifest.watermark != previous + 1:
            raise ValueError("Missing or out-of-order watermark")
        count = inserted = 0
        for count, row in enumerate(rows, 1):
            claim, line, revision, received, cents = row
            ids = (int(claim), int(line), int(revision))
            if min(ids) < 1 or int(cents) < 0:
                raise ValueError("Invalid claim key or replacement amount")
            received = date.fromisoformat(received).isoformat()
            if (
                reference is not None
                and not reference.execute(
                    "SELECT 1 FROM claim WHERE id=? AND client_id=?",
                    (ids[0], manifest.tenant),
                ).fetchone()
            ):
                raise ValueError("Claim reference is outside the tenant or absent")
            delivery_key = (manifest.tenant, *ids)
            values = (received, int(cents))
            existing = db.execute(
                "SELECT received_date,replacement_cents FROM delivery "
                "WHERE tenant=? AND claim_id=? AND line_no=? AND version=?",
                delivery_key,
            ).fetchone()
            if existing and tuple(existing) != values:
                raise ValueError("Same claim version has conflicting payloads")
            if existing is None:
                db.execute(
                    "INSERT INTO delivery VALUES (?,?,?,?,?,?,?,?)",
                    (*delivery_key, *values, manifest.source, manifest.watermark),
                )
                inserted += 1
            if interrupt_after == count:
                raise RuntimeError("Simulated interruption")
        if count != manifest.records:
            raise ValueError("Record count does not match manifest")
        db.execute("INSERT INTO batch VALUES (?,?,?,?)", (*key, serialized))
    return inserted


def load_files(
    database: Path,
    manifest_file: Path,
    csv_file: Path,
    reference_path: Path | None = None,
):
    from contextlib import ExitStack, closing

    manifest = Manifest(**json.loads(manifest_file.read_text(encoding="utf-8")))
    with ExitStack() as stack:
        db = stack.enter_context(closing(sqlite3.connect(database)))
        reference = (
            None
            if reference_path is None
            else stack.enter_context(
                closing(
                    sqlite3.connect(
                        f"{reference_path.resolve().as_uri()}?mode=ro", uri=True
                    )
                )
            )
        )
        return load(db, manifest, csv_file.read_bytes(), reference=reference)


def replay_feed(
    reference_path: Path, journal: Path, tenant: int, batch_size: int = 10_000
):
    """Read generated delivery pages in source-ID order and commit each manifest atomically."""
    if not 1 <= batch_size <= 50_000:
        raise ValueError("Batch size must be between 1 and 50,000")
    journal.parent.mkdir(parents=True, exist_ok=True)
    cutoff = "2026-03-31T23:59:59+00:00"
    last_id = watermark = count = inserted = 0
    with (
        closing(
            sqlite3.connect(f"{reference_path.resolve().as_uri()}?mode=ro", uri=True)
        ) as source,
        closing(sqlite3.connect(journal)) as target,
    ):
        while True:
            rows = source.execute(
                """
                SELECT d.id,d.claim_id,d.line_no,d.version,d.received_date,d.replacement_cents
                FROM claim_delivery d JOIN claim c ON c.id=d.claim_id
                WHERE d.id>? AND c.client_id=? ORDER BY d.id LIMIT ?
            """,
                (last_id, tenant, batch_size),
            ).fetchall()
            if not rows:
                break
            watermark += 1
            last_id = rows[-1][0]
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            writer.writerow(FIELDS)
            writer.writerows(row[1:] for row in rows)
            payload = stream.getvalue().encode()
            manifest = Manifest(
                tenant,
                f"synthetic-deliveries-{batch_size}",
                watermark,
                1,
                "2026-03-01",
                cutoff,
                cutoff,
                len(rows),
                hashlib.sha256(payload).hexdigest(),
            )
            inserted += load(target, manifest, payload, reference=source)
            count += len(rows)
    return {
        "tenant": tenant,
        "batches": watermark,
        "deliveries": count,
        "inserted_versions": inserted,
    }
