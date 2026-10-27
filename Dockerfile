# syntax=docker/dockerfile:1
# One image for both processes:
#   web:    default CMD (uvicorn; serves the API and the built UI)
#   worker: python -m inbox_helper.worker
# Both apply pending migrations at startup (Postgres advisory lock, so starting them together is safe).
# Secrets (GEMINI_API_KEY, OPENROUTER_API_KEY, DATABASE_URL) come from the host's environment, never from the image.

FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY inbox_helper/ inbox_helper/
COPY policies/ policies/
COPY data/messages.csv data/messages.csv
COPY --from=ui /ui/dist frontend/dist

RUN useradd --create-home --uid 10001 app && mkdir -p .cache .data && chown app .cache .data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
# --proxy-headers: HTTPS is terminated by the host's proxy (Render, Fly, a load balancer)
CMD ["sh", "-c", "exec uvicorn inbox_helper.server:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
