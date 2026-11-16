# Integration acceptance

| Existing and verified | Existing but incomplete | Missing | Planned changes |
|---|---|---|---|
| Versioned delivery journal and independently reconciled ledger | Close evidence and prediction evidence are served independently | Matched forecast and matured actuals in one tenant-scoped answer | Join only the served forecast cohort and independently sum payment events |
| Point-in-time feature joins, MLflow, ridge, boosting and PyTorch | Historical split schedule does not guarantee every label matured before the next decision | Strict replay schedule and seasonal baseline | Add an opt-in chronological experiment and preserve published evidence |
| Signed registry, promotion, monitoring and rollback | Serving uses an unsigned static batch CSV | Approved artifact carrying model and monitoring provenance | Export a signed snapshot from the current registry champion |
| Authenticated finance and single prediction endpoints | Multi-month and restatement tools operate without prediction context | Governed prediction, drift and variance investigation | Add typed tools and persisted execution checkpoints |
| Keycloak and Docker build, local Qwen finance evaluation and CI | New journey has no independent acceptance evidence | Reproducible offline integration and failure tests | Exercise authenticated routes and compare values against the ledger |

## Integration candidate acceptance

| Gate | Result | Evidence |
| --- | --- | --- |
| Data and reconciliation | Passed locally | Fresh 1,500-member, three-client demo with 35,201 member-months per cutoff and no ledger or close-row differences. |
| Chronological ML | Passed locally | Both 50,000-member runs matched split fingerprints and metrics. Ridge won validation against the prior-quarter and seasonal baselines, boosting, and the CPU MLP. |
| Registry and serving | Passed locally | Validation-gated promotion, candidate rejection, controlled rollback, signed forecasts, matched single and paginated predictions. |
| Historical and restatement tools | Passed locally | 281/281 deterministic financial cases. Docker verified an exact late-correction record alongside the aggregate restatement bridge. |
| Integrated forecast and drift | Passed locally | Returned approved forecast, matured actual and prior-quarter totals for the same 500-member cohort. Fictional client 2 received a signed drift alert under its own token. |
| Safety and recovery | Passed locally | Authentication, tenant denial, stale version, ambiguous dates, signed-artifact tampering, incomplete actuals, misleading tool totals, retry and Docker restart were checked. |
| Open-weight inference | Passed locally | Two actual Qwen requests for historical interpretation in the integrated Docker run. Forecast tool selection and numerical checks run offline. |
| Publication | Pending | GitHub branch available for PR review and publication after repository write access is restored. |

[Strict model comparison](evidence/v2.1-strict-model.json) · [Lifecycle, HTTP traces, restart and Qwen](evidence/v2.1-investigations.json)

The fixed forecast tool plan avoids unbounded tool execution. An unresolvable request returns an escalation for human review. Registry writes require a separate operator workflow. Forecast outputs are point estimates. The evaluation and drift thresholds apply to synthetic data. Hosted-model evaluation and public cloud deployment were outside this run.
