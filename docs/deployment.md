# Deployment

The small synthetic demo starts with `python -m healthcare.cli smoke --database out/v2.sqlite`. The 50,000-member workload is a separate benchmark. Set a random `CLAIMS_DEMO_SECRET` of at least 32 bytes in the local process and use `docker compose up --build -d`. Use `CLAIMS_HTTP_PORT` if port 8000 is in use. Optional versioned predictions use `docker compose -f compose.yaml -f compose.predictions.yaml up --build -d` with `CLAIMS_PREDICTIONS_HOST` pointing to the CSV. Both inputs are mounted read-only. `docker compose down` removes the service and network while keeping those files.

For a Linux host or a managed single-container service, build the same Dockerfile and supply a read-only directory containing the synthetic close database and optional predictions. Supply the following runtime configuration through the host or service settings:

```dotenv
CLAIMS_AUTH_MODE=oidc
CLAIMS_DATABASE=/data/claims.sqlite
CLAIMS_PREDICTIONS=/data/predictions.csv
CLAIMS_OIDC_ISSUER=https://identity.example.invalid
CLAIMS_OIDC_JWKS_URL=https://identity.example.invalid/jwks
CLAIMS_OIDC_AUDIENCE=claims-api
```

Replace the example URLs with the approved issuer. Omit `CLAIMS_PREDICTIONS` when serving finance only. The issuer must issue an RS256 JWT access token with type `at+jwt`, audience `claims-api`, integer `tenant_id` assigned by the issuer, and `claims:read` scope. Configure TLS at the ingress and use a private service or restrict access there. The container serves HTTP on port 8000. Verify readiness, an authorized request, a cross-tenant denial, and recovery after publishing a new read-only snapshot. A single worker owns the demo rate limiter, so a multi-replica deployment needs rate limits at the ingress.

The API answers finance questions locally by default. Enable the hosted router only in an approved environment using `CLAIMS_ENABLE_BILLED_LLM=1`, `CLAIMS_LLM_ENDPOINT`, `CLAIMS_LLM_MODEL`, and a secret-injected `CLAIMS_LLM_API_KEY`. The provider receives question text. Keep private or regulated information out of that input.

## Local TLS identity and inference verification

Install the development requirements and generate disposable credentials and a small synthetic dataset. Run the following from the repository root.

```text
python -m pip install -r requirements-v2.txt
python -m healthcare.local_oidc
docker compose -p claims-v2-acceptance -f compose.oidc.yaml up --build -d
python -m healthcare.verify_local_oidc
docker compose -p claims-v2-acceptance -f compose.oidc.yaml down --volumes
```

Wait for Keycloak discovery before running verification. The identity provider is bound to loopback port 18443 and the API to 18764. The fixture generator writes a seven-day CA and TLS certificate, random credentials for fictional users, a SQLite close, and a ridge prediction file to ignored `out/local-oidc`. It requires a fresh fixture directory. The password grant is enabled for the disposable test clients. Use an approved identity provider and authorization-code flow for a real deployment.

For offline inference, download [Qwen2.5-1.5B-Instruct Q4_K_M](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf) to `out/qwen2.5-1.5b-instruct-q4_k_m.gguf` and verify its SHA-256 is `6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e`. Append `-f compose.local-llm.yaml` to the Compose commands. Verify with `python -m healthcare.verify_local_oidc --model`. The fixture credentials, certificates, model weights, and generated datasets stay local.
