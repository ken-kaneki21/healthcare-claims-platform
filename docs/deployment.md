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
