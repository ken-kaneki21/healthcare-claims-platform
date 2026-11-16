"""Bounded, tenant-scoped investigations over an approved forecast and close."""

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from time import monotonic

from healthcare.agent import MONTH, POLICY, question_answer

STATES = (
    "REQUEST_RECEIVED",
    "AUTHORIZED",
    "INTENT_CLASSIFIED",
    "TOOLS_SELECTED",
    "TOOLS_EXECUTED",
    "RESULTS_VALIDATED",
    "ANSWER_GENERATED",
    "ANSWER_VERIFIED",
    "COMPLETED",
)
FORECAST = re.compile(
    r"\b(?:forecasts?|predictions?|model version|model validation|drift)\b",
    re.IGNORECASE,
)
ACTUALS = re.compile(
    r"\b(?:actuals?|variance|difference|movement|compare|why)\b", re.IGNORECASE
)
SIDE_EFFECT = re.compile(
    r"\b(?:execute|run|write|delete|deploy|switch|override)\b.*\b(?:sql|shell|model|tenant|tool|table)\b",
    re.IGNORECASE,
)


class EvidenceUnavailable(Exception):
    """The requested result cannot be supported by the approved inputs."""


def metadata(snapshot, tenant):
    return {
        "tenant_id": tenant,
        "model_version": snapshot["model_version"],
        "as_of": snapshot["as_of"],
        "horizon_end_exclusive": snapshot["horizon_end_exclusive"],
        "prediction_timestamp": snapshot["generated_at"],
        "evidence_id": snapshot["snapshot_id"],
        "units": "USD cents",
        "estimate_type": "point forecast",
    }


def cohort_tool(db, tenant, snapshot, members):
    # SUM on the selected served members only. Both receipt and service bounds
    # are half-open, matching the training label in train_cost.cohort.
    covered, latest = db.execute(
        "SELECT max(starts), (SELECT max(cutoff) FROM close_run) FROM month"
    ).fetchone()
    if covered is None or latest is None:
        raise EvidenceUnavailable("Reporting coverage is unavailable")
    window_covered = db.execute(
        "SELECT count(*) FROM month WHERE starts>=? AND starts<?",
        (snapshot["as_of"], snapshot["horizon_end_exclusive"]),
    ).fetchone()[0]
    cutoff = snapshot["actual_receipt_cutoff_exclusive"]
    if window_covered != 3 or latest < cutoff:
        raise EvidenceUnavailable("Actuals have not matured for all forecast months")
    actual, prior, entries = db.execute(
        """
        SELECT coalesce(sum(CASE WHEN d.starts>=:start AND p.received_date<:cutoff
                            THEN p.delta_cents END),0),
               coalesce(sum(CASE WHEN d.starts<:start AND p.received_date<:start
                            THEN p.delta_cents END),0),
               count(CASE WHEN d.starts>=:start AND p.received_date<:cutoff THEN 1 END)
        FROM payment_event p JOIN claim c ON c.id=p.claim_id
        JOIN month d ON d.id=c.month_id
        WHERE c.client_id=:tenant AND c.member_id IN (SELECT value FROM json_each(:members))
          AND d.starts>=date(:start,'-3 months') AND d.starts<:end
        """,
        {
            "start": snapshot["as_of"],
            "end": snapshot["horizon_end_exclusive"],
            "cutoff": cutoff,
            "tenant": tenant,
            "members": json.dumps(list(members)),
        },
    ).fetchone()
    return {
        "source": "payment_event / claim / month",
        "row_count": entries,
        "actual_receipt_cutoff_exclusive": cutoff,
        "actual_cents": actual,
        "prior_quarter_as_of_cents": prior,
    }


def verify_actuals(db, tenant, snapshot, members, actual):
    window = db.execute(
        "SELECT id FROM month WHERE starts=?", (snapshot["as_of"],)
    ).fetchone()
    if window is None:
        raise EvidenceUnavailable("Forecast period is absent from reporting")
    index = window[0]
    cohort = json.dumps(list(members))
    for field, start, end, cutoff in (
        ("actual_cents", index, index + 2, snapshot["actual_receipt_cutoff_exclusive"]),
        ("prior_quarter_as_of_cents", index - 3, index - 1, snapshot["as_of"]),
    ):
        expected = db.execute(
            """
            SELECT coalesce(sum(p.delta_cents),0)
            FROM payment_event p WHERE p.received_date<? AND p.claim_id IN (
                SELECT id FROM claim WHERE client_id=? AND month_id BETWEEN ? AND ?
                  AND member_id IN (SELECT value FROM json_each(?))
            )
            """,
            (cutoff, tenant, start, end, cohort),
        ).fetchone()[0]
        if type(actual.get(field)) is not int or actual[field] != expected:
            raise EvidenceUnavailable(
                "Financial tool output differs from the payment ledger"
            )


def late_correction(db, tenant, evidence):
    row = db.execute(
        """
        SELECT c.id,p.line_no,p.version,p.received_date,p.delta_cents
        FROM payment_event p JOIN claim c ON c.id=p.claim_id
        JOIN month d ON d.id=c.month_id
        WHERE c.client_id=? AND d.starts=? AND p.received_date>? AND p.received_date<=?
          AND p.version>1 AND p.delta_cents<>0
        ORDER BY abs(p.delta_cents) DESC,c.id,p.line_no,p.version LIMIT 1
        """,
        (tenant, evidence["month"], evidence["original_cutoff"], evidence["cutoff"]),
    ).fetchone()
    return {
        "name": "late_correction",
        "source": "payment_event / claim / month",
        "tenant_id": tenant,
        "row_count": int(row is not None),
        "example": dict(
            zip(
                ("claim_id", "line_no", "version", "received_date", "net_effect_cents"),
                row,
            )
        )
        if row is not None
        else None,
    }


class Investigations:
    def __init__(self, claims_uri: str, checkpoints: Path, snapshot: dict, router):
        self.claims_uri = claims_uri
        self.checkpoints = checkpoints
        self.snapshot = snapshot
        self.router = router
        with closing(sqlite3.connect(checkpoints)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS investigation (tenant INTEGER, request_id TEXT, "
                "request_hash TEXT, evidence TEXT NOT NULL, PRIMARY KEY(tenant,request_id))"
            )

    def run(
        self,
        tenant: int,
        request_id: str,
        question: str,
        period: int | None,
        version: str | None,
    ):
        snapshot = self.snapshot
        key = (tenant, request_id)
        digest = hashlib.sha256(
            json.dumps([question, period, version, snapshot["snapshot_id"]]).encode()
        ).hexdigest()
        with closing(sqlite3.connect(self.checkpoints, timeout=2)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO investigation VALUES (?,?,?,?)",
                (
                    *key,
                    digest,
                    json.dumps({"status": "retryable", "trace": list(STATES[:2])}),
                ),
            )
            existing = db.execute(
                "SELECT request_hash,evidence FROM investigation WHERE tenant=? AND request_id=?",
                key,
            ).fetchone()
            if existing and existing[0] != digest:
                return {"status": "conflict"}
            if existing:
                saved = json.loads(existing[1])
                if saved.get("status") != "retryable":
                    return saved
        trace = list(STATES[:4])
        try:
            result = self.execute(tenant, question, period, version)
        except EvidenceUnavailable as error:
            result = {"status": "no_evidence", "reason": str(error)}
        except (sqlite3.OperationalError, TimeoutError):
            result = {
                "status": "retryable",
                "reason": "A read was interrupted. Retry with the same request ID.",
            }
        if result["status"] == "ok":
            result["trace"] = list(STATES)
        else:
            result["trace"] = (trace[:2] if result["status"] == "denied" else trace) + [
                "ESCALATED"
            ]
        result["request_id"] = request_id
        with closing(sqlite3.connect(self.checkpoints, timeout=2)) as db, db:
            db.execute(
                "INSERT INTO investigation VALUES (?,?,?,?) ON CONFLICT(tenant,request_id) "
                "DO UPDATE SET evidence=excluded.evidence WHERE investigation.request_hash=excluded.request_hash "
                "AND json_extract(investigation.evidence,'$.status')='retryable'",
                (*key, digest, json.dumps(result, allow_nan=False)),
            )
            stored_hash, stored = db.execute(
                "SELECT request_hash,evidence FROM investigation WHERE tenant=? AND request_id=?",
                key,
            ).fetchone()
        return json.loads(stored) if stored_hash == digest else {"status": "conflict"}

    def execute(self, tenant, question, period, version):
        if POLICY.search(question) or SIDE_EFFECT.search(question):
            return {"status": "denied"}
        with closing(sqlite3.connect(self.claims_uri, uri=True, timeout=2)) as db:
            if not FORECAST.search(question):
                historical = question_answer(db, tenant, question, self.router)
                tools = [
                    {
                        "name": "financial_close",
                        "source": historical.get("evidence", {}).get("view"),
                    }
                ]
                if (
                    historical.get("status") == "ok"
                    and historical.get("operation") == "restatement"
                ):
                    tools.append(late_correction(db, tenant, historical["evidence"]))
                return {**historical, "tools": tools}
            snapshot = self.snapshot
            deadline = monotonic() + 4
            db.set_progress_handler(lambda: int(monotonic() > deadline), 10000)
            months = set(MONTH.findall(question))
            if len(months) > 1:
                return {"status": "ambiguous"}
            if (
                (period is not None and period != snapshot["period"])
                or (version is not None and version != snapshot["model_version"])
                or (months and months != {snapshot["as_of"][:7]})
            ):
                raise EvidenceUnavailable(
                    "No approved snapshot matches the requested period or version"
                )
            members = snapshot["by_tenant"][tenant]
            if not members:
                raise EvidenceUnavailable(
                    "No forecasts exist for the authorized cohort"
                )
            evidence = metadata(snapshot, tenant)
            values = {"count": len(members), "forecast_cents": sum(members.values())}
            tools = [
                {
                    "name": "approved_forecast",
                    "source": "signed forecast snapshot",
                    "row_count": len(members),
                }
            ]
            if ACTUALS.search(question):
                actual = cohort_tool(db, tenant, snapshot, members)
                verify_actuals(db, tenant, snapshot, members, actual)
                values.update(
                    {
                        key: actual[key]
                        for key in ("actual_cents", "prior_quarter_as_of_cents")
                    }
                )
                values["actual_minus_forecast_cents"] = (
                    actual["actual_cents"] - values["forecast_cents"]
                )
                values["forecast_minus_prior_cents"] = (
                    values["forecast_cents"] - actual["prior_quarter_as_of_cents"]
                )
                tools.append({"name": "matured_actual_and_prior", **actual})
            if re.search(r"\b(?:drift|model validation)\b", question, re.IGNORECASE):
                report = next(
                    (
                        row
                        for row in snapshot["drift"]["tenants"]
                        if row["tenant"] == tenant
                    ),
                    None,
                )
                if report is None or report["rows"] != len(members):
                    raise EvidenceUnavailable(
                        "Monitoring evidence disagrees with the serving cohort"
                    )
                tools.append(
                    {
                        "name": "model_monitor",
                        "source": "signed monitoring snapshot",
                        "model_version": snapshot["model_version"],
                        "report": report,
                    }
                )
                evidence["validation_mae_usd"] = snapshot["validation_mae_usd"]
                evidence["validation_sha256"] = snapshot["validation_sha256"]
            summary = f"The approved forecast totals {values['forecast_cents']} USD cents across {values['count']} members."
            if "actual_cents" in values:
                summary += (
                    f" Matured actuals total {values['actual_cents']} USD cents."
                    f" Actuals minus forecast is {values['actual_minus_forecast_cents']} USD cents."
                    f" Forecast minus prior-quarter paid cost is {values['forecast_minus_prior_cents']} USD cents."
                )
            return {
                "status": "ok",
                "values": values,
                "evidence": evidence,
                "tools": tools,
                "summary": summary,
            }
