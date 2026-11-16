"""Build the portfolio-scale synthetic claims database and verify two closes."""
import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from time import perf_counter


CLOSES = (("original", "2026-01-15"), ("revised", "2026-03-31"))
SCHEMA_PATH = Path(__file__).with_name("platform.sql")


def materialize_closes(db, *, from_journal=False):
    delivery_relation = "approved_delivery" if from_journal else "claim_delivery"
    versioned_rules = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='effective_client_rule'"
    ).fetchone() is not None
    rule_join = (
        "JOIN effective_client_rule v ON v.client_id=e.client_id AND v.month_id=e.month_id"
        if versioned_rules else ""
    )
    risk_month = (
        "e.month_id-(e.month_id-v.effective_month)%v.risk_period_months"
        if versioned_rules else "1+((e.month_id-1)/3)*3"
    )
    factor = "*v.benchmark_basis_points/10000" if versioned_rules else ""
    rule_version = (
        "synthetic-2"
        if versioned_rules and db.execute("SELECT count(*) FROM client").fetchone()[0] == 3
        else "synthetic-1"
    )
    db.executescript("""
        CREATE TABLE close_run(id TEXT PRIMARY KEY, cutoff TEXT NOT NULL, rules_version TEXT NOT NULL);
        CREATE TABLE close_fact(
            run_id TEXT REFERENCES close_run(id),client_id INTEGER,member_id INTEGER,month_id INTEGER,
            paid_cents INTEGER NOT NULL, benchmark_cents INTEGER,
            PRIMARY KEY(run_id,client_id,member_id,month_id)
        ) WITHOUT ROWID;
    """)
    checks = []
    for run, cutoff in CLOSES:
        started = perf_counter()
        db.execute("INSERT INTO close_run VALUES (?, ?, ?)", (run, cutoff, rule_version))
        db.execute(f"""
            CREATE TEMP TABLE observed AS
            WITH versions AS (
                SELECT claim_id,line_no,version,MIN(replacement_cents) AS paid
                FROM {delivery_relation} WHERE received_date<=?
                GROUP BY claim_id,line_no,version
                HAVING MIN(replacement_cents)=MAX(replacement_cents)
            ), latest AS (
                SELECT *,ROW_NUMBER() OVER (PARTITION BY claim_id,line_no ORDER BY version DESC) AS rank
                FROM versions
            )
            SELECT c.client_id,c.member_id,c.month_id,SUM(v.paid) paid
            FROM latest v JOIN claim c ON c.id=v.claim_id WHERE rank=1
            GROUP BY c.client_id,c.member_id,c.month_id
        """, (cutoff,))
        db.execute("""
            CREATE TEMP TABLE expected AS
            SELECT c.client_id,c.member_id,c.month_id,SUM(p.delta_cents) paid
            FROM payment_event p JOIN claim c ON c.id=p.claim_id
            WHERE p.received_date<=? GROUP BY c.client_id,c.member_id,c.month_id
        """, (cutoff,))
        differences = db.execute("""
            SELECT
                (SELECT count(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM observed))
              + (SELECT count(*) FROM (SELECT * FROM observed EXCEPT SELECT * FROM expected))
        """).fetchone()[0]
        if differences:
            raise RuntimeError(f"{run}: payment ledger and delivery rollup differ on {differences} rows")
        db.execute("CREATE UNIQUE INDEX observed_key ON observed(client_id,member_id,month_id)")
        db.execute(f"""
            INSERT INTO close_fact
            SELECT ?,e.client_id,e.member_id,e.month_id,COALESCE(o.paid,0),
                   r.cents*s.risk_basis_points{factor}/10000
            FROM member_month e
            JOIN member m ON m.client_id=e.client_id AND m.id=e.member_id
            JOIN month d ON d.id=e.month_id
            JOIN provider p ON p.client_id=e.client_id AND p.id=e.provider_id
            {rule_join}
            LEFT JOIN risk_snapshot s ON s.client_id=e.client_id AND s.member_id=e.member_id
                 AND s.month_id={risk_month}
            LEFT JOIN rate r ON r.client_id=e.client_id AND r.region=p.region
                 AND r.year=CAST(substr(d.starts,1,4) AS INTEGER) AND r.cohort=m.cohort
            LEFT JOIN observed o
              ON o.client_id=e.client_id AND o.member_id=e.member_id AND o.month_id=e.month_id
        """, (run,))
        db.execute("DROP TABLE observed")
        db.execute("DROP TABLE expected")
        rows, paid = db.execute(
            "SELECT count(*),sum(paid_cents) FROM close_fact WHERE run_id=?", (run,)
        ).fetchone()
        checks.append({"run": run, "cutoff": cutoff, "rows": rows, "paid_cents": paid,
                       "ledger_differences": differences, "seconds": round(perf_counter()-started, 2)})
    db.executescript("""
        CREATE VIEW monthly_finance AS
        SELECT run_id,client_id,month_id,COUNT(*) member_months,SUM(paid_cents) paid_cents,
               SUM(benchmark_cents) benchmark_cents,
               COUNT(*)-COUNT(benchmark_cents) missing_benchmark_rows,
               1.0*SUM(paid_cents)/COUNT(*) pmpm_cents,
               CASE WHEN COUNT(benchmark_cents)=COUNT(*)
                   THEN 1.0*SUM(paid_cents)/NULLIF(SUM(benchmark_cents),0) END expense_to_benchmark
        FROM close_fact GROUP BY run_id,client_id,month_id;
        CREATE VIEW restatement AS
        SELECT revised.client_id,revised.month_id,original.paid_cents original_paid_cents,
               revised.paid_cents revised_paid_cents,
               revised.paid_cents-original.paid_cents difference_cents
        FROM monthly_finance revised JOIN monthly_finance original USING(client_id,month_id)
        WHERE revised.run_id='revised' AND original.run_id='original';
    """)
    return checks


def build(database, members, seed, tenants=2):
    if tenants not in (2, 3) or members < tenants:
        raise ValueError("Use two or three tenants and at least one member per tenant")
    started = perf_counter()
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.exists():
        raise FileExistsError(f"Use a new database path: {database}")
    with tempfile.TemporaryDirectory(dir=database.parent) as temp:
        work = Path(temp) / "claims.sqlite"
        with closing(sqlite3.connect(work)) as db:
            db.executescript("""
                CREATE TEMP TABLE config(members INTEGER, months INTEGER, seed INTEGER, tenants INTEGER);
                CREATE TEMP TABLE numbers(id INTEGER PRIMARY KEY);
            """)
            db.execute("INSERT INTO config VALUES (?,24,?,?)", (members, seed, tenants))
            db.executemany("INSERT INTO numbers VALUES (?)", ((n,) for n in range(1,max(members,250)+1)))
            db.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            checks = materialize_closes(db)
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RuntimeError("Foreign key check failed")
            tables = ("client","provider","member","member_alias","member_month","risk_snapshot",
                      "claim","encounter","diagnosis","payment_event","claim_delivery","close_fact")
            counts = {table:db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
            db.commit()
        work.rename(database)
    return {"members":members,"seed":seed,"months":24,"rows":counts,"closes":checks,
            "database_bytes":database.stat().st_size,"seconds":round(perf_counter()-started,2)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--members", type=int, default=50000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tenants", type=int, choices=(2, 3), default=2)
    args = parser.parse_args()
    if not 2<=args.members<=1000000 or not 0<=args.seed<=1000000:
        parser.error("members must be 2–1,000,000 and seed must be 0–1,000,000")
    print(json.dumps(build(args.database,args.members,args.seed,args.tenants),indent=2))
