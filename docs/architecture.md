# Local platform architecture

```mermaid
flowchart LR
  G[Synthetic generator] --> D[Versioned deliveries]
  G --> O[Signed payment deltas]
  D --> C[Baseline close SQL]
  O --> V[Independent reconciliation]
  C --> V
  C --> P[Parquet close facts]
  P --> B[dbt finance marts]
  D --> J[Manifested replay journal]
  J --> C
  O --> M[Point-in-time cost experiments]
  C --> A[Tenant-scoped financial tools]
  A --> S[Local FastAPI service]
  A --> E[Financial gold evaluation]
```

Payment deltas are signed numeric adjustments. The ledger does not use cryptographic signatures. The journal-backed close recomputes both cutoffs in a separate database using accepted deliveries and the existing independent ledger. The baseline command remains available. The API can open either verified SQLite close database in read-only mode.
