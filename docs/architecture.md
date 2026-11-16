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
  O --> M[Point-in-time cost experiments]
  C --> A[Tenant-scoped financial tools]
  A --> S[Local FastAPI service]
  A --> E[Financial gold evaluation]
```

Payment deltas are signed numeric adjustments. The ledger does not use cryptographic signatures. The portable build preserves the existing materialized close and separately validates journal replay. The journal is the integration boundary for future close ingestion. The API opens the verified baseline SQLite database in read-only mode.
