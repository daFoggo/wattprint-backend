# Plan Đ3: đồng ý, cửa ra chung, nhật ký gửi ra ngoài (R3.3–R3.6)

Lane L (migration, auth, copilot, web). Một vòng review (opus). Base: snapshot lúc bắt đầu.

## Thiết kế

- **Đồng ý** `public.tb_consent` (id, user_id → tb_users ON DELETE CASCADE, purpose `wappi|voice|email`, granted,
  version, created_at); chỉ INSERT, không UPDATE/DELETE cho `wattprint_app`. Trạng thái = dòng mới nhất mỗi
  (user, purpose). Chưa có dòng = chưa đồng ý. `CONSENT_VERSION = "2026-11-28"` (đổi lời mời thì đổi số, người dùng
  phải đồng ý lại).
- **Cổng ra ngoài** `app/common/outbound.py`:
  - `PARTIES`: `openrouter`, `astralx`, `openweather`, `telegram`, `smtp`, `text2sql` (nội bộ nhưng chuyển tiếp
    câu hỏi tới OpenRouter, nên ghi là `openrouter` qua text2sql).
  - `await outbound.require(user_id, purpose)` ném `ConsentRequiredError` (403 `consent_required`).
  - `await outbound.record(party, purpose, data, detail, user_id=, home_id=)` ghi một dòng `tb_outbound_log`
    (phiên riêng, commit ngay; không ghi nội dung).
  - `outbound.client(party, **httpx_kwargs)`: `httpx.AsyncClient` với base URL của bên đó (URL chỉ ở `config.py`
    và file này).
  - Thứ tự ở mỗi chỗ gọi: `require` (khi mục đích cần đồng ý) → `record` → `client(...)` gửi.
- **Nhật ký** `public.tb_outbound_log` (id, created_at, user_id NULL, home_id NULL, party, purpose, data text[],
  detail NULL); index (user_id, created_at), (home_id, created_at). Giữ 90 ngày: xóa trong job dọn dẹp có sẵn
  (`prune_scope_tokens` cùng chỗ).
- **API**: `GET /users/me/consents`, `PUT /users/me/consents/{purpose}` `{granted}`; `GET /users/me/outbound`
  (30 ngày: dòng của người gọi, cộng dòng không gắn người của nhà họ như thời tiết).
- **Chat**: route `POST /copilot/chat` kiểm `wappi` trước khi lưu câu hỏi; voice kiểm `voice`. Sự kiện `done` và
  `reply` có `sent`: `{parties, data, detail}` (bên nhận từ `usage.providers`, loại dữ liệu theo công cụ đã chạy).
- **👎**: `FeedbackIn.share_content: bool = False`; Telegram chỉ nhận nội dung khi `true`, nếu không chỉ báo
  "một câu trả lời bị chấm 👎" kèm id.
- **Email**: mail cảnh báo và tóm tắt tuần chỉ gửi cho người có đồng ý `email`; `notify_anomaly`, `notify_tier`
  mặc định tắt cho tài khoản mới (server default).

## Task (backend trước, web sau)

1. Migration + model + test vai (`test_roles.py`: hai bảng mới vào ma trận; app chỉ INSERT/SELECT `tb_consent`).
2. `outbound.py` + test đơn vị; chuyển `llm.py`, `guard.py`, `documents.py`, `voice.py`, `weather.py`,
   `notify.py`, `mail.py`, `query_data`/`_one_number_sql` sang dùng. Test quét mã: URL ngoài chỉ ở `config.py`,
   `outbound.py`.
3. API đồng ý + chặn chat/voice + test (chưa đồng ý 403, không có request nào ra ngoài; rút lại bị chặn ngay; mỗi lần
   bật tắt đúng một dòng). `make_member` mặc định đồng ý `wappi`, `voice` để test cũ giữ nguyên ý.
4. `sent` trong câu trả lời; `share_content`; email theo đồng ý; prune 90 ngày; `GET /users/me/outbound`.
5. Bảng thử quyền: thêm 3 dòng route mới; chạy lại.
6. Web (`wattprint-web/apps/dashboard`): chữ trong `messages/{vi,en}/copilot.json` trước; hộp đồng ý (dùng
   `responsive-dialog`), dòng báo dưới ô chat, mục "Đã gửi ra ngoài", ô tích ở 👎, `EmptyState` khi chưa đồng ý.
   Tự thử bằng tài khoản test và khách demo.

Standards: `.claude/rules/migrations.md`, `tests.md`, `copilot.md`, `data.md`; web: `docs/adding-a-feature.md`,
`docs/design-system.md`.

Rủi ro: tài khoản đang dùng (kể cả khách demo) bị hỏi đồng ý lần đầu sau khi triển khai; đó là hành vi mong muốn.
