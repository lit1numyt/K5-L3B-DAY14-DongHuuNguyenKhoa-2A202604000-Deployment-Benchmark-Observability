"""
Kết nối Redis dùng chung cho rate limiter và cost guard.

  • Client tạo lazy từ REDIS_URL — redis-py chỉ mở kết nối khi có lệnh đầu tiên,
    nên app vẫn KHỞI ĐỘNG ĐƯỢC khi Redis chưa sẵn sàng.
  • Timeout ngắn để /ready và /ask không treo khi Redis chết.
  • redis_healthy() dùng cho GET /ready.
"""
import redis

from app.config import settings

r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
    health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False


def close() -> None:
    try:
        r.close()
    except redis.RedisError:
        pass
