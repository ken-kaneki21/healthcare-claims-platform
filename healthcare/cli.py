"""Discoverable Windows/Linux commands for the local claims platform."""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from build_platform import build
from healthcare.agent import evaluate_agent
from healthcare.ingest import load_files, replay_feed


def evaluate(path: Path, live=False):
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        if live:
            import httpx

            from healthcare.agent import provider_router

            endpoint = os.environ["CLAIMS_LLM_ENDPOINT"]
            if not endpoint.startswith("https://"):
                raise ValueError("CLAIMS_LLM_ENDPOINT must use HTTPS")
            model = os.environ["CLAIMS_LLM_MODEL"]
            with httpx.Client() as client:
                route, usage = provider_router(
                    client, endpoint, os.environ["CLAIMS_LLM_API_KEY"], model
                )
                report = evaluate_agent(db, route, model)
            report["provider_requests"] = usage["requests"]
            report["reported_tokens"] = usage["tokens"]
        else:
            report = evaluate_agent(db)
            report["reported_tokens"] = 0
    if not live and report["passed"] != report["cases"]:
        raise RuntimeError("Financial evaluation gate failed")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "smoke",
            "full-build",
            "benchmark",
            "eval-agent",
            "train",
            "serve",
            "token",
            "ingest",
            "replay-feed",
            "journal-close",
            "register-model",
            "promote-model",
            "rollback-model",
            "predict-model",
            "release-check",
        ),
    )
    parser.add_argument("--database", type=Path, default=Path("out/v2.sqlite"))
    parser.add_argument("--out", type=Path, default=Path("out/v2-evidence.json"))
    parser.add_argument("--members", type=int, default=10000)
    parser.add_argument("--tenants", type=int, choices=(2, 3), default=2)
    parser.add_argument("--provider", choices=("mock", "live"), default="mock")
    parser.add_argument("--allow-billed", action="store_true")
    parser.add_argument("--tracking", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--model-report", type=Path)
    parser.add_argument("--period", type=int, choices=range(7, 25), default=21)
    parser.add_argument("--torch-cpu", action="store_true")
    parser.add_argument("--shift-database", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--tenant", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    if args.command in ("smoke", "full-build", "benchmark"):
        members = {"smoke": 1000, "full-build": 50000}.get(args.command, args.members)
        report = build(args.database, members, 42, args.tenants)
        if args.command == "smoke":
            report["agent"] = evaluate(args.database)
            report["replay"] = replay_feed(
                args.database, args.out.with_suffix(".sqlite"), 1
            )
    elif args.command in ("eval-agent", "release-check"):
        if args.provider == "live" and not args.allow_billed:
            parser.error("Live evaluation requires explicit --allow-billed")
        report = evaluate(args.database, args.provider == "live")
    elif args.command == "train":
        from healthcare.experiments import compare

        report = compare(args.database, args.out, args.tracking, args.torch_cpu, args.shift_database)
    elif args.command == "ingest":
        if args.manifest is None or args.csv is None:
            parser.error("ingest requires --manifest and --csv")
        report = {
            "inserted": load_files(
                args.database, args.manifest, args.csv, args.reference
            )
        }
    elif args.command == "replay-feed":
        if args.reference is None:
            parser.error("replay-feed requires --reference")
        report = replay_feed(args.reference, args.database, args.tenant)
    elif args.command == "journal-close":
        from healthcare.journal_close import rebuild

        if args.reference is None or args.journal is None:
            parser.error("journal-close requires --reference and --journal")
        report = rebuild(args.reference, args.journal, args.database)
    elif args.command in (
        "register-model",
        "promote-model",
        "rollback-model",
        "predict-model",
    ):
        from healthcare.registry import champion, register, transition

        secret = os.environ["CLAIMS_REGISTRY_SECRET"]
        args.database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(args.database)) as db:
            if args.command == "register-model":
                if args.model_report is None or args.version is None:
                    parser.error("register-model requires --model-report and --version")
                bundle = json.loads(args.model_report.read_text(encoding="utf-8"))[
                    "registry_bundle"
                ]
                register(db, args.version, bundle, secret)
                report = {"registered": args.version}
            elif args.command == "predict-model":
                from tempfile import TemporaryDirectory

                from train_cost import predict

                if args.reference is None:
                    parser.error("predict-model requires --reference")
                bundle = champion(db, secret)
                if bundle["features"] != [
                    "age_band",
                    "high_needs",
                    "paid_3_months_usd",
                    "paid_6_months_usd",
                    "claim_count_6_months",
                ]:
                    raise ValueError(
                        "Promoted model does not match the batch feature contract"
                    )
                with TemporaryDirectory() as directory:
                    model_path = Path(directory) / "model.json"
                    model_path.write_text(
                        json.dumps(
                            {"model_version": bundle["version"], **bundle["artifact"]}
                        ),
                        encoding="utf-8",
                    )
                    report = predict(args.reference, model_path, args.period, args.out)
            else:
                if args.command == "promote-model" and args.version is None:
                    parser.error("promote-model requires --version")
                report = transition(
                    db,
                    secret,
                    args.version if args.command == "promote-model" else None,
                )
    elif args.command == "token":
        from healthcare.api import issue_token

        print(issue_token(os.environ["CLAIMS_DEMO_SECRET"], args.tenant))
        return
    else:
        import uvicorn

        from healthcare.api import create_app

        predictions = os.getenv("CLAIMS_PREDICTIONS")
        uvicorn.run(
            create_app(
                args.database,
                os.environ["CLAIMS_DEMO_SECRET"],
                Path(predictions) if predictions else None,
                requests_per_minute=int(os.getenv("CLAIMS_REQUESTS_PER_MINUTE", "120")),
            ),
            host="127.0.0.1",
            port=8000,
        )
        return
    print(json.dumps(report, indent=2))
    if args.command in ("smoke", "full-build", "benchmark", "eval-agent"):
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
