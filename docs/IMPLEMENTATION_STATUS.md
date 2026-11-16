# V2 implementation status

This branch starts from main commit `3073a277129f0964500643e4dd64f44edff37f98`. Main passed CI before the branch was created. The local tag `v2-baseline-3073a27` records that point. The original generator, SQL close, dbt models, and ridge commands are preserved.

| Gate | State | Evidence and remaining work |
| --- | --- | --- |
| R0 Baseline | Done | Four original tests passed. A fresh 1,000-member run produced 59,565 deliveries. A fresh 50,000-member run produced 2,979,003 deliveries and reconciled both closes with zero differences. |
| R1 Ingestion | Partial | `healthcare/ingest.py` validates manifests and appends source pages into a transactional journal. Tests cover rollback, replay, corrections, schema mismatch, checksums, and tenant references. The baseline financial close still reads the generator tables. Journal-backed close integration and persistent quarantine are open. |
| R2 Contracts | Partial | The alternate field map accepts a third-tenant fixture. The full generator and dbt still use two fictional tenants. Effective-dated third-tenant rate rules and a full analytical test of that tenant are open. |
| R3 Scale | Partial | Fresh 1K, 10K, and 50K profiles reconciled in SQLite. Peak RAM, Spark comparison, and incremental backfill benchmark are open. |
| R4 Training | Partial | `healthcare/experiments.py` adds sklearn ridge, histogram gradient boosting, an optional CPU PyTorch MLP, and optional MLflow tracking. Split identity assertions and split fingerprints are implemented. Independently shifted seeds, ablations and feature leakage negative tests are open. |
| R5 Model operations | Partial | The API can serve precomputed, versioned predictions from the existing batch output. Signed promotion artifacts, drift monitoring, model registry and rollback are open. |
| R6 Financial AI | Partial | `healthcare/agent.py` provides a rules router, gold case generator and configurable live routing adapter. Offline evaluation uses signed-ledger totals. Live model calls, richer tool coverage, diverse adversarial cases, robustness statistics, and cost evaluation are open. |
| R7 Service | Partial | `healthcare/api.py` provides FastAPI routes and signed demo tenant identity. Integration tests deny cross-tenant paths and body overrides. Compose configuration parses. Container startup, identity-provider integration, production rate limiting and cloud deployment are open. |
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
