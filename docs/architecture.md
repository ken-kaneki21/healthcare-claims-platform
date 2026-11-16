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

The V2 path is `synthetic source → transactional journal → original/revised member-month closes → Parquet → dbt finance marts`. Payment-event deltas independently verify the paid amounts at both cutoffs. The finance API reads the published SQLite snapshot and prediction CSV. The offline model path trains on point-in-time cohorts, runs validation-only selection, signs a ridge artifact, and monitors feature and prediction distributions before or after rollback.

```mermaid
flowchart LR
  Synth["Synthetic clients"] --> Journal["Manifest journal"]
  Rules["Dated rules and enrollment"] --> Close["Original and revised closes"]
  Journal --> Close
  Ledger["Independent payment-event ledger"] --> Close
  Close --> dbt["Parquet, DuckDB and dbt"]
  Close --> API["Tenant-scoped finance API"]
  Ledger --> Train["Point-in-time features and validation"]
  Train --> Registry["Signed local model registry"]
  Registry --> Monitor["Drift monitor"]
  Registry --> Batch["Versioned prediction CSV"]
  Batch --> API
```

The live local reference stack adds TLS Keycloak and Qwen inference as separate containers. Keycloak issues signed access tokens with tenant, scope and role claims. The API uses the model to propose an operation, then runs parameterized SQLite queries and builds the user-facing evidence from those rows. Model, identity and API processes communicate on the Compose network, with development endpoints on loopback.
