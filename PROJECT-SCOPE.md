# Healthcare data and AI platform

## Scope agreed

Build one independent platform with generated U.S. healthcare data. Its first use case is claims close and reconciliation. Add reporting, a second fictional client, one predictive model, and one financial assistant as successive releases over the same data. Professional experience and portfolio results have separate evidence.

| Release | Proof required |
| --- | --- |
| Claims foundation | Local fault drills cover transactional replay, conflicting duplicate deliveries and member-level differences hidden by matching totals. The full generator creates two clients and two close snapshots from shared synthetic events. |
| Financial reporting | SQLite produces reconciled close snapshots. dbt and DuckDB produce paid expense, PMPM, benchmark coverage and restatement from Parquet. Source manifests and official-format adapters remain open. |
| Second client and scale | Full-scale reconciliation ran for two fictional clients with local query filters. Full versus incremental backfill timings, memory profiling and authenticated tenant isolation remain open. |
| Predictive ML | Local time-aware evaluation and versioned batch inference are implemented. A model registry, feature monitoring and additional model comparisons remain open. |
| Financial AI | The deterministic tools and their oracle checks are implemented. The LLM, natural-language evaluation, token cost and latency report remain open. |

## Current data contract

| Dataset | Grain and key | Dependencies and rules |
| --- | --- | --- |
| Dataset configuration | One row per database | Defines generation seed and member count. A new seed or count requires another database. |
| Eligibility | Member × service month | Generated member identifier. Eligible months remain in the report even when expense is zero. |
| Claim feed | Claim ID × version | Each claim references a generated member and uses its service month. Amounts are integer cents. Received date determines cutoff visibility. A new version replaces the prior payment and a void replaces it with zero. |
| Member-month reference | Member × service month × report cutoff | Computed from the generator's payment events separately from the SQL implementation. |
| Member-month report | Member × service month × report cutoff | Latest available claim versions grouped by service month and joined to eligibility. |
| Reconciliation report | One summary per run and one detail per differing key | Compares the reference and SQL output. Tracks mismatches separately from aggregate variance. |

The current schema is illustrative. Future CMS-shaped ingestion should pin a publicly documented version and record each intentional deviation. Separate enrollment, provider and rate changes by effective date. Keep client and member identifiers fictional.

## Two additions worth locking in

- **Month-end restatement trail.** Save both original and revised closes with cutoff, source manifest and rule version. Produce a bridge showing changes due to late arrivals, revised claim versions, and changed rules. Keep the first published close reproducible.
- **Evidence for each release.** Store test reports and benchmark metadata with the code revision, seed, cutoff, dataset size, workload and environment. Compare any AI explanation with a rules-only baseline. An office pilot has its own measurement record and approval.

Next implementation milestone is a replayable batch loader whose manifest shows which delivery affected which report period. Cloud deployment remains a later milestone.
