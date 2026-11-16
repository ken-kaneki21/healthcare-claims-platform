# Healthcare claims platform

## V2 local preview

The [implementation status](docs/IMPLEMENTATION_STATUS.md) records reproduced benchmarks, open gates and scope limits. Install `requirements-v2.txt` for API and model comparisons.

```text
python -m pip install -r requirements-v2.txt
python -m unittest discover -v
python -m healthcare.cli smoke --database out/v2.sqlite
python -m healthcare.cli train --database out/v2.sqlite --out out/v2-model-evidence.json
python -m healthcare.cli eval-agent --database out/v2.sqlite --provider mock
python -m healthcare.cli full-build --database out/v2-full.sqlite
```

Set `CLAIMS_DEMO_SECRET` to a randomly generated value of at least 32 bytes, then use `python -m healthcare.cli token --tenant 1` and `python -m healthcare.cli serve --database out/v2.sqlite` for the loopback API and OpenAPI documentation. Use the token in the Authorization Bearer header. See [security](docs/security.md) and the [runbook](docs/runbooks.md).

A synthetic healthcare database and claims-close workflow for two fictional clients. The full local run generated **50,000 members, 1,181,592 member-months, 1,727,344 claims, and 2,979,003 claim deliveries** over 24 months. Providers, member aliases, encounters, diagnoses, risk snapshots, rates, payments, and reporting tables share the same generated keys.

## Full build

From the repository root, use Python 3.10 or later. Install the pinned dependency to run the model.

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -v
python build_platform.py --database out/healthcare-platform.sqlite
python financial_tools.py --database out/healthcare-platform.sqlite --evaluate
python train_cost.py --database out/healthcare-platform.sqlite --out out/model-evidence.json
python train_cost.py --database out/healthcare-platform.sqlite --model out/model-evidence.json --period 21 --out out/predictions.csv
```

The default seed is 42. The builder refuses to overwrite an existing database. The full SQLite file is about 485 MB and stays outside Git. The build uses temporary disk space for the close checks.

| Path | What runs locally |
| --- | --- |
| Source and raw deliveries | Two fictional clients share a schema. Provider attribution changes over time. Claim lines include repeats, delays, zero pay and signed adjustments in the source ledger. Raw deliveries carry replacement amounts. |
| Reporting | Two frozen close cutoffs, member-month reports, PMPM, a synthetic expense-to-benchmark ratio and a restatement view. Missing benchmark values remain explicit. |
| dbt analytics | Export close facts to Parquet and build a reporting mart and restatement table in DuckDB. The incremental monthly model loads each immutable close once. |
| Reconciliation | The warehouse calculates from versioned deliveries. The oracle calculates independently by summing payment-ledger deltas. Differences fail the build. |
| Cost prediction | Ridge regression and a prior-quarter spend baseline. Features use only payments received before the prediction date. The evaluation holds out later periods, unseen members, and a second fictional client. The trained coefficients can produce versioned batch predictions. |
| Financial tools | Read-only, parameterized close and restatement queries scoped to a selected fictional client. The CLI returns values and their source view and reports unsupported or missing requests. It is the deterministic tool layer for a future LLM. |

### Measured full-scale run

- Original and revised closes each reconciled 1,181,592 member-month rows with zero differences against the payment ledger. They took 21.79 and 22.42 seconds. Total build time was 86.52 seconds on the development laptop.
- The cost model trained on 60,000 synthetic member-period rows. On 5,000 unseen members in a later period, mean absolute error was $302.27 versus $330.05 for prior-quarter spend. On 25,000 members from the held-out fictional client, it was $377.26 versus $561.72. These are synthetic benchmark results.
- The financial tools passed 96 numerical checks and two unsupported or missing-evidence checks. Four automated test cases passed locally.
- Exported 2,363,184 close facts to Parquet. Ran three dbt models and three data tests twice. All 96 monthly aggregate rows matched SQLite after the incremental rerun.

All inputs are independently generated. The database is an illustrative claims model. The expense-to-benchmark ratio is a portfolio metric. Public CMS field layouts and official settlement are outside this implementation. The tenant filter is a query constraint in a local CLI. An authenticated service would need to bind it to the calling identity.

### Build the dbt marts

```powershell
python -m pip install -r requirements-analytics.txt
python export_closes.py --database out/healthcare-platform.sqlite --out out/close_fact.parquet
$env:CLAIMS_CLOSE_PARQUET = (Resolve-Path out/close_fact.parquet).Path.Replace('\','/')
$env:CLAIMS_ANALYTICS_DB = (Join-Path (Get-Location) 'out/claims_analytics.duckdb').Replace('\','/')
dbt build --project-dir analytics --profiles-dir analytics
```

Keep published close IDs immutable when reusing a DuckDB file. Use a new warehouse file or `dbt build --full-refresh` when changing the source dataset under the same close IDs.

## Small fault drills

When a claims workflow moves to a new warehouse, a matching grand total can hide missing members or errors that cancel out. This demo compares the replacement output with an independently calculated reference at the member-month level.

All members, claims, dates and amounts are generated from a seed. The files use a small teaching schema inspired by claims feeds. They do not implement official CMS file layouts, risk adjustment, or financial settlement. [CMS claims feed documentation](https://www.cms.gov/files/document/cclf-information-packet.pdf)

### Run the fault drills

Requires Python 3.10 or later and its standard library. From this directory:

```powershell
python demo.py --out out/clean
python demo.py --out out/offsetting --fault offsetting
python demo.py --out out/missing --fault missing
```

The clean run exits with status 0. The two fault drills intentionally exit with status 1. See `reconciliation.json` for the failing keys and differing values in cents.

| File | Grain |
| --- | --- |
| eligibility.csv | One row per eligible synthetic member and service month |
| claim_feed.csv | One row per received claim version, with repeated delivery of some versions |
| reference_member_month.csv | One row per eligible member-month, calculated in Python as claims and corrections are generated |
| actual_member_month.csv | One row per eligible member-month, calculated in SQLite from the received feed, with optional test faults |
| reconciliation.json | Run summary and one entry per missing or changed output key |

The SQL loads identical deliveries twice, deduplicates by claim and version, selects the latest version received by the cutoff, and rolls up by service month. A correction is a replacement amount and a cancellation sets it to zero. Claims arriving after the cutoff are excluded for that report. A duplicate key with a different payload aborts and rolls back the batch.

To verify a replay across process restarts and rerun the report with a later cutoff:

```powershell
python demo.py --out out/april --database out/claims.sqlite
python demo.py --out out/replay --database out/claims.sqlite
python demo.py --out out/june --database out/claims.sqlite --cutoff 2025-06-30
python -m unittest discover -v
```

Use a fresh database path when changing the seed or population size. The cutoff filters reporting only. This demo generates the full feed up front and does not measure incremental extraction from a source.

### Verified fault-drill results

With seed 42 and 1,000 synthetic members, the clean run reconciled 1,749 member-months from 5,762 deliveries representing 5,238 unique claim versions. Repeating the clean run produced the same files. Both fault drills failed as intended. One found two offsetting errors and the other found a missing member-month with zero paid expense. The total paid remained equal in both cases.

The next release should add a source manifest and incremental extraction. See [project scope](PROJECT-SCOPE.md) for the release order.
