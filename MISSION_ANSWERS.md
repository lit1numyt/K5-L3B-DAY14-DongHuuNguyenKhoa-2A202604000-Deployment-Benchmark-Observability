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

