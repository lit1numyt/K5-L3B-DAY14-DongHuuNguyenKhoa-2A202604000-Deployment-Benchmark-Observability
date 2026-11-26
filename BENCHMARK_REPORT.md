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

- [ ] Dashboard Grafana khi đang có tải (thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 1 alert đang **firing**

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | | | |
| B | `MOCK_SLOW_RATE=0.3` | | | |
| C | `LLM_MODEL=mock-llm-large` | | | |
| D | `docker pause` 1 instance | | | |
| E | `AGENT_VERSION=v1` | | | |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

...

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất bạn tìm được:

- `trace_id`: ...
- Tổng thời gian: ... ms
- Span chiếm nhiều thời gian nhất: ... (... ms, ...%)
- Dòng log tương ứng (grep theo `trace_id`):

```json

```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | | | | | |
| 3 | | | | | |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

...

---

## 6. Kết luận

- 3 điều bạn học được về benchmark & observability:
  1. ...
  2. ...
  3. ...
- Nếu đưa agent này lên production thật, bạn sẽ thêm metric / alert nào nữa?

...
