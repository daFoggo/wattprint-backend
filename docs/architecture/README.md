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
| `05-component-insight.excalidraw` | Component | Bên trong insight: consumer, read model, detector, view công bố cho text2sql |
| `06-component-copilot.excalidraw` | Component | Bên trong copilot: guardrail, orchestrator, verifier, RAG, saga, notifier |
| `07-component-text2sql.excalidraw` | Component | Bên trong text2sql: catalog, pipeline, compiler SQL, executor chỉ đọc, chỉ mục Qdrant |

Vẽ 3 cấp đầu của C4 (Context, Container, Component), như cách làm thông dụng; không vẽ cấp Code. File được sinh bởi `gen_excalidraw.py` (`python gen_excalidraw.py docs/architecture`);
thêm `--all` để sinh cả sơ đồ Deployment và Dynamic (`x1`–`x6`) khi cần. Chạy lại script sẽ ghi đè
các chỉnh sửa tay trong Excalidraw, nên sau khi bắt đầu chỉnh tay thì coi file `.excalidraw` là bản gốc.

## 1. Service nghiệp vụ (5) và phần mềm có sẵn

Trên sơ đồ, service xếp theo luồng dữ liệu, từ dữ liệu sensor tới khuyến nghị: **nilm, core, insight, copilot,
text2sql** (nilm đứng trước core vì core gọi nilm ngay trong lúc ingest). Nhờ vậy mọi lời gọi đồng bộ đều nối hai ô
kề nhau. Lời gọi đồng bộ có bốn cạnh, không cạnh nào tạo vòng: `core → nilm`, `insight → core`, `copilot → insight`,
`copilot → text2sql`. Bên cần số liệu gọi bên giữ số liệu; dữ liệu đi theo luồng nghiệp vụ bằng sự kiện qua RabbitMQ
(core → insight → copilot; nilm trả kết quả ngay trong response). Một service chết chỉ ảnh hưởng service gọi tới nó.

| Service | Trách nhiệm | Dữ liệu riêng | Gọi tới |
|---|---|---|---|
| `core` | Nhà, thành viên, mã mời, ghép công tơ, thiết bị, nhận batch số đo, biểu giá 5 bậc, hóa đơn. Nguồn sự thật | `core_db` (TimescaleDB) | `nilm` |
| `nilm` | Suy luận NILMFormer, hiệu chỉnh theo hộ, phiên bản model | `nilm_db` + volume model | không |
| `insight` | Read model tiêu thụ (CQRS), bất thường, chạy ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh nhóm, what-if, M&V, view chỉ đọc công bố cho text2sql | `insight_db` (TimescaleDB) | `core`, Open-Meteo |
| `copilot` | Hỏi đáp (pull), gợi ý chủ động (push), guardrail PII và prompt injection, verifier, RAG, xếp hạng theo phản hồi, thông báo, thống kê token, saga kế hoạch tiết kiệm | `copilot_db`, collection Qdrant `copilot_knowledge_v1` | `insight`, `text2sql`, LLM provider, Expo Push, Telegram |
| `text2sql` | Trả lời câu hỏi tự do về số liệu: catalog (bảng, cột, metric, glossary, rule), tìm metric, LLM lập plan theo ID, compiler dựng SQL, chạy chỉ đọc trên view của insight, che PII trên kết quả | `text2sql_db` (catalog, phiên truy vấn), collection Qdrant `text2sql_semantics_v1` | LLM provider; đọc view `insight_db` bằng role `text2sql_ro` |

`text2sql` xây trên ứng dụng mã nguồn `ai-agent-superset-standalone` (FastAPI, Python 3.14). Trong WattPrint, người hỏi
lấy từ `X-User-Id` do copilot chuyển tiếp, nguồn dữ liệu duy nhất là các view công bố của `insight_db`, catalog khai báo
các metric năng lượng (kWh theo thiết bị, tiền theo bậc giá), ingestion worker chạy như background task trong lifespan.

**Hội thoại chỉ có ở copilot.** Lịch sử chat của người dùng (`ai_conversation`, `ai_message`) nằm ở `copilot_db`.
text2sql chỉ giữ **phiên truy vấn**: plan, metric đã chọn, câu SQL đã chạy, trạng thái chờ người hỏi chọn quan hệ, để xử
lý câu hỏi nối tiếp ("còn tháng trước?"). Lượt hỏi số liệu đầu tiên trong một cuộc chat, text2sql tạo phiên và trả mã
phiên; copilot lưu mã này trong `ai_tool_call` và gửi lại ở các lượt sau. Người dùng không thấy phiên truy vấn; API
phiên của text2sql chỉ dùng cho trang quản trị xem lại truy vấn.

Phần mềm có sẵn: Envoy (API gateway), Keycloak (identity), RabbitMQ (broker), PostgreSQL, Qdrant (vector store). Mỗi
service là **một container**: API, consumer, outbox relay và job định kỳ chạy chung một process (background task
trong lifespan của FastAPI).

### Stack (10 container, 2 ngôn ngữ: Python và TypeScript)

| Lớp | Chọn | Lý do |
|---|---|---|
| Gateway | Envoy 1.40 (`envoyproxy/envoy`), một file `envoy.yaml` | Kiểm JWT, rate limit, request id, timeout, retry, TLS đều là bộ lọc có sẵn, không phải viết code. CNCF graduated, lõi của Istio và Envoy Gateway |
| Identity | Keycloak 26 | Đã có realm. Lưu vào `keycloak_db` trên Postgres chung (`KC_DB_URL_DATABASE`), không cần container DB riêng |
| Database | Một PostgreSQL 18 + TimescaleDB 2.31 (`timescale/timescaledb:2.31.0-pg18`) | Một server, 6 database, mỗi database một role. TimescaleDB lo chuỗi số đo (hypertable, continuous aggregate 1h/1d, nén, xóa theo hạn) ở `core_db` và read model ở `insight_db` |
| Vector store | Qdrant 1.20 (`qdrant/qdrant:v1.20.1`), không publish port | Vector store duy nhất. Mỗi service một collection, khóa JWT của Qdrant giới hạn theo collection. Tìm kết hợp vector và full-text trong một truy vấn, đúng cách text2sql tìm metric. Vector dựng lại được từ chữ trong `copilot_db` và `text2sql_db` |
| Broker | RabbitMQ 4 (`rabbitmq:4-management`), quorum queue | `delivery-limit` + dead-letter exchange có sẵn, không cần queue TTL để retry |
| Service | Python 3.14, FastAPI, SQLAlchemy async + asyncpg, Alembic, pydantic-settings | Giữ như code hiện tại |
| Messaging | FastStream (RabbitMQ) | Consumer viết như route FastAPI, tự sinh tài liệu AsyncAPI, có broker giả lập trong bộ nhớ để test |
| Gọi HTTP | httpx + tenacity; breaker và bulkhead (`asyncio.Semaphore`) tự viết trong `libs/common` | pybreaker chỉ hỗ trợ async qua Tornado, nên không dùng |
| Text-to-SQL | Service `text2sql` (nền `ai-agent-superset-standalone`): sqlglot, LLM qua API tương thích OpenAI, presidio | LLM không viết SQL: chỉ chọn metric và cột theo ID trong catalog, compiler dựng câu SQL |
| Mã nguồn | Monorepo uv workspace: `services/{core,nilm,insight,copilot,text2sql}` + `libs/common` | Một lockfile; phần chịu lỗi, log, outbox/inbox viết một lần. `libs/common` không chứa model nghiệp vụ |
| Kiểm tra | ruff, pytest, Postman + Newman, GitHub Actions | |
| Client | Next.js (pnpm + turbo), Expo | Repo riêng, không đổi |

Không dùng: Prometheus, Grafana, Loki, Jaeger, OpenResty/Lua, container worker riêng, container `keycloak-db` riêng.
Điểm cộng đã đủ trần 1,0 mà không cần giám sát tập trung (xem mục 8).

**Vì sao chia như vậy**

- Ranh giới theo dữ liệu và nghiệp vụ: ghi nhận (core), tính toán ML (nilm), phân tích (insight), tương tác AI
  (copilot), hỏi đáp số liệu (text2sql).
- Khác nhau về tài nguyên và kiểu lỗi: nilm nặng CPU/RAM (PyTorch), copilot phụ thuộc LLM ngoài chậm và hay lỗi,
  insight chạy theo lô và lịch, core cần nhận số đo ổn định.
- text2sql tách khỏi copilot vì có dữ liệu riêng (catalog metric, glossary, mô tả cột do quản trị viên khai báo),
  có worker embedding riêng, và giữ nguyên được mã nguồn gốc khi gọi qua API thay vì chép vào copilot.
- Insight giữ bản sao dữ liệu tiêu thụ cập nhật bằng sự kiện (pattern
  [CQRS](https://microservices.io/patterns/data/cqrs.html)), nên text2sql chạy trên view của database phân tích
  của insight, không chạm vào database ghi nhận của core.

## 2. Nguồn số đo

Ngoài đời, mỗi nhà gắn một cảm biến dòng (CT) ở aptomat tổng, ví dụ Shelly EM hoặc ESP32 + ESPHome, đo công suất tổng
và gửi batch số đo qua HTTPS tới gateway bằng API key của thiết bị. Đồ án không có thiết bị nên dùng **REFIT replayer**:
script Python đọc CSV của bộ dữ liệu REFIT và gửi batch qua gateway y như cảm biến thật (cùng endpoint, cùng API key,
cùng `Idempotency-Key`), có thể tua nhanh thời gian. Trên sơ đồ chỉ vẽ REFIT replayer, kèm ghi chú nó thay cho cảm biến
thật và dữ liệu là public dataset.
Khi dev có thể seed nhanh dữ liệu REFIT bằng revision Alembic `b2183c4aca1c` (ghi thẳng vào `core_db`); khi demo và
kiểm thử, dữ liệu luôn đi qua REFIT replayer và gateway.

## 2b. Dữ liệu

Bảng nào sang database nào, cách text2sql đọc dữ liệu sau khi bỏ `copilot_ro`: `docs/database-design.md` mục 7.
Thứ tự làm: `docs/superpowers/plans/2026-11-10-microservices-split.md`.

- Một PostgreSQL server (TimescaleDB), sáu database `core_db`, `insight_db`, `copilot_db`, `nilm_db`, `text2sql_db`,
  `keycloak_db`, mỗi database một role riêng. Không service nào có quyền vào database của service khác, trừ một ngoại
  lệ có kiểm soát: role `text2sql_ro` chỉ có `SELECT` trên các view mà insight công bố trong `insight_db`.
- View công bố lọc theo `current_setting('app.home_id', true)`. Executor của text2sql đặt giá trị này từ `X-User-Id`
  trong cùng transaction chỉ đọc; chưa đặt thì view không trả dòng nào. Insight sở hữu view, đổi view là đổi hợp đồng
  với text2sql.
- Một Qdrant, mỗi service một collection: `copilot_knowledge_v1` (tri thức RAG), `text2sql_semantics_v1` (catalog).
  Chữ gốc nằm ở database của service, Qdrant chỉ giữ vector để tìm.
- Ghi dữ liệu và ghi sự kiện trong cùng transaction (transactional outbox). Outbox relay lấy bản ghi bằng
  `SELECT … FOR UPDATE SKIP LOCKED`, nên chạy nhiều tiến trình cũng không gửi trùng. Consumer lưu `message_id` đã
  xử lý (inbox) để idempotent.
- Bảng hiện có cần đổi chủ khi tách: `insight.*` và `copilot.savings_measure` → `insight_db`;
  `energy.inference_run` → `nilm_db`; `energy.weather_hourly` và `core.device_alert_rule` → `insight_db`;
  `copilot.*`, `knowledge.*` → `copilot_db` (cột `embedding` chuyển sang Qdrant). View `copilot_ro` được thay bằng
  view công bố của insight cho text2sql.

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
- Route theo prefix `/api/core/`, `/api/insight/`, `/api/copilot/`, `/api/nilm/` (admin), `/api/text2sql/` (admin,
  quản lý catalog) tới cluster tương ứng. Người dùng cuối hỏi số liệu qua copilot, không gọi thẳng text2sql. Mỗi route có
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

- Mọi lời gọi giữa service: timeout (connect 1s, read 3s; LLM 20s; `copilot → text2sql` 30s vì gồm nhiều lần gọi LLM),
  retry tối đa 2 lần có backoff và jitter (tenacity) chỉ cho request idempotent hoặc có `Idempotency-Key`, circuit
  breaker (`core → nilm`, `copilot → LLM`, `copilot → text2sql`, `text2sql → LLM`). text2sql lỗi thì copilot vẫn trả
  lời bằng các tool cố định của insight (dự báo, what-if, so sánh tháng),
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
| 2. ≥3 service, dữ liệu riêng | 5 service, 5 database (và collection Qdrant riêng cho copilot, text2sql) |
| 3. ≥4 endpoint, OpenAPI | FastAPI sinh OpenAPI, CI kiểm file đã commit |
| 4. Gateway | Envoy, chỉ định tuyến và chính sách |
| 5. Gọi liên service tin cậy | Mục 5 |
| 6. Luồng nhiều bước | Mục 3 và 5; sơ đồ `x2`, `x5` (sinh bằng `--all`) |
| 7. Container | Dockerfile mỗi service, một `docker-compose.yml`, `docker compose up` |
| 8. Postman, thử lỗi | Collection chạy qua gateway; tắt nilm, làm chậm LLM, có số liệu trước/sau |
| Điểm cộng (trần 1,0) | RabbitMQ + consumer idempotent + DLQ (0,5); JWT ở gateway (0,25); circuit breaker + bulkhead (0,25); CI (0,25). Tổng 1,25, dư 0,25 phòng một mục bị trừ |
