# syntax=docker/dockerfile:1
# ── Stage 1: builder — cài dependencies vào /install ─────────────
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ── Stage 2: runtime — chỉ copy site-packages + source ──────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    ENVIRONMENT=production

RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=app:app app/ ./app/
COPY --chown=app:app utils/ ./utils/

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=2)" || exit 1

# exec → uvicorn là PID 1, nhận SIGTERM trực tiếp khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --timeout-graceful-shutdown 8"]
