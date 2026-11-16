FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89
WORKDIR /app
COPY requirements-serving.txt ./
RUN apk upgrade --no-cache \
    && python -m pip install --no-cache-dir --upgrade "pip>=26.2,<27" \
    && python -m pip install --no-cache-dir -r requirements-serving.txt
COPY healthcare ./healthcare
COPY financial_tools.py .
USER 65534:65534
CMD ["uvicorn", "healthcare.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
