"""Publish and verify the approved forecast that the serving process pins."""

import hashlib
import hmac
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from healthcare.registry import champion, signature


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def publish(database: Path, registry: Path, period: int, output: Path, secret: str):
    from healthcare.experiments import FEATURES
    from healthcare.monitoring import evaluate
    from train_cost import cohort, predict_values

    with closing(
        sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        bundle = champion(db, secret)
    if bundle["features"] != FEATURES:
        raise ValueError("Approved model feature contract does not match")
    before = fingerprint(database)
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        window = db.execute(
            "SELECT starts,date(starts,'+3 months'),date(starts,'+3 months','+90 days') "
            "FROM month WHERE id=?",
            (period,),
        ).fetchone()
        if window is None or not 7 <= period <= 24:
            raise ValueError("Unknown forecast period")
        rows = cohort(db, period, include_target=False)
    estimates = predict_values(rows, bundle["artifact"])
    drift = evaluate(database, period, bundle)
    if before != fingerprint(database):
        raise ValueError("Claims database changed during publication")
    artifact = {
        "schema": 1,
        "database_sha256": before,
        "model_version": bundle["version"],
        "validation_mae_usd": bundle["validation_mae_usd"],
        "validation_sha256": bundle["validation_sha256"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": period,
        "as_of": window[0],
        "horizon_end_exclusive": window[1],
        "actual_receipt_cutoff_exclusive": window[2],
        "predictions": [
            [int(row[0]), int(row[1]), round(float(value) * 100)]
            for row, value in zip(rows, estimates, strict=True)
        ],
        "drift": drift,
    }
    payload = json.dumps(artifact, sort_keys=True, allow_nan=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump({"payload": payload, "signature": signature(payload, secret)}, stream)
    return {"version": bundle["version"], "rows": len(rows), "period": period}


def load(path: Path, database: Path, secret: str):
    envelope = json.loads(path.read_text(encoding="utf-8"))
    payload = envelope["payload"]
    if not hmac.compare_digest(envelope["signature"], signature(payload, secret)):
        raise ValueError("Invalid forecast snapshot signature")
    snapshot = json.loads(payload)
    if snapshot["schema"] != 1 or snapshot["database_sha256"] != fingerprint(database):
        raise ValueError("Forecast snapshot does not match the claims database")
    if (
        snapshot["drift"]["version"] != snapshot["model_version"]
        or snapshot["drift"]["period"] != snapshot["period"]
    ):
        raise ValueError("Drift evidence does not match the served forecast")
    snapshot["snapshot_id"] = hashlib.sha256(payload.encode()).hexdigest()
    snapshot["by_tenant"] = {1: {}, 2: {}, 3: {}}
    for tenant, member, cents in snapshot.pop("predictions"):
        if (
            tenant not in snapshot["by_tenant"]
            or member < 1
            or type(cents) is not int
            or cents < 0
        ):
            raise ValueError("Invalid forecast record")
        members = snapshot["by_tenant"][tenant]
        if member in members:
            raise ValueError("Duplicate forecast record")
        members[member] = cents
    return snapshot
