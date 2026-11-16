# Financial investigation engineering walkthrough

## Reproduce the local workflow

Install the development dependencies with `python -m pip install -r requirements-v2.txt`. Set fresh random values of at least 32 bytes in `CLAIMS_DEMO_SECRET` and `CLAIMS_REGISTRY_SECRET` for the process that launches Compose. Keep them in the local environment.

```text
python -m healthcare.integration_demo
docker compose -p claims-investigation -f compose.yaml -f compose.investigation.yaml up --build -d
python -m healthcare.verify_integration
docker compose -p claims-investigation -f compose.yaml -f compose.investigation.yaml restart api
python -m healthcare.verify_integration
docker compose -p claims-investigation -f compose.yaml -f compose.investigation.yaml down --volumes
```

Wait for `/ready` after startup and restart. The demo generates a new `out/integrated` directory with all datasets and signed artifacts. Use a fresh output directory for a repeat and point `CLAIMS_INTEGRATION_ROOT` at it. The HTTP verifier emits synthetic trace evidence. An unchanged response after restart proves the persisted request can replay against the same snapshot. Append `-f compose.local-llm.yaml` to the startup and shutdown commands after following the [model download instructions](deployment.md#local-tls-identity-and-inference-verification). Run `python -m healthcare.verify_integration --prefix qwen` with fresh request IDs to exercise model-assisted historical routing.

## Six interview scenarios

### 1. A duplicate correction changes a close total

Start at `build_platform.build`, `platform.sql`, `healthcare.ingest.replay_feed`, and `healthcare.journal_close.rebuild`. The seeded generator creates fictional clients, eligibility, versions and payment event deltas. The manifest journal accepts an exact replay and quarantines a conflicting version. The close selects the last approved version at each receipt cutoff. A separate sum of payment deltas checks identical tenant, member, and service-month grain. Run `python -m healthcare.scale --members 1000 --tenants 3 --out out/interview-close`. Expect both cutoffs to reconcile, with zero additional versions on replay. A matching grand total can conceal offsetting member-level differences, so the verifier compares both directions at full row grain.

### 2. A validation label arrives after the model would have shipped

`train_cost.cohort` uses payment receipts strictly before the prediction date for its historical features. Its outcome includes three future service months and a 90-day receipt window, with an exclusive cutoff. The strict experiment in `healthcare.experiments.compare` uses training periods 7 and 8, validation period 14 and test period 21. It asserts that labels mature before the next decision date and checks that member identities are disjoint across splits. Run `python -m healthcare.cli train --strict-timeline --database out/integrated/close.sqlite --out out/strict-model.json`. Expect hashes for each split, prior-quarter and seasonal baselines, and validation-only candidate search. Seasonal naive uses the same service quarter a year earlier and falls back to prior-quarter spend for members without full historical eligibility.

### 3. The neural network wins on one population

Compare the later unseen-member, held-out-client and independent-seed results. The ridge champion is selected from validation and packages a scaler, coefficients and intercept in JSON. The MLP applies a linear layer, ReLU and a final linear output. It optimizes squared error on scaled targets with seeded Adam updates. Each batch clears gradients, backpropagates loss and applies a parameter update. Run the strict training command with `--torch-cpu` in the optional training environment. Expect lower MAE to vary across evaluation slices. WAPE reports total absolute error relative to total absolute observed cost, and high-cost MAE uses a threshold estimated from training only. A standardized ridge coefficient describes an association conditional on the other features and training design.

### 4. Rollback needs to restore the previous approved forecast

`healthcare.registry.transition` compares validation fingerprints, thresholds and scores in one SQLite transaction. `healthcare.integration_demo.prepare` scores a perturbed earlier artifact against the same validation data, promotes the better ridge, rejects the weaker candidate, and republishes the earlier artifact after rollback. Inspect `out/integrated/lifecycle.json` for the decisions and forecast totals. `healthcare.forecast_snapshot.publish` signs the forecasts, model metadata, reporting window and drift evidence, and binds them to the closed claims database hash. A serving process pins that snapshot at startup. A promotion affects serving after publication and an explicit restart with the approved artifact.

### 5. A user asks why forecast and actuals differ

Run `python -m healthcare.verify_integration` and inspect `variance_and_drift`. `healthcare.investigation.Investigations.execute` selects up to three read-only tools. The signed snapshot supplies the approved forecast and flagged distribution shifts. A parameterized ledger query supplies matured actuals and prior-quarter spend for exactly those forecast members. `verify_actuals` independently reconstructs the same sums by member IDs, service-period IDs and receipt cutoff. The application computes differences in integer cents and emits sources, row counts, model version and snapshot ID. Cohort movement and drift flags describe observed differences. A causal explanation would require a separate design.

### 6. A tool fails or an untrusted prompt asks to switch tenants

`healthcare.api.create_app` derives scope from the verified access token. Forecast arguments can constrain the pinned version and period. The request schema has no tenant override. Qwen can interpret natural-language historical questions through the released `provider_router`. The structured forecast plan runs on the offline path with the same evidence checks. `Investigations.run` keys persisted results by tenant and request ID, rejects conflicting reuse, and retries bounded reads after a recoverable error. User text is stored only as a request digest. SQL statements and forecast publication are separate from the agent's permissions. Run `python -m unittest test_integrated_investigation -v` for stale model, tampering, contradictory values, interruption, retry and cross-tenant tests. Expect an evidence-free escalation when a result cannot be supported.

## Operational limits

The lightweight Python workflow uses a small fixed tool catalog and SQLite checkpoints. Its highest-value retry guarantee is deterministic replay of authenticated reads. It has no workflow scheduler or live model reload. A failed investigation can be reviewed from its escalation and request ID. Registry promotion requires an operator. Finite ledger coverage governs whether actuals can be compared. You need a writable checkpoint volume, immutable published inputs, and one serving snapshot per process. Scope is a local synthetic reference stack.
