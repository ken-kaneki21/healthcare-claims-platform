"""Atomic manifest-driven delivery loading into a local append-only journal."""

import csv
import hashlib
import io
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime
from itertools import islice
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
CLIENT_SCHEMAS = {1: 1, 2: 1, 3: 2}
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
CREATE TABLE IF NOT EXISTS quarantine(
    id INTEGER PRIMARY KEY, tenant INTEGER, source TEXT, watermark INTEGER,
    payload_sha256 TEXT NOT NULL, reason TEXT NOT NULL,
    rejected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    db: sqlite3.Connection,
    manifest: Manifest,
    payload: bytes,
    *,
    reference: sqlite3.Connection | None = None,
    interrupt_after: int | None = None,
):
    db.executescript(DDL)
    try:
        return _load(
            db, manifest, payload, reference=reference, interrupt_after=interrupt_after
        )
    except (ValueError, csv.Error) as error:
        # Store the failure after rollback, without copying source rows into diagnostics.
        reason = (
            error.args[0]
            if error.args
            and error.args[0]
            in {
                "Invalid tenant, source, or watermark",
                "Unknown source schema version",
                "Payload checksum mismatch",
                "Period must be the first day of a month",
                "Manifest timestamps must be ordered and timezone-aware",
                "Unexpected source columns",
                "Replay manifest differs from committed batch",
                "Missing or out-of-order watermark",
                "Invalid claim key or replacement amount",
                "Claim reference is outside the tenant or absent",
                "Same claim version has conflicting payloads",
                "Record count does not match manifest",
            }
            else "Invalid CSV field, encoding, or timestamp"
        )
        with db:
            db.execute(
                "INSERT INTO quarantine(tenant,source,watermark,payload_sha256,reason) VALUES (?,?,?,?,?)",
                (
                    manifest.tenant,
                    manifest.source,
                    manifest.watermark,
                    hashlib.sha256(payload).hexdigest(),
                    reason,
                ),
            )
        raise


def _load(
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
        while chunk := list(islice(rows, 500)):
            batch = []
            for claim, line, revision, received, cents in chunk:
                ids = (int(claim), int(line), int(revision))
                amount = int(cents)
                if min(ids) < 1 or amount < 0 or max(*ids, amount) >= 2**63:
                    raise ValueError("Invalid claim key or replacement amount")
                received = date.fromisoformat(received).isoformat()
                batch.append((manifest.tenant, *ids, received, amount, *key[1:]))
            if reference is not None:
                claim_ids = {row[1] for row in batch}
                placeholders = ",".join("?" for _ in claim_ids)
                matched = reference.execute(
                    f"SELECT count(*) FROM claim WHERE client_id=? AND id IN ({placeholders})",
                    (manifest.tenant, *claim_ids),
                ).fetchone()[0]
                if matched != len(claim_ids):
                    raise ValueError("Claim reference is outside the tenant or absent")
            try:
                # Exact duplicates are no-ops. A differing payload deliberately
                # hits the NOT NULL constraint so the whole manifest rolls back.
                cursor = db.executemany(
                    """
                    INSERT INTO delivery VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(tenant,claim_id,line_no,version) DO UPDATE
                    SET replacement_cents=NULL
                    WHERE delivery.received_date<>excluded.received_date
                       OR delivery.replacement_cents<>excluded.replacement_cents
                    """,
                    batch,
                )
            except sqlite3.IntegrityError as error:
                if error.args != (
                    "NOT NULL constraint failed: delivery.replacement_cents",
                ):
                    raise
                raise ValueError(
                    "Same claim version has conflicting payloads"
                ) from error
            inserted += cursor.rowcount
            if interrupt_after is not None and count < interrupt_after <= count + len(
                batch
            ):
                raise RuntimeError("Simulated interruption")
            count += len(batch)
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
    reference_path: Path,
    journal: Path,
    tenant: int,
    batch_size: int = 10_000,
    *,
    max_batches: int | None = None,
):
    """Read generated delivery pages in source-ID order and commit each manifest atomically."""
    schema = CLIENT_SCHEMAS.get(tenant)
    if schema is None:
        raise ValueError("Unknown fictional tenant")
    if not 1 <= batch_size <= 50_000:
        raise ValueError("Batch size must be between 1 and 50,000")
    if max_batches is not None and max_batches < 1:
        raise ValueError("Max batches must be positive")
    journal.parent.mkdir(parents=True, exist_ok=True)
    cutoff = "2026-03-31T23:59:59+00:00"
    last_id = watermark = count = inserted = 0
    with (
        closing(
            sqlite3.connect(f"{reference_path.resolve().as_uri()}?mode=ro", uri=True)
        ) as source,
        closing(sqlite3.connect(journal)) as target,
    ):
        # Drive pagination from the delivery primary key. A regular JOIN can
        # start from the tenant index and sort the remaining deliveries per page.
        while max_batches is None or watermark < max_batches:
            rows = source.execute(
                """
                SELECT d.id,d.claim_id,d.line_no,d.version,d.received_date,d.replacement_cents
                FROM claim_delivery d CROSS JOIN claim c ON c.id=d.claim_id
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
            writer.writerow(CONTRACTS[schema])
            writer.writerows(row[1:] for row in rows)
            payload = stream.getvalue().encode()
            manifest = Manifest(
                tenant,
                f"synthetic-deliveries-{batch_size}",
                watermark,
                schema,
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
