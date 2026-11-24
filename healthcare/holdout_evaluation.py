"""Evaluate a new synthetic finance holdout and the local provider boundary."""

import argparse
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from statistics import median
from time import perf_counter

import httpx

from build_platform import build
from healthcare.agent import provider_router, question_answer, rules
from healthcare.provider import settings

ORACLE = """
SELECT
    (SELECT coalesce(sum(p.delta_cents),0) FROM payment_event p
     JOIN claim c ON c.id=p.claim_id
     WHERE c.client_id=1 AND c.month_id=m.id AND p.received_date<=?),
    (SELECT count(*) FROM member_month e WHERE e.client_id=1 AND e.month_id=m.id)
FROM month m WHERE m.starts=?
"""


def oracle_check(db, case, response):
    if case["status"] != "ok":
        return "values" not in response, "evidence" not in response
    cutoff = db.execute("SELECT cutoff FROM close_run WHERE id='revised'").fetchone()[0]
    expected = []
    for month in case["months"]:
        paid, enrollment = db.execute(ORACLE, (cutoff, month)).fetchone()
        expected.append(paid / enrollment if case["metric"] == "pmpm" else paid)
    evidence = response.get("evidence", {})
    evidence_ok = (
        evidence.get("client_id") == 1
        and evidence.get("cutoff") == cutoff
        and evidence.get("month") == case["months"][0]
        and evidence.get("view") == "monthly_finance"
    )
    if len(expected) == 1:
        amounts_ok = response.get("values", {}).get("paid_cents") == expected[0]
    else:
        evidence_ok &= evidence.get("comparison_month") == case["months"][1]
        amounts_ok = response.get("values") == {
            "first": expected[0], "second": expected[1],
            "difference": expected[1] - expected[0],
        }
    return amounts_ok, evidence_ok


def evaluate(db, cases, route, usage):
    rows = []
    for case in cases:
        before = usage.get("requests", 0)
        start = perf_counter()
        try:
            response = question_answer(db, 1, case["question"], route)
        except httpx.HTTPError as error:
            response = {"status": type(error).__name__}
        ms = (perf_counter() - start) * 1000
        numeric, evidence = oracle_check(db, case, response)
        status_ok = response["status"] == case["status"]
        tool_ok = response.get("operation") == case["tool"]
        months = case["months"]
        actual_evidence = response.get("evidence", {})
        correct_arguments = (
            actual_evidence.get("month") == months[0]
            and (len(months) == 1 or actual_evidence.get("comparison_month") == months[1])
            if months
            else not actual_evidence
        )
        rows.append({
            "id": case["id"], "actual": response["status"],
            "expected": case["status"], "actual_tool": response.get("operation"),
            "expected_tool": case["tool"], "tool_correct": tool_ok,
            "arguments_correct": correct_arguments, "numerical_correct": numeric,
            "evidence_correct": evidence, "model_invoked": usage.get("requests", 0) > before,
            "unsupported_answer": case["status"] != "ok" and "values" in response,
            "tenant_boundary_failure": (
                case["id"] == "wrong-client" and response["status"] != "denied"
            ),
            "passed": status_ok and tool_ok and correct_arguments and numeric and evidence,
            "elapsed_ms": ms,
        })
    return {
        "cases": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "cases_using_model": sum(row["model_invoked"] for row in rows),
        "unsupported_answers": sum(row["unsupported_answer"] for row in rows),
        "tenant_boundary_failures": sum(row["tenant_boundary_failure"] for row in rows),
        "latency_p50_ms": median(row["elapsed_ms"] for row in rows),
        "latency_p95_ms": sorted(row["elapsed_ms"] for row in rows)[
            (95 * len(rows) + 99) // 100 - 1
        ],
        "provider_usage": usage,
        "rows": rows,
    }


def mock_transport_checks(db):
    question = "How much did we pay in the 2025-06 close?"
    endpoint = "http://127.0.0.1:18765/v1/chat/completions"

    def transport(request):
        mode = request.url.path
        if mode == "/timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        content = {"operation": "close"}
        if mode == "/invalid":
            content["tenant"] = 2
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"total_tokens": 0},
        })

    results = {}
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        for mode, expected in (("valid", "ok"), ("invalid", "unsupported"),
                               ("timeout", "ReadTimeout")):
            route, usage = provider_router(client, endpoint.rsplit("/", 3)[0] + "/" + mode,
                                          "", "mock")
            try:
                response = question_answer(db, 1, question, route)
                actual = response["status"]
            except httpx.ReadTimeout:
                actual = "ReadTimeout"
            results[mode] = actual == expected and usage["requests"] == 1
    wrong_month = question_answer(db, 1, question, lambda _: {
        "operation": "close", "month": "2025-07-01",
    })
    results["contradictory_tool_month"] = wrong_month == {"status": "unsupported"}
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--require-correct", action="store_true")
    args = parser.parse_args()
    data = json.loads(Path("tests/fixtures/finance_holdout_v1.json").read_text(encoding="utf-8"))
    report = {"fixture": data["version"], "label_provenance": data["label_provenance"],
              "dataset": {"members": 100, "seed": 73, "tenants": 3, "synthetic": True}}
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "claims.sqlite"
        build(database, 100, 73, tenants=3)
        with closing(sqlite3.connect(database)) as db:
            report["rules"] = evaluate(db, data["cases"], rules, {})
            report["mock_transport"] = mock_transport_checks(db)
            report["live"] = {"status": "not_requested"}
            if args.live:
                endpoint, key, model = settings(local=True)
                with httpx.Client(trust_env=False) as client:
                    try:
                        probe = client.get(endpoint.rsplit("/", 2)[0] + "/models", timeout=2)
                        probe.raise_for_status()
                    except httpx.HTTPError as error:
                        report["live"] = {"status": "blocked", "reason": type(error).__name__}
                    else:
                        route, usage = provider_router(client, endpoint, key, model)
                        report["live"] = {
                            "status": "ran", "model": model,
                            **evaluate(db, data["cases"], route, usage),
                        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(f"Deterministic: {report['rules']['passed']}/{report['rules']['cases']}")
    print(f"Mock boundary: {report['mock_transport']}")
    print(f"Live: {report['live']['status']}")
    failed = (
        report["rules"]["passed"] != report["rules"]["cases"]
        or not all(report["mock_transport"].values())
        or (
            args.live and (
                report["live"]["status"] != "ran"
                or report["live"]["passed"] != report["live"]["cases"]
            )
        )
    )
    return int(args.require_correct and failed)


if __name__ == "__main__":
    raise SystemExit(main())
