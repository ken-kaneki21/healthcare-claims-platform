# Financial agent evaluation

The offline run uses a rules-based router. It checks close amounts, PMPM and restatement values against signed ledger totals and eligibility counts. Additional cases check unavailable periods and direct requests for another numbered tenant. The case generator is versioned as `finance-gold-1`. Many questions use templates. Treat this score as an integration regression check.

The optional HTTPS adapter sends only the synthetic question to a configured chat-completions service. The provider can choose an allowed operation and a month. SQL supplies amounts and evidence. Configure `CLAIMS_LLM_ENDPOINT`, `CLAIMS_LLM_MODEL`, and `CLAIMS_LLM_API_KEY`, then run `python -m healthcare.cli eval-agent --database out/v2.sqlite --provider live --allow-billed` only after approving the provider and its charges. No live metric is recorded in this branch.
