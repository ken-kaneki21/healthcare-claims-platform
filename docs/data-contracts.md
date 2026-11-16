# Data contracts

| Record | Key or grain | Contract |
| --- | --- | --- |
| Batch manifest | Tenant, source, watermark | SHA-256, schema version, first day of source period, timezone-aware effective and receive times, expected record count |
| Canonical delivery | Tenant, claim, line, version | Positive identifiers, ISO received date, replacement amount in integer cents, source and watermark |
| Member-month | Tenant, member, service month | Eligibility determines presence. A missing benchmark can remain null. |
| Close report | Close ID, tenant, member, service month | Immutable cutoffs in the baseline build. Sum amounts after resolving delivered versions. |
| Model input | Tenant, member, prediction period | Historical claim payments available before prediction cutoff. Target uses the next three service months with a 90-day arrival window. |

Ingestion contract V1 expects the canonical delivery field names. V2 maps the corresponding alternate header fields in `healthcare/ingest.py`. Existing manifest identity is immutable. A bad source batch must be corrected and retried from its original watermark.

## Effective-dated rules

`client_rule` is keyed by client and effective service month. A new policy row starts on its effective month and applies until the next version. Eligibility entry and exit moduli drive independently generated member spans per fictional client in three-client mode. Attribution changes are materialized into `member_month.provider_id`, so a later provider change does not rewrite historical attribution. The risk snapshot cadence and benchmark basis points use the rule at the service month. The two-client legacy policy retains the original close outputs. A missing risk snapshot or rate leaves the member benchmark null.

The dbt finance grain is one row per close, client and service month. PMPM is paid cents divided by eligible member-months. The expense-to-benchmark ratio remains null when any benchmark input is missing or the total benchmark is zero. A corrected Parquet snapshot updates changed groups and deletes groups that disappeared.
