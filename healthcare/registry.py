"""Local registry for signed JSON model bundles and reversible deployment."""

import hashlib
import hmac
import json
import math
import re
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS model(
    version TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS promotion(
    id INTEGER PRIMARY KEY, version TEXT REFERENCES model(version), action TEXT NOT NULL
);
"""


def signature(payload: str, secret: str):
    if len(secret.encode()) < 32:
        raise ValueError("Registry secret must be at least 32 bytes")
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def register(db: sqlite3.Connection, version: str, bundle: dict, secret: str):
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,80}", version):
        raise ValueError("Invalid model version")
    required = (
        "features",
        "training_sha256",
        "validation_sha256",
        "validation_mae_usd",
        "baseline_validation_mae_usd",
        "artifact",
    )
    if not all(field in bundle for field in required):
        raise ValueError("Missing registry metadata")
    if not all(re.fullmatch(r"[0-9a-f]{64}", bundle[field]) for field in required[1:3]):
        raise ValueError("Invalid dataset fingerprint")
    scores = [bundle[field] for field in required[3:5]]
    if not all(
        type(score) in (float, int) and math.isfinite(score) and score >= 0
        for score in scores
    ):
        raise ValueError("Invalid validation scores")
    features = bundle["features"]
    artifact = bundle["artifact"]
    if (
        not isinstance(features, list)
        or not features
        or not all(isinstance(name, str) for name in features)
    ):
        raise ValueError("Invalid feature schema")
    for key in ("mean", "scale", "coefficients"):
        values = artifact.get(key)
        if (
            not isinstance(values, list)
            or len(values) != len(features)
            or not all(
                type(value) in (int, float) and math.isfinite(value) for value in values
            )
        ):
            raise ValueError("Invalid model coefficient shape")
    if any(value <= 0 for value in artifact["scale"]) or not math.isfinite(
        artifact.get("intercept", math.inf)
    ):
        raise ValueError("Invalid model scale or intercept")
    payload = json.dumps(
        {"version": version, **{name: bundle[name] for name in required}},
        sort_keys=True,
        allow_nan=False,
    )
    db.executescript(SCHEMA)
    with db:
        db.execute(
            "INSERT INTO model VALUES (?,?,?)",
            (version, payload, signature(payload, secret)),
        )


def load_bundle(db: sqlite3.Connection, version: str, secret: str):
    row = db.execute(
        "SELECT payload,signature FROM model WHERE version=?", (version,)
    ).fetchone()
    if row is None:
        raise ValueError("Unknown model version")
    if not hmac.compare_digest(row[1], signature(row[0], secret)):
        raise ValueError("Model signature mismatch")
    result = json.loads(row[0])
    if result["version"] != version:
        raise ValueError("Signed model version mismatch")
    return result


def champion(db: sqlite3.Connection, secret: str):
    row = db.execute(
        "SELECT version FROM promotion ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ValueError("No champion has been promoted")
    return load_bundle(db, row[0], secret)


def transition(db: sqlite3.Connection, secret: str, candidate: str | None = None):
    db.executescript(SCHEMA)
    with db:
        db.execute("BEGIN IMMEDIATE")
        history = db.execute(
            "SELECT version FROM promotion ORDER BY id DESC LIMIT 2"
        ).fetchall()
        if candidate is None:
            if len(history) < 2:
                raise ValueError("No prior champion to restore")
            version, action = history[1][0], "rollback"
            load_bundle(db, version, secret)
        else:
            version, action = candidate, "promote"
            bundle = load_bundle(db, version, secret)
            if bundle["validation_mae_usd"] >= bundle["baseline_validation_mae_usd"]:
                raise ValueError("Candidate did not beat validation baseline")
            if history:
                current = load_bundle(db, history[0][0], secret)
                if (
                    current["validation_sha256"] != bundle["validation_sha256"]
                    or current["features"] != bundle["features"]
                ):
                    raise ValueError("Validation data and feature schema must match")
                if bundle["validation_mae_usd"] >= current["validation_mae_usd"]:
                    raise ValueError("Candidate did not beat champion")
        db.execute(
            "INSERT INTO promotion(version,action) VALUES (?,?)", (version, action)
        )
    return {"version": version, "action": action}
