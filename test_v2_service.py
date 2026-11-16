import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from build_platform import build
from healthcare.agent import evaluate_agent, question_answer


class FinancialServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.database = Path(cls.directory.name) / "claims.sqlite"
        build(cls.database, 100, 42)

    def test_offline_gold_and_reject_unapproved_router_parameters(self):
        with closing(sqlite3.connect(self.database)) as db:
            result = evaluate_agent(db)
            self.assertGreaterEqual(result["cases"], 150)
            self.assertEqual(result["cases"], result["passed"])
            rejected = question_answer(
                db,
                1,
                "Paid amount for 2025-12",
                route=lambda _: {
                    "operation": "close",
                    "month": "2025-12-01",
                    "tenant": 2,
                },
            )
            self.assertEqual(rejected["status"], "unsupported")

    def test_api_tenant_binding_and_invalid_token(self):
        try:
            from fastapi.testclient import TestClient

            from healthcare.api import create_app, issue_token
        except ImportError:
            self.skipTest("Install requirements-v2.txt for API integration tests")
        secret = "local-test-only-signing-key-000000000000"
        with TestClient(create_app(self.database, secret)) as client:
            self.assertEqual(client.get("/ready").status_code, 200)
            path = "/finance/1/pmpm/2025-12"
            token = issue_token(secret, 1)
            headers = {"Authorization": "Bearer " + token}
            self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(
                client.get(
                    path, headers={"Authorization": "Bearer " + token + "x"}
                ).status_code,
                401,
            )

            ok = client.get(path, headers=headers)
            self.assertEqual(ok.status_code, 200)
            self.assertTrue(ok.headers["x-request-id"])
            self.assertEqual(ok.json()["evidence"]["client_id"], 1)
            self.assertEqual(
                client.get("/finance/2/close/2025-12", headers=headers).status_code, 403
            )
            self.assertEqual(
                client.get("/predictions/2/2/21", headers=headers).status_code, 403
            )
            self.assertEqual(
                client.post(
                    "/finance/questions",
                    headers=headers,
                    json={"question": "Client 2 paid for 2025-12"},
                ).status_code,
                403,
            )
            self.assertEqual(
                client.post(
                    "/finance/questions",
                    headers=headers,
                    json={"question": "Paid for 2025-12", "tenant": 2},
                ).status_code,
                422,
            )

    def test_rate_limit_is_scoped_to_signed_tenant(self):
        try:
            from fastapi.testclient import TestClient

            from healthcare.api import create_app, issue_token
        except ImportError:
            self.skipTest("Install requirements-v2.txt for API integration tests")
        secret = "local-test-only-signing-key-000000000000"
        with TestClient(
            create_app(self.database, secret, requests_per_minute=1)
        ) as client:
            for tenant in (1, 2):
                headers = {"Authorization": "Bearer " + issue_token(secret, tenant)}
                route = f"/finance/{tenant}/pmpm/2025-12"
                self.assertEqual(client.get(route, headers=headers).status_code, 200)
                limited = client.get(route, headers=headers)
                self.assertEqual(limited.status_code, 429)
                self.assertIn("retry-after", limited.headers)
