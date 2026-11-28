# Review Đ0 (lane L): khóa dịch vụ text2sql, proxy frontend, thu quyền `wattprint_ai`

Chủ dự án yêu cầu chỉ chạy 1 vòng review (2026-11-28), nên không có R2/R3. Hai reviewer `sdlc:reviewer` (opus,
mode full) chạy song song, mỗi repo một package. Một phiên làm việc song song đã sửa vài điểm trên cùng cây; bảng
dưới gộp cả hai.

| Repo | Base | Snapshot R1 | Kết luận |
|---|---|---|---|
| wattprint-text2sql-mcp | `6157dd2` | `72d4d15` | fix 1, 2, 3 |
| wattprint-backend | `2c297f9db1e788f68f04da835a86384a10e44487` | `051aa2d746ae7cbca162ea0593f5356074fcc33b` | fix 1 |

## text2sql

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Must | `scripts/text2sql_eval/run_eval.py:287` không gửi khóa: cả lượt eval sẽ 401/503 | Client gửi `X-Service-Key` từ `config` |
| 2 | Should | `test_own_knowledge_keeps_its_own_keys` gửi GET vào route chỉ nhận POST → 405, không kiểm gì | Gọi mọi route own-knowledge đúng method, cấm 405/503. Thử bọc own-knowledge bằng cổng khóa: test đỏ 10 ca |
| 3 | Should | Handbook còn "chưa có xác thực" ở 20 trang | Sửa thành "đòi `X-Service-Key`, chưa phân quyền theo người dùng", kèm link |
| 4 | Minor | Test "đúng khóa" chỉ thử một route | Lặp mọi route, cấm 401/503 |
| 5 | Minor | Tên `test:charts` không còn đúng | Đổi thành `test`; sửa verify.sh, AGENTS.md, README, bieu-do.md |
| 6 | Minor | `tests/service_key.py` có docstring, trái quy ước | Đã xóa |

Reviewer không chấm, không coi là lỗi: proxy cho ai tới được cổng frontend gọi API (trước đây trình duyệt gọi thẳng
cổng backend; spec R0.1 chấp nhận việc UI chưa có đăng nhập); `proxyTarget` bỏ path prefix trong `API_URL` (không
cấu hình nào dùng prefix).

## backend

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Should | `docs/diagrams/privacy/*` ngoài phạm vi Đ0 | Ruling bên dưới |
| 2 | Minor | `database-design-guide.md` bảng schema còn "AI chỉ đọc" | Sửa hai dòng |
| 3 | Minor | `Result.tuples()` deprecated | Dùng `rows.all()` |

Ruling: diagrams ngoài phạm vi — đó là việc Đ8-C1 làm từ phiên trước, chưa commit; không đưa vào commit Đ0, review
cùng Đ8 theo R6.1 — nếu sai: Đ8 review lại 770 dòng, không mất gì khác.

## Kiểm tra sau khi sửa

- text2sql `scripts/verify.sh`: 380 test Python pass (7 skip), 87 test frontend pass. Một lần hook báo 1 test đỏ
  không lặp lại được qua 10 lần chạy.
- backend: toàn bộ pytest 720 pass; 1 lỗi ở `test_copilot_upkeep` do chạy `test_roles` song song cùng DB test, chạy
  riêng pass. `-m migrations`: 9 pass. `test_roles.py`: 49 pass.

## Task 5 (đã làm 2026-11-28, chủ dự án cho phép tự làm)

- R0.2: kết nối "Wattprint" của text2sql đăng nhập bằng `wattprint_copilot_ro`, không phải `wattprint_ai_user`.
- Khóa: dùng lại khóa 64 ký tự sẵn có trong `.env` backend, đặt cùng giá trị vào `.env` text2sql; hash hai bên khớp.
- Dựng lại `backend`, `frontend` của text2sql. API không khóa 401, có khóa 200, `/openapi.json` 200; UI qua proxy 200.
- Áp `7ed04a4f7308` lên DB dev: `wattprint_ai` chỉ còn SELECT `dim_tariff_plan`, `metric_definition`.
- Wappi hỏi tự do (một câu, backend → text2sql có khóa): `answered`, 14.67 kWh.
- SSE qua proxy Next (`next start` trong container, cổng 11100): 10 event đến rải trong 2.4 giây, không dồn cuối.

## Chưa làm

- Prod (wattprint.ptitai.org) chưa đổi: chỉ triển khai khi chủ dự án yêu cầu.
