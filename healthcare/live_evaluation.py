"""Evaluate the same authored questions with rules and live model routing."""

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from statistics import median, quantiles
from time import perf_counter

import httpx

from healthcare.agent import provider_router, question_answer, rules
from healthcare.provider import settings


def evaluate(db, cases, route, usage):
    counts = Counter()
    failures = []
    latencies = []
    for index, case in enumerate(cases, 1):
        status, operation, question = case.split("|", 2)
        expected = question_answer(db, 1, question, rules)
        before = usage["requests"]
        started = perf_counter()
        try:
            result = question_answer(db, 1, question, route)
        except httpx.HTTPError as error:
            result = {"status": type(error).__name__}
        latencies.append(1000 * (perf_counter() - started))
        counts["cases"] += 1
        invoked = usage["requests"] > before
        counts["cases_using_model"] += invoked
        status_ok = result["status"] == status
        tool_ok = result.get("operation") == (operation or None)
        if status == "ok":
            counts["financial_cases"] += 1
            counts["financial_cases_using_model"] += invoked
            values_ok = status_ok and result.get("values") == expected.get("values")
            evidence_ok = status_ok and result.get("evidence") == expected.get(
                "evidence"
            )
            counts["numeric_correct"] += values_ok
            counts["evidence_correct"] += evidence_ok
            counts["financial_tool_correct"] += status_ok and tool_ok
        else:
            counts["refusal_cases"] += 1
            counts["refusal_status_correct"] += status_ok
            values_ok = evidence_ok = "values" not in result
            counts["unsupported_answers"] += not values_ok
        if status_ok and tool_ok and values_ok and evidence_ok:
            counts["passed"] += 1
        else:
            failures.append(
                {
                    "fixture_line": index,
                    "model_invoked": invoked,
                    "expected_status": status,
                    "actual_status": result["status"],
                    "expected_tool": operation or None,
                    "actual_tool": result.get("operation"),
                    "values_match": values_ok,
                    "evidence_matches": evidence_ok,
                }
            )
    return {
        **counts,
        "requests": usage["requests"],
        "tokens": usage.get("tokens", 0),
        "p50_ms": median(latencies),
        "p95_ms": quantiles(latencies, n=100, method="inclusive")[94],
        "failures": failures,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--suite", type=Path, default=Path("tests/fixtures/financial_questions.txt")
    )
    args = parser.parse_args()
    cases = args.suite.read_text(encoding="utf-8").splitlines()
    endpoint, key, model = settings(local=True)
    with (
        closing(
            sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
        ) as db,
        httpx.Client(trust_env=False) as client,
    ):
        route, usage = provider_router(client, endpoint, key, model)
        report = {
            "model": model,
            "prompt": "finance-router-v4",
            "authored_cases": True,
            "rules": evaluate(db, cases, rules, {"requests": 0}),
            "model_assisted": evaluate(db, cases, route, usage),
            "provider_cost_usd": 0,
        }
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
