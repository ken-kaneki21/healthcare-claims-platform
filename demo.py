"""Generate fictional source files and reconcile a claims migration in SQLite."""
import argparse
import csv
import json
import random
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

SCHEMA = """
    CREATE TABLE IF NOT EXISTS dataset_config(
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1), seed INTEGER, members INTEGER
    );
    CREATE TABLE IF NOT EXISTS eligibility(
        member TEXT, month TEXT, PRIMARY KEY(member, month)
    );
    CREATE TABLE IF NOT EXISTS feed(
        claim_id INTEGER, version INTEGER, member TEXT NOT NULL, service TEXT NOT NULL,
        received TEXT NOT NULL, part INTEGER NOT NULL CHECK (part IN (0, 1)),
        cents INTEGER NOT NULL CHECK (cents >= 0), PRIMARY KEY(claim_id, version)
    );
    CREATE TRIGGER IF NOT EXISTS reject_conflicting_claim_version
    BEFORE INSERT ON feed WHEN EXISTS (
        SELECT 1 FROM feed AS f WHERE f.claim_id = NEW.claim_id AND f.version = NEW.version
        AND (f.member, f.service, f.received, f.part, f.cents) IS NOT
            (NEW.member, NEW.service, NEW.received, NEW.part, NEW.cents)
    )
    BEGIN
        SELECT RAISE(ABORT, 'claim version has conflicting payloads');
    END;
"""


def load_batch(db, eligibility, deliveries, seed, members):
    with db:
        # Take the write lock before checking the database's seed and population.
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT INTO dataset_config VALUES (1, ?, ?) ON CONFLICT DO NOTHING", (seed, members))
        if db.execute("SELECT seed, members FROM dataset_config").fetchone() != (seed, members):
            raise ValueError("A different seed or population requires a separate database.")
        db.executemany("INSERT INTO eligibility VALUES (?, ?) ON CONFLICT DO NOTHING", eligibility)
        before = db.total_changes
        db.executemany("INSERT INTO feed VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING", deliveries)
        return db.total_changes - before


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def run(output, members, seed, fault, cutoff=date(2025, 4, 15), database=":memory:"):
    rng = random.Random(seed)
    eligibility = []
    feed = []
    reference = {}
    claim_id = 0
    for member_id in range(1, members + 1):
        member = f"SYN-{member_id:06}"
        first_month = rng.randint(1, 2)
        last_month = rng.randint(first_month, 3)
        for month in range(first_month, last_month + 1):
            service = date(2025, month, rng.randint(1, 28))
            service_month = service.isoformat()[:7]
            eligibility.append((member, service_month))
            reference[member, service_month] = [0, 0]
            for _ in range(rng.randint(0, 5)):
                claim_id += 1
                part = rng.randrange(2)
                received = service + timedelta(days=rng.randint(5, 45))
                amount = rng.randint(1500, 250000) if part == 0 else rng.randint(1000, 32000)
                feed.append((claim_id, 1, member, service.isoformat(), received.isoformat(), part, amount))
                if received <= cutoff:
                    reference[member, service_month][part] += amount
                if rng.random() < 0.20:
                    corrected = amount // 2 if rng.random() < 0.75 else 0
                    revised = received + timedelta(days=rng.randint(1, 20))
                    feed.append((claim_id, 2, member, service.isoformat(), revised.isoformat(), part, corrected))
                    if revised <= cutoff:
                        reference[member, service_month][part] += corrected - amount

    replay = list(feed)
    replay.extend(feed[::10])
    rng.shuffle(replay)
    expected = [(member, month, *amounts) for (member, month), amounts in reference.items()]
    with closing(sqlite3.connect(database)) as db:
        db.executescript(SCHEMA)
        inserted = load_batch(db, eligibility, replay, seed, members)
        replayed = load_batch(db, eligibility, replay, seed, members)
        actual = db.execute("""
            WITH received_claims AS (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY claim_id ORDER BY version DESC) AS rank
                FROM feed WHERE received <= ?
            ), monthly AS (
                SELECT member, substr(service, 1, 7) AS month,
                    SUM(CASE WHEN part = 0 THEN cents ELSE 0 END) AS part_a,
                    SUM(CASE WHEN part = 1 THEN cents ELSE 0 END) AS part_b
                FROM received_claims WHERE rank = 1 GROUP BY member, month
            )
            SELECT e.member, e.month, COALESCE(m.part_a, 0), COALESCE(m.part_b, 0)
            FROM eligibility e LEFT JOIN monthly m USING (member, month)
            ORDER BY e.member, e.month
        """, (cutoff.isoformat(),)).fetchall()
        deduplicated_count = db.execute("SELECT count(*) FROM feed").fetchone()[0]

    if fault == "missing":
        actual.pop()
    elif fault == "offsetting":
        first, second = actual[:2]
        drift = min(first[2], 1000) or 1000
        actual[:2] = [(*first[:2], first[2] + drift, first[3]),
                      (*second[:2], second[2] - drift, second[3])]

    expected_by_key = {(member, month): (a, b) for member, month, a, b in expected}
    actual_by_key = {(member, month): (a, b) for member, month, a, b in actual}
    mismatches = [
        {"member": key[0], "month": key[1],
         "expected": expected_by_key.get(key), "actual": actual_by_key.get(key)}
        for key in sorted(expected_by_key.keys() | actual_by_key.keys())
        if expected_by_key.get(key) != actual_by_key.get(key)
    ]
    expected_cents = sum(a + b for _, _, a, b in expected)
    actual_cents = sum(a + b for _, _, a, b in actual)
    duplicate_keys = len(actual) - len(actual_by_key)
    passed = not mismatches and not duplicate_keys and deduplicated_count == len(feed) and replayed == 0
    summary = {
        "seed": seed, "members": members, "cutoff": cutoff.isoformat(), "fault": fault,
        "received_feed_rows": len(replay), "stored_unique_versions": deduplicated_count,
        "inserted_claim_versions": inserted, "replay_inserted_claim_versions": replayed,
        "expected_member_months": len(expected), "actual_member_months": len(actual),
        "duplicate_output_keys": duplicate_keys, "expected_cents": expected_cents,
        "actual_cents": actual_cents, "variance_cents": actual_cents - expected_cents,
        "mismatch_count": len(mismatches), "passed": passed,
    }
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "eligibility.csv", ("member_id", "service_month"), eligibility)
    write_csv(output / "claim_feed.csv",
              ("claim_id", "version", "member_id", "service_date", "received_date", "part_code", "paid_cents"),
              replay)
    columns = ("member_id", "service_month", "part_a_cents", "part_b_cents")
    write_csv(output / "reference_member_month.csv", columns, expected)
    write_csv(output / "actual_member_month.csv", columns, actual)
    (output / "reconciliation.json").write_text(
        json.dumps({"summary": summary, "mismatches": mismatches}, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--members", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2025, 4, 15))
    parser.add_argument("--database", type=Path, help="Optional SQLite database to reuse across runs.")
    parser.add_argument("--fault", choices=("none", "missing", "offsetting"), default="none")
    args = parser.parse_args()
    if args.members < 2:
        parser.error("at least two members are required")
    try:
        if args.database:
            args.database.parent.mkdir(parents=True, exist_ok=True)
        summary = run(args.out, args.members, args.seed, args.fault, args.cutoff, args.database or ":memory:")
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Reconciliation could not run: {error}\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
