"""Build synthetic evidence and stage the signed offline investigation demo."""

import argparse
import copy
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from healthcare.experiments import compare
from healthcare.forecast_snapshot import fingerprint, load, publish
from healthcare.registry import register, transition
from healthcare.scale import run


def prepare(root: Path, secret: str, members: int = 1500):
    import numpy as np

    from train_cost import cohort, predict_values

    scale = run(root, members, tenants=3)
    close = root / "close.sqlite"
    training = compare(close, root / "experiment.json", strict_timeline=True)
    bundle = training["registry_bundle"]
    with closing(sqlite3.connect(close)) as db:
        all_rows = cohort(db, training["periods"]["validation"])
    rows = all_rows[
        (all_rows[:, 0] == 1) & (all_rows[:, 1] % 5 != 0) & (all_rows[:, 1] % 7 == 0)
    ]
    previous = copy.deepcopy(bundle)
    for offset in (1, -1, 5, -5, 20, -20):
        previous["artifact"]["intercept"] = bundle["artifact"]["intercept"] + offset
        previous["validation_mae_usd"] = float(
            np.abs(predict_values(rows, previous["artifact"]) - rows[:, -1]).mean()
        )
        if (
            bundle["validation_mae_usd"]
            < previous["validation_mae_usd"]
            < bundle["baseline_validation_mae_usd"]
        ):
            break
    else:
        raise ValueError(
            "Could not stage a weaker approved synthetic validation candidate"
        )

    registry = root / "registry.sqlite"
    first = root / "forecast-previous.json"
    active = root / "forecast.json"
    rolled_back = root / "forecast-rollback.json"
    with closing(sqlite3.connect(registry)) as db:
        register(db, "ridge-previous", previous, secret)
        initial = transition(db, secret, "ridge-previous")
        publish(close, registry, 21, first, secret)
        register(db, "ridge-approved", bundle, secret)
        promoted = transition(db, secret, "ridge-approved")
        publish(close, registry, 21, active, secret)
        rejection = None
        try:
            transition(db, secret, "ridge-previous")
        except ValueError as error:
            rejection = str(error)
        if rejection != "Candidate did not beat champion":
            raise RuntimeError("Expected a validation-gated rejection")
        rollback = transition(db, secret)
        publish(close, registry, 21, rolled_back, secret)
        transition(db, secret, "ridge-approved")
    initial_snapshot = load(first, close, secret)
    active_snapshot = load(active, close, secret)
    rollback_snapshot = load(rolled_back, close, secret)
    if initial_snapshot["by_tenant"] != rollback_snapshot["by_tenant"]:
        raise RuntimeError("Rollback did not reproduce the previous forecast")

    def totals(snapshot):
        return {
            tenant: sum(rows.values()) for tenant, rows in snapshot["by_tenant"].items()
        }

    report = {
        "members": members,
        "close_sha256": fingerprint(close),
        "close_fact_mismatches": scale["close_fact_mismatches"],
        "closes": scale["journal_close"]["closes"],
        "initial": initial,
        "promoted": promoted,
        "rejected": rejection,
        "rollback": rollback,
        "previous_validation_mae_usd": previous["validation_mae_usd"],
        "champion_validation_mae_usd": bundle["validation_mae_usd"],
        "prediction_totals_cents": {
            "previous": totals(initial_snapshot),
            "approved": totals(active_snapshot),
            "rollback": totals(rollback_snapshot),
        },
    }
    (root / "lifecycle.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("out/integrated"))
    parser.add_argument("--members", type=int, default=1500)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(args.out, os.environ["CLAIMS_REGISTRY_SECRET"], args.members),
            indent=2,
        )
    )
