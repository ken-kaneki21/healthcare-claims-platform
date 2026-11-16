# Local service security

Use the API on a local loopback binding. Demo tokens use a server-held HMAC secret with a maximum one-hour lifetime. Issue them through the local CLI and keep them out of logs and source files. There is no public token creation endpoint. Both finance and prediction routes bind data access to the signed tenant. Explicitly targeting another tenant returns 403. Extra body fields are rejected and queries bind SQL parameters.

The local identity mechanism has no revocation, external identity integration, per-user roles or production rate limits. Prompt checks catch explicit cases covered by evaluation. Tenant isolation relies on the identity and database query filters. It does not depend on the prompt. The live provider adapter has a request timeout and does not receive ledger rows.
