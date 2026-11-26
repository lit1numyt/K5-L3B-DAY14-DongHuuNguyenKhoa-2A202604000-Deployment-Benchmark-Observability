# Deployment Information

## Public URL
https://agent-production-9adfa0eb.up.railway.app

## Platform
Railway (project `k5-day14-agent`, region `iad`). There are 2 services:
- `agent`: built from `06-lab-complete/Dockerfile` with `railway up`. `railway.toml` sets the builder to DOCKERFILE and the healthcheck to `/health`.
- `Redis`: a Railway database. The agent connects to it over the private network (`redis.railway.internal`).

## Test Commands

```bash
BASE=https://agent-production-9adfa0eb.up.railway.app
# AGENT_API_KEY = the key set with `railway variables` (not in the repo)
```

### Health Check
```bash
curl $BASE/health
# {"status":"ok","environment":"production"}
curl $BASE/ready
# {"status":"ready","redis":"ok"}
```

### API Test (with authentication)
```bash
curl -X POST $BASE/ask \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# {"question":"Hello","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","cost_usd":1.035e-05}
```

### CP6 self-check (status code only, key not printed)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```
Actual result (2026-11-26): `200`, `200`, `401`, `200`. The rate limit was also checked: 12 consecutive requests with the key returned `200 ×8` then `429 ×4`. Two earlier requests in the same minute had already used part of the 10/minute window.

`python check_production_ready.py --public-url $BASE` → `✅ Public URL: GET .../health → 200`.

## Environment Variables Set
- `PORT`: set by Railway. The Dockerfile CMD uses `${PORT:-8000}`.
- `REDIS_URL`: `${{Redis.REDIS_URL}}`, a reference variable pointing to the Redis service.
- `AGENT_API_KEY`: a random 32-byte value set with `railway variables`. It is not in the repo.
- `ENVIRONMENT`: `production`.
- `LOG_LEVEL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`: code defaults (`INFO`, `10`, `1.0`, `10.0`).

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png): output of `railway status`, `deployment list` and `logs`. Both services are Online and the deployment shows SUCCESS.
- [Service running](screenshots/running.png): `/health` and `/ready` on the public URL.
- [Test results](screenshots/test.png): the 4 CP6 commands, the rate-limit test, and the checker run with `--public-url`.
