"""Run temporal cost experiments on the existing point-in-time cohort builder."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path


def compare(
    database: Path, output: Path, tracking: Path | None = None, torch_cpu: bool = False,
    shift_database: Path | None = None,
):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    from train_cost import cohort

    with closing(
        sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    ) as db:
        history = np.concatenate([cohort(db, index) for index in (7, 10, 13)])
        validation = cohort(db, 17)
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
            raise ValueError("Shift evaluation requires a separately generated database")
        with closing(sqlite3.connect(f"{shift_database.resolve().as_uri()}?mode=ro", uri=True)) as db:
            shifted = cohort(db, 21)
        if len(shifted) == 0:
            raise ValueError("Shift cohort is empty")
        tests["independent_population"] = splits["independent_population"] = shifted

    models = {
        "ridge": make_pipeline(StandardScaler(), Ridge(alpha=100)),
        "hist_gradient_boosting": HistGradientBoostingRegressor(
            max_iter=80, max_leaf_nodes=15, l2_regularization=10, random_state=42
        ),
    }
    for model in models.values():
        model.fit(train[:, 2:-1], train[:, -1])
    # Drop the three-month spend feature and measure the change on validation only.
    feature_columns = [2, 3, 5, 6]
    ablated = make_pipeline(StandardScaler(), Ridge(alpha=100))
    ablated.fit(train[:, feature_columns], train[:, -1])
    ablated_mae = float(np.abs(np.maximum(0, ablated.predict(valid[:, feature_columns]))-valid[:,-1]).mean())
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
    for name, rows in {"validation": valid, **tests}.items():
        truth = rows[:, -1]
        predictions = {"prior_quarter": rows[:, 4]}
        predictions.update(
            {
                key: np.maximum(0, model.predict(rows[:, 2:-1]))
                for key, model in models.items()
            }
        )
        if torch_cpu:
            predictions["torch_mlp"] = neural_prediction(rows[:, 2:-1])
        results[name] = {}
        for model_name, values in predictions.items():
            error = values - truth
            results[name][model_name] = {
                "mae_usd": float(np.abs(error).mean()),
                "rmse_usd": float(np.sqrt((error**2).mean())),
            }
    manifest = {
        name: {"rows": len(data), "sha256": hashlib.sha256(data.tobytes()).hexdigest()}
        for name, data in splits.items()
    }
    report = {
        "experiment_version": "v2-cost-comparison-1",
        "seed": 42,
        "target": "next three service months, 90-day arrival completion",
        "periods": {"train": [7, 10, 13], "validation": 17, "test": 21},
        "splits": manifest,
        "metrics": results,
        "torch_cpu": torch_cpu,
        "validation_ablation_without_recent_spend_mae_usd": ablated_mae,
    }
    scaler, fitted = (step[1] for step in models["ridge"].steps)
    report["registry_bundle"] = {
        "features": [
            "age_band",
            "high_needs",
            "paid_3_months_usd",
            "paid_6_months_usd",
            "claim_count_6_months",
        ],
        "training_sha256": manifest["train"]["sha256"],
        "validation_sha256": manifest["validation"]["sha256"],
        "validation_mae_usd": results["validation"]["ridge"]["mae_usd"],
        "baseline_validation_mae_usd": results["validation"]["prior_quarter"][
            "mae_usd"
        ],
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
                        }
                    )
            mlflow.log_artifact(str(output))
    return report
