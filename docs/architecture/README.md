# Kiến trúc WattPrint (bản chốt cho bài tập lớn microservices)

Sơ đồ vẽ theo mô hình C4 ([c4model.com](https://c4model.com)): mỗi sơ đồ có tiêu đề ghi loại và phạm vi,
có chú giải, mỗi khối ghi loại và công nghệ, mỗi mũi tên ghi mục đích và giao thức. Mở file `.excalidraw`
bằng [excalidraw.com](https://excalidraw.com) (Open) hoặc extension Excalidraw của VS Code.

| File | Loại C4 | Trả lời câu hỏi |
|---|---|---|
| `00-overview.excalidraw` | Tổng quan 1 trang | Nhìn nhanh toàn hệ thống, dùng cho slide |
| `01-system-context.excalidraw` | System Context | WattPrint làm gì, ai dùng, nối với hệ thống ngoài nào |
| `02-container.excalidraw` | Container | Gồm những khối chạy độc lập nào, ai gọi ai, dữ liệu của ai |
| `03-component-core.excalidraw` | Component | Bên trong core: router, service, client, outbox relay |
| `04-component-nilm.excalidraw` | Component | Bên trong nilm: API suy luận, engine NILMFormer, kho model |
| `05-component-insight.excalidraw` | Component | Bên trong insight: consumer, read model, detector, truy vấn an toàn |
| `06-component-copilot.excalidraw` | Component | Bên trong copilot: guardrail, orchestrator, verifier, RAG, saga, notifier |

Vẽ 3 cấp đầu của C4 (Context, Container, Component), như cách làm thông dụng; không vẽ cấp Code. File được sinh bởi `gen_excalidraw.py` (`python gen_excalidraw.py docs/architecture`);
thêm `--all` để sinh cả sơ đồ Deployment và Dynamic (`x1`–`x6`) khi cần. Chạy lại script sẽ ghi đè
các chỉnh sửa tay trong Excalidraw, nên sau khi bắt đầu chỉnh tay thì coi file `.excalidraw` là bản gốc.

## 1. Service nghiệp vụ (4) và phần mềm có sẵn

Lời gọi đồng bộ chỉ đi một chiều **copilot → insight → core → nilm**. Dữ liệu đi ngược lên bằng sự kiện qua
RabbitMQ (core → insight → copilot; nilm trả kết quả ngay trong response), nên không có vòng phụ thuộc và một service chết chỉ ảnh hưởng tầng ngay trên.

| Service | Trách nhiệm | Dữ liệu riêng | Gọi tới |
|---|---|---|---|
| `core` | Nhà, thành viên, mã mời, ghép công tơ, thiết bị, nhận batch số đo, biểu giá 5 bậc, hóa đơn. Nguồn sự thật | `core_db` (TimescaleDB) | `nilm` |
| `nilm` | Suy luận NILMFormer, hiệu chỉnh theo hộ, phiên bản model | `nilm_db` + volume model | không |
| `insight` | Read model tiêu thụ (CQRS), bất thường, chạy ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh nhóm, what-if, M&V, truy vấn an toàn cho Text-to-SQL | `insight_db` (TimescaleDB) | `core`, Open-Meteo |
| `copilot` | Hỏi đáp (pull), gợi ý chủ động (push), guardrail PII và prompt injection, verifier, RAG, xếp hạng theo phản hồi, thông báo, thống kê token, saga kế hoạch tiết kiệm | `copilot_db` (pgvector) | `insight`, LLM provider, Expo Push, Telegram |

Phần mềm có sẵn: Envoy (API gateway), Keycloak (identity), RabbitMQ (broker), PostgreSQL. Mỗi service là **một
container**: API, consumer, outbox relay và job định kỳ chạy chung một process (background task trong lifespan của FastAPI).

### Stack (8 container, 2 ngôn ngữ: Python và TypeScript)

| Lớp | Chọn | Lý do |
|---|---|---|
| Gateway | Envoy 1.40 (`envoyproxy/envoy`), một file `envoy.yaml` | Kiểm JWT, rate limit, request id, timeout, retry, TLS đều là bộ lọc có sẵn, không phải viết code. CNCF graduated, lõi của Istio và Envoy Gateway |
| Identity | Keycloak 26 | Đã có realm. Lưu vào `keycloak_db` trên Postgres chung (`KC_DB_URL_DATABASE`), không cần container DB riêng |
| Database | Một PostgreSQL 18 + TimescaleDB 2.31 + pgvector (`timescale/timescaledb:2.31.0-pg18`) | Một server, 5 database, mỗi database một role. TimescaleDB lo chuỗi số đo (hypertable, continuous aggregate 1h/1d, nén, xóa theo hạn) ở `core_db` và read model ở `insight_db`; pgvector cho RAG ở `copilot_db` |
| Broker | RabbitMQ 4 (`rabbitmq:4-management`), quorum queue | `delivery-limit` + dead-letter exchange có sẵn, không cần queue TTL để retry |
| Service | Python 3.12, FastAPI, SQLAlchemy async + asyncpg, Alembic, pydantic-settings | Giữ như code hiện tại |
| Messaging | FastStream (RabbitMQ) | Consumer viết như route FastAPI, tự sinh tài liệu AsyncAPI, có broker giả lập trong bộ nhớ để test |
| Gọi HTTP | httpx + tenacity; breaker và bulkhead (`asyncio.Semaphore`) tự viết trong `libs/common` | pybreaker chỉ hỗ trợ async qua Tornado, nên không dùng |
| Mã nguồn | Monorepo uv workspace: `services/{core,nilm,insight,copilot}` + `libs/common` | Một lockfile; phần chịu lỗi, log, outbox/inbox viết một lần. `libs/common` không chứa model nghiệp vụ |
| Kiểm tra | ruff, pytest, Postman + Newman, GitHub Actions | |
| Client | Next.js (pnpm + turbo), Expo | Repo riêng, không đổi |

Không dùng: Prometheus, Grafana, Loki, Jaeger, OpenResty/Lua, container worker riêng, container `keycloak-db` riêng.
Điểm cộng đã đủ trần 1,0 mà không cần giám sát tập trung (xem mục 8).

**Vì sao chia như vậy**

- Ranh giới theo dữ liệu và nghiệp vụ: ghi nhận (core), tính toán ML (nilm), phân tích (insight), tương tác AI (copilot).
- Khác nhau về tài nguyên và kiểu lỗi: nilm nặng CPU/RAM (PyTorch), copilot phụ thuộc LLM ngoài chậm và hay lỗi,
  insight chạy theo lô và lịch, core cần nhận số đo ổn định.
- Insight giữ bản sao dữ liệu tiêu thụ cập nhật bằng sự kiện (pattern
  [CQRS](https://microservices.io/patterns/data/cqrs.html)), nên Text-to-SQL của copilot chạy trên database phân tích
  của insight, không chạm vào database ghi nhận của core.

## 2. Nguồn số đo

Ngoài đời, mỗi nhà gắn một cảm biến dòng (CT) ở aptomat tổng, ví dụ Shelly EM hoặc ESP32 + ESPHome, đo công suất tổng
và gửi batch số đo qua HTTPS tới gateway bằng API key của thiết bị. Đồ án không có thiết bị nên dùng **REFIT replayer**:
script Python đọc CSV của bộ dữ liệu REFIT và gửi batch qua gateway y như cảm biến thật (cùng endpoint, cùng API key,
cùng `Idempotency-Key`), có thể tua nhanh thời gian. Trên sơ đồ chỉ vẽ REFIT replayer, kèm ghi chú nó thay cho cảm biến
thật và dữ liệu là public dataset.
Dữ liệu REFIT hiện được seed bởi revision Alembic `e2b726548f8c`, ghi thẳng vào database; REFIT replayer gọi API sẽ là một script riêng khi tách service.

## 2b. Dữ liệu

Bảng nào sang database nào, cách Copilot đọc dữ liệu sau khi bỏ `copilot_ro`: `docs/database-design.md` mục 7.
Thứ tự làm: `docs/superpowers/plans/2026-11-10-microservices-split.md`.

- Một PostgreSQL server (TimescaleDB + pgvector), năm database `core_db`, `insight_db`, `copilot_db`, `nilm_db`,
  `keycloak_db`, mỗi database một role riêng. Không service nào có quyền vào database của service khác.
- Ghi dữ liệu và ghi sự kiện trong cùng transaction (transactional outbox). Outbox relay lấy bản ghi bằng
  `SELECT … FOR UPDATE SKIP LOCKED`, nên chạy nhiều tiến trình cũng không gửi trùng. Consumer lưu `message_id` đã
  xử lý (inbox) để idempotent.
- Bảng hiện có cần đổi chủ khi tách: `insight.*` và `copilot.savings_measure` → `insight_db`;
  `energy.inference_run` → `nilm_db`; `energy.weather_hourly` và `core.device_alert_rule` → `insight_db`;
  `copilot.*`, `knowledge.*` → `copilot_db`. View `copilot_ro` được thay bằng API truy vấn an toàn của insight.

## 3. Sự kiện qua RabbitMQ

Cách vẽ: theo [C4](https://c4model.com/abstractions/queues-and-topics), mỗi queue là một container lưu message, còn
RabbitMQ (broker) chỉ là chuyện triển khai. Luồng chi tiết đi theo thứ tự quen thuộc trong tài liệu RabbitMQ:
producer → exchange → queue → consumer.

Một sự kiện đi như sau (ví dụ core báo cho insight có số liệu tiêu thụ mới):

1. core lưu kết quả NILM và một dòng vào bảng `outbox` trong **cùng một transaction**.
2. Outbox relay (vòng lặp nền trong core) đọc dòng chưa gửi bằng `SELECT … FOR UPDATE SKIP LOCKED`.
3. Relay publish lên exchange `wattprint.events`, routing key `energy.usage.updated`, đợi broker xác nhận rồi mới
   đánh dấu đã gửi.
4. Exchange kiểu topic chép message vào mọi queue có binding khớp; `insight.usage` bind `energy.usage.*` và
   `core.device.*`.
5. RabbitMQ giao message cho consumer của insight. Lỗi thì consumer nack, RabbitMQ giao lại.
6. Consumer tra `message_id` trong bảng `inbox`: có rồi thì bỏ qua; chưa có thì cập nhật read model và ghi inbox
   cùng một transaction, rồi ack.
7. Giao quá 3 lần vẫn lỗi: queue chuyển message sang dead-letter exchange `wattprint.dlx`.
8. `wattprint.dlx` chép message vào `insight.usage.dlq`; message nằm đó, không mất.
9. Nhóm vận hành xem DLQ trên RabbitMQ UI (:11099), sửa lỗi, chuyển message về `insight.usage` để chạy lại.

Outbox chống trường hợp lưu DB xong mà publish lỗi (hoặc ngược lại). Inbox cần vì RabbitMQ giao ít nhất một lần,
một message có thể đến hai lần.

Danh sách sự kiện (exchange `wattprint.events`, topic):

| Routing key | Phát | Nhận | Mục đích |
|---|---|---|---|
| `energy.usage.updated` | core | insight | Có estimate mới, kèm tổng theo giờ từng thiết bị |
| `core.device.changed` | core | insight | Đồng bộ danh mục thiết bị vào read model |
| `insight.alert.created` | insight | copilot | Kích hoạt gợi ý chủ động |

Mỗi consumer một quorum queue với policy: `delivery-limit = 3`, `dead-letter-exchange` trỏ tới `<queue>.dlq`,
`dead-letter-strategy = at-least-once`, `overflow = reject-publish`. Consumer lỗi thì nack, RabbitMQ giao lại; quá 3 lần
message sang DLQ, xem và đẩy lại bằng RabbitMQ management. Giao lại diễn ra ngay, không có độ trễ giữa các lần;
cần chờ thì thêm một queue TTL.

## 4. Gateway và bảo mật

- Gateway là Envoy, một listener HTTP (lab) hoặc HTTPS (server, chứng chỉ Let's Encrypt lấy bằng certbot). Nếu server
  đã có nginx chung thì nginx giữ tên miền và HTTPS, Envoy đứng sau ở cổng 11093.
- Route theo prefix `/api/core/`, `/api/insight/`, `/api/copilot/`, `/api/nilm/` tới cluster tương ứng, mỗi route có
  `timeout`, `retry_policy` (chỉ `connect-failure`, `reset` cho GET; không retry POST).
- Bộ lọc `local_ratelimit` (rate limit), `x-request-id` do Envoy tự sinh, giới hạn kích thước body.
- Bộ lọc `jwt_authn`, provider Keycloak:
  - `issuer` = URL realm, `audiences` = `wattprint-api`, `allowed_algorithms: [RS256]`.
  - `remote_jwks` trỏ tới `…/protocol/openid-connect/certs`, bật `async_fetch` để JWKS tải ở main thread theo chu kỳ,
    không tải theo request.
  - `claim_to_headers`: `sub` → `X-User-Id`, `realm_access.roles` → `X-User-Roles`. Envoy xóa header cùng tên do
    client gửi lên trước khi gán.
  - Route ingest của thiết bị đo không yêu cầu JWT; core kiểm API key thiết bị và công tơ có thuộc nhà không.
- Keycloak cần audience mapper để token có `aud = wattprint-api`.
- Gateway không chứa luật nghiệp vụ. Quyền theo nhà, theo gói Pro, theo role admin do từng service kiểm.
- Lời gọi giữa service đi thẳng trong network nội bộ của compose, không qua gateway, chuyển tiếp `X-User-*` và
  `X-Request-ID`. Service không publish port nên chỉ gateway và service khác gọi được.

## 5. Độ tin cậy (`libs/common`)

- Mọi lời gọi giữa service: timeout (connect 1s, read 3s; LLM 20s), retry tối đa 2 lần có backoff và jitter (tenacity)
  chỉ cho request idempotent hoặc có `Idempotency-Key`, circuit breaker (`core → nilm`, `copilot → LLM`),
  `asyncio.Semaphore` giới hạn lời gọi đồng thời (bulkhead) và `mem_limit`/`cpus` cho từng container.
- Phân loại lỗi: 4xx của service phía sau giữ nguyên; timeout → 504; không kết nối được hoặc breaker mở → 503 kèm
  `Retry-After`.
- Địa chỉ service lấy từ biến môi trường. Mỗi container có `/health` (còn sống) và `/ready` (đã nối DB, broker, model).
- Luồng nhiều bước: nhận số đo → nilm, `PENDING_INFERENCE` khi không biết kết quả (sơ đồ `x2`, sinh bằng `--all`); saga kế hoạch tiết kiệm
  hoàn tác theo thứ tự ngược (sơ đồ `x5`).

## 6. Log và CI

- Log: mỗi container ghi JSON ra stdout có `request_id` (Envoy sinh, service truyền tiếp), xem bằng
  `docker compose logs`.
- Số liệu thử lỗi trước/sau lấy từ báo cáo Newman (độ trễ, tỷ lệ lỗi theo request) và log.
- GitHub Actions: ruff + pytest từng service, build image, `docker compose up`, Newman chạy Postman collection, kiểm
  OpenAPI không lệch so với file đã commit.

## 7. Cổng (chỉ gateway mở ra ngoài, còn lại bind 127.0.0.1)

| Cổng | Thành phần |
|---|---|
| 11091, 11092 | Next.js landing, dashboard (chạy ngoài compose) |
| 11093 | Gateway Envoy, điểm vào duy nhất (thay API cũ, client không đổi URL); 443 khi lên server |
| 11095 | Keycloak |
| 11096 | PostgreSQL (chỉ để debug) |
| 11099 | RabbitMQ management |

## 8. Đối chiếu yêu cầu đề

| Yêu cầu | Đáp ứng |
|---|---|
| 1. ≥5 luật nghiệp vụ | Mã ghép dùng một lần có hạn; mỗi tài khoản một nhà; batch idempotent và liên tục; hóa đơn theo đúng phiên bản biểu giá 5 bậc; dự báo cần ≥7 ngày dữ liệu; so sánh nhóm cần ≥10 hộ; M&V cần ≥14 ngày; Copilot chỉ cho gói Pro; tối đa N thông báo mỗi ngày, có giờ yên tĩnh |
| 2. ≥3 service, dữ liệu riêng | 4 service, 4 database |
| 3. ≥4 endpoint, OpenAPI | FastAPI sinh OpenAPI, CI kiểm file đã commit |
| 4. Gateway | Envoy, chỉ định tuyến và chính sách |
| 5. Gọi liên service tin cậy | Mục 5 |
| 6. Luồng nhiều bước | Mục 3 và 5; sơ đồ `x2`, `x5` (sinh bằng `--all`) |
| 7. Container | Dockerfile mỗi service, một `docker-compose.yml`, `docker compose up` |
| 8. Postman, thử lỗi | Collection chạy qua gateway; tắt nilm, làm chậm LLM, có số liệu trước/sau |
| Điểm cộng (trần 1,0) | RabbitMQ + consumer idempotent + DLQ (0,5); JWT ở gateway (0,25); circuit breaker + bulkhead (0,25); CI (0,25). Tổng 1,25, dư 0,25 phòng một mục bị trừ |
