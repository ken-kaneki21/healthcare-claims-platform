FROM python:3.12-slim
WORKDIR /app
COPY requirements-serving.txt ./
RUN python -m pip install --no-cache-dir --upgrade "pip>=26.2,<27" \
    && python -m pip install --no-cache-dir -r requirements-serving.txt
COPY healthcare ./healthcare
COPY financial_tools.py .
USER 65534:65534
CMD ["uvicorn", "healthcare.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]
