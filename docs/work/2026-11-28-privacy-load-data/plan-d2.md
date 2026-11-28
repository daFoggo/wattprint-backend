# Plan Đ2: giảm chi tiết gửi AI (R3.1, R3.2, R3.7, R3.8)

Lane L (migration, copilot). Base backend: cây bẩn của Đ0+Đ1, snapshot lấy khi bắt đầu; text2sql: như vậy.
Một vòng review (opus), theo yêu cầu của chủ dự án.

Đã kiểm trước khi viết:
- ZDR chạy với mọi model đang dùng (2026-11-28, mỗi model một lời gọi thật với
  `provider: {zdr: true, data_collection: "deny"}`): chat `openai/gpt-6-luna` (Azure), guard
  `meta-llama/llama-guard-4-12b` (DeepInfra), embed `baai/bge-m3` (Parasail), embed text2sql
  `openai/text-embedding-3-small` (Azure). Không cần lùi sang AstralX.
- R3.7 phần lớn đã đúng: `routes/copilot.py:54` che câu hỏi trước khi lưu; guard, lịch sử, tìm tài liệu đều đọc
  bản đã lưu. Bản chữ của giọng nói trả về trình duyệt rồi quay lại thành câu hỏi, cũng qua chỗ che đó. Chỉ thêm
  test chứng minh guard nhận câu đã che.

## Task 1. Migration `updates/20261128_<rev>_copilot_less_detail` (DB)

- `tb_home.ai_detail varchar(8) NULL CHECK IN ('daily','hourly')`; `tb_scope_token.detail varchar(8) NOT NULL
  DEFAULT 'daily' CHECK IN (...)`.
- Hàm `copilot_ro.current_detail()` (SECURITY DEFINER, như `current_home()`): mức của token đang đặt; thiếu, hết
  hạn, sai thì NULL. Quyền EXECUTE chỉ cho `wattprint_copilot_ro`.
- DROP `copilot_ro.reading_1m`, `copilot_ro.device_estimate_1m`, `copilot_ro.device_cycle`.
- Tạo lại `copilot_ro.home` không có `name`, `postal_code`, `occupants`.
- `copilot_ro.reading_1h`, `copilot_ro.device_estimate_1h`: thêm `AND copilot_ro.current_detail() = 'hourly'`.
- `copilot_ro.alert`: `ts` thành ngày (giờ Việt Nam) khi mức không phải `hourly`.
- downgrade dựng lại đúng định nghĩa cũ (lấy từ `pg_get_viewdef` trên DB dev trước khi đổi).
- Test (đỏ trước) `tests/db/test_roles.py`: copilot đọc view phút bị từ chối (view không còn); token `daily` đọc
  `_1h` ra 0 dòng, token `hourly` ra dòng; `home` không có cột định danh; `alert.ts` là nửa đêm khi `daily`;
  `current_detail()` khóa như `current_home()`; ma trận quyền cập nhật; round trip `-m migrations`.
- Standards: `.claude/rules/migrations.md`, `.claude/rules/tests.md`.

## Task 2. Mức chi tiết trong backend (BE)

- `app/config.py`: `copilot_ai_detail_default: str = "daily"`.
- `ScopeToken.detail`, `Home.ai_detail` (model). `Ctx.detail` lấy `home.ai_detail or default` trong `chat.answer`.
- `query_data`, `_one_number_sql`: `ScopeToken(home_id=..., detail=ctx.detail)`.
- `standby` ở `daily`: trả `{"error": ...}` nói vì sao, không đọc `reading_1m`.
- `alerts` ở `daily`: `since` chỉ còn ngày; bỏ `start_hour`, `at` trong `figures`.
- `PATCH /homes/current` nhận `ai_detail` (`daily|hourly|null`); route đã chỉ cho chủ nhà (thành viên, khách demo
  403 theo bảng thử quyền). `HomeRead` trả `ai_detail` và mức hiệu lực.
- `scripts/seed_demo_homes.py`: nhà demo `ai_detail = 'hourly'`.
- Test: `tests/test_copilot_tools.py` (standby, alerts theo mức; token mang mức), `tests/test_home_api.py`
  (PATCH ai_detail), `tests/test_copilot_api.py` (guard nhận câu đã che).
- Standards: `.claude/rules/copilot.md`, `.claude/rules/data.md`.

## Task 3. ZDR (BE, T2S)

- Backend: `llm.py` provider openrouter `extra` thêm `provider`; `guard.py`; `documents.py` chỉ khi gọi OpenRouter.
- text2sql: `get_chat_models.py` `extra_body={"provider": ...}`; `get_embedding_models.py` thêm `provider`.
- Test: body gửi đi có `provider` (MockTransport) ở cả hai repo; AstralX không nhận trường này.

## Task 4. text2sql (T2S)

- Đồng bộ metadata kết nối WattPrint (API có khóa) để bỏ view phút, `device_cycle` và cột định danh khỏi schema và
  từ điển dữ liệu; xóa mục từ điển của các đối tượng đã mất nếu đồng bộ không tự xóa.

## Task 5. Áp lên dev và eval (OPS, DOC)

- Áp migration; nhà demo `hourly`; một câu hỏi thật ở mỗi mức.
- Eval Wappi một nhà, một lượt ở `hourly` và `daily`; ghi số vào `docs/eval/`.

Rủi ro: text2sql còn cache schema cũ trong Qdrant (ingestion) → hỏi tự do trỏ vào view đã mất thì lỗi; xử lý ở
Task 4 bằng đồng bộ lại và chạy ingestion.
