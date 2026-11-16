# V2 implementation status

This branch starts from main commit `3073a277129f0964500643e4dd64f44edff37f98`. Main passed CI before the branch was created. The local tag `v2-baseline-3073a27` records that point. The original generator, SQL close, dbt models, and ridge commands are preserved.

| Gate | State | Evidence and remaining work |
| --- | --- | --- |
| R0 Baseline | Done | Four original tests passed. A fresh 1,000-member run produced 59,565 deliveries. A fresh 50,000-member run produced 2,979,003 deliveries and reconciled both closes with zero differences. |
| R1 Ingestion | Done for local acceptance | `healthcare/ingest.py` and `healthcare/journal_close.py` rebuild both cutoffs from approved deliveries and reject an incomplete tenant feed. Quarantine persists the reason and payload checksum after rollback. The baseline command still works. |
| R2 Contracts | Partial | Three fictional clients ran through journal close and dbt. Client 3 uses contract V2 and a different synthetic cost factor. Full versus incremental dbt results matched across 144 rows. Richer versioned rule configuration and independent source eligibility variation remain open. |
| R3 Scale | Partial | Fresh 1K, 10K, and 50K baseline profiles reconciled. A 10K repeat measured 55,732 deliveries per build second and a sampled peak working set of 43,544,576 bytes. Peak memory at 50K and a historical backfill benchmark remain open. |
| R4 Training | Partial | The CPU model comparison was rerun with a separate seed-113, 10K population and a validation-only ablation. A test proves a late historical correction cannot leak into features. Validation hyperparameter search and broader error-slice reporting remain open. |
| R5 Model operations | Partial | `healthcare/registry.py` signs JSON models and gates promotion using matching validation fingerprints and validation MAE. Rollback and tamper detection passed fixture tests. A trained registered ridge model produced 50,000 batch predictions. The API can read that batch after restart. Drift monitoring remains open. |
| R6 Financial AI | Partial | `healthcare/agent.py` decomposes restatements into late first payments and adjustments and reports numerical, tool and evidence results separately. 281/281 deterministic checks passed on the three-client fixture, including templated cases. Live LLM calls and independently authored coverage remain open. |
| R7 Service | Partial | `healthcare/api.py` provides signed tenant identity, structured request logs, and per-process rate limiting. Integration tests deny cross-tenant paths and body overrides. The GitHub Actions container passed readiness, an allowed finance request and a denied cross-tenant request. Production identity and cloud deployment remain open. |
| R8 Publication | Partial | V2 branch with CI configuration and documentation. Merge, public tag, and release assets are gated on completion and authorization. |

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
