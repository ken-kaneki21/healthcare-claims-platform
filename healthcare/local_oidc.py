"""Prepare synthetic, disposable fixtures for the local Keycloak stack."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_urlsafe

from build_platform import build
from train_cost import predict, train

ROOT = Path("out/local-oidc")
ISSUER = "https://localhost:18443/realms/claims"


def prepare(root: Path = ROOT):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    root.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Claims disposable development CA")]
    )
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])

    def certificate(subject, issuer, key):
        return (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=7))
        )

    ca = (
        certificate(ca_name, ca_name, ca_key)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server = (
        certificate(server_name, ca_name, server_key)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.DNSName("keycloak")]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    (root / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (root / "server.pem").write_bytes(server.public_bytes(serialization.Encoding.PEM))
    (root / "server-key.pem").write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )

    passwords = {
        user: token_urlsafe(24)
        for user in ("analyst-a", "analyst-b", "analyst-c", "observer")
    }
    tenant_mapper = {
        "name": "tenant number",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-usermodel-attribute-mapper",
        "config": {
            "user.attribute": "tenant_id",
            "claim.name": "tenant_id",
            "jsonType.label": "int",
            "access.token.claim": "true",
        },
    }

    def client(name, audience, scopes, lifetime="300"):
        return {
            "clientId": name,
            "protocol": "openid-connect",
            "enabled": True,
            "publicClient": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "attributes": {
                "access.token.header.type.rfc9068": "true",
                "access.token.lifespan": lifetime,
            },
            "defaultClientScopes": scopes,
            "protocolMappers": [
                tenant_mapper,
                {
                    "name": "subject",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-sub-mapper",
                    "config": {"access.token.claim": "true"},
                },
                {
                    "name": "realm access roles",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-usermodel-realm-role-mapper",
                    "config": {
                        "claim.name": "realm_access.roles",
                        "jsonType.label": "String",
                        "multivalued": "true",
                        "access.token.claim": "true",
                    },
                },
                {
                    "name": "resource audience",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {
                        "included.custom.audience": audience,
                        "access.token.claim": "true",
                    },
                },
            ],
        }

    realm = {
        "realm": "claims",
        "enabled": True,
        "sslRequired": "all",
        "roles": {"realm": [{"name": "claims-analyst"}, {"name": "claims-observer"}]},
        "clientScopes": [
            {
                "name": "claims:read",
                "protocol": "openid-connect",
                "attributes": {"include.in.token.scope": "true"},
            }
        ],
        "clients": [
            client("claims-local", "claims-api", ["claims:read"]),
            client("wrong-audience", "other-api", ["claims:read"]),
            client("no-claims-scope", "claims-api", []),
            client("short-lived", "claims-api", ["claims:read"], "2"),
        ],
        "users": [
            {
                "username": user,
                "firstName": "Fictional",
                "lastName": user,
                "email": f"{user}@example.invalid",
                "emailVerified": True,
                "enabled": True,
                "realmRoles": [
                    "claims-observer" if user == "observer" else "claims-analyst"
                ],
                "attributes": {"tenant_id": [str(min(index, 3))]},
                "credentials": [
                    {"type": "password", "value": password, "temporary": False}
                ],
            }
            for index, (user, password) in enumerate(passwords.items(), 1)
        ],
    }
    (root / "claims-realm.json").write_text(json.dumps(realm), encoding="utf-8")
    (root / "credentials.json").write_text(json.dumps(passwords), encoding="utf-8")
    report = build(root / "claims.sqlite", 1000, 42, tenants=3)
    train(root / "claims.sqlite", root / "model.json")
    predict(root / "claims.sqlite", root / "model.json", 21, root / "predictions.csv")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    prepare()
