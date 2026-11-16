"""Tenant-scoped deterministic finance tools and a reproducible evaluation."""
import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path


QUERIES = {
    "close": """
        SELECT f.paid_cents,f.member_months,f.pmpm_cents,f.missing_benchmark_rows,
               f.benchmark_cents,f.expense_to_benchmark
        FROM monthly_finance f JOIN month m ON m.id=f.month_id
        WHERE f.client_id=? AND m.starts=? AND f.run_id='revised'
    """,
    "restatement": """
        SELECT r.original_paid_cents,r.revised_paid_cents,r.difference_cents
        FROM restatement r JOIN month m ON m.id=r.month_id
        WHERE r.client_id=? AND m.starts=?
    """,
}


def answer(db, client_id, operation, month):
    if operation not in QUERIES:
        return {"status":"unsupported"}
    db.row_factory = sqlite3.Row
    row = db.execute(QUERIES[operation],(client_id,month)).fetchone()
    if row is None:
        return {"status":"no_evidence"}
    return {"status":"ok","evidence":{"client_id":client_id,"month":month,
            "view":"monthly_finance" if operation=="close" else "restatement"},"values":dict(row)}


def evaluate(db):
    cases = 0
    for client in (1,2):
        originals = db.execute("""
            SELECT m.starts,SUM(p.delta_cents)
            FROM payment_event p JOIN claim c ON c.id=p.claim_id JOIN month m ON m.id=c.month_id
            WHERE c.client_id=? AND p.received_date<='2026-01-15'
            GROUP BY m.starts
        """,(client,)).fetchall()
        revised = dict(tuple(row) for row in db.execute("""
            SELECT m.starts,SUM(p.delta_cents)
            FROM payment_event p JOIN claim c ON c.id=p.claim_id JOIN month m ON m.id=c.month_id
            WHERE c.client_id=? AND p.received_date<='2026-03-31'
            GROUP BY m.starts
        """,(client,)))
        for month, original in originals:
            expected = revised[month]
            base = answer(db,client,"close",month)
            delta = answer(db,client,"restatement",month)
            if base["values"]["paid_cents"]!=expected or delta["values"]["difference_cents"]!=expected-original:
                raise AssertionError(f"wrong financial result for client {client} on {month}")
            cases += 2
    if answer(db,1,"arbitrary SQL","2025-01-01")["status"]!="unsupported":
        raise AssertionError("unexpected tool was accepted")
    if answer(db,1,"close","1999-01-01")["status"]!="no_evidence":
        raise AssertionError("missing period was accepted")
    return {"passed":cases+2,"financial_cases":cases,"unsupported_or_missing_cases":2}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database",type=Path,required=True)
    parser.add_argument("--client",type=int,choices=(1,2))
    parser.add_argument("--operation",choices=tuple(QUERIES))
    parser.add_argument("--month")
    parser.add_argument("--evaluate",action="store_true")
    args=parser.parse_args()
    if not args.evaluate and (args.client is None or args.operation is None or args.month is None):
        parser.error("provide --client, --operation, and --month, or use --evaluate")
    with closing(sqlite3.connect(f"{args.database.resolve().as_uri()}?mode=ro",uri=True)) as db:
        result=evaluate(db) if args.evaluate else answer(db,args.client,args.operation,args.month)
    print(json.dumps(result,indent=2))
