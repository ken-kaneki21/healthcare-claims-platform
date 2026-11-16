"""Run temporal cost experiments on the existing point-in-time cohort builder."""

import hashlib
import json
import platform
import sqlite3
from contextlib import closing
from pathlib import Path
from time import perf_counter

FEATURES = [
    "age_band",
    "high_needs",
    "paid_3_months_usd",
    "paid_6_months_usd",
    "claim_count_6_months",
]


def seasonal(db, period, rows):
    """Use the same service quarter one year earlier, with a tenure fallback."""
    observations = {}
    for tenant, member, paid in db.execute(
        """
        SELECT e.client_id,e.member_id,coalesce(sum(p.delta_cents),0)
        FROM member_month e
        LEFT JOIN claim c ON c.client_id=e.client_id AND c.member_id=e.member_id
                          AND c.month_id=e.month_id
        LEFT JOIN payment_event p ON p.claim_id=c.id
            AND p.received_date<(SELECT starts FROM month WHERE id=:period)
        WHERE e.month_id BETWEEN :period-12 AND :period-10
        GROUP BY e.client_id,e.member_id HAVING count(DISTINCT e.month_id)=3
        """,
        {"period": period},
    ):
        observations[tenant, member] = paid / 100
    return [observations.get((row[0], row[1]), row[4]) for row in rows]


def compare(
    database: Path,
    output: Path,
    tracking: Path | None = None,
    torch_cpu: bool = False,
    shift_database: Path | None = None,
    *,
    strict_timeline: bool = False,
):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from train_cost import cohort

    training_periods = (7, 8) if strict_timeline else (7, 10, 13)
    validation_period = 14 if strict_timeline else 17
    with closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        if strict_timeline:
            decisions = [(period, validation_period) for period in training_periods]
            decisions.append((validation_period, 21))
            for label_period, decision_period in decisions:
                ordered = db.execute(
                    "SELECT date(a.starts,'+3 months','+90 days') <= b.starts "
                    "FROM month a CROSS JOIN month b WHERE a.id=? AND b.id=?",
                    (label_period, decision_period),
                ).fetchone()
                if ordered != (1,):
                    raise ValueError("Labels were not mature at the next decision date")
        history = np.concatenate([cohort(db, index) for index in training_periods])
        validation = cohort(db, validation_period)
        test = cohort(db, 21)
    train = history[
        (history[:, 0] == 1) & (history[:, 1] % 5 != 0) & (history[:, 1] % 7 != 0)
    ]
    valid = validation[
        (validation[:, 0] == 1)
        & (validation[:, 1] % 5 != 0)
        & (validation[:, 1] % 7 == 0)
    ]
    tests = {
        "unseen_members": test[(test[:, 0] == 1) & (test[:, 1] % 5 == 0)],
        "held_out_client": test[test[:, 0] == 2],
    }
    splits = {"train": train, "validation": valid, **tests}
    identities = {name: set(map(tuple, data[:, :2])) for name, data in splits.items()}
    for i, name in enumerate(splits):
        if any(identities[name] & identities[other] for other in list(splits)[i + 1 :]):
            raise AssertionError("Member identity crosses a split")
    if any(len(rows) == 0 for rows in splits.values()):
        raise ValueError("Use a larger generated population")
    if shift_database:
        if shift_database.resolve() == database.resolve():
            raise ValueError(
                "Shift evaluation requires a separately generated database"
            )
        with closing(
            sqlite3.connect(f"{shift_database.resolve().as_uri()}?mode=ro", uri=True)
        ) as db:
            shifted = cohort(db, 21)
        if len(shifted) == 0:
            raise ValueError("Shift cohort is empty")
        tests["independent_population"] = splits["independent_population"] = shifted

    candidates = {
        "ridge": [
            (alpha, make_pipeline(StandardScaler(), Ridge(alpha=alpha)))
            for alpha in (1, 10, 100, 1000)
        ],
        "hist_gradient_boosting": [
            (
                leaves,
                HistGradientBoostingRegressor(
                    max_iter=80,
                    max_leaf_nodes=leaves,
                    l2_regularization=10,
                    random_state=42,
                ),
            )
            for leaves in (7, 15, 31)
        ],
    }
    models = {}
    search = {}
    selected = {}
    for name, choices in candidates.items():
        scores = {}
        for value, model in choices:
            model.fit(train[:, 2:-1], train[:, -1])
            prediction = np.maximum(0, model.predict(valid[:, 2:-1]))
            scores[value] = float(np.abs(prediction - valid[:, -1]).mean())
        best = min(scores, key=scores.__getitem__)
        models[name] = dict(choices)[best]
        search[name] = scores
        selected[name] = best
    # Drop the three-month spend feature and measure the change on validation only.
    feature_columns = [2, 3, 5, 6]
    ablated = make_pipeline(StandardScaler(), Ridge(alpha=selected["ridge"]))
    ablated.fit(train[:, feature_columns], train[:, -1])
    ablated_mae = float(
        np.abs(
            np.maximum(0, ablated.predict(valid[:, feature_columns])) - valid[:, -1]
        ).mean()
    )
    if torch_cpu:
        import torch

        torch.manual_seed(42)
        torch.set_num_threads(2)
        features = StandardScaler().fit(train[:, 2:-1])
        inputs = torch.from_numpy(features.transform(train[:, 2:-1]).astype("float32"))
        targets = torch.from_numpy((train[:, -1] / 1000).astype("float32")).reshape(
            -1, 1
        )
        network = torch.nn.Sequential(
            torch.nn.Linear(inputs.shape[1], 16),
            torch.nn.ReLU(),
            torch.nn.Linear(16, 1),
        )
        optimizer = torch.optim.Adam(network.parameters(), lr=0.003)
        loss = torch.nn.MSELoss()
        for _ in range(12):
            for batch in torch.randperm(len(inputs)).split(512):
                optimizer.zero_grad()
                loss(network(inputs[batch]), targets[batch]).backward()
                optimizer.step()
        network.eval()

        def neural_prediction(x):
            with torch.no_grad():
                tensor = torch.from_numpy(features.transform(x).astype("float32"))
                return np.maximum(0, network(tensor).numpy().ravel() * 1000)

    results = {}
    timings = {}
    high_cost_threshold = float(np.quantile(train[:, -1], 0.90))
    for name, rows in {"validation": valid, **tests}.items():
        truth = rows[:, -1]
        started = perf_counter()
        predictions = {"prior_quarter": rows[:, 4]}
        if strict_timeline:
            source = shift_database if name == "independent_population" else database
            assert source is not None
            with closing(
                sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
            ) as db:
                predictions["seasonal_naive"] = np.asarray(
                    seasonal(
                        db, validation_period if name == "validation" else 21, rows
                    )
                )
        predictions.update(
            {
                key: np.maximum(0, model.predict(rows[:, 2:-1]))
                for key, model in models.items()
            }
        )
        if torch_cpu:
            predictions["torch_mlp"] = neural_prediction(rows[:, 2:-1])
        results[name] = {}
        prediction_elapsed_ms = (perf_counter() - started) * 1000
        for model_name, values in predictions.items():
            error = values - truth
            results[name][model_name] = {
                "mae_usd": float(np.abs(error).mean()),
                "rmse_usd": float(np.sqrt((error**2).mean())),
                "p95_absolute_error_usd": float(np.quantile(np.abs(error), 0.95)),
                "mean_error_usd": float(error.mean()),
            }
            if strict_timeline:
                denominator = np.abs(truth).sum()
                high = truth >= high_cost_threshold
                results[name][model_name]["wape_percent"] = (
                    float(100 * np.abs(error).sum() / denominator)
                    if denominator
                    else None
                )
                results[name][model_name]["high_cost_mae_usd"] = (
                    float(np.abs(error[high]).mean()) if np.any(high) else None
                )
        # Keep per-model error slices alongside overall errors.
        for model_name, values in predictions.items():
            error = values - truth
            for label, mask in (
                ("standard", rows[:, 3] == 0),
                ("high_needs", rows[:, 3] == 1),
            ):
                if np.any(mask):
                    results[name][model_name][f"{label}_mae_usd"] = float(
                        np.abs(error[mask]).mean()
                    )
        if strict_timeline:
            timings[name] = prediction_elapsed_ms
    manifest = {
        name: {"rows": len(data), "sha256": hashlib.sha256(data.tobytes()).hexdigest()}
        for name, data in splits.items()
    }
    report = {
        "experiment_version": "v2-cost-strict-1"
        if strict_timeline
        else "v2-cost-comparison-2",
        "seed": 42,
        "target": "next three service months, 90-day arrival completion",
        "periods": {
            "train": list(training_periods),
            "validation": validation_period,
            "test": 21,
        },
        "splits": manifest,
        "metrics": results,
        "torch_cpu": torch_cpu,
        "validation_ablation_without_recent_spend_mae_usd": ablated_mae,
        "validation_search_mae_usd": search,
        "selected_parameters": {
            "ridge_alpha": selected["ridge"],
            "boosting_max_leaf_nodes": selected["hist_gradient_boosting"],
        },
    }
    if strict_timeline:
        report.update(
            {
                "environment": {
                    "python": platform.python_version(),
                    "os": platform.system(),
                    "machine": platform.machine(),
                    "processor": platform.processor(),
                },
                "combined_inference_and_seasonal_query_ms": timings,
                "high_cost_threshold_usd": high_cost_threshold,
            }
        )
    scaler, fitted = (step[1] for step in models["ridge"].steps)
    report["ridge_standardized_coefficients"] = dict(
        zip(FEATURES, fitted.coef_.tolist())
    )
    reference_predictions = np.maximum(0, models["ridge"].predict(valid[:, 2:-1]))
    report["registry_bundle"] = {
        "features": FEATURES,
        "training_sha256": manifest["train"]["sha256"],
        "validation_sha256": manifest["validation"]["sha256"],
        "validation_mae_usd": results["validation"]["ridge"]["mae_usd"],
        "baseline_validation_mae_usd": min(
            results["validation"][name]["mae_usd"]
            for name in (
                ("prior_quarter", "seasonal_naive")
                if strict_timeline
                else ("prior_quarter",)
            )
        ),
        "monitor_reference": {
            "feature_mean": valid[:, 2:-1].mean(axis=0).tolist(),
            "feature_std": valid[:, 2:-1].std(axis=0).tolist(),
            "prediction_p50": float(np.median(reference_predictions)),
            "prediction_p95": float(np.quantile(reference_predictions, 0.95)),
        },
        "artifact": {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist(),
            "coefficients": fitted.coef_.tolist(),
            "intercept": float(fitted.intercept_),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if tracking:
        import mlflow

        mlflow.set_tracking_uri("sqlite:///" + tracking.resolve().as_posix())
        mlflow.set_experiment("synthetic-claims-v2")
        with mlflow.start_run(run_name=report["experiment_version"]):
            mlflow.log_params(
                {"seed": 42, "train_rows": len(train), "validation_rows": len(valid)}
            )
            for split, scores in results.items():
                for model, metrics in scores.items():
                    mlflow.log_metrics(
                        {
                            f"{split}.{model}.{metric}": value
                            for metric, value in metrics.items()
                            if value is not None
                        }
                    )
            mlflow.log_artifact(str(output))
    return report
