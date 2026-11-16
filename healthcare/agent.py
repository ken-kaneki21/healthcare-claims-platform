"""Financial question routing with deterministic, tenant-bound answers."""

import json
import re
import sqlite3
from datetime import date
from time import perf_counter

from financial_tools import answer

MONTH = re.compile(r"\b\d{4}-(?:0[1-9]|1[0-2])\b")
POLICY = re.compile(
    r"\b(?:tenant|client)\s*#?\s*\d+\b|\b(?:ignore|override)\b.*\binstructions\b",
    re.IGNORECASE,
)
OPERATIONS = {
    "close": "close",
    "paid": "close",
    "restatement": "restatement",
    "pmpm": "pmpm",
    "benchmark coverage": "benchmark_coverage",
}


def rules(question: str):
    month = MONTH.search(question)
    if month is None:
        return {"operation": "unsupported"}
    text = question.lower()
    operation = next(
        (value for name, value in reversed(OPERATIONS.items()) if name in text),
        "unsupported",
    )
    return {"operation": operation, "month": month.group() + "-01"}


def question_answer(db: sqlite3.Connection, tenant: int, question: str, route=rules):
    if not question or len(question) > 500:
        return {"status": "unsupported"}
    if POLICY.search(question):
        return {"status": "denied"}
    selected = route(question)
    if not isinstance(selected, dict) or selected.keys() - {"operation", "month"}:
        return {"status": "unsupported"}
    operation, month = selected.get("operation"), selected.get("month")
    if operation not in (
        "close",
        "restatement",
        "pmpm",
        "benchmark_coverage",
    ) or not isinstance(month, str):
        return {"status": "unsupported"}
    try:
        if date.fromisoformat(month).day != 1 or not MONTH.fullmatch(month[:-3]):
            return {"status": "unsupported"}
    except ValueError:
        return {"status": "unsupported"}
    result = answer(
        db, tenant, "restatement" if operation == "restatement" else "close", month
    )
    result["operation"] = operation
    if result["status"] != "ok":
        return result
    result["evidence"]["cutoff"] = "2026-03-31"
    if operation == "restatement":
        result["evidence"]["original_cutoff"] = "2026-01-15"
    elif operation == "pmpm":
        result["values"] = {
            key: result["values"][key]
            for key in ("paid_cents", "member_months", "pmpm_cents")
        }
    elif operation == "benchmark_coverage":
        result["values"] = {
            key: result["values"][key]
            for key in ("member_months", "missing_benchmark_rows")
        }
    return result


def provider_router(client, endpoint: str, api_key: str, model: str):
    """Adapter for a configured chat-completions endpoint. It sends only the question."""
    usage = {"tokens": 0, "requests": 0}

    def route(question):
        response = client.post(
            endpoint,
            headers={"Authorization": "Bearer " + api_key},
            json={
                "model": model,
                "max_tokens": 100,
                "temperature": 0,
                "messages": [
                    {
                        "role": "system",
                        "content": "Return JSON with operation and month YYYY-MM-01. "
                        "Operations: close, restatement, pmpm, benchmark_coverage, unsupported. "
                        "Return unsupported if no period is supplied. Never produce queries or amounts.",
                    },
                    {"role": "user", "content": question},
                ],
            },
            timeout=10,
        )
        response.raise_for_status()
        try:
            body = response.json()
            usage["requests"] += 1
            usage["tokens"] += int(body.get("usage", {}).get("total_tokens", 0))
            return json.loads(body["choices"][0]["message"]["content"])
        except (TypeError, ValueError, IndexError, KeyError):
            return {"operation": "unsupported"}

    return route, usage


def gold_questions(db):
    # Expected amounts use signed ledger deltas, separate from the reporting views.
    ledger = {}
    for tenant, month, cutoff, total in db.execute("""
        WITH cutoffs(cutoff) AS (VALUES ('2026-01-15'),('2026-03-31'))
        SELECT c.client_id,m.starts,k.cutoff,sum(p.delta_cents) FROM payment_event p
        JOIN claim c ON c.id=p.claim_id JOIN month m ON m.id=c.month_id CROSS JOIN cutoffs k
        WHERE p.received_date<=k.cutoff GROUP BY c.client_id,m.starts,k.cutoff
    """):
        ledger[tenant, month, cutoff] = total
    for tenant, month, members in db.execute("""
        SELECT e.client_id,m.starts,count(*) FROM member_month e
        JOIN month m ON m.id=e.month_id GROUP BY e.client_id,m.starts ORDER BY 1,2
    """):
        old = ledger.get((tenant, month, "2026-01-15"), 0)
        paid = ledger.get((tenant, month, "2026-03-31"), 0)
        yield (
            tenant,
            f"Paid amount for {month[:7]}",
            "ok",
            "close",
            month,
            {"paid_cents": paid},
        )
        yield (
            tenant,
            f"PMPM for {month[:7]}",
            "ok",
            "pmpm",
            month,
            {"pmpm_cents": paid / members},
        )
        yield (
            tenant,
            f"Restatement for {month[:7]}",
            "ok",
            "restatement",
            month,
            {"difference_cents": paid - old},
        )
    for year in range(1990, 2020):
        yield 1, f"Close for {year}-12", "no_evidence", "close", f"{year}-12-01", {}
    for month in range(1, 16):
        for tenant in (1, 2):
            yield (
                tenant,
                f"Client {3 - tenant} paid amount, scenario {month}",
                "denied",
                None,
                None,
                {},
            )


def evaluate_agent(db, route=rules, provider="deterministic_rules"):
    passed = cases = 0
    timings = []
    for tenant, question, status, operation, month, expected in gold_questions(db):
        started = perf_counter()
        result = question_answer(db, tenant, question, route)
        timings.append((perf_counter() - started) * 1000)
        cases += 1
        correct = result["status"] == status
        if status == "ok" and correct:
            evidence = result["evidence"]
            correct = (
                evidence["client_id"],
                evidence["month"],
                result["operation"],
            ) == (tenant, month, operation)
            correct = correct and all(
                abs(result["values"][key] - value) < 1e-6
                for key, value in expected.items()
            )
        passed += int(correct)
    timings.sort()
    return {
        "evaluation_version": "finance-gold-1",
        "provider": provider,
        "cases": cases,
        "passed": passed,
        "p50_ms": timings[len(timings) // 2],
        "p95_ms": timings[int(len(timings) * 0.95)],
    }
