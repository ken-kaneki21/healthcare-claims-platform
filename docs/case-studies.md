# Engineering case studies

All measurements use synthetic records from this repository.

## Data engineering — Replaying an interrupted claims feed

Batch manifests record tenant, source and watermark. The retry test replays a batch without duplicating accepted deliveries. Validation failures retain a reason and payload checksum in quarantine. The close refuses to publish from an incomplete journal.

## Analytics engineering — Revising a closed month

The original and revised cutoffs use separate snapshots at member-month grain. A third synthetic client used the alternate feed schema and contract V2. Its run produced 23,632 member-months per cutoff across all three clients with zero ledger differences. The incremental dbt rerun and full refresh returned the same 144 finance rows.

## Applied AI — Explaining a payment adjustment

The financial API separates late first payments from adjustments and checks that their sum matches the ledger. In the rules-only evaluation, 216 financial cases matched expected numbers, tool choices and evidence. Across all 281 cases, denied, missing, ambiguous and unsupported requests returned the expected status. The suite includes templated variants.

## AI platform — Binding requests to the authenticated client

The service resolves the tenant from a signed token and denies route and body overrides. In GitHub Actions, the container passed readiness, returned HTTP 200 for an allowed query and HTTP 403 for a cross-tenant query. Local integration tests also cover the request limit.

## MLOps — Promoting a reproducible batch model

The registry verifies signed artifacts and compares models on the same validation and feature fingerprints. A locally registered ridge model produced 50,000 versioned predictions. Controlled tests verified downgrade rejection, rollback and artifact tamper detection.

## ML engineering — Testing whether a result transfers

A point-in-time test checks that a historical correction arriving after the feature cutoff is excluded. Ridge achieved USD 301.29 MAE on later unseen members, while gradient boosting achieved USD 366.61 on the held-out client. On a separately generated 10,000-member population, ridge scored USD 345.61 MAE against USD 530.89 for prior-quarter spend.
