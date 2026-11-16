"""Read-only local demonstration API with signed tenant identity."""

import base64
import binascii
import csv
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import time
import uuid
from collections import deque
from contextlib import closing
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from healthcare.agent import MONTH, question_answer

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
    secret: str,
    predictions: Path | None = None,
    *,
    requests_per_minute: int = 120,
) -> FastAPI:
    if len(secret.encode()) < 32:
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
            for row in csv.DictReader(stream):
                predictions_by_key[
                    int(row["client_id"]), int(row["member_id"]), int(row["period"])
                ] = row

    def identity(authorization: Annotated[str | None, Header()] = None) -> int:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        tenant = verify_token(secret, authorization[7:])
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

    @app.post("/finance/questions")
    def finance(request: Question, tenant: Annotated[int, Depends(identity)]):
        with closing(sqlite3.connect(read_uri, uri=True, timeout=2)) as db:
            result = question_answer(db, tenant, request.question)
        status = {
            "denied": 403,
            "no_evidence": 404,
            "unsupported": 422,
            "ambiguous": 422,
        }.get(result["status"])
        if status:
            raise HTTPException(status, result["status"])
        return result

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
        return finance(Question(question=f"{operation} for {month}"), tenant)

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
    return create_app(
        Path(os.environ["CLAIMS_DATABASE"]),
        os.environ["CLAIMS_DEMO_SECRET"],
        Path(path) if path else None,
        requests_per_minute=int(os.getenv("CLAIMS_REQUESTS_PER_MINUTE", "120")),
    )
