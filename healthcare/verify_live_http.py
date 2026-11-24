"""Run the frozen synthetic finance suite through a loopback HTTP service."""

import argparse
import hashlib
import json
import secrets
import socket
import sqlite3
import tempfile
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx
import uvicorn

from build_platform import build
from healthcare.agent import provider_router
from healthcare.api import create_app, issue_token
from healthcare.holdout_evaluation import oracle_check
from healthcare.provider import settings

FIXTURE = Path("tests/fixtures/finance_holdout_v1.json")
STATUS = {
    "ok": 200,
    "denied": 403,
    "no_evidence": 404,
    "ambiguous": 422,
    "unsupported": 422,
}


def run(fixture, report, model_path, runtime_revision, startup_timeout):
    endpoint, key, model = settings(local=True)
    report["model"] = {
        "alias": model,
        "requested_runtime_revision": runtime_revision,
    }
    digest = hashlib.sha256()
    with model_path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    report["model"]["artifact_sha256"] = digest.hexdigest()
    deadline = time.monotonic() + startup_timeout
    with httpx.Client(trust_env=False, timeout=5) as probe:
        while True:
            try:
                metadata = probe.get(endpoint.rsplit("/", 2)[0] + "/models")
                metadata.raise_for_status()
                aliases = [entry.get("id") for entry in metadata.json().get("data", [])]
                if model not in aliases:
                    raise ValueError(
                        "Ready model endpoint does not advertise the configured alias"
                    )
                break
            except httpx.HTTPError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)

    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "finance.sqlite"
        build(database, 100, 73, tenants=3)
        secret = secrets.token_hex(32)
        events = []
        configurations = []

        def route(question):
            event = {"attempted": True, "http_status": None}
            events.append(event)

            def request_hook(request):
                payload = json.loads(request.content)
                config = {
                    key: payload[key]
                    for key in ("model", "temperature", "max_tokens", "response_format")
                }
                config["system_prompt"] = payload["messages"][0]["content"]
                if config not in configurations:
                    configurations.append(config)

            def response_hook(response):
                event["http_status"] = response.status_code
                if response.is_success:
                    payload = response.read()
                    try:
                        result = json.loads(payload)
                        event["provider_model"] = result.get("model")
                        event["provider_usage"] = result.get("usage")
                        event["model_proposal"] = result["choices"][0]["message"][
                            "content"
                        ]
                    except (ValueError, TypeError, KeyError, IndexError):
                        event["invalid_response_envelope"] = True

            start = time.perf_counter()
            try:
                with httpx.Client(
                    trust_env=False,
                    event_hooks={
                        "request": [request_hook],
                        "response": [response_hook],
                    },
                ) as client:
                    interpret, usage = provider_router(client, endpoint, key, model)
                    decision = interpret(question)
                    event.update(decision=decision, router_usage=usage)
                    return decision
            finally:
                event["elapsed_ms"] = (time.perf_counter() - start) * 1000

        app = create_app(database, secret, question_router=route)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", lifespan="off")
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            thread.start()
            try:
                deadline = time.monotonic() + 8
                while not server.started:
                    if not thread.is_alive() or time.monotonic() >= deadline:
                        raise RuntimeError("Loopback HTTP service did not start")
                    time.sleep(0.05)
                with (
                    httpx.Client(
                        base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=30
                    ) as http,
                    closing(sqlite3.connect(database)) as db,
                ):
                    check_cases(fixture, report, events, http, db, secret)
            finally:
                server.should_exit = True
                thread.join(timeout=5)
        report["provider_configurations"] = configurations


def check_cases(fixture, report, events, http, db, secret):
    def ask(question, tenant=None):
        headers = (
            {"Authorization": f"Bearer {issue_token(secret, tenant)}"} if tenant else {}
        )
        return http.post(
            "/finance/questions", json={"question": question}, headers=headers
        )

    report["anonymous_status"] = ask(fixture["cases"][0]["question"]).status_code
    report["cases"] = rows = []
    for case in fixture["cases"]:
        before = len(events)
        start = time.perf_counter()
        response = ask(case["question"], 1)
        elapsed_ms = (time.perf_counter() - start) * 1000
        body = response.json()
        numeric, evidence = oracle_check(db, case, body)
        tool_ok = body.get("operation") == case["tool"] if response.is_success else None
        body_status = body.get("status") if response.is_success else body.get("detail")
        rows.append(
            {
                "id": case["id"],
                "http": response.status_code,
                "expected": case["status"],
                "response_status": body_status,
                "expected_arguments": case["months"],
                "effective_tool": body.get("operation"),
                "evidence": body.get("evidence"),
                "values": body.get("values"),
                "numeric_oracle_match": numeric,
                "evidence_match": evidence,
                "tool_match": tool_ok,
                "elapsed_ms": elapsed_ms,
                "model_events": events[before:],
                "passed": response.status_code == STATUS[case["status"]]
                and body_status == case["status"]
                and numeric
                and evidence
                and tool_ok is not False,
            }
        )

    # Inspect an identity-selected tenant independently of free-text policy.
    before = len(events)
    wrong_tenant = http.get(
        "/finance/2/close/2025-06",
        headers={"Authorization": f"Bearer {issue_token(secret, 1)}"},
    )
    report["wrong_tenant_status"] = wrong_tenant.status_code
    tenant_two = http.get(
        "/finance/2/close/2025-06",
        headers={"Authorization": f"Bearer {issue_token(secret, 2)}"},
    )
    scoped = tenant_two.json()
    report["tenant_two"] = {
        "http": tenant_two.status_code,
        "tenant": scoped.get("evidence", {}).get("client_id"),
        "model_calls": len(events) - before,
    }
    report["model_http_attempts"] = len(events)
    report["model_http_responses_2xx"] = sum(
        200 <= (event["http_status"] or 0) < 300 for event in events
    )
    report["routed_financial_cases_with_model_response"] = sum(
        row["passed"]
        and row["http"] == 200
        and any("model_proposal" in event for event in row["model_events"])
        for row in rows
    )
    report["passed"] = (
        report["anonymous_status"] == 401
        and report["wrong_tenant_status"] == 403
        and report["tenant_two"] == {"http": 200, "tenant": 2, "model_calls": 0}
        and all(row["passed"] for row in rows)
        and report["routed_financial_cases_with_model_response"] > 0
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--model-file", required=True, type=Path)
    parser.add_argument("--runtime-revision", required=True)
    parser.add_argument("--startup-timeout", type=int, default=0)
    args = parser.parse_args()
    raw = FIXTURE.read_bytes()
    fixture = json.loads(raw)
    report = {
        "fixture": fixture["version"],
        "fixture_sha256": hashlib.sha256(raw).hexdigest(),
        "scope": "signed-demo bearer authentication over HTTP; synthetic ledger",
        "dataset": {"members": 100, "seed": 73, "tenants": 3},
        "model_http_attempts": 0,
        "model_http_responses_2xx": 0,
        "passed": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        try:
            run(
                fixture,
                report,
                args.model_file,
                args.runtime_revision,
                args.startup_timeout,
            )
            report["status"] = "passed" if report["passed"] else "failed"
        except (httpx.HTTPError, OSError, ValueError, KeyError, RuntimeError) as error:
            report["status"] = "blocked" if "cases" not in report else "failed"
            report["error_type"] = type(error).__name__
            report["error"] = str(error)
        json.dump(report, output, indent=2)
        output.write("\n")
    print(report["status"])
    return 0 if report["passed"] else 2 if report["status"] == "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
