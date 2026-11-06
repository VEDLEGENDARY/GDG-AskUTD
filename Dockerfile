FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN pip install --no-cache-dir "fastapi>=0.110,<1" "uvicorn[standard]>=0.30,<1" \
    "pydantic>=2.8,<3" "python-dotenv>=1,<2"
COPY backend/__init__.py backend/__init__.py
COPY backend/app backend/app
COPY backend/data/chunks backend/data/chunks
RUN mkdir -p backend/storage && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
