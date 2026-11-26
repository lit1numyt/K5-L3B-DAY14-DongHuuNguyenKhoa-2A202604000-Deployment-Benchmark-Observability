"""
Production AI Agent — Part 6 Final Project.

Kiểm tra:
    python check_production_ready.py
"""
import json
import logging
import sys
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging — mỗi dòng log là 1 JSON object
# ─────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        payload.update(getattr(record, "extra_fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("agent")
    log.handlers = [handler]
    log.setLevel(settings.log_level)
    log.propagate = False
    return log


logger = _setup_logging()


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"extra_fields": fields})


app = FastAPI(title="Production AI Agent")


@app.middleware("http")
async def request_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log_event("request", method=request.method, path=request.url.path,
              status=response.status_code, ms=round((time.perf_counter() - started) * 1000, 1))
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


@app.get("/health")
def health():
    """Liveness — luôn 200 khi process còn chạy, không phụ thuộc Redis."""
    return {"status": "ok", "environment": settings.environment}


@app.get("/ready")
def ready():
    """Readiness — 503 khi Redis không kết nối được."""
    if not redis_healthy():
        return JSONResponse(status_code=503, content={"status": "not ready", "redis": "unreachable"})
    return {"status": "ready", "redis": "ok"}


@app.post("/ask")
def ask(body: AskRequest):
    answer = llm_ask(body.question)
    return {"question": body.question, "answer": answer}
