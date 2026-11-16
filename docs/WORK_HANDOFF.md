# V2 work checkpoint

Branch: `feature/v2-integrated-ai-platform`. This checkpoint is based on
`5d965ea4697ec78dd76d66d9b4ab0870017b9cf2`. Run `git rev-parse HEAD` to obtain the hash
containing this document. Follow [PR #1](https://github.com/ken-kaneki21/healthcare-claims-platform/pull/1)
for the published branch and CI.

## Current implementation

- `platform.sql`, `build_platform.py`, and `analytics/models/monthly_finance.sql` add dated client rules and update existing month aggregates when source facts change.
- `healthcare/ingest.py` and `healthcare/scale.py` introduce ordered primary-key extraction, grouped claim validation, atomic deduplication, and a repeatable interrupted replay and backfill measurement.
- `healthcare/experiments.py`, `train_cost.py`, `healthcare/registry.py`, `healthcare/monitoring.py`, and `healthcare/cli.py` add validation-only search, cohort error metrics, signed baseline distributions, and monitoring on features available at prediction time.
- `healthcare/agent.py`, `healthcare/api.py`, and `healthcare/identity.py` add evidence-backed two-month comparisons, optional hosted question routing, and issuer-, audience-, and scope-validated JWT access.
- `Dockerfile`, `compose.yaml`, `compose.predictions.yaml`, `requirements-serving.txt`, `requirements-v2.txt`, and `.github/workflows/tests.yml` separate serving dependencies, add resource limits, and test persistent inputs through service restart.
- `test_journal_close.py`, `test_oidc.py`, `test_financial_questions.py`, and `test_model_monitoring.py` cover dated rules, identity, independent finance cases and drift.

## Reproduction

```powershell
python -m pip install -r requirements-v2.txt -r requirements-analytics.txt
python -m unittest discover -v
ruff check healthcare test_oidc.py test_financial_questions.py test_model_monitoring.py
python -m healthcare.scale --members 50000 --out out/release-scale-50000
python -m healthcare.scale --members 1000 --tenants 3 --out out/release-three-client
python -m healthcare.cli eval-agent --database out/release-three-client/close.sqlite --out out/release-agent.json
```

Use new output directories for each benchmark. The benchmark records recovery, duplicate replay, close parity, and process peak memory. See the evidence and output paths in the implementation status.

## Environment and release gates

Windows, 12 logical processors, Python 3.10 for the original suite and a separate Python 3.14 CPU training environment. Docker Desktop engine 29.3.1 and Compose 5.1.1 were reachable from the host. Port 8000 was occupied during testing, so a separate loopback port was used. The local LLM runtime and hosted credentials were not configured. The full-scale dataset and model binaries stay under ignored `out/`.

Use a provider-approved environment for live evaluation, verify a real OIDC issuer against the deployment, and keep PR #1 in draft while any mandatory gate remains open. See [release status](IMPLEMENTATION_STATUS.md) for measured results, audit findings and open work.
