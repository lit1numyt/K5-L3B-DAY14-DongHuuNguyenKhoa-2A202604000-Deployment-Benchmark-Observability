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

