# Healthcare Claims Platform V2.0.0

This local reference release demonstrates financial reconciliation, analytics, cost modeling, and tenant-scoped questions over synthetic healthcare claims.

- Reconciled both financial cutoffs across 50,000 synthetic members, 2,979,003 deliveries, and 1,181,592 member-month records per close.
- Verified journal replay and recovery, three-client dbt reporting, and local model monitoring, promotion, prediction, and rollback.
- Verified TLS Keycloak token issuance, finance and prediction access for three fictional tenants, cross-tenant denial, signing-key refresh, and Docker restart recovery.
- Evaluated Qwen2.5-1.5B-Instruct Q4_K_M locally with deterministic financial tools. Passed 135 authored cases with 65 real model calls, and 281 ledger and policy cases with 247 real model calls.
- Passed 19 Python tests, Ruff, targeted type checks, dbt, and the final serving-image security checks.

Use the [Docker quickstart](deployment.md#local-tls-identity-and-inference-verification) to reproduce the stack. See [release verification](evidence/v2-local-release-verification.json), [live-model evaluation](evidence/v2-live-llm-evaluation.json), and [implementation status](IMPLEMENTATION_STATUS.md) for scope, tests, and limitations.

Public cloud deployment and real healthcare use have no verification in this release.
