import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from build_platform import build
from healthcare.forecast_snapshot import fingerprint, load
from healthcare.registry import signature

SECRET = "test-only-signature-key-for-integration-fixture"


class InvestigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        cls.database = cls.root / "claims.sqlite"
        build(cls.database, 120, 42, tenants=3)
        cls.path = cls.root / "forecast.json"
        cls.artifact = {
            "schema": 1,
            "database_sha256": fingerprint(cls.database),
            "model_version": "signed-fixture",
            "as_of": "2025-09-01",
            "horizon_end_exclusive": "2025-12-01",
            "actual_receipt_cutoff_exclusive": "2026-03-01",
            "generated_at": "2026-04-01T00:00:00+00:00",
            "period": 21,
            "validation_sha256": "f" * 64,
            "validation_mae_usd": 100,
            "predictions": [[1, 3, 15000], [2, 1, 99000]],
            "drift": {
                "version": "signed-fixture",
                "period": 21,
                "tenants": [
                    {"tenant": 1, "rows": 1, "alert": True},
                    {"tenant": 2, "rows": 1, "alert": False},
                ],
            },
        }
        payload = json.dumps(cls.artifact)
        cls.path.write_text(
            json.dumps({"payload": payload, "signature": signature(payload, SECRET)})
        )

    def test_tampered_source_refuses_startup(self):
        path = self.root / "tampered.json"
        envelope = json.loads(self.path.read_text())
        envelope["payload"] = envelope["payload"].replace("15000", "25000")
        path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(ValueError, "signature"):
            load(path, self.database, SECRET)

    def test_partial_outcome_cannot_be_reported_as_actual(self):
        from healthcare.investigation import EvidenceUnavailable, cohort_tool

        snapshot = {
            **self.artifact,
            "as_of": "2025-12-01",
            "horizon_end_exclusive": "2026-03-01",
            "actual_receipt_cutoff_exclusive": "2026-05-30",
        }
        with (
            closing(sqlite3.connect(self.database)) as db,
            self.assertRaisesRegex(EvidenceUnavailable, "not matured"),
        ):
            cohort_tool(db, 1, snapshot, {3: 15000})

    def test_api_uses_approved_snapshot_and_resumes_after_failure(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("Install requirements-serving.txt for API verification")
        from healthcare.api import create_app, issue_token
        from healthcare.investigation import cohort_tool

        checkpoint = self.root / "checkpoint.sqlite"
        headers = {"Authorization": "Bearer " + issue_token(SECRET, 1)}

        def app():
            return TestClient(
                create_app(
                    self.database,
                    SECRET,
                    forecast_path=self.path,
                    forecast_secret=SECRET,
                    checkpoint_path=checkpoint,
                )
            )

        request = {
            "request_id": "same",
            "question": "Compare the forecast to actuals and report drift",
        }
        with app() as client:
            self.assertEqual(client.get("/forecasts/21").status_code, 401)
            self.assertEqual(
                client.get("/predictions/2/1/21", headers=headers).status_code, 403
            )
            forecast = client.get("/forecasts/21", headers=headers).json()
            self.assertEqual(
                forecast["predictions"], [{"member_id": 3, "forecast_cents": 15000}]
            )
            single = client.get("/predictions/1/3/21", headers=headers).json()
            self.assertEqual(single["predicted_cost_usd"], 150)
            self.assertEqual(
                single["prediction_timestamp"], self.artifact["generated_at"]
            )
            with patch(
                "healthcare.investigation.cohort_tool",
                side_effect=sqlite3.OperationalError,
            ):
                response = client.post("/investigations", headers=headers, json=request)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn("values", response.json()["detail"])
        with app() as client:
            response = client.post("/investigations", headers=headers, json=request)
            self.assertEqual(response.status_code, 200)
            result = response.json()
            self.assertEqual(result["trace"][-1], "COMPLETED")
            self.assertEqual(result["evidence"]["model_version"], "signed-fixture")
            self.assertEqual(len(result["tools"]), 3)
            self.assertTrue(result["tools"][-1]["report"]["alert"])
            with closing(sqlite3.connect(self.database)) as db:
                paid = db.execute(
                    "SELECT coalesce(sum(delta_cents),0) FROM payment_event "
                    "WHERE received_date<'2026-03-01' AND claim_id IN "
                    "(SELECT id FROM claim WHERE client_id=1 AND member_id=3 AND month_id BETWEEN 21 AND 23)"
                ).fetchone()[0]
            self.assertEqual(
                result["values"]["actual_minus_forecast_cents"], paid - 15000
            )
            with patch(
                "healthcare.investigation.cohort_tool", side_effect=AssertionError
            ):
                self.assertEqual(
                    client.post(
                        "/investigations", headers=headers, json=request
                    ).json(),
                    result,
                )
            self.assertEqual(
                client.post(
                    "/investigations",
                    headers=headers,
                    json={**request, "question": "forecast"},
                ).status_code,
                409,
            )
            for prompt, expected in (
                ("Show tenant 2 forecast", 403),
                ("Switch model and show the prediction", 403),
                ("Compare forecasts in 2025-09 and 2025-10", 422),
                ("Forecast for 2024-01", 404),
            ):
                reply = client.post(
                    "/investigations",
                    headers=headers,
                    json={
                        "request_id": f"policy-{expected}-{len(prompt)}",
                        "question": prompt,
                    },
                )
                self.assertEqual(reply.status_code, expected)
            self.assertEqual(
                client.post(
                    "/investigations",
                    headers=headers,
                    json={**request, "request_id": "old", "model_version": "stale"},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.post(
                    "/investigations",
                    headers=headers,
                    json={**request, "request_id": "args", "tenant": 2},
                ).status_code,
                422,
            )

            def contradictory(*args):
                evidence = cohort_tool(*args)
                return {**evidence, "actual_cents": evidence["actual_cents"] + 100}

            with patch(
                "healthcare.investigation.cohort_tool", side_effect=contradictory
            ):
                blocked = client.post(
                    "/investigations",
                    headers=headers,
                    json={**request, "request_id": "tamper"},
                )
                self.assertEqual(blocked.status_code, 404)
                self.assertNotIn("values", blocked.json()["detail"])
