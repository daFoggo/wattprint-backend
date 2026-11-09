# Kế hoạch tách WattPrint thành microservices

> **Cho agent thực thi:** dùng superpowers:subagent-driven-development (khuyên dùng) hoặc superpowers:executing-plans,
> làm lần lượt từng phase. Bước dùng checkbox (`- [ ]`). Mỗi phase kết thúc bằng mục **Kiểm chứng** chạy thật, có
> output, rồi mới sang phase sau.

**Mục tiêu:** chuyển backend từ một app FastAPI + một database sang 4 service nghiệp vụ (core, nilm, insight, copilot)
sau một API gateway, đáp ứng đề bài tập lớn (`bai-tap-lon-yeu-cau-gui-sinh-vien_1.docx`) và đạt trần điểm cộng 1,0.

**Kiến trúc chốt:** `docs/architecture/README.md` và các sơ đồ `docs/architecture/00`–`06`. File này chỉ nói
làm theo thứ tự nào; quyết định kiến trúc nằm ở README đó, có lệch thì README thắng.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, pydantic-settings, FastStream (RabbitMQ),
httpx + tenacity, PyTorch (chỉ nilm), uv workspace; Envoy 1.40; Keycloak 26; PostgreSQL 18 + TimescaleDB 2.31 +
pgvector; RabbitMQ 4; Docker Compose v2; ruff, pytest, Postman + Newman, GitHub Actions.

## Ràng buộc chung

- 8 container: `gateway` (Envoy), `keycloak`, `postgres`, `rabbitmq`, `core`, `nilm`, `insight`, `copilot`. Không
  Prometheus, không container worker riêng, không `keycloak-db` riêng.
- Lời gọi đồng bộ chỉ đi một chiều copilot → insight → core → nilm. Chiều ngược lại chỉ bằng sự kiện.
- Mỗi service chỉ có quyền vào database của chính nó (một role mỗi database).
- Mọi lời gọi giữa service đi qua `libs/common`: timeout (connect 1s, read 3s, LLM 20s), retry tối đa 2 lần chỉ cho
  request idempotent hoặc có `Idempotency-Key`, circuit breaker, bulkhead; timeout → 504, không kết nối được hoặc
  breaker mở → 503 kèm `Retry-After`, 4xx của bên kia giữ nguyên.
- Địa chỉ service, database, broker lấy từ biến môi trường. Mỗi service có `GET /health` và `GET /ready`.
- Mỗi service ≥ 4 endpoint REST, OpenAPI do FastAPI sinh, file OpenAPI được commit và CI kiểm không lệch.
- `libs/common` chỉ chứa phần kỹ thuật (HTTP client, breaker, log, outbox/inbox, đọc header user), không chứa model
  nghiệp vụ.
- Cổng giữ dải 1109x: gateway 11093, Keycloak 11095, Postgres 11096 (chỉ debug), RabbitMQ UI 11099; còn lại không
  publish.
- Commit theo phase trên nhánh `feat/microservices`, không push khi chưa được yêu cầu.

## Điểm review

- Token Keycloak hợp lệ qua gateway; token sai chữ ký, sai `iss`, sai `aud`, `alg: none` đều bị 401.
- Client tự gửi `X-User-Id` không có tác dụng (Envoy xóa trước khi gán).
- Gửi lại cùng một batch (cùng `Idempotency-Key`) không tạo dữ liệu trùng.
- Tắt nilm: ingest trả 202 `PENDING_INFERENCE`, không 500; bật lại thì batch tự hoàn tất.
- Message lỗi 3 lần nằm trong DLQ, không mất; giao lại một message không xử lý hai lần.
- `docker compose up` từ volume rỗng chạy được không cần bước tay.

## Lưu ý trước khi bắt đầu

- Phase 2 dựng lại database dev từ đầu: lịch sử migration cũ (13 revision, một database) không dùng tiếp, mỗi service
  có lịch sử migration mới. Dữ liệu REFIT nạp lại bằng REFIT replayer. Ai cần giữ dữ liệu dev thì dump trước.
- Thiết kế bảng, aggregate, policy TimescaleDB trong `docs/database-design.md` giữ nguyên; chỉ đổi database chứa
  chúng (mục 7 của file đó).

---

### Phase 1: Khung monorepo, gateway, compose

**Files:**
- Tạo: `pyproject.toml` (workspace gốc), `libs/common/` (package `wattprint_common`), `services/{core,nilm,insight,copilot}/`
  mỗi service có `pyproject.toml`, `Dockerfile`, `app/main.py` với `/health`, `/ready`; `gateway/envoy.yaml`;
  `infra/postgres/init/01-databases.sql` (tạo 5 database, 5 role); `infra/rabbitmq/definitions.json` (exchange,
  queue, binding, policy DLQ).
- Sửa: `docker-compose.yml`, `README.md`, `docs/keycloak-auth.md`, `keycloak/realm/wattprint-realm.json`
  (audience mapper `wattprint-api`; client credentials cho từng service).

- [ ] Chuyển sang uv workspace; `uv sync` và `uv run ruff check` chạy ở gốc.
- [ ] `libs/common`: đọc `X-User-Id`/`X-User-Roles`/`X-Request-ID`, log JSON ra stdout có `request_id`, khung
      `/health` và `/ready`.
- [ ] `envoy.yaml`: listener 11093; route theo prefix `/api/{core,insight,copilot,nilm}/`; `jwt_authn` với `issuer`,
      `audiences`, `allowed_algorithms: [RS256]`, `remote_jwks` + `async_fetch`, `claim_to_headers`; route ingest bỏ
      JWT; `local_ratelimit`; timeout và retry theo route (không retry POST).
- [ ] Compose: Keycloak dùng `keycloak_db` trên Postgres chung; xóa service `keycloak-db` và volume của nó khỏi
      compose; RabbitMQ nạp `definitions.json`; `mem_limit`/`cpus` cho từng container.
- [x] Postgres lên `timescale/timescaledb:2.31.0-pg18` (làm sớm, 2026-11-10, trong compose hiện tại): volume mới mount vào `/var/lib/postgresql` (từ PG18 image
      để `PGDATA` ở `/var/lib/postgresql/18/docker`, không còn `/var/lib/postgresql/data`); đặt
      `timescaledb.enable_cagg_reorder_groupby = off` cho cả server để tránh timescale/timescaledb#10500 (lỗi chỉ có
      trên PG18, gặp khi `DISTINCT`/`GROUP BY` trên continuous aggregate rồi `ORDER BY`).
- [ ] Sửa README backend và `docs/keycloak-auth.md` cho đúng cách chạy mới.

**Kiểm chứng:**
- `docker compose up -d` từ volume rỗng; `docker compose ps` đủ 8 container healthy.
- `SELECT version()` ra PostgreSQL 18; `\dx` trong `core_db` có `timescaledb` 2.31.0, trong `copilot_db` có `vector`;
  `SHOW timescaledb.enable_cagg_reorder_groupby` ra `off`.
- `curl :11093/api/core/health` không token → 401; có token Keycloak thật → 200; token sửa một ký tự → 401.
- RabbitMQ UI thấy exchange `wattprint.events`, `wattprint.dlx`, 2 queue và 2 DLQ.

### Phase 2: core

**Files:**
- Chuyển: `app/models/{core,catalog,energy,billing,ops,user}.py`, `app/services/{ingest,meter,billing,aggregates,users}.py`,
  `app/cli/` vào `services/core/app/`; `tests/` liên quan vào `services/core/tests/`.
- Tạo: `services/core/alembic/` với migration nền mới cho `core_db` (gộp phần core của 13 revision cũ, bỏ `insight`,
  `copilot`, `copilot_ro`, `knowledge`, `energy.inference_run`, `energy.weather_hourly`, `core.device_alert_rule`);
  bảng `outbox`; routers homes, meters, devices, ingest, bills; `tools/refit_replayer.py`.

- [ ] Migration nền `core_db` dựng được từ volume rỗng; giữ nguyên hypertable, aggregate, policy, `ops.set_policies`.
- [ ] API: nhà, thành viên, mã mời, ghép công tơ, thiết bị, ingest batch (`Idempotency-Key`, API key thiết bị),
      hóa đơn. Luật: một tài khoản một nhà; mã dùng một lần có hạn; batch idempotent và liên tục; hóa đơn theo
      phiên bản biểu giá.
- [ ] Outbox: ghi cùng transaction với dữ liệu; relay `FOR UPDATE SKIP LOCKED`, publish có xác nhận.
- [ ] REFIT replayer: đọc CSV REFIT, gửi batch qua gateway như cảm biến thật (thay `app/cli/load_refit.py` ghi thẳng DB).

**Kiểm chứng:** pytest của core xanh; replayer nạp house 1 qua gateway; gửi lại cùng batch → 0 dòng mới; message
`energy.usage.updated` xuất hiện trong `insight.usage` (xem bằng RabbitMQ UI).

### Phase 3: nilm và luồng ingest → nilm

**Files:** `services/nilm/app/` (chuyển `app/ml/nilm/`), migration `nilm_db` (`inference_run`, model registry,
hiệu chỉnh), volume `models`; `libs/common` thêm HTTP client có retry, breaker, bulkhead; core thêm `NilmClient`,
`PendingRetrier`.

- [ ] API nilm: `POST /inferences`, quản lý phiên bản model (admin), `/health`, `/ready` (đã nạp model).
- [ ] core gọi nilm qua `libs/common`; lỗi hạ tầng → batch `PENDING_INFERENCE`, trả 202; retrier gửi lại theo backoff
      1, 2, 4 phút, quá 5 lần → `FAILED`.

**Kiểm chứng:** ingest bình thường → 201 `DONE`; `docker compose stop nilm` → 202 `PENDING_INFERENCE` trong < 2 s;
bật lại → batch tự thành `DONE`. Ghi số liệu trước/sau cho báo cáo (kịch bản lỗi 1).

### Phase 4: insight

**Files:** `services/insight/app/`, migration `insight_db` (chuyển `insight.*`, `savings_measure`, `weather_hourly`,
`device_alert_rule`; thêm read model theo giờ dạng hypertable, `inbox`, `outbox`, view cho truy vấn an toàn).

- [ ] Consumer FastStream cho `insight.usage`, idempotent bằng `inbox`; cập nhật read model.
- [ ] Detector (bất thường, chạy ngầm, chạm bậc, vượt ngân sách) → alert + outbox → `insight.alert.created`.
- [ ] API: tiêu thụ, dự báo (≥ 7 ngày dữ liệu), ngân sách, so sánh nhóm (≥ 10 hộ), what-if, M&V (≥ 14 ngày),
      `POST /queries` (SQL guard: một câu SELECT trên view cho phép, ép `home_id`, timeout 2s).
- [ ] `CoreClient` lấy biểu giá và thiết bị; `WeatherClient` gọi Open-Meteo.

**Kiểm chứng:** pytest xanh; ném lỗi trong consumer → message vào `insight.usage.dlq` sau 3 lần; giao lại cùng
message → read model không đổi; `POST /queries` với `DELETE`, nhiều câu, hoặc không có `home_id` → 400.

### Phase 5: copilot

**Files:** `services/copilot/app/`, migration `copilot_db` (`copilot.*` trừ `savings_measure` và `scope_token`,
`knowledge.*`, `inbox`, `outbox`, bảng saga).

- [ ] Chat API: guardrail (PII, prompt injection, gói Pro), orchestrator gọi tool qua `InsightClient`, verifier,
      RAG pgvector; LLM timeout 20s + breaker, lỗi thì trả 503 kèm số liệu thô.
- [ ] Alert consumer → ranker → notifier (Expo Push, Telegram); giới hạn số thông báo mỗi ngày, giờ yên tĩnh.
- [ ] Plans API: saga kích hoạt kế hoạch tiết kiệm, bù trừ theo thứ tự ngược, PENDING + reconciler khi timeout.

**Kiểm chứng:** pytest xanh; làm chậm LLM quá 20s → breaker mở, các request sau trả 503 ngay thay vì treo
(kịch bản lỗi 2, ghi số liệu trước/sau); saga bước 2 bị 422 → `DELETE /savings-measures/{id}` được gọi.

### Phase 6: Postman, CI, số liệu cho báo cáo

**Files:** `postman/wattprint.postman_collection.json`, `postman/local.postman_environment.json`,
`.github/workflows/ci.yml`, `services/*/openapi.json`.

- [ ] Collection ≥ 10 request qua gateway, có test assertion, gồm 2 kịch bản lỗi ở phase 3 và 5.
- [ ] CI: ruff + pytest từng service, build image, `docker compose up`, Newman, kiểm OpenAPI không lệch.
- [ ] Bảng số liệu trước/sau (độ trễ, tỷ lệ lỗi từ báo cáo Newman) cho 2 kịch bản lỗi.

**Kiểm chứng:** workflow CI xanh trên nhánh; `newman run` local in đủ request, 0 assertion lỗi ở trạng thái bình thường.
