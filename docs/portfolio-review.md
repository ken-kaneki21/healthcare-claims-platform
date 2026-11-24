# Healthcare Claims Platform review candidate

Source checkpoint `8b5267c`. The isolated signed-demo HTTP run uses a seeded 100-member, three-tenant synthetic ledger and a pinned local llama.cpp/Qwen 2.5 1.5B Instruct Q4_K_M runtime. Identity and policy checks gate deterministic financial tools. An independent SQL reference checks financial outcomes.

Follow [the local acceptance runbook](live-http-acceptance.md). Use the existing permitted Qwen GGUF, the pinned image and a fresh output directory:

```powershell
pwsh -NoProfile -File scripts/verify-live-http.ps1 -Python (Get-Command python).Source -ModelFile (Read-Host 'Path to the approved local GGUF') -OutputDirectory (Join-Path $PWD ('local/finance-' + (Get-Date -Format yyyyMMdd-HHmmss)))
```

All 11 authored checks matched expectations. Three successful financial cases matched independent SQL. Two actual provider calls returned HTTP 200. One selected a financial route and the other proposal was stopped by policy. [Accepted HTTP report](evidence/sprint-http-acceptance.json). The report pins the runtime and model hash. Local signed-demo authentication, Keycloak/OIDC and production security have different scopes.

The historical managed probe failed before any HTTP provider call. No new Healthcare Qwen serving benchmark ran in the sprint. The companion's separate tiny CPU decoder experiment is independent of this project. Model and container binaries are excluded. Review their upstream notices and code licence before publication.
