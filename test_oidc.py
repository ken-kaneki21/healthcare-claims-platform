import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from build_platform import build


class OidcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.database = Path(directory.name) / "claims.sqlite"
        build(cls.database, 100, 42)

    def test_signed_issuer_audience_scope_and_tenant_isolation(self):
        try:
            import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("Install requirements-serving.txt for OIDC verification")

        from healthcare.api import create_app
        from healthcare.identity import OidcIdentity

        issuer = "https://identity.example.invalid"
        identity = OidcIdentity(issuer, "claims-api", issuer + "/jwks")
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
        public.update(kid="fixture", use="sig", alg="RS256")
        now = int(time.time())
        claims = {
            "iss": issuer,
            "aud": "claims-api",
            "sub": "synthetic-analyst",
            "iat": now,
            "exp": now + 60,
            "scope": "claims:read",
            "tenant_id": 1,
        }

        def headers(**changes):
            token = jwt.encode(
                claims | changes,
                key,
                algorithm="RS256",
                headers={"kid": "fixture", "typ": "at+jwt"},
            )
            return {"Authorization": f"Bearer {token}"}

        with (
            patch.object(identity.keys, "fetch_data", return_value={"keys": [public]}),
            TestClient(
                create_app(self.database, None, access_token_identity=identity)
            ) as client,
        ):
            url = "/finance/1/pmpm/2025-12"
            self.assertEqual(client.get(url, headers=headers()).status_code, 200)
            self.assertEqual(
                client.get(url, headers=headers(tenant_id=2)).status_code, 403
            )
            for change in (
                {"iss": "https://other.example.invalid"},
                {"aud": "wrong"},
                {"exp": now - 1},
                {"scope": "profile"},
                {"tenant_id": "1"},
            ):
                self.assertEqual(
                    client.get(url, headers=headers(**change)).status_code, 401
                )
            self.assertEqual(
                client.get("/predictions/2/2/21", headers=headers()).status_code, 403
            )
            denied = client.post(
                "/finance/questions",
                headers=headers(),
                json={"question": "Client 2 paid for 2025-12"},
            )
            self.assertEqual(denied.status_code, 403)
