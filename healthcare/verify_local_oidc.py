"""Exercise real Keycloak access tokens over TLS and the local claims API."""

import argparse
import csv
import json
import os
import ssl
import time
from unittest.mock import patch

import httpx
import jwt

from healthcare.identity import OidcIdentity
from healthcare.local_oidc import ISSUER, ROOT

API = "http://127.0.0.1:18764"


def verify(*, model: bool, restart_check: bool):
    passwords = json.loads((ROOT / "credentials.json").read_text(encoding="utf-8"))
    tls = ssl.create_default_context(cafile=ROOT / "ca.pem")
    with (
        httpx.Client(verify=tls, trust_env=False, timeout=25) as issuer,
        httpx.Client(trust_env=False, timeout=25) as service,
        (ROOT / "predictions.csv").open(encoding="utf-8", newline="") as predictions,
    ):
        discovery = issuer.get(ISSUER + "/.well-known/openid-configuration")
        discovery.raise_for_status()
        metadata = discovery.json()
        if metadata["issuer"] != ISSUER:
            raise RuntimeError("Unexpected discovery issuer")
        jwks = issuer.get(metadata["jwks_uri"])
        jwks.raise_for_status()
        members = {}
        for row in csv.DictReader(predictions):
            members.setdefault(int(row["client_id"]), row["member_id"])

        def token(user, client="claims-local"):
            response = issuer.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "password",
                    "client_id": client,
                    "username": user,
                    "password": passwords[user],
                    "scope": "openid",
                },
            )
            response.raise_for_status()
            return response.json()["access_token"]

        checks = {"discovery": discovery.status_code, "jwks": jwks.status_code}

        def check(label, path, expected, access=None, body=None):
            headers = {"Authorization": f"Bearer {access}"} if access else {}
            response = service.request(
                "POST" if body else "GET", API + path, headers=headers, json=body
            )
            if response.status_code != expected:
                raise RuntimeError(
                    f"{label}: HTTP {response.status_code}, expected {expected}"
                )
            checks[label] = response.status_code
            return response.json()

        check("ready", "/ready", 200)
        a = token("analyst-a")
        finance = "/finance/1/pmpm/2025-12"
        if restart_check:
            check("finance_after_restart", finance, 200, a)
            check("prediction_after_restart", f"/predictions/1/{members[1]}/21", 200, a)
            return checks
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(ROOT / "ca.pem")}):
            different_issuer = OidcIdentity(ISSUER + "-other", "claims-api", metadata["jwks_uri"])
            try:
                different_issuer(a)
            except ValueError as error:
                if not isinstance(error.__cause__, jwt.InvalidIssuerError):
                    raise
                checks["wrong_issuer_real_token"] = "rejected"
            else:
                raise RuntimeError("Verifier accepted a real token with the wrong issuer")

        for index, analyst in enumerate(("analyst-a", "analyst-b", "analyst-c"), 1):
            access = token(analyst)
            check(
                f"tenant_{index}_finance", f"/finance/{index}/pmpm/2025-12", 200, access
            )
            check(
                f"tenant_{index}_prediction",
                f"/predictions/{index}/{members[index]}/21",
                200,
                access,
            )
        check("anonymous", finance, 401)
        check("cross_tenant_finance", "/finance/2/pmpm/2025-12", 403, a)
        check("cross_tenant_prediction", f"/predictions/2/{members[2]}/21", 403, a)
        check(
            "cross_tenant_agent",
            "/finance/questions",
            403,
            a,
            {"question": "Client 2 paid amount in 2025-12"},
        )
        check("wrong_role", finance, 401, token("observer"))
        check("wrong_audience", finance, 401, token("analyst-a", "wrong-audience"))
        check("missing_scope", finance, 401, token("analyst-a", "no-claims-scope"))
        left, middle, signature = a.split(".")
        replacement = "A" if signature[0] != "A" else "B"
        check(
            "tampered_signature",
            finance,
            401,
            ".".join((left, middle, replacement + signature[1:])),
        )
        check(
            "oversized_question", "/finance/questions", 422, a, {"question": "x" * 501}
        )
        check("invalid_period", "/finance/1/pmpm/2025-13", 422, a)
        expiring = token("analyst-a", "short-lived")
        check("short_lived_before_expiry", finance, 200, expiring)
        time.sleep(3)
        check("expired", finance, 401, expiring)
        text = (
            "What was the per-member-per-month paid cost in 2025-12?"
            if model
            else "PMPM for 2025-12"
        )
        result = check("agent", "/finance/questions", 200, a, {"question": text})
        expected = check("agent_oracle", finance, 200, a)
        if result["values"] != expected["values"]:
            raise RuntimeError("Agent output differs from the financial tool")
        return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="store_true")
    parser.add_argument("--restart-check", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(verify(model=args.model, restart_check=args.restart_check), indent=2)
    )
