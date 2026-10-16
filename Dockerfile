FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY frontend ./frontend
COPY data ./data

RUN python -m pip install . \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8765"]
