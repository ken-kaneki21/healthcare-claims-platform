# V2 continuation notes

The draft pull request adds a journal-backed close, transactional quarantine, a three-client ingestion and dbt path, local model promotion and rollback, additional financial evaluation cases, and local API rate limiting. Main remains the last published baseline. The implementation status lists the remaining gates for a final release.

The local preview uses entirely synthetic data and illustrative calculations. It can be evaluated without a paid service. A live LLM evaluation requires explicit spending approval and provider configuration. Cloud deployment is optional and requires an approved account and budget.

The verified V2 candidate includes dated analytics rules, faster historical replay, signed-model monitoring, an OIDC integration with signed fixtures, and Windows Docker restart evidence. The hosted model and cloud deployment checks remain open. See the [work checkpoint](WORK_HANDOFF.md) for reproduction.
