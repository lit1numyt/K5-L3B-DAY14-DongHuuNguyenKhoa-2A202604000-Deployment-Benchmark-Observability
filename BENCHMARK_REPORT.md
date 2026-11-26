# Benchmark & Observability Report — Day 14

> Copy file này thành `BENCHMARK_REPORT.md` trong repo của bạn và điền đầy đủ.
> Mọi con số phải lấy từ report JSON / CSV / screenshot thật, không ước lượng.

**Họ tên:** Dong Huu Nguyen Khoa (2A202604000)
**Ngày chạy:** 2026-11-26
**Môi trường:** MacBook Apple M4 (10 CPU, 16 GB RAM), macOS, Python 3.11, Docker Desktop (10 CPU / 7.7 GB cho VM)

> Nguồn số liệu: mục 2–3 lấy từ `reports/*.json` (bản gốc trong `06-lab-complete/benchmark-observability/develop/reports/`), mục 5 từ `benchmark-results/*.csv`.

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–180 ms/call + retrieval ~20 ms, nên p95 bình thường ~220 ms (đo được 216.7 ms khi không có request chậm). 500 ms để dư ~2× cho jitter/tải mà người dùng chat vẫn thấy "tức thì". Đây cũng là SLO mặc định của `load_test.py` và alert `HighLatencyP95`. Không đặt theo p99 vì 3% request "slow" của provider (~1.7 s) nằm ngoài tầm kiểm soát của agent. |
| Error rate `/ask` | < 2 % | Mock upstream lỗi ~1% (`MOCK_ERROR_RATE=0.01`), đo được 0.67–1.33%. 2% chừa error budget cho lỗi upstream tự nhiên nhưng vẫn bắt được sự cố thật (thí nghiệm A: 20%). |
| Accuracy trên golden dataset | ≥ 100 % (23/23), không regression | Golden dataset nhỏ (23 câu) và tất định, nên một câu sai là một lỗ hổng kiến thức cụ thể chứ không phải nhiễu. Sau khi sửa KB, v2 đạt 23/23, nên quality gate trong CI dùng `--min-accuracy 1.0` + `--baseline`. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

`python load_test.py --url http://localhost:8002 --requests 300 --concurrency <c> --out reports/load_v2_c<c>.json`

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 4.07 | 192.9 | 222.2 | 1699.8 | 1.00% | ✅ PASS |
| 10 | 44.19 | 190.0 | 218.2 | 1697.5 | 1.33% | ✅ PASS |
| 50 | 107.58 | 191.2 | 224.8 | 1703.7 | 0.67% | ✅ PASS |
| 100 | 72.43 | 323.7 | 3090.4 | 3377.9 | 1.00% | ❌ FAIL (p95) |

**Nhận xét:** RPS chỉ tăng gần tuyến tính ở mức thấp. Từ 1 → 10, RPS tăng 10.9× (4.07 → 44.19) còn latency gần như không đổi: theo Little's law, RPS ≈ concurrency / latency ≈ 10 / 0.226 s ≈ 44. Từ 10 → 50, RPS chỉ tăng 2.4× (lý thuyết là ~5×, khoảng 220 req/s), nghĩa là hệ thống bắt đầu bão hoà dù p95 vẫn ổn. Ở 100, RPS còn **giảm** xuống 72.43 và p95 vọt lên 3090 ms (p50 323.7 ms): request phải xếp hàng. Lý do: agent develop chạy **1 process uvicorn duy nhất** (1 event loop, `uvicorn.run` không có workers) và load generator chạy chung máy. Mỗi request vẫn tốn CPU cho JSON, metrics, tracing, mở kết nối, nên khi CPU của event loop bão hoà thì phần chờ (queueing) cộng thẳng vào latency. Muốn tăng tiếp phải scale ngang (nhiều worker/instance sau LB), không phải tăng concurrency.

### 2.2 Tail latency

`--requests 300 --concurrency 20`, khởi động lại v2 với từng giá trị `MOCK_SLOW_RATE`:

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 188.8 | 216.7 | 231.9 |
| 0.03 (mặc định) | 215.4 | 219.8 | 1703.7 |
| 0.1 | 332.7 | 1688.3 | 1711.9 |

**Nhận xét:** **p99** nhạy nhất. Với 3% request chậm, avg chỉ tăng 26.6 ms (188.8 → 215.4) và p95 gần như đứng yên, nhưng p99 nhảy từ 231.9 ms lên **1703.7 ms** (×7.3), vì 3% > 1% nên p99 rơi đúng vào nhóm request chậm. Với 10% request chậm (> 5%), cả **p95** cũng lên 1688.3 ms trong khi avg mới tăng 143.9 ms. SLO không nên đặt theo average: avg trộn 90% request nhanh với 10% request rất chậm thành một con số "trông ổn" (332 ms < 500 ms), che mất việc cứ 10 người dùng thì có 1 người phải chờ ~1.7 s. Percentile mô tả trực tiếp trải nghiệm của nhóm người dùng tệ nhất, và đó mới là thứ cần cam kết.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.35% (1/23) | 91.3% (21/23) | 100% (23/23) |
| Avg tokens / câu | 56.8 | 109.3 | 117.7 |
| Tổng cost (USD) | 0.000400 | 0.000764 | 0.000825 |
| Cost / câu đúng (USD) | 0.00040035 | 0.00003639 | 0.00003589 |
| Quality gate | FAIL (min 80%) | PASS (min 80%, baseline v1) | PASS (min 100%, baseline v2, 0 regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| security-02 | `token`, `hết hạn`, `chữ ký` | Retrieval không tìm được tài liệu nào (v2 trả câu generic). Thêm entry `["jwt", "api key", "xác thực"]` vào `KNOWLEDGE_BASE`, giải thích JWT là token tự chứa có chữ ký và thời điểm hết hạn, khác API key cố định. |
| scaling-03 | `cpu`, `memory`, `custom metrics` | Thêm entry `["hpa", "autoscal", "kubernetes"]`: HPA scale theo CPU, memory hoặc custom metrics. Sửa cả `develop/` lẫn `production/utils/mock_llm.py`, khởi động lại v2, eval với `--baseline reports/eval_v2.json`: 23/23, regression = 0. |

**Quality gate trong CI:** `run_eval.py` trả exit code **1** khi accuracy < `--min-accuracy` hoặc có câu bị regression so với `--baseline`. Tự kiểm: chạy v1 với `--baseline reports/eval_v2.json` → **exit=1**; v2 sau khi sửa → **exit=0**. File `.github/workflows/eval-gate.yml` khởi động agent v2 rồi chạy `python eval/run_eval.py --min-accuracy 1.0 --baseline reports/eval_v2_fixed.json`. Exit code ≠ 0 làm step fail → job `eval` đỏ, và khi bật branch protection *Require status checks to pass* thì PR không merge được.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:** v2 thêm bước retrieval và nhét context vào prompt, nên mỗi câu tốn **1.92× token** (56.8 → 109.3) và tổng cost gần gấp đôi. Latency gần như không đổi (p50 159.7 → 192.2 ms, khoảng +20–30 ms cho retrieval, p95 223.5 → 213.3 ms nằm trong nhiễu). Đổi lại accuracy tăng từ 4.35% lên 91.3%, nên **cost / câu đúng rẻ hơn ~11×** (0.000400 → 0.0000364 USD). Nhìn "cost / câu" thì v1 rẻ hơn, nhưng câu trả lời sai là chi phí bỏ đi, nên "cost / câu đúng" mới là chỉ số công bằng để so hai phiên bản. Sửa KB tốn thêm 8.4 token/câu nhưng còn làm cost/câu đúng giảm nhẹ nữa.

---

## 4. Observability stack (production)

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals): `screenshots/grafana-dashboard.png`. Locust 100 user, 3 instance (Instances up = 3), Traffic 47.2 req/s, Error rate 1.29%, p95 292 ms.
- [x] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian): `screenshots/jaeger-slow-trace.png`
- [x] Một trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png`
- [x] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**: `screenshots/prometheus-alert-firing.png`. **3 alert firing cùng lúc**: `AgentHighErrorRate`, `AgentHighLatencyP95`, `LLMCostBurnRateHigh`. Ảnh chụp lúc 12:46:01 UTC, khi A và B đang chạy chồng lên nhau.

### 4.2 Thí nghiệm "phá hệ thống"

Cách làm: Locust headless 30 user (`-u 30 -r 5`) chạy suốt bài, 3 agent. Mỗi thay đổi áp dụng bằng biến môi trường trên lệnh `docker compose -p k5-day14-observability up -d --no-build --scale agent=3 agent` (không tạo file `.env`). Một script poll `GET /api/v1/alerts` của Prometheus mỗi 5 s. Thời gian tính từ lúc lệnh `up` trả về (container đã được tạo lại) tới lúc alert chuyển `pending` rồi `firing`. Prometheus scrape và evaluate mỗi 5 s, nên sai số khoảng ±5 s.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (critical) | pending sau 35 s → **firing sau 95 s** | Error rate: 1.07% → 23.8%; Requests/s theo status code (503 tăng vọt) |
| B | `MOCK_SLOW_RATE=0.3` (chồng lên A) | `AgentHighLatencyP95` (warning) | pending sau 25 s → **firing sau 145 s** | Latency p95: 294 ms → 1886 ms, trong khi avg chỉ 217 → 544 ms; panel LLM latency p95 theo model |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (warning) | pending sau 30 s → **firing sau 150 s** | Cost burn rate: ~$1.7/giờ → $17.03/giờ; LLM latency (p95 /ask 198 → 701 ms) |
| D | `docker pause k5-day14-observability-agent-1` | `AgentInstanceDown` (critical, `instance=172.18.0.8:8000`) | pending sau 10 s → **firing sau 40 s** | Instances up 3 → 2. Error rate của agent vẫn xanh (1.8%) |
| E | `AGENT_VERSION=v1` | **Không có** (alerts = `{}` sau 2 phút) | — | Retrieval hit ratio mất hẳn (`agent_retrieval_total` không còn series), tokens/s giảm còn một nửa (input 1350 → 676/s), bảng version đổi `v2` → `v1` |

Ghi chú:
- Thời gian firing ≈ thời gian để cửa sổ `rate(...[1m])` vượt ngưỡng (pending) cộng với `for:` của rule (A: 1m, B: 2m, C: 2m, D: 30s). Vì vậy A nhanh hơn B và C, còn D nhanh nhất vì `up == 0` đúng ngay ở lần scrape hỏng đầu tiên.
- `LLMCostBurnRateHigh` đã firing từ trước bài chaos do đợt benchmark 100 user (ngưỡng $2/giờ). Tôi chạy C cuối cùng, sau khi alert này đã hết, để đo cho sạch. Giá model large / small là 16.7× (input $0.0025 so với $0.00015). Lúc firing, burn rate mới tăng ~10× vì `rate(...[5m])` mới chứa ~2.5 phút dữ liệu của model large.
- Mỗi lần `up -d` đổi biến môi trường, Compose tạo lại **cả 3 agent cùng lúc** (không rolling). Nginx giữ IP cũ tới `valid=10s`, nên Locust thấy một loạt `502` ngay tại 6 thời điểm áp dụng thay đổi (1428 lỗi 502 trên `/ask`, tất cả nằm trong các cửa sổ 12:41:5x, 12:43:3x, 12:46:0x, 12:48:2x, 12:50:2x, 12:52:5x). Agent không đếm được các lỗi này. Production cần rolling update và readiness gate.

**Thí nghiệm D: vì sao Locust thấy lỗi 504 mà dashboard agent vẫn xanh?** Trong lúc pause, Locust ghi nhận **27 lỗi `504 Gateway Time-out`** (12:47:12–12:48:03, khớp 27 dòng 504 trong log Nginx). Request được Nginx chuyển tới instance bị pause, container này nhận TCP nhưng không bao giờ trả lời. Sau `proxy_read_timeout 10s`, Nginx trả 504 cho client. Request đó chưa bao giờ được agent xử lý xong, nên `http_requests_total` của agent không đếm nó, và error rate của agent chỉ 1.8% (mức nền của `MOCK_ERROR_RATE=0.01`). Metric chỉ phản ánh những gì chính service đó nhìn thấy. Vì vậy production cần giám sát ở tầng load balancer (metric/log 5xx của Nginx) và synthetic check từ bên ngoài. `proxy_next_upstream` + `AgentInstanceDown` giúp hệ thống tự vượt qua: 2 instance còn lại vẫn phục vụ, RPS /ask chỉ giảm nhẹ rồi hồi lại.

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

v1 vẫn trả 200 nhanh (p95 thậm chí giảm từ 294 → 198 ms vì không còn bước retrieval), nên mọi metric hạ tầng đều "đẹp", nhưng câu trả lời sai (eval ở mục 3: v1 chỉ 4.35% so với v2 91.3%). Cách phát hiện:
1. **Quality gate trước khi deploy:** `run_eval.py --min-accuracy ... --baseline` chạy trong CI (`.github/workflows/eval-gate.yml`), exit code ≠ 0 thì chặn merge. Đây là chốt chặn chính.
2. **Giám sát chất lượng online:** alert trên metric "proxy" của chất lượng, ví dụ retrieval hit ratio (`agent_retrieval_total`) rơi về 0, tokens input/request giảm đột ngột (context không còn được nhét vào prompt), hay `agent_info{version}` đổi ngoài lịch release.
3. **Eval định kỳ trên production** (chạy golden set hoặc LLM-as-judge trên mẫu traffic thật), kèm feedback của người dùng (thumbs up/down). Alert khi điểm chất lượng tụt dưới SLO.

### 4.4 Trả lời Exercise 7.4

1. **p95 và avg:** Khi có tải 100 user / 3 instance, dashboard cho p95 = 292 ms (ảnh Grafana). Ở mức nền 30 user, Prometheus đo avg 234 ms và p95 294 ms. Hai số gần nhau vì phần lớn request chỉ mất bằng latency mock LLM (~200 ms). Khoảng cách lộ ra khi có đuôi chậm: ở thí nghiệm B (30% request chậm), avg chỉ tăng 217 → 544 ms (~2.5×) còn p95 tăng 294 → 1886 ms (~6.4×), p99 trên dashboard luôn ~1.8 s. Khoảng cách avg ↔ p95 lớn nghĩa là phân phối có **đuôi dài**: một nhóm nhỏ request rất chậm bị trung bình "giấu" đi, trong khi chính nhóm đó là những người dùng trải nghiệm tệ. Vì vậy SLO đặt theo p95/p99, không theo avg.
2. **Requests/s theo instance:** Nginx chia gần như đều. Trong 90 s cuối của lần chạy `scale_3` (tới 12:36:00 UTC), 3 instance nhận 1889 / 1877 / 1857 request /ask (33.6% / 33.4% / 33.0%), do upstream round-robin với `resolve`.
3. **Input tokens/s > output tokens/s:** trong lần chạy `scale_3`, 90 s có 439,002 input tokens so với 232,816 output tokens (≈1.9×). Lúc 30 user cũng giữ tỉ lệ đó (2644 so với 1400 tokens/s). Lý do là input = system prompt + **context retrieval** + câu hỏi, còn output chỉ là câu trả lời ngắn. Bằng chứng: khi chuyển sang v1 (không retrieval, thí nghiệm E), input tokens/s giảm một nửa. Output đắt hơn (small: $0.0006 so với $0.00015 cho mỗi 1K), nhưng input chiếm số lượng lớn, nên muốn tối ưu chi phí phải tiết kiệm context.
4. **`curl http://localhost:8080/metrics` → `404 Not Found`** (trang lỗi của nginx/1.31.10). `nginx.conf` có `location = /metrics { return 404; }`: metrics chỉ cho Prometheus scrape trực tiếp từng agent qua mạng nội bộ Docker (`agent:8000/metrics`), không công khai qua cổng vào. Lý do: `/metrics` lộ thông tin nội bộ (route, lưu lượng, chi phí, version, số instance), giúp kẻ tấn công trinh sát hệ thống. Nếu đi qua load balancer, mỗi lần scrape lại rơi vào một instance ngẫu nhiên, nên số liệu cũng sai.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: `4176dc4379bc3f4e9fd9fff8bc552497` (ảnh `screenshots/jaeger-slow-trace.png`)
- Tổng thời gian: 1727.6 ms (`POST /ask`)
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (1695.0 ms, 98.1%). Span `retrieve` chỉ 27.2 ms (1.6%). Đây là request rơi vào nhánh `MOCK_SLOW_RATE`: LLM chậm, còn retrieval và phần app không đáng kể.
- Dòng log tương ứng (`docker compose logs agent | grep 4176dc4379bc3f4e9fd9fff8bc552497`):

```json
{"ts": "2026-11-26T07:55:31.473597+00:00", "level": "INFO", "service": "observable-agent", "instance": "4d46c115d3a8", "event": "llm_call", "trace_id": "4176dc4379bc3f4e9fd9fff8bc552497", "span_id": "981cdf631d0ca5dd", "request_id": "f1c891e681f2", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 76, "output_tokens": 39, "cost_usd": 3.5e-05, "llm_ms": 1693.8}
{"ts": "2026-11-26T07:55:31.473790+00:00", "level": "INFO", "service": "observable-agent", "instance": "4d46c115d3a8", "event": "http_request", "trace_id": "4176dc4379bc3f4e9fd9fff8bc552497", "span_id": "981cdf631d0ca5dd", "request_id": "f1c891e681f2", "method": "POST", "route": "/ask", "status": 200, "ms": 1726.4}
```

Trace lỗi (`screenshots/jaeger-error-trace.png`): `trace_id` `2694dfc29f121bfb94d53177c005a510`, 853.8 ms, status 503, span LLM có event `exception`. Log khớp:

```json
{"ts": "2026-11-26T07:55:24.287564+00:00", "level": "INFO", "service": "observable-agent", "instance": "4d46c115d3a8", "event": "llm_error", "trace_id": "2694dfc29f121bfb94d53177c005a510", "span_id": "812e17ca0ffdcfc1", "request_id": "2f487aec5a13", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 60.11 | 200 | 230 | 1700 | 67 / 7170 (0.93%) |
| 3 | 60.46 | 200 | 230 | 1700 | 57 / 7213 (0.79%) |

Số liệu lấy từ dòng `POST /ask` trong `benchmark-results/scale_1_stats.csv` và `scale_3_stats.csv`. Lệnh chạy: `docker compose -p k5-day14-observability run --rm --no-deps locust ... --headless -u 100 -r 10 -t 2m --csv /mnt/results/scale_N`. Trong lúc chạy đã kiểm tra lại có đúng 1 hoặc 3 container agent và 1 hoặc 3 target Prometheus `up`. Toàn bộ failures là `503` từ mock LLM (`MOCK_ERROR_RATE=0.01`), không có 502 hay 504.

> Lưu ý về cách chạy: lệnh trong CHECKPOINTS (`docker compose run --rm locust ...` **không** có `--no-deps`) làm Compose khởi động lại dependency `agent` theo `deploy.replicas: 2`. Vì vậy lần chạy "1 instance" đầu tiên thực ra có 2 agent. Lần đó tôi đã bỏ kết quả và chạy lại với `--no-deps`. Lần chạy `scale_1` thứ hai cũng bị bỏ, vì Docker VM bị khựng: Locust đặt 120 s nhưng thực tế chạy 504 s. Bảng trên là lần chạy sạch (đều 119 s).

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không** cải thiện p95 (230 ms cả hai) và RPS gần như không đổi (~60 req/s). Lý do là hệ thống chưa bão hoà: 100 user Locust, mỗi user nghỉ 0.5–2 s giữa 2 request, thì tải tối đa chỉ khoảng 100 / (1.25 s + ~0.24 s) ≈ 67 req/s, gần đúng với Aggregated 66.1 req/s. Một agent async với mock LLM ~200 ms (`asyncio.sleep`) xử lý mức này dư sức, nên p50 ≈ latency của mock LLM. Nút thắt nằm ở **phía tạo tải (think time của user)** và ở **chính LLM upstream** (p99 1700 ms là các request trúng `MOCK_SLOW_RATE`). Thêm instance không làm LLM nhanh hơn. Muốn thấy scale có tác dụng, phải tăng tải tới lúc 1 instance bão hoà (như c=100 ở mục 2.1 với `load_test.py`, nơi p95 vọt lên 3090 ms), hoặc agent phải có phần việc tốn CPU. Scale ngang giúp **availability** (thí nghiệm D: pause 1 instance thì 2 instance còn lại vẫn phục vụ) nhiều hơn là giúp latency ở mức tải này.

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. **Trung bình nói dối, phải nhìn percentile.** `MOCK_SLOW_RATE` 0 → 0.1 hay thí nghiệm B làm p95/p99 nhảy vọt trong khi avg chỉ nhích nhẹ. SLO và alert phải đặt trên p95/p99, và một trace chậm trong Jaeger chỉ ra ngay thủ phạm (span `chat mock-llm-small` chiếm 98.1%).
  2. **Benchmark phải kiểm soát điều kiện chạy, nếu không số liệu vô nghĩa.** Lần đo "1 instance" đầu tiên thực ra có 2 agent (`compose run` không `--no-deps`), một lần khác bị Docker VM khựng (120 s thành 504 s). Lúc chạy phải kiểm tra lại số instance và thời gian, và hiểu tải đang bị giới hạn ở đâu: scale 1 → 3 không đổi gì vì think time của Locust mới là giới hạn, không phải agent.
  3. **Hạ tầng xanh ≠ hệ thống đúng.** Thí nghiệm E (v1 trả lời sai nhưng nhanh hơn) không kích hoạt alert nào, và thí nghiệm D sinh 504 ở Nginx mà agent không thấy. Cần cả 3 lớp: metric/alert hạ tầng, giám sát ở edge (load balancer, synthetic check), và eval chất lượng có exit code làm quality gate trong CI.
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

  - **Metric 5xx/latency ở Nginx/LB** (nginx-prometheus-exporter hoặc parse access log) và alert khi tỉ lệ 502/504 ở edge > 1%. Đây là chỗ thí nghiệm D và các lần redeploy làm lỗi mà agent không thấy.
  - **Synthetic probe từ bên ngoài** (blackbox exporter gọi `/ready` và một câu hỏi mẫu có đáp án biết trước), cảnh báo cả khi trả lời sai nội dung.
  - **Alert chất lượng:** retrieval hit ratio < ngưỡng, input tokens/request tụt đột ngột, điểm eval online/feedback người dùng giảm, `agent_info{version}` đổi ngoài giờ release.
  - **Multi-window burn-rate alert cho SLO** (ví dụ 1h + 5m, theo error budget) thay cho ngưỡng cố định, để giảm cả báo động giả lẫn báo chậm. Thêm alert ngân sách theo ngày/tháng (giống cost guard ở Part 6) và theo từng `user_id`.
  - **Saturation:** in-flight requests / instance, CPU/memory container, queue depth, và lỗi `429`/`402` từ rate limit + cost guard. Thêm rolling update có readiness gate để redeploy không gây 502.
