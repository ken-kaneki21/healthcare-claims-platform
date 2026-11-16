# V2 implementation status

This branch starts from main commit `3073a277129f0964500643e4dd64f44edff37f98`. Main passed CI before the branch was created. The local tag `v2-baseline-3073a27` records that point. The original generator, SQL close, dbt models, and ridge commands are preserved.

| Gate | State | Evidence and remaining work |
| --- | --- | --- |
| R0 Baseline | Done | Original code path and historical close results reproduced. |
| R1 Ingestion | Done locally | Both cutoffs use committed deliveries and reconcile to the independent ledger. Quarantine, conflict handling, interruption, and identical replay are tested. |
| R2 Analytics | Done locally | Three fictional clients, dated rules and alternate feed contracts run end to end. dbt incremental and full-refresh results match after changing and removing existing groups. |
| R3 Scale | Done locally | Fresh 1K, 10K and 50K recovery benchmarks and replay parity are recorded in the evidence. |
| R4 Training | Done locally | Validation-only search, point-in-time tests, cohort errors, coefficient analysis and independent seed-113 and seed-291 evaluations passed. |
| R5 Model operations | Done locally | Promoted the tuned signed candidate, generated 50,000 predictions, flagged one synthetic tenant for drift, and restored and reran the prior version. |
| R6 Financial AI | Done for local scope | Guarded Qwen model and deterministic financial tools passed the authored live retest. See the evaluation evidence for model invocations, metrics and prior failures. |
| R7 Service | Done for local scope | Real Keycloak issuance, tenant isolation, Docker restart and serving-image OS and Python scans passed. Cloud deployment remains unverified. |
| R8 Publication | Release verification | See the GitHub pull request and release record for publication status. |

## Reproduced measurements

Windows, AMD Ryzen 5 5600H, 12 logical processors, generator seed 42. Times are observed build wall time. Each row uses a fresh database. This run did not measure peak RAM or cloud costs.

| Population | Claim deliveries | Member-months per close | Ledger differences per close | Build seconds |
| ---: | ---: | ---: | ---: | ---: |
| 1,000 | 59,565 | 23,632 | 0 | 1.20 |
| 10,000 | 595,776 | 236,318 | 0 | 11.52 |
| 50,000 | 2,979,003 | 1,181,592 | 0 | 56.07 |

The full dataset contained 1,727,344 claims. Original and revised close times were 13.62 and 14.01 seconds. The existing README's 86.52-second full build and original ridge metrics describe a different run.

The 1K smoke processed 29,332 deliveries for tenant 1 as three source batches. Its rules-only agent evaluation passed 204/204 generated cases. These were structured numerical and policy checks on synthetic fixtures, including templated variants. They provide no live LLM quality score.

The full CPU experiment trained on 51,429 rows, validated on 2,857 rows and logged split fingerprints and metrics to a local MLflow SQLite store. The two later-period holdouts contained 5,000 unseen members and 25,000 members from the held-out client.

| Model | Unseen-member MAE | Held-out-client MAE |
| --- | ---: | ---: |
| Prior-quarter spend | $330.05 | $561.72 |
| sklearn ridge | $301.29 | $377.03 |
| Histogram gradient boosting | $376.63 | $366.61 |
| PyTorch MLP | $311.60 | $376.63 |

Ridge had the lowest validation MAE and the lowest MAE on the unseen-member holdout. Gradient boosting had the lowest MAE on the held-out client. These values describe the V2 experiment, separate from the original ridge artifact used for batch inference.

Verification included eight Python tests and Ruff. The initial Ruff run found four import or style issues, which were fixed. The restricted Windows process stalled in the HTTP integration test. The same suite finished successfully in the host process. Compose configuration requires a demo secret and passed with a generated value. Docker Desktop's Linux engine was unavailable for a container run.

## Current branch verification

Thirteen Python tests and Ruff passed locally. GitHub Actions passed on the branch push and pull request. The pull request run built and started the Docker container and verified HTTP 200 and 403 for the appropriate tenant requests.

The three-client 1K build processed 59,565 deliveries. Journal-backed close produced 23,632 member-months at each cutoff with zero ledger differences. Export produced 47,264 close rows. The incremental and full dbt builds agreed across 144 finance rows.

On the separately generated seed-113 population, the prior-quarter baseline, ridge, gradient boosting and PyTorch scored USD 530.89, 345.61, 364.80 and 348.21 MAE, respectively. Ridge validation MAE was USD 313.94 and rose to USD 315.62 when recent spend was withheld. A signed ridge artifact produced 50,000 versioned predictions locally.

The deterministic finance evaluation passed 281 of 281 cases. All 216 financial cases matched numeric, tool and evidence expectations. Median and p95 per-case latency were 5.00 ms and 13.44 ms. No live model was invoked.

At 50K, the journal ingestion accepted 2,979,003 source deliveries in 299 manifests and kept 2,854,878 unique delivery versions. Ingestion across both clients took 1,009.52 seconds on the Windows test host. Journal-backed materialization took 31.72 seconds end to end. Each cutoff produced 1,181,592 member-months with zero ledger differences. Two-way SQL EXCEPT found zero differing close rows between the journal and the baseline.

The dependency audit found advisories in the local installer and in the optional PyTorch environment. Upgrading pip to 26.3 cleared its findings. A repeat audit still reported 17 advisories for filelock 4.1.0, a PyTorch dependency. The configured package index offered no compatible filelock 4.2.1 or later for this Python 3.10 environment. The local dependency gate remains open. The serving container does not install PyTorch.

## Release verification after the implementation checkpoint

The original measurements above remain historical. The current verified changes introduce effective-dated client rules, indexed and batched journal ingestion, validation-only model search, registered-model monitoring, evidence-backed multi-month finance comparisons and an OIDC access-token verifier.

- Three-client journal run: 23,468 member-months per cutoff, zero ledger differences, and zero close row differences. The changed-and-removed snapshot check passed with 142 identical finance rows for incremental and full refresh.
- Tests: 17 Python tests, Ruff and a targeted mypy check of identity, monitoring, registry, and scale passed. The authored suite covered 159 questions, and the ledger-based evaluation passed 281/281 with 216/216 numerical, tool, and evidence checks. Only deterministic evaluation ran.
- Local Docker on Windows: readiness, authenticated finance and predictions, anonymous and cross-tenant denials, agent responses and restart recovery passed. The original smoke attempt found port 8000 in use. The verified run used port 18764 and cleaned up its service and network.
- Model: the validation search selected ridge alpha 1000 and a seven-leaf boosting configuration. The registry accepted the tuned ridge and produced 50,000 predictions. The 10,000-member monitor flagged fictional client 2 for a recent-spend shift of 0.799 against a 0.75 threshold. Rolling back restored the original model and produced 50,000 predictions again.
- Dependency audit: the serving image and the audited Python 3.14 training packages showed zero findings after updating filelock and setuptools. The exact CPU PyTorch wheel could not be matched by the PyPI scanner. A separate OSV check found zero advisories against the upstream release.

See [model comparison](evidence/v2-tuned-model.json), [monitor report](evidence/v2-model-monitor.json), [deterministic evaluation](evidence/v2-rules-evaluation.json), and the [Python dependency audit](evidence/v2-dependency-audit-summary.json).

### Fresh scale and recovery benchmark

Windows, AMD Ryzen 5 5600H, Python 3.10, storage in the OneDrive workspace. Each run generated a fresh seed-42 database, committed one page, backfilled the rest and rebuilt both closes. A second replay inserted zero versions. Peak memory comes from the Python process rather than the launcher. Build, journal and close numbers are wall seconds.

| Members | Deliveries | Build | Journal | Backfill after checkpoint | Journal closes | End-to-end | Repeat replay | Peak memory |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1,000 | 59,565 | 1.47 | 0.764 | 0.649 | 1.00 | 3.23 | 0.220 | 39.8 MiB |
| 10,000 | 595,776 | 17.52 | 42.385 | 41.621 | 10.35 | 70.257 | 2.146 | 62.8 MiB |
| 50,000 | 2,979,003 | 115.79 | 853.040 | 850.551 | 56.83 | 1,025.659 | 8.055 | 158.7 MiB |

At 50K, the journal contained 2,854,878 unique versions in a 220,053,504-byte database. The source database was 484,765,696 bytes. Journal throughput was 3,492 deliveries per second. Both closes reconciled 1,181,592 member-months apiece with zero row or ledger differences against the frozen baseline. The observed full ingestion time moved from 1,009.52 to 853.04 seconds. The runs shared a machine and dataset shape, with differing concurrent load, so the paired profiling comparison is stronger evidence for the cause.

On the same 1,000-member source, paired cProfile runs counted 176,251 direct SQLite execute calls before the change and 157 direct calls plus 120 executemany calls after it. Workspace runtime went from 8.906 to 1.046 seconds. The local temporary directory showed the same pattern. At 10K, extraction-only timing went from 6.81 to 1.39 seconds after replacing a repeated temporary sort with a primary-key range scan. See [benchmark results](evidence/v2-scale-and-analytics.json) for raw counts, memory, sizes and outputs.

## Local release verification

A fresh 50,000-member regression generated 1,727,344 claims and 2,979,003 deliveries. Both original and revised closes reconciled 1,181,592 member-months with zero differences against the independent ledger. The fresh build took 144.26 seconds. This run measured generation and closes. The earlier journal-ingestion and memory figures remain the historical benchmark.

The local Keycloak stack verified signed tokens against real TLS discovery and JWKS, enforced scope and role, and isolated all three fictional tenants on finance, prediction and agent paths. It recovered after an API restart. The local CPU model-backed agent matched the financial tool on an authenticated natural-language request. Use the evidence links and [release notes](RELEASE.md) for exact scope.

The release regression also rebuilt three dbt models and ran three dbt tests across an incremental rerun and full refresh. All 144 finance rows matched. The model training smoke completed and the full test suite passed 19 Python tests, Ruff, and the targeted type check. [Identity, container, and data evidence](evidence/v2-local-release-verification.json) and [live-model evidence](evidence/v2-live-llm-evaluation.json) contain the redacted outputs.
