# Frozen finance evaluation over authenticated HTTP

The runner starts only the existing pinned llama.cpp container with a
read-only local Qwen GGUF mount and a disposable loopback port. An isolated
native Uvicorn instance uses the application's signed demo bearer tokens and
a new 100-member, three-tenant synthetic SQLite ledger with seed 73.

```powershell
pwsh -NoProfile -File scripts/verify-live-http.ps1 -Python <venv-python.exe> -ModelFile <existing-qwen.gguf> -OutputDirectory <new-evidence-directory> -PreflightOnly
pwsh -NoProfile -File scripts/verify-live-http.ps1 -Python <venv-python.exe> -ModelFile <existing-qwen.gguf> -OutputDirectory <different-evidence-directory>
```

The fresh output directory contains gate.json and, once HTTP evaluation is
attempted, http.json. The integration report records the fixture hash,
requested runtime pin, GGUF hash, system prompt and routing schema, attempted
model requests, HTTP responses, effective tool arguments, model proposals,
numeric results, evidence and timings. The oracle uses independent SQL over
the seeded payment events. Anonymous and wrong-tenant requests must return
401 and 403. The valid second-tenant token must be scoped to tenant 2. Cases
resolved deterministically have no provider events. Error HTTP responses
carry status detail and do not expose internal tool identity. This exercises
the signed-demo scope. Keycloak/OIDC remains a separate deployment mode.

24 November 2026: static Compose validation confirmed the pinned model image,
loopback mapping and read-only mount. The GGUF was present and hashed.
The model probe failed with Winsock 10013 in the managed environment. The
frozen cases have zero new live model calls and no authenticated HTTP score.
Retain the deterministic and mock reports separately.
