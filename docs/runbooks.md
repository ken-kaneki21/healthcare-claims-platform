# Local runbook

Use a new database path for a clean build. Keep generated databases under `out/`. To retry ingestion, reuse the original immutable payload and manifest. An interrupted transaction inserts neither the pending deliveries nor its watermark. Check the source checksum and header before advancing an out-of-order batch.

If readiness returns 503, check the database path and that the build committed. If API authorization fails, issue a fresh short-lived token using the same local secret as the API. If the Compose configuration passes while startup fails to connect to Docker, start the local daemon and rerun `docker compose up --build`. No cloud execution is required for these checks.

Use `python -m healthcare.cli monitor-model --database out/registry.sqlite --reference out/current.sqlite --period 21 --out out/drift.json` with the registry signing secret in the process environment. Defaults alert at a 0.75 standardized feature-mean shift or a 25% prediction percentile shift. A drift report prompts investigation. Retrain with `python -m healthcare.cli train --database out/current.sqlite --out out/candidate.json`, then compare on a shared validation fingerprint before promotion.
