# Đ0: vá text2sql và vai database — kế hoạch triển khai

> **Cho người thực thi:** làm inline theo quy trình sdlc của repo (không dùng subagent-driven-development); sau khi xong
> chạy vòng review R1 bằng `sdlc:reviewer`, `model: opus`. Các bước dùng ô `- [ ]` để theo dõi.

**Mục tiêu:** không ai gọi được API của text2sql nếu không có khóa dịch vụ, và vai database `wattprint_ai` không còn đọc
được dữ liệu của bất kỳ nhà nào.

**Cách làm:** kiểm khóa chuyển từ router chat ra mức app của text2sql và đóng khi chưa cấu hình. Giao diện quản trị
của text2sql đang gọi API thẳng từ trình duyệt, nên thêm một route chuyển tiếp cùng nguồn gắn khóa ở phía server, theo
mẫu `app/api/own-knowledge` đã có. Ở backend WattPrint, một revision mới thu quyền của vai không còn ai dùng.

**Công nghệ:** FastAPI, unittest (text2sql); Next.js App Router, `node --test` (frontend text2sql); Alembic, pytest
trong container `api` (backend).

**Spec:** [spec.md](spec.md) R0.1–R0.3. Checklist: [checklist.md](checklist.md) mục Đ0.

**Base:** `wattprint-text2sql-mcp` `6157dd2` (cây sạch). `wattprint-backend`: cây có thư mục tài liệu chưa commit, lấy
snapshot bằng `review-package.mjs --snapshot` trước khi sửa.

## Ràng buộc chung

- text2sql: không docstring; không `os.getenv` ngoài `backend/core/setting.py`; dòng tối đa 120 ký tự; đổi hành vi thì sửa
  handbook trong cùng thay đổi; tài liệu tiếng Việt có dấu. Không sửa `.env`. `compose.yaml` cần chủ repo duyệt.
- backend: revision viết tay, mới, không sửa và không format revision đã áp; không đụng thuộc tính của vai, chỉ quyền;
  bảng hoặc view đổi quyền thì cập nhật `tests/db/test_roles.py`; test chạy bằng `docker compose exec -T api pytest`.
- Không khởi động lại, dựng lại hay dừng container nào. Stack text2sql đang chạy từ image đã dựng, nên sửa mã không ảnh
  hưởng nó cho tới khi chủ dự án dựng lại (Task 5).
- Không commit; chủ dự án commit khi muốn.

## Review Focus

1. Luồng SSE của chat đi qua route chuyển tiếp bị gom lại thay vì chảy từng phần: người dùng thấy chat đứng im. Bước
   kiểm bằng máy chủ giả ở Task 2 xem các phần có tới lần lượt không.
2. Khóa chỉ được đặt ở một trong hai dịch vụ: Wappi hỏi tự do phải báo "text2sql answered 401/503" như hiện nay, không
   vỡ. Test ở Task 4.
3. Healthcheck của compose gọi `GET /openapi.json`: phải vẫn mở khi không có khóa, nếu không frontend không bao giờ
   lên. Test ở Task 1.
4. Script và công cụ gọi API qua HTTP (`scripts/text2sql_eval`, `simulation/`) không gửi khóa sẽ hỏng. Task 1 bước 6.
5. Yêu cầu không phải JSON (tải file, nếu có) qua route chuyển tiếp: phải giữ nguyên `Content-Type`. Test ở Task 2.

---

### Task 1: text2sql kiểm khóa trên mọi router, đóng khi chưa cấu hình (R0.1)

**Files:**
- Modify: `backend/core/security.py` (thêm `require_service_key`), `backend/modules/text2sql/routes/router_chat.py`
  (bỏ hàm cục bộ và `dependencies` của router), `backend/main.py:62-72`
- Create: `tests/test_service_key.py`, `tests/service_key.py` (hằng `SERVICE_KEY`, `SERVICE_HEADERS`, hàm `use_service_key(test)`)
- Modify: 17 chỗ `TestClient(app…)` trong 14 file test (thêm `headers=SERVICE_HEADERS`), `tests/test_text2sql_chat.py:984-996`
- Modify: `README.md:126,136`, `.env.example:48-50`, `docs/handbook/hanh-vi-api.md`

**Interfaces:**
- Produces: `backend.core.security.require_service_key(x_service_key: str | None = Header(None)) -> None`.
  Khóa chưa đặt hoặc rỗng → `HTTPException(503, "Backend chưa được cấu hình TEXT2SQL_SERVICE_KEY.")`; thiếu hoặc sai →
  `HTTPException(401, "Thiếu hoặc sai X-Service-Key.")`; so sánh bằng `hmac.compare_digest`.
- Áp cho mọi `app.include_router(...)` trừ `own_knowledge_router` (đã có khóa riêng, đã đóng khi thiếu).

- [ ] **Bước 1: viết test đỏ** `tests/test_service_key.py`, duyệt `app.routes` có đường dẫn bắt đầu `/api/v1/` và không
  thuộc `/api/v1/own-knowledge`, thay mọi tham số đường dẫn bằng một UUID:
  - `test_every_route_rejects_a_missing_key`: mọi (method, path) trả 401 khi không có header.
  - `test_every_route_rejects_a_wrong_key`: 401 với `X-Service-Key: wrong`.
  - `test_unset_key_fails_closed`: `config.text2sql_service_key` là `None` rồi `SecretStr("")`, mọi route trả 503.
  - `test_right_key_passes_the_gate`: với khóa đúng, không route nào trả 401 hay 503.
  - `test_openapi_stays_open`: `GET /openapi.json` trả 200 không cần khóa.
  - `test_own_knowledge_keeps_its_own_keys`: route own-knowledge không đổi hành vi khi thiếu `X-Service-Key`.
- [ ] **Bước 2: chạy, thấy đỏ.** `uv run --frozen python -m unittest tests.test_service_key -v` → các test 401 và 503
  thất bại vì route đang trả 200/404/422.
- [ ] **Bước 3: chuyển `require_service_key` sang `backend/core/security.py`** với hành vi ở Interfaces; gắn
  `dependencies=[Depends(require_service_key)]` vào từng `include_router` trong `main.py`.
- [ ] **Bước 4: sửa các test hiện có.** `tests/service_key.py` đặt khóa test vào `config` trong `setUp` và trả lại ở
  cleanup; 17 `TestClient` thêm `headers=SERVICE_HEADERS`. `test_service_key_is_required_once_set` đổi nhánh khóa rỗng
  từ 200 sang 503.
- [ ] **Bước 5: chạy toàn bộ.** `scripts/verify.sh` → `OK`, số test tăng đúng bằng số test mới.
- [ ] **Bước 6: tìm người gọi HTTP khác.** `grep -rn "api/v1" scripts simulation` (bỏ qua test); chỗ nào gọi API thì
  gửi `X-Service-Key` lấy từ cấu hình, kèm test của chính script đó nếu script đã có test.
- [ ] **Bước 7: tài liệu.** README, `.env.example` (bỏ câu "để trống thì không kiểm"), mục mới trong `hanh-vi-api.md`
  nêu 401, 503 và route nào được miễn; ghi **đã triển khai**.

### Task 2: giao diện text2sql gọi API qua route chuyển tiếp cùng nguồn (R0.1)

**Files:**
- Create: `frontend/lib/backend-proxy.ts`, `frontend/lib/backend-proxy.test.ts`, `frontend/app/api/v1/[...path]/route.ts`
- Modify: `frontend/lib/api.ts:1` (`API_URL = ""`), `frontend/package.json` (script `test:charts` thành `test`, chạy cả hai
  nhóm test; sửa tên trong `scripts/verify.sh` và AGENTS.md cho khớp), `frontend/Dockerfile:13-14` (bỏ `NEXT_PUBLIC_API_URL`),
  `compose.yaml` mục `frontend` (thêm `TEXT2SQL_SERVICE_KEY`, bỏ build arg; chờ duyệt), `.env.example`,
  `docs/handbook/frontend/README.md`

**Interfaces:**
- Produces: `proxyTarget(path: string[], search: string, backendUrl: string): string | null` trả
  `${backendUrl}/api/v1/${path.join("/")}${search}`, và `null` khi `path[0] === "own-knowledge"`.
- Produces: `upstreamHeaders(contentType: string | null, key: string): Headers` giữ nguyên `Content-Type` của yêu cầu,
  thêm `X-Service-Key`, không chuyển tiếp header nào khác.
- Route: `GET, POST, PUT, PATCH, DELETE`; `dynamic = "force-dynamic"`; thiếu `TEXT2SQL_SERVICE_KEY` → 503
  `{ detail: "Frontend chưa được cấu hình khóa dịch vụ." }`; `proxyTarget` trả `null` → 404; lỗi mạng → 502; trả lại
  `upstream.body` nguyên dòng chảy kèm `Content-Type`, `Cache-Control`, `X-Accel-Buffering` của upstream.

- [ ] **Bước 0: đọc** `frontend/AGENTS.md`, `docs/handbook/frontend/README.md` và tài liệu route handler của bản Next
  đang cài trước khi viết.
- [ ] **Bước 1: viết test đỏ** `frontend/lib/backend-proxy.test.ts`:
  - `proxyTarget(["conversations", "x"], "?a=1", "http://b")` bằng `"http://b/api/v1/conversations/x?a=1"`.
  - `proxyTarget(["own-knowledge", "admin"], "", "http://b")` bằng `null`.
  - `upstreamHeaders("multipart/form-data; boundary=x", "k")` giữ đúng `Content-Type` đó và có `X-Service-Key: k`.
  - `upstreamHeaders(null, "k")` không có `Content-Type`.
- [ ] **Bước 2: chạy, thấy đỏ** (`node --test lib/backend-proxy.test.ts` → module chưa tồn tại).
- [ ] **Bước 3: viết `backend-proxy.ts` và route**, rồi đổi `API_URL` thành chuỗi rỗng. Kiểm bằng grep rằng không
  server component nào gọi `apiFetch` lúc render (đường dẫn tương đối chỉ chạy được ở trình duyệt).
- [ ] **Bước 4: test xanh; `npm run lint`, `npm run typecheck`.**
- [ ] **Bước 5: kiểm bằng máy chủ giả.** Một máy chủ HTTP nhỏ ở cổng tạm in lại header nhận được và trả 3 phần SSE
  cách nhau 300 ms; chạy `next dev` ở cổng tạm với `API_URL` trỏ vào đó và một khóa giả; `curl -N` qua route chuyển
  tiếp phải thấy `X-Service-Key` tới nơi và 3 phần về lần lượt, không gom một cục. Tắt cả hai tiến trình sau khi kiểm.
- [ ] **Bước 6: tài liệu.** Handbook frontend: trình duyệt không còn gọi backend trực tiếp; biến môi trường mới.

### Task 3: thu quyền của vai `wattprint_ai` (R0.3)

**Files:**
- Create: `alembic/versions/updates/20261128_<rev>_revoke_ai_role_home_data.py` (`down_revision` là head hiện tại, lấy
  bằng `docker compose exec -T api alembic heads`)
- Modify: `tests/db/test_roles.py`, `README.md:58`, `docs/database-design.md:143`

**Interfaces:**
- upgrade: `REVOKE SELECT ON ai.fact_reading_1m, ai.fact_estimate_1m, ai.fact_energy, ai.dim_home, ai.dim_device FROM wattprint_ai`.
- downgrade: `GRANT SELECT` lại đúng năm đối tượng đó.

- [ ] **Bước 1: viết test đỏ** trong `tests/db/test_roles.py`:
  `test_ai_role_reads_reference_data_only`: tập `(table_schema, table_name, privilege_type)` của
  `information_schema.role_table_grants` với `grantee = 'wattprint_ai'` bằng đúng
  `{("ai", "dim_tariff_plan", "SELECT"), ("ai", "metric_definition", "SELECT")}`. Tập thật khác thế (vai còn quyền nào
  ngoài năm đối tượng trên) thì dừng lại, đưa quyền đó vào revision trước khi viết tiếp.
- [ ] **Bước 2: chạy, thấy đỏ.** `docker compose exec -T api pytest -q tests/db/test_roles.py -k ai_role`.
- [ ] **Bước 3: viết revision** (hook sẽ hỏi chủ repo duyệt).
- [ ] **Bước 4: test xanh;** thêm ca khứ hồi đánh dấu `migrations` theo mẫu
  `test_revision_downgrade_removes_grants_and_upgrade_restores_them`; chạy `pytest -q -m migrations -k ai_role`.
- [ ] **Bước 5: tài liệu.** README và `database-design.md`: vai `wattprint_ai` chỉ còn đọc dữ liệu tham chiếu.

### Task 4: backend luôn gửi khóa khi gọi text2sql (R0.1)

**Files:**
- Modify: `tests/test_copilot_tools.py`; `app/modules/copilot/services/tools.py:781-784,943` chỉ khi test chỉ ra thiếu

- [ ] **Bước 1: viết test** theo cách file này đang giả lập text2sql:
  - `test_query_data_sends_the_service_key`: đặt `settings.text2sql_service_key`, yêu cầu tới `T2S_STREAM` có
    `X-Service-Key` đúng giá trị.
  - `test_one_number_sql_sends_the_service_key`: tương tự cho lời gọi ở dòng 943.
  - `test_query_data_reports_a_refused_key`: text2sql trả 401 → `Outcome.data == {"error": "text2sql answered 401"}`.
- [ ] **Bước 2: chạy.** Test nào đỏ thì sửa đúng chỗ gọi đó cho gửi header; test xanh sẵn thì để nguyên mã.
- [ ] **Bước 3:** `docker compose exec -T api pytest -q tests/test_copilot_tools.py`, rồi verify của repo.

### Task 5: triển khai trên dev (chủ dự án làm hoặc duyệt từng lệnh)

- [ ] R0.2: trước khi bật khóa, gọi `GET http://127.0.0.1:11101/api/v1/database-connections` (chỉ đọc) xem tên người
  dùng trong URI đã che của kết nối WattPrint; không phải `wattprint_copilot_ro` thì đổi ở giao diện text2sql.
- [ ] Sinh một khóa ngẫu nhiên từ 32 ký tự; đặt `TEXT2SQL_SERVICE_KEY` trong `.env` của text2sql và cùng giá trị trong
  `.env` của backend.
- [ ] Dựng lại `backend` và `frontend` của text2sql; khởi động lại `api` của backend; áp revision của Task 3.
- [ ] Kiểm: `curl` thẳng `127.0.0.1:11101/api/v1/database-connections` không khóa trả 401; mở giao diện text2sql ở
  cổng 11100 vẫn liệt kê được kết nối; hỏi Wappi một câu hỏi tự do vẫn ra kết quả.
- [ ] Không làm bước này trong 48 giờ trước giờ chấm.

## Tự rà

- R0.1 → Task 1, 2, 4, 5. R0.2 → Task 5 bước đầu. R0.3 → Task 3.
- Tên dùng nhất quán: `require_service_key`, `SERVICE_HEADERS`, `proxyTarget`, `upstreamHeaders`.
- Năm dòng Review Focus đều có test hoặc bước kiểm ở task giữ phần mã tương ứng.
