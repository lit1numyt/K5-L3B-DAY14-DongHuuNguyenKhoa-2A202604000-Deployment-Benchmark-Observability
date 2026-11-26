# Day 14 Lab — Mission Answers

> Mọi output dưới đây là output thật chạy trên máy (macOS, Docker Desktop, Python 3.11). Token / key đã được che.

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secret** (dòng 17–18): `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL` có cả mật khẩu `password123`. Push lên GitHub là lộ key ngay, và đổi key thì phải sửa code + deploy lại.
2. **Log ra secret** (dòng 34): `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")`. Khi chạy thật, log của tôi in đúng dòng `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`, nên ai đọc được log (log aggregator, CI) cũng có key.
3. **`print()` thay vì structured logging** (dòng 33, 38): không có level, timestamp hay format máy đọc được, không lọc/tìm kiếm được trên Loki/Datadog, và còn log nguyên nội dung câu hỏi/câu trả lời của user.
4. **Config cứng, không có config management** (dòng 21–22): `DEBUG = True`, `MAX_TOKENS = 500` cố định trong code, không đổi được giữa dev/staging/prod.
5. **Không có health check** (dòng 42): gọi `GET /health` trả **404** (xem output 1.2). Platform không biết agent còn sống để restart.
6. **Bind `localhost` + port cứng 8000** (dòng 51–52): trong container, `localhost` nghĩa là không nhận kết nối từ ngoài container; Railway/Render cấp `PORT` qua env nên port cứng sẽ không khớp.
7. **`reload=True` ở production** (dòng 53): bật file watcher (tốn CPU, có thể restart giữa chừng), chỉ dùng cho dev.
8. **Không xử lý graceful shutdown**: không có lifespan/cleanup, không có readiness để load balancer ngừng gửi traffic trước khi tắt.

### Exercise 1.2: Chạy bản develop

```text
$ curl -X POST "http://localhost:8000/ask?question=Hello"
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
$ curl -i http://localhost:8000/health
HTTP/1.1 404 Not Found
```

Nó chạy được, nhưng không production-ready: không có `/health` (404), log lộ secret, chỉ nghe trên `localhost:8000`.

Bản production (`01-localhost-vs-production/production`, `ENVIRONMENT=development python app.py`):

```text
$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","model":"gpt-4o-mini"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.9,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:24:06.845647+00:00"}
$ curl http://localhost:8000/ready
{"ready":true}
```

### Exercise 1.3: So sánh develop vs production

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`OPENAI_API_KEY`, `DEBUG`, `MAX_TOKENS`) | `config.py` đọc mọi giá trị từ env (`os.getenv`), `validate()` fail-fast nếu thiếu `AGENT_API_KEY` ở production | Cùng một artifact chạy được ở dev/staging/prod chỉ bằng cách đổi env; secret không nằm trong git; thiếu config thì crash ngay lúc start thay vì lỗi lúc có traffic |
| Secrets | Key trong code và bị `print` ra log | Đọc từ env, log chỉ ghi `question_length`, không ghi secret | Lộ key = mất tiền / bị lạm dụng; log thường được nhiều người/hệ thống đọc hơn code |
| Health check | Không có (`/health` → 404) | `GET /health` (liveness, uptime, version) + `GET /ready` (readiness, 503 khi chưa sẵn sàng) | Platform dùng liveness để restart container chết, load balancer dùng readiness để chỉ gửi traffic tới instance đã sẵn sàng |
| Logging | `print()` dạng text tự do | JSON (`{"time":...,"level":...,"msg":...}`) và event có cấu trúc | Log aggregator parse, lọc, đếm, alert được; có level để tắt debug ở prod |
| Shutdown | Đột ngột, không cleanup | `lifespan` để startup/shutdown + handler SIGTERM, uvicorn chờ request đang chạy xong | Deploy/scale-in không cắt ngang request của user, đóng kết nối DB/Redis sạch sẽ |
| Host / Port | `localhost:8000` cứng | `HOST=0.0.0.0`, `PORT` từ env | Container và cloud platform inject `PORT`; `0.0.0.0` mới nhận được traffic từ ngoài container |
| Reload / Debug | `reload=True`, `DEBUG=True` luôn bật | Chỉ bật khi `DEBUG=true` | Debug ở prod tốn tài nguyên và có thể lộ thông tin nội bộ |
| CORS | Không cấu hình | `ALLOWED_ORIGINS` từ env | Giới hạn origin được gọi API từ trình duyệt |

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`

1. **Base image:** `python:3.11`, bản Python **full** (Debian + build tools, gcc, header...). Tiện nhưng rất nặng (image develop đo được 1.67 GB, xem 2.3).
2. **Working directory:** `/app` (`WORKDIR /app`). Mọi lệnh `COPY`/`RUN`/`CMD` sau đó chạy tương đối với `/app`.
3. **Vì sao `COPY requirements.txt` trước `COPY` code:** Docker cache theo layer. Code thay đổi liên tục còn dependencies hiếm khi đổi. Copy `requirements.txt` rồi `pip install` trước thì layer cài đặt được cache và chỉ build lại khi `requirements.txt` đổi. Nếu `COPY . .` trước, mỗi lần sửa 1 dòng code sẽ invalidate cache và phải `pip install` lại từ đầu.
4. **CMD vs ENTRYPOINT:** `CMD` là lệnh/tham số **mặc định**, bị ghi đè khi chạy `docker run image <lệnh khác>`. `ENTRYPOINT` là executable **cố định** của container, tham số của `docker run` được nối vào sau nó (chỉ đổi được bằng `--entrypoint`). Thường dùng `ENTRYPOINT` cho binary chính, `CMD` cho tham số mặc định. Cả hai nên dùng exec form (`["..."]`) để process là PID 1 và nhận được SIGTERM.

### Exercise 2.2: Build và chạy bản develop

Build từ gốc repo: `docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .`, chạy `docker run -p 8000:8000 my-agent:develop`:

```text
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.0,"container":true}
```

### Exercise 2.3: Multi-stage build và kích thước image

- **Stage 1 (`builder`, `python:3.11-slim`):** cài `gcc`, `libpq-dev` rồi `pip install --user -r requirements.txt` vào `/root/.local`. Stage này có đủ build tools nhưng **không** được deploy.
- **Stage 2 (`runtime`, `python:3.11-slim`):** tạo user non-root `appuser`, chỉ `COPY --from=builder /root/.local` (site-packages đã cài) + `main.py` + `utils/`, có `HEALTHCHECK`, chạy `uvicorn` 2 workers.
- **Vì sao nhỏ hơn:** image cuối không chứa gcc/headers/apt cache/pip cache, và dùng base `slim` thay vì full `python:3.11`. Chỉ phần cần để *chạy* được copy sang.

`docker images my-agent` (đo trên máy tôi):

```text
my-agent:advanced   3babec8b9a81        265MB         57.5MB        
my-agent:develop    180f7033b987       1.67GB          415MB        
[my-agent:develop] 415378586
```

| Image | Disk usage (unpacked) | Content size (compressed) |
|---|---|---|
| `my-agent:develop` (single-stage, `python:3.11`) | 1.67 GB = 1670 MB | 415 MB |
| `my-agent:advanced` (multi-stage, `python:3.11-slim`) | 265 MB | 57.5 MB |
| **Chênh lệch** | **giảm 84.1 %** ((1670 − 265) / 1670) | **giảm 86.2 %** |

- Develop: **1670 MB**
- Production: **265 MB**
- Difference: **−84.1 %**

### Exercise 2.4: Docker Compose stack

Chạy `touch .env.local && docker compose -p k5-day14-docker up -d --build` trong `02-docker/production/`:

```text
SERVICE   IMAGE                   STATUS                    PORTS
agent     k5-day14-docker-agent   Up 15 seconds (healthy)   8000/tcp
nginx     nginx:alpine            Up 15 seconds             0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp
qdrant    qdrant/qdrant:v1.9.0    Up 26 seconds (healthy)   6333-6334/tcp
redis     redis:7-alpine          Up 26 seconds (healthy)   6379/tcp
```

Sơ đồ kiến trúc:

```text
                    host :80 / :443
                          │
                   ┌──────▼──────┐
  Client ────────► │    nginx    │  reverse proxy + LB, rate limit 10 r/s/IP,
                   │ (nginx:alpine)│  security headers
                   └──────┬──────┘
                          │ http://agent:8000   (network "internal", không expose port)
                   ┌──────▼──────┐
                   │    agent    │  FastAPI, uvicorn 2 workers, HEALTHCHECK /health
                   └───┬─────┬───┘
     redis://redis:6379│     │http://qdrant:6333
                ┌──────▼─┐ ┌─▼────────┐
                │ redis  │ │  qdrant  │
                │ cache, │ │ vector DB│
                │ session│ │  (RAG)   │
                └────────┘ └──────────┘
   volumes: redis_data, qdrant_data   ·   agent depends_on redis + qdrant (service_healthy)
```

Các service giao tiếp qua bridge network `internal` bằng tên service (DNS nội bộ của Docker). Chỉ nginx publish port ra host, còn agent/redis/qdrant không truy cập được trực tiếp từ ngoài.

Test qua Nginx:

```text
$ curl http://localhost/health
{"status":"ok","uptime_seconds":14.7,"version":"2.0.0","timestamp":"2026-11-26T07:30:32.912772"}
$ curl -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
{"answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

## Part 4: API Security

### Exercise 4.1: API key authentication (`04-api-gateway/develop/app.py`)

- **Key được check ở đâu?** Trong dependency `verify_api_key` (dòng 39–54). Hàm này đọc header `X-API-Key` qua `APIKeyHeader(name="X-API-Key", auto_error=False)` và được gắn vào `/ask` bằng `Depends(verify_api_key)`. Key đúng lấy từ env `AGENT_API_KEY` (dòng 35).
- **Sai key thì sao?** Thiếu header → **401** `Missing API key`; có header nhưng sai → **403** `Invalid API key` (bản demo này phân biệt 401/403; ở Part 6 tôi trả 401 cho cả hai trường hợp theo hợp đồng chấm).
- **Rotate key thế nào?** Key nằm trong env chứ không trong code: đặt giá trị mới cho `AGENT_API_KEY` trên platform rồi restart/redeploy, không phải sửa code. Muốn không downtime thì cho app chấp nhận tạm 2 key (cũ + mới, vd `AGENT_API_KEYS=old,new`), cập nhật client sang key mới, rồi bỏ key cũ.

Chạy `AGENT_API_KEY=secret-key-123 python app.py`:

```text
# Không có key
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
content-length: 67
content-type: application/json

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

# Sai key
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
content-length: 29
content-type: application/json

{"detail":"Invalid API key."}

# Có key
$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
content-length: 114
content-type: application/json

{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT authentication (`04-api-gateway/production/`)

JWT flow trong `auth.py`: `POST /auth/token` kiểm username/password (`authenticate_user`), rồi `create_token` ký JWT **HS256** bằng `JWT_SECRET` (env) với claims `sub`, `role`, `iat`, `exp` (60 phút). Client gửi `Authorization: Bearer <token>`; `verify_token` decode + verify chữ ký và hạn: thiếu token hoặc token hết hạn → **401**, token sai chữ ký/không hợp lệ → **403**. Server không cần lưu session (stateless), và role nằm ngay trong token để phân quyền.

### Exercise 4.3: Rate limiting

- **Algorithm:** **Sliding window** (sliding window log): mỗi user có một `deque` timestamp, mỗi request bỏ các timestamp cũ hơn 60 s rồi đếm.
- **Limit:** `rate_limiter_user` = **10 req/phút**, `rate_limiter_admin` = **100 req/phút**.
- **Bypass cho admin:** không bypass hẳn mà chọn limiter theo `role` trong JWT (`limiter = rate_limiter_admin if role == "admin" else rate_limiter_user`), nên admin có quota cao hơn.
- Lưu ý: limiter này nằm trong RAM, nên chạy nhiều instance/worker thì mỗi instance đếm riêng. Ở Part 6 tôi chuyển sang Redis sorted set.

Output thật (token của `student` đã che), đúng 10 request 200 rồi 429:

```text
# Lấy token
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
content-length: 307
content-type: application/json
vary: Origin

{"access_token":"<TOKEN_MASKED>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN_MASKED>"}

# Không có token → 401
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
content-length: 76
content-type: application/json
vary: Origin

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

# Exercise 4.3 — vòng lặp 20 request với token student (limit 10/phút)
$ for i in {1..20}; do curl -s -o /dev/null -w "req $i -> %{http_code}
" -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"question\": \"Test $i\"}"; done
req 1 -> 200
req 2 -> 200
req 3 -> 200
req 4 -> 200
req 5 -> 200
req 6 -> 200
req 7 -> 200
req 8 -> 200
req 9 -> 200
req 10 -> 200
req 11 -> 429
req 12 -> 429
req 13 -> 429
req 14 -> 429
req 15 -> 429
req 16 -> 429
req 17 -> 429
req 18 -> 429
req 19 -> 429
req 20 -> 429

# Response 429 đầy đủ
$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Test 21"}'
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795678351
retry-after: 59
content-length: 98
content-type: application/json
vary: Origin

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard

Cách tôi làm trong `06-lab-complete/app/cost_guard.py`:

1. **Trước khi gọi LLM**, `check_budget()` đọc 2 counter trong Redis bằng một lệnh `MGET`: `cost:daily:<YYYY-MM-DD>` và `cost:monthly:<YYYY-MM>` (UTC). Nếu tổng ≥ `DAILY_BUDGET_USD` hoặc ≥ `MONTHLY_BUDGET_USD` thì trả **HTTP 402 Payment Required**, không gọi LLM nữa.
2. **Sau khi gọi LLM**, `record_cost(input_tokens, output_tokens)` tính `cost = in/1000 × $0.00015 + out/1000 × $0.0006` (giá gpt-4o-mini) rồi `INCRBYFLOAT` vào cả 2 key trong một pipeline, kèm `EXPIRE` (2 ngày / 32 ngày).
3. **Reset tự động:** tên key chứa ngày/tháng, nên sang ngày/tháng mới là key mới bắt đầu từ 0. Key cũ tự hết hạn, không cần cron.
4. **Vì sao Redis:** mọi worker/instance cộng dồn chung một counter, và counter vẫn còn khi restart (script chấm kiểm tra: budget 0.000001 USD → **402** ở request thứ 2).
5. So với solution mẫu (per-user `$10/tháng`, `current + estimated_cost > 10`): tôi giữ budget toàn cục theo hợp đồng chấm. Muốn per-user chỉ cần thêm `user_id` vào key (`cost:monthly:<user>:<YYYY-MM>`).

**Rate limit vs cost guard:** rate limit bảo vệ **tốc độ** (chống spam/DoS, chia công bằng tài nguyên theo thời gian), còn cost guard bảo vệ **tiền** (tổng chi trong ngày/tháng). Một user gọi đều 9 req/phút cả ngày không vi phạm rate limit nhưng vẫn có thể đốt hết ngân sách, nên cần cả hai.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks

`05-scaling-reliability/develop/app.py` đã có:
- `GET /health` (**liveness**): trả 200 khi process còn chạy, kèm uptime và check memory. Platform restart container khi endpoint này fail.
- `GET /ready` (**readiness**): 200 khi `_is_ready=True`, **503** khi đang khởi động/đang tắt. Load balancer chỉ route traffic tới instance ready.

Khác nhau: liveness trả lời câu hỏi "có cần **restart** không?", readiness trả lời "có nên **gửi traffic** vào không?". Vì vậy ở Part 6, `/health` không phụ thuộc Redis (Redis chết mà restart agent cũng không giải quyết được gì, chỉ gây restart loop), còn `/ready` trả 503 khi mất Redis để LB tạm rút instance ra.

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":3.8,"version":"1.0.0","environment":"development","timestamp":"2026-11-26T07:31:48.696910+00:00","checks":{"memory":{"status":"ok","used_percent":81.1}}}
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

### Exercise 5.2: Graceful shutdown

App dùng `lifespan`: khi shutdown, đặt `_is_ready=False` (readiness → 503) và chờ `_in_flight_requests` về 0 (middleware đếm request đang chạy), tối đa 30 s. Handler SIGTERM chỉ log và **để uvicorn xử lý**: uvicorn ngừng nhận kết nối mới, chờ request đang chạy xong rồi chạy phần shutdown của lifespan.

Test: gửi `POST /ask` rồi `kill -TERM <pid>` ngay sau 50 ms:

```text
in-flight request result:
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."} [HTTP 200]
--- server log:
INFO:     Shutting down
INFO:     127.0.0.1:51225 - "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Waiting for application shutdown.
2026-11-26 14:31:51,893 INFO 🔄 Graceful shutdown initiated...
2026-11-26 14:31:51,893 INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [74037]
2026-11-26 14:31:51,893 INFO Received signal 15 — uvicorn will handle graceful shutdown
```

Request đang chạy vẫn nhận **200**, uvicorn log `Shutting down` → hoàn thành request → `Application shutdown complete` → process thoát.

### Exercise 5.3: Stateless design

`05-scaling-reliability/production/app.py` lưu session/conversation history trong Redis (`session:<id>`, `SETEX` có TTL) thay vì dict trong RAM. Mọi instance đọc/ghi cùng một chỗ, nên request kế tiếp của cùng session có thể đi vào instance bất kỳ. Nếu để `conversation_history = {}` trong RAM, mỗi instance có bản riêng: user bị "mất trí nhớ" khi LB chuyển sang instance khác, và mất hết khi instance restart/scale-in. Ở Part 6 tôi áp dụng cùng nguyên tắc cho rate limit và cost guard (Redis), và script chấm xác nhận state còn sau khi restart agent.

### Exercise 5.4: Load balancing

`docker compose -p k5-day14-scaling up -d --build --scale agent=3` trong `05-scaling-reliability/production/`:

```text
NAME                       STATUS                    PORTS
k5-day14-scaling-agent-1   Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 12 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 12 seconds             0.0.0.0:8080->80/tcp, [::]:8080->80/tcp
k5-day14-scaling-redis-1   Up 23 seconds (healthy)   6379/tcp
```

10 request `POST /chat` qua Nginx (cổng 8080), đếm theo `served_by`, Nginx round-robin đều ra 3 instance:

```text
   3 instance-3475f6
   3 instance-82ec2b
   4 instance-e14b97
```

### Exercise 5.5: Test stateless

`python test_stateless.py`:

```text
============================================================
Stateless Scaling Demo
============================================================

Session ID: 1ec6aeba-6e3c-4a71-a860-e4d4b1807f64

Request 1: [instance-e14b97]
  Q: What is Docker?
  A: Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!...

Request 2: [instance-3475f6]
  Q: Why do we need containers?
  A: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận....

Request 3: [instance-82ec2b]
  Q: What is Kubernetes?
  A: Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ O...

Request 4: [instance-e14b97]
  Q: How does load balancing work?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

Request 5: [instance-3475f6]
  Q: What is Redis used for?
  A: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé....

------------------------------------------------------------
Total requests: 5
Instances used: {'instance-e14b97', 'instance-82ec2b', 'instance-3475f6'}
✅ All requests served despite different instances!

--- Conversation History ---
Total messages: 10
  [user]: What is Docker?...
  [assistant]: Container là cách đóng gói app để chạy ở mọi nơi. Build once...
  [user]: Why do we need containers?...
  [assistant]: Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã đư...
  [user]: What is Kubernetes?...
  [assistant]: Đây là câu trả lời từ AI agent (mock). Trong production, đây...
  [user]: How does load balancing work?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...
  [user]: What is Redis used for?...
  [assistant]: Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đ...

✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 request của cùng một session được Nginx chia cho cả 3 instance (`instance-e14b97`, `instance-3475f6`, `instance-82ec2b`), nhưng history vẫn đủ 10 message (5 user + 5 assistant) theo đúng thứ tự, vì không instance nào giữ state trong RAM: tất cả đọc/ghi `session:<id>` trong Redis.

Thêm (tự kiểm): tắt hẳn một instance rồi gọi tiếp cùng session:

```text
$ docker stop k5-day14-scaling-agent-1
k5-day14-scaling-agent-1
after-kill req 1 -> 200
after-kill req 2 -> 200
after-kill req 3 -> 200
after-kill req 4 -> 200
history messages: 18
```

Nginx chuyển traffic sang 2 instance còn lại, mọi request vẫn 200 và history tiếp tục tăng (10 → 18 message), không mất dữ liệu. Xong thì `docker compose -p k5-day14-scaling down -v`.

