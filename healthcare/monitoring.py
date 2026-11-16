"""Compare a champion's current features and predictions with its validation reference."""

import math
import sqlite3
from contextlib import closing
from pathlib import Path


def evaluate(
    database: Path,
    period: int,
    bundle: dict,
    *,
    feature_threshold: float = 0.75,
    prediction_threshold: float = 0.25,
):
    import numpy as np

    from healthcare.experiments import FEATURES
    from train_cost import cohort, predict_values

    if not all(
        math.isfinite(value) and value > 0
        for value in (feature_threshold, prediction_threshold)
    ):
        raise ValueError("Drift thresholds must be positive and finite")
    if bundle["features"] != FEATURES or "monitor_reference" not in bundle:
        raise ValueError("Champion needs a matching signed monitoring reference")
    with closing(
        sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    ) as db:
        rows = cohort(db, period, include_target=False)
    if not len(rows):
        raise ValueError("No eligible members in monitoring period")
    ref = bundle["monitor_reference"]
    reports = []
    for tenant in np.unique(rows[:, 0]):
        population = rows[rows[:, 0] == tenant]
        missing = (~np.isfinite(population[:, 2:-1])).sum(axis=0)
        if np.any(missing):
            raise ValueError(
                "Monitoring population contains missing or non-finite features"
            )
        features = population[:, 2:-1].mean(axis=0)
        change = np.abs(features - ref["feature_mean"]) / np.maximum(
            ref["feature_std"], 1.0
        )
        predicted = predict_values(population, bundle["artifact"])
        if not np.all(np.isfinite(predicted)):
            raise ValueError("Non-finite predictions in monitoring population")
        stats = {}
        for label, quantile in (("p50", 0.50), ("p95", 0.95)):
            observed = float(np.quantile(predicted, quantile))
            expected = ref[f"prediction_{label}"]
            shift = abs(observed - expected) / max(1.0, expected)
            stats[label] = {
                "observed_usd": observed,
                "relative_shift": shift,
                "alert": shift >= prediction_threshold,
            }
        reports.append(
            {
                "tenant": int(tenant),
                "rows": len(population),
                "missing_feature_count": int(missing.sum()),
                "features": {
                    name: {
                        "mean": float(mean),
                        "standardized_shift": float(delta),
                        "alert": bool(delta >= feature_threshold),
                    }
                    for name, mean, delta in zip(FEATURES, features, change)
                },
                "predictions": stats,
                "alert": bool(
                    np.any(change >= feature_threshold)
                    or any(item["alert"] for item in stats.values())
                ),
            }
        )
    return {
        "version": bundle["version"],
        "period": period,
        "feature_threshold": feature_threshold,
        "prediction_threshold": prediction_threshold,
        "tenants": reports,
    }
