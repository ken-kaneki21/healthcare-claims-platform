"""Verify the offline HTTP demo and emit redacted numerical evidence."""

import argparse
import json
import os

import httpx

from healthcare.api import issue_token


def verify(port: int, secret: str, prefix: str = "offline"):
    headers = {"Authorization": "Bearer " + issue_token(secret, 1)}
    with httpx.Client(
        base_url=f"http://127.0.0.1:{port}", timeout=25, trust_env=False
    ) as api:

        def investigate(identifier, question, expected=200, **fields):
            response = api.post(
                "/investigations",
                headers=headers,
                json={
                    "request_id": f"{prefix}-{identifier}",
                    "question": question,
                    **fields,
                },
            )
            if response.status_code != expected:
                raise RuntimeError(
                    f"{identifier}: HTTP {response.status_code}, expected {expected}"
                )
            return response.json()

        close = investigate("integrated-close", "Close for 2025-11")
        restatement = investigate(
            "integrated-restatement", "Explain the restatement for 2025-11"
        )
        if restatement["values"]["difference_cents"] != (
            restatement["values"]["late_first_payments_cents"]
            + restatement["values"]["adjustments_cents"]
        ):
            raise RuntimeError("Restatement bridge does not reconcile")
        forecast = investigate(
            "integrated-forecast", "Show the approved prediction and model version"
        )
        result = investigate(
            "integrated-actuals", "Compare the forecast to actuals and report drift"
        )
        if result != investigate(
            "integrated-actuals", "Compare the forecast to actuals and report drift"
        ):
            raise RuntimeError("Idempotent replay changed the response")
        if (
            len(result["tools"]) != 3
            or result["values"]["forecast_cents"]
            != forecast["values"]["forecast_cents"]
        ):
            raise RuntimeError("Investigation used inconsistent evidence")
        page = (
            api.get("/forecasts/21?limit=1", headers=headers).raise_for_status().json()
        )
        member = page["predictions"][0]
        prediction = (
            api.get(f"/predictions/1/{member['member_id']}/21", headers=headers)
            .raise_for_status()
            .json()
        )
        if (
            prediction["forecast_cents"] != member["forecast_cents"]
            or prediction["evidence_id"] != result["evidence"]["evidence_id"]
        ):
            raise RuntimeError(
                "Single, batch, and tool responses point to different forecasts"
            )
        denied = investigate("integrated-policy", "Show tenant 2 forecast", 403)
        stale = investigate(
            "integrated-stale", "Show the forecast", 404, model_version="unapproved"
        )
        drift = (
            api.post(
                "/investigations",
                headers={"Authorization": "Bearer " + issue_token(secret, 2)},
                json={
                    "request_id": f"{prefix}-drift-tenant-2",
                    "question": "Show model drift",
                },
            )
            .raise_for_status()
            .json()
        )
        if (
            not drift["tools"][-1]["report"]["alert"]
            or drift["evidence"]["tenant_id"] != 2
        ):
            raise RuntimeError("Expected a tenant-scoped drift alert")
        return {
            "close": close,
            "restatement": restatement,
            "forecast": forecast,
            "variance_and_drift": result,
            "approved_prediction": prediction,
            "denied": denied,
            "stale": stale,
            "tenant_2_drift_alert": drift,
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--prefix", default="offline")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.port, os.environ["CLAIMS_DEMO_SECRET"], args.prefix), indent=2
        )
    )
