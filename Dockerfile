FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt requirements-v2.txt ./
RUN pip install --no-cache-dir -r requirements-v2.txt
COPY healthcare ./healthcare
COPY financial_tools.py .
USER 65534:65534
CMD ["uvicorn", "healthcare.api:from_environment", "--factory", "--host", "0.0.0.0", "--port", "8000"]
