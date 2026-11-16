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

Windows, AMD Ryzen 5 5600H, 12 logical processors, 16.47 GB physical RAM, Python 3.10 for the original suite and a separate Python 3.14 CPU training environment. Docker Desktop engine 29.3.1 and Compose 5.1.1 were reachable from the host. Port 8000 was occupied during testing, so a separate loopback port was used. No supported local LLM runtime or configured hosted endpoint was found. The full-scale dataset and model binaries stay under ignored `out/`.

Use a provider-approved environment for live evaluation, verify a real OIDC issuer against the deployment, and keep PR #1 in draft while any mandatory gate remains open. See [release status](IMPLEMENTATION_STATUS.md) for measured results, audit findings and open work.

## Verified checkpoints

- Implementation commits: `07a9f2b` for data and scale, `8248958` for model tuning and monitoring, and `1bcfa0d` for the financial API, identity, and deployment.
- `python -m unittest discover -q` passed 17 tests. The separate authored case loop exercised 159 questions. Ruff and the targeted type check passed.
- The Windows Compose run first hit an occupied port. Retrying on loopback port 18764 passed startup, authentication, prediction, restart and shutdown checks.
- A Python 3.12 serving-image audit found zero advisories across 22 distributions. A Python 3.14 training environment resolved the filelock and setuptools advisories. The exact CPU torch variant was skipped by the PyPI lookup. The upstream release returned zero OSV findings.
- Benchmark, model, monitoring, and finance evidence are in [docs/evidence](evidence/). The working databases and full output are in ignored `out/`.

## Optional hosted verification

Use an approved provider and set `CLAIMS_LLM_ENDPOINT`, `CLAIMS_LLM_MODEL`, and `CLAIMS_LLM_API_KEY` in the local process. Run `python -m healthcare.cli eval-agent --database out/mandate-three/close.sqlite --provider live --allow-billed --out out/live-evaluation.json` with an approved budget. Validate a real issuer and deployment using [the deployment instructions](deployment.md). Review the unresolved exact CPU wheel and container OS package coverage before release. The draft PR already points to these checks.
## Local identity and model verification checkpoint

The current acceptance harness uses Keycloak, ephemeral local TLS, a small generated database and a pinned llama.cpp overlay. Prepare credentials with `python -m healthcare.local_oidc`, then follow [the quickstart](deployment.md#local-tls-identity-and-inference-verification). The real identity path and local model are tested separately from optional public cloud hosting. Live case and audit evidence belongs in `docs/evidence/`. The previous source reconciliation and model benchmarks remain historical evidence.

## Release candidate verified

- Implementation checkpoint: `6858ea050b598f9d7cec7a41e8a9ced55487a510`.
- The final regression passed 19 Python tests, Ruff, five targeted type checks, and three dbt models and three dbt tests. The 50,000-member source and close rerun reproduced both financial cutoffs.
- The authored Qwen pipeline retest passed 135/135 with 65 real model calls. The separate ledger suite passed 281/281 with 247 real model calls. The initial and interrupted failures are retained in [live evidence](evidence/v2-live-llm-evaluation.json).
- Real TLS Keycloak verified all three tenants, wrong issuer, invalid audience, role, scope, expiration, signature, restart, and disposable issuer signing-key replacement. The API was still running when it accepted newly signed tokens over refreshed JWKS.
- The final Python 3.12 Alpine application image passed `pip check`, the installed-package audit and Trivy's high/critical OS scan. The [security and regression evidence](evidence/v2-local-release-verification.json) records the original Debian and first Alpine findings.
- Release scope is local Docker with fictional data. Public cloud and production identity certification remain outside the verified scope. Use [the deployment quickstart](deployment.md#local-tls-identity-and-inference-verification) to reproduce the release.

A fresh clone of the implementation checkpoint installed dependencies, generated its own fixture data and certificates, built the API without cache, and passed the full Keycloak, Qwen, finance, prediction and restart acceptance run. Its HTTP results are recorded in the release verification evidence.
