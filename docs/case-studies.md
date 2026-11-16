# Engineering case studies

All workloads use fictional clients and synthetic records. See [verification evidence](evidence/) for measured outputs.

## Reliable ingestion and replay

**Problem.** A late or repeated delivery could change a financial close if it were applied twice. The first full replay also took nearly 17 minutes.

**Implementation.** Checksummed manifests commit with their approved delivery versions. Invalid batches retain a reason and checksum in quarantine. Exact duplicate versions are no-ops. Conflicting versions roll back the whole batch. The extractor now paginates in delivery-ID order, and the loader validates claim ownership in groups and uses an atomic SQLite upsert.

**Verification and trade-off.** The recovery benchmark starts with one committed page, backfills the remainder and replays the whole source a second time. A repeat adds zero versions. DB writes stay atomic at the manifest boundary. The SQLite writer remains single-process. In paired 1,000-member profiling runs, direct SQLite execute calls dropped from 176,251 to 157 and wall time fell from 8.906 to 1.046 seconds. The 50,000-member run completed with zero row differences against the prior frozen closes.

## Financial reconciliation and restatement

**Problem.** Claims can arrive after a report is frozen, and a mutable balance can hide the original financial result.

**Implementation.** Each snapshot selects the latest approved delivery version available at its cutoff. A separate ledger sums payment deltas at the same cutoff. The API attributes revision differences to late first payments or adjustments, and emits an explanation only when the bridge ties to the ledger.

**Verification and trade-off.** Both 50,000-member closes reconcile to the cent at member-month grain. Rebuilding a close requires both the committed journal and reference dimensions. An incomplete journal aborts publication.

## Multi-client analytics engineering

**Problem.** A new fictional client supplied a different schema and risk period. The original dbt incremental model treated each close ID as permanently unchanged.

**Implementation.** Schema V2 maps alternate names to the order of the canonical fields. Effective-month rules determine synthetic eligibility, attribution, risk cadence and benchmark factors. The mart updates changed close groups and removes groups missing from the source snapshot.

**Verification and trade-off.** The three-client run produced 23,468 member-months per cutoff with zero ledger differences. After a source correction and deletion, the incremental and full refresh results matched across 142 finance rows. The incremental run scans the current source snapshot to detect removals.

## Predictive ML and generalization

**Problem.** Random train/test splitting can leak later revisions or member-specific behavior. A model that works for its training client can also generalize poorly to another.

**Implementation.** Cohorts use disjoint member groups, cutoff-aware features and later-period outcomes. Ridge and boosting parameters are selected on validation only. The comparison records an independent seed, a recent-spend ablation, error percentiles and cohort MAE.

**Verification and trade-off.** On Python 3.14, ridge reached USD 301.25 MAE on unseen members compared with USD 330.05 for prior-quarter spend. Boosting reached USD 366.45 on the held-out client versus ridge's USD 376.92. The synthetic populations support reproducible comparisons. They cannot estimate errors on an actual health plan.

## Model lifecycle and monitoring

**Problem.** A model that wins in training needs verifiable promotion criteria and a reversible deployment decision.

**Implementation.** The local registry signs the feature contract, split fingerprints, validation metrics, coefficients and monitoring reference. Model promotion compares the same validation split. The monitor checks feature means and prediction percentiles per tenant without reading outcome labels.

**Verification and trade-off.** The tuned ridge improved validation MAE from USD 313.94 to USD 313.75. Promotion and rollback each generated 50,000 versioned predictions. The independent 10,000-member run alerted on recent spend for fictional client 2. Distribution alerts can indicate shift before labels arrive. They do not estimate predictive accuracy.

## Financial AI and authenticated service boundaries

**Problem.** Financial questions need evidence, and a request body must never override the authenticated tenant.

**Implementation.** Tool routing is restricted to approved operations and periods. SQL supplies every amount. The API validates issuer, audience, expiry and scope for OIDC access tokens. The hosted question adapter is opt-in.

**Verification and trade-off.** The parameterized suite passed 281 cases. A separate authored suite passed 159 questions, with a separate numeric ledger assertion for two-month PMPM. The OIDC test used signed access-token fixtures, and real Docker recovered its prediction after restart. Live model quality and cloud identity verification depend on a configured environment.

### Local release retest

The real Keycloak stack validated the issuer, audience, scope, role, expiry and signature, and rejected cross-tenant finance, prediction and agent access. A guarded Qwen-backed question matched the authenticated financial endpoint. Across 135 authored scenarios, 65 used real model inference. All 135 passed after adding the tool schema and deterministic constraints for explicit metric names. The initial model prompt failed 36 scenarios, and schema-only routing still returned answers to ten unsupported requests. These failure cases drove the tool and scope constraints.
