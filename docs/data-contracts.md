# Data contracts

| Record | Key or grain | Contract |
| --- | --- | --- |
| Batch manifest | Tenant, source, watermark | SHA-256, schema version, first day of source period, timezone-aware effective and receive times, expected record count |
| Canonical delivery | Tenant, claim, line, version | Positive identifiers, ISO received date, replacement amount in integer cents, source and watermark |
| Member-month | Tenant, member, service month | Eligibility determines presence. A missing benchmark can remain null. |
| Close report | Close ID, tenant, member, service month | Immutable cutoffs in the baseline build. Sum amounts after resolving delivered versions. |
| Model input | Tenant, member, prediction period | Historical claim payments available before prediction cutoff. Target uses the next three service months with a 90-day arrival window. |

Ingestion contract V1 expects the canonical delivery field names. V2 maps the corresponding alternate header fields in `healthcare/ingest.py`. Existing manifest identity is immutable. A bad source batch must be corrected and retried from its original watermark.
