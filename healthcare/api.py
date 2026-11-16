"""Read-only local demonstration API with signed tenant identity."""

import base64
import binascii
import csv
import hashlib
import hmac
import json
import logging
import math
import os
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from healthcare.agent import MONTH, question_answer, rules

LOGGER = logging.getLogger("uvicorn.error")


def issue_token(secret: str, tenant: int, lifetime: int = 3600) -> str:
    if (
        len(secret.encode()) < 32
        or tenant not in (1, 2, 3)
        or not 1 <= lifetime <= 3600
    ):
        raise ValueError(
            "Require a 32-byte secret, demo tenant 1–3, and a TTL up to one hour"
        )
    message = (
        base64.urlsafe_b64encode(
            json.dumps(
                {"tenant": tenant, "exp": int(time.time()) + lifetime},
                separators=(",", ":"),
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    return (
        message
        + "."
        + hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    )


def verify_token(secret: str, token: str) -> int:
    try:
        message, signature = token.split(".")
        if not message or len(message) > 256 or len(signature) != 64:
            raise ValueError
        expected = hmac.new(
            secret.encode(), message.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(
            base64.urlsafe_b64decode(message + "=" * (-len(message) % 4))
        )
        tenant, expiration = payload["tenant"], payload["exp"]
        if (
            type(tenant) is not int
            or tenant not in (1, 2, 3)
            or type(expiration) is not int
        ):
            raise ValueError
        if not 0 < expiration - time.time() <= 3600:
            raise ValueError
        return tenant
    except (ValueError, TypeError, KeyError, binascii.Error) as error:
        raise HTTPException(401, "Invalid or expired demo token") from error


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=500)


def create_app(
    database: Path,
    secret: str | None,
    predictions: Path | None = None,
    *,
    requests_per_minute: int = 120,
    access_token_identity: Callable[[str], int] | None = None,
    question_router: Callable[[str], dict] = rules,
) -> FastAPI:
    if access_token_identity is None and (secret is None or len(secret.encode()) < 32):
        raise ValueError("CLAIMS_DEMO_SECRET must contain at least 32 bytes")
    if not 1 <= requests_per_minute <= 10_000:
        raise ValueError("Requests per minute must be 1–10,000")
    app = FastAPI(title="Synthetic claims local API", version="2.0.0-dev")
    requests = {tenant: deque() for tenant in (1, 2, 3)}
    lock = Lock()
    read_uri = f"{database.resolve().as_uri()}?mode=ro"
    predictions_by_key: dict[tuple[int, int, int], dict[str, str]] = {}
    if predictions is not None:
        with predictions.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != [
                "client_id",
                "member_id",
                "period",
                "model_version",
                "predicted_cost_usd",
            ]:
                raise ValueError("Invalid prediction columns")
            for row in reader:
                client, member, period = (
                    int(row[name]) for name in ("client_id", "member_id", "period")
                )
                key = client, member, period
                cost = float(row["predicted_cost_usd"])
                if (
                    client not in requests
                    or member < 1
                    or not 7 <= period <= 24
                    or not row["model_version"]
                    or not math.isfinite(cost)
                    or cost < 0
                    or key in predictions_by_key
                ):
                    raise ValueError("Invalid prediction row")
                predictions_by_key[key] = row

    def identity(authorization: Annotated[str | None, Header()] = None) -> int:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        token = authorization[7:]
        if access_token_identity is None:
            assert secret is not None
            tenant = verify_token(secret, token)
        else:
            try:
                tenant = access_token_identity(token)
            except ValueError as error:
                raise HTTPException(401, "Invalid access token") from error
        with lock:
            now = time.monotonic()
            recent = requests[tenant]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= requests_per_minute:
                raise HTTPException(
                    429,
                    "Tenant request limit reached",
                    headers={"Retry-After": str(max(1, 60 - int(now - recent[0])))},
                )
            recent.append(now)
        return tenant

    @app.middleware("http")
    async def request_id(request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        identifier = uuid.uuid4().hex
        response.headers["X-Request-ID"] = identifier
        LOGGER.info(
            json.dumps(
                {
                    "request_id": identifier,
                    "method": request.method,
                    "status": response.status_code,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/ready")
    def readiness():
        try:
            with closing(sqlite3.connect(read_uri, uri=True, timeout=2)) as db:
                db.execute("SELECT id FROM close_run LIMIT 1").fetchone()
        except sqlite3.Error as error:
            raise HTTPException(503, "Claims database unavailable") from error
        return {"status": "ready"}

    def finance_response(question: str, tenant: int, route):
        try:
            with closing(sqlite3.connect(read_uri, uri=True, timeout=2)) as db:
                result = question_answer(db, tenant, question, route)
        except (httpx.HTTPError, sqlite3.Error) as error:
            raise HTTPException(
                503, "Finance service temporarily unavailable"
            ) from error
        status = {
            "denied": 403,
            "no_evidence": 404,
            "unsupported": 422,
            "ambiguous": 422,
        }.get(result["status"])
        if status:
            raise HTTPException(status, result["status"])
        return result

    @app.post("/finance/questions")
    def finance(request: Question, tenant: Annotated[int, Depends(identity)]):
        return finance_response(request.question, tenant, question_router)

    @app.get("/finance/{tenant_id}/{operation}/{month}")
    def finance_tool(
        tenant_id: int,
        operation: Literal["close", "restatement", "pmpm"],
        month: str,
        tenant: Annotated[int, Depends(identity)],
    ):
        if tenant_id != tenant:
            raise HTTPException(403, "Tenant outside token scope")
        if not MONTH.fullmatch(month):
            raise HTTPException(422, "Use a month in YYYY-MM format")
        return finance_response(f"{operation} for {month}", tenant, rules)

    @app.get("/models")
    def models(_tenant: Annotated[int, Depends(identity)]):
        return {
            "versions": sorted(
                {
                    row["model_version"]
                    for key, row in predictions_by_key.items()
                    if key[0] == _tenant
                }
            )
        }

    @app.get("/predictions/{tenant_id}/{member_id}/{period}")
    def prediction(
        tenant_id: int,
        member_id: int,
        period: int,
        tenant: Annotated[int, Depends(identity)],
    ):
        if tenant_id != tenant:
            raise HTTPException(403, "Tenant outside token scope")
        row = predictions_by_key.get((tenant, member_id, period))
        if row is None:
            raise HTTPException(404, "No matching batch prediction")
        return {
            "member_id": member_id,
            "period": period,
            "model_version": row["model_version"],
            "predicted_cost_usd": float(row["predicted_cost_usd"]),
        }

    return app


def from_environment():
    path = os.getenv("CLAIMS_PREDICTIONS")
    mode = os.getenv("CLAIMS_AUTH_MODE", "demo")
    token_identity = None
    secret = None
    if mode == "demo":
        secret = os.environ["CLAIMS_DEMO_SECRET"]
    elif mode == "oidc":
        from healthcare.identity import OidcIdentity

        token_identity = OidcIdentity(
            os.environ["CLAIMS_OIDC_ISSUER"],
            os.environ["CLAIMS_OIDC_AUDIENCE"],
            os.environ["CLAIMS_OIDC_JWKS_URL"],
        )
    else:
        raise ValueError("CLAIMS_AUTH_MODE must be demo or oidc")
    route = rules
    if os.getenv("CLAIMS_ENABLE_BILLED_LLM") == "1":
        from urllib.parse import urlsplit

        from healthcare.agent import provider_router

        endpoint = os.environ["CLAIMS_LLM_ENDPOINT"]
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
        ):
            raise ValueError("Configure an HTTPS LLM endpoint")
        api_key = os.environ["CLAIMS_LLM_API_KEY"]
        model = os.environ["CLAIMS_LLM_MODEL"]

        def route(question):
            with httpx.Client() as client:
                interpret, _ = provider_router(client, endpoint, api_key, model)
                return interpret(question)

    return create_app(
        Path(os.environ["CLAIMS_DATABASE"]),
        secret,
        Path(path) if path else None,
        requests_per_minute=int(os.getenv("CLAIMS_REQUESTS_PER_MINUTE", "120")),
        access_token_identity=token_identity,
        question_router=route,
    )
