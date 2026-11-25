# Authored finance routing holdout

This small suite checks questions over a freshly generated three-tenant
dataset with 100 synthetic members and seed 73. The implementation assistant
wrote the 11 cases and froze them in commit `3b7e69e` before changes.
The labels have no independent human validation.

From a checkout with the existing `requirements-v2.txt` environment:

```powershell
python -m healthcare.holdout_evaluation --out out/finance-holdout.json --require-correct
python -m unittest -v test_financial_questions test_local_model test_journal_close test_v2_ingest
```

The comparison uses an independent SQL sum of ledger events and count of
enrolment rows. It checks the requested tool and period, amounts, evidence
scope and boundary behavior.

| Layer | Baseline | After |
|---|---:|---:|
| Deterministic authored holdout | 8/11 | 11/11 |
| Mock transport boundary | 4/4 | 4/4 |
| Wrong-client case | 0 boundary failures | 0 boundary failures |
| Unexpected values on an abstention case | 1 | 0 |
| Live-model evaluation on this holdout | Pending | Blocked at the loopback model probe |

See [baseline](evidence/finance-holdout-baseline.json),
[after](evidence/finance-holdout-after.json) and
[live preflight](evidence/finance-holdout-live-check.json). The historical
Qwen report in [agent evaluation](agent-evaluation.md) uses a different
set. A model may select a historical finance operation. The application
resolves dates, enforces tenant scope and calculates numbers. The new
two-month comparison is deterministic, with no model call.

For a live rerun, start the existing local Qwen overlay using the local
deployment guide, set the loopback endpoint and model ID and add `--live`
with a new output path. The runtime needs to serve both `/v1/models` and
`/v1/chat/completions`. The fixture includes a copied-note policy case.
It does not claim coverage of arbitrary retrieved instructions. It includes
an invalid provider argument, contradictory proposed date and a simulated
timeout at the adapter boundary. An authenticated HTTP replay and independent
review are separate gates.
