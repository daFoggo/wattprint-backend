# Bảng thử quyền: bản trước khi sửa

In từ lần chạy thật bằng `docker compose exec -T api python scripts/print_permission_matrix.py` (test
`tests/test_permissions.py` và các ca vai database trong `tests/db/test_roles.py`). Mỗi ô là mã HTTP thật một chủ
thể nhận được khi gọi thao tác đó trên dữ liệu của nhà A. Dữ liệu mẫu được dựng mới cho từng thao tác.

Chủ thể (thành viên và khách demo đều có kế hoạch tiết kiệm của riêng mình): chưa đăng nhập; chủ nhà B (gọi vào thiết bị, cảnh báo, kế hoạch, nhắc, hội thoại của nhà A bằng id);
khách demo (vai `viewer`, chỉ đọc); thành viên; chủ nhà A; admin (không thuộc nhà nào).

Cách đọc: 401 chưa đăng nhập; 403 không được phép; 404 không tìm thấy (với chủ nhà khác nghĩa là không lộ là có);
404 của admin là "không có nhà", nên admin không đọc được dữ liệu nhà nào. Ở dự báo, `plans/basis` và cohort,
404/422 của chủ nhà là "chưa đủ dữ liệu" (cần một tuần số đo, mười nhà), không phải bị từ chối.

## Kết quả

Chạy lúc 2026-11-28 02:09 UTC, 45 thao tác API.

| Thao tác | Chưa đăng nhập | Chủ nhà khác | Khách demo | Thành viên | Chủ nhà | Admin | Khớp mong đợi |
|---|---|---|---|---|---|---|---|
| `GET /api/v1/billing/current` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/billing/devices/forecast` | 401 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/billing/forecast` | 401 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/billing/history` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `POST /api/v1/copilot/chat` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/copilot/conversations` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `DELETE /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 204 | 404 | đúng |
| `GET /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 200 | 404 | đúng |
| `PATCH /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 200 | 404 | đúng |
| `PUT /api/v1/copilot/messages/{message_id}/feedback` | 401 | 404 | 404 | 404 | 204 | 404 | đúng |
| `GET /api/v1/copilot/messages/{message_id}/speech` | 401 | 404 | 404 | 404 | 200 | 404 | đúng |
| `POST /api/v1/copilot/voice/transcribe` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/demo/homes` | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `POST /api/v1/demo/homes/{key}/guest` | 403 | 403 | 403 | 403 | 403 | 403 | đúng |
| `POST /api/v1/demo/homes/{key}/view` | 401 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/energy/activity` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/devices` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/devices/{device_id}` | 401 | 404 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/overview` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/series` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/stream` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/weather` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/expected` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/health` | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/homes/current` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `PATCH /api/v1/homes/current` | 401 | 200 | 403 | 403 | 200 | 404 | đúng |
| `GET /api/v1/homes/provinces` | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/insights/alerts` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `PATCH /api/v1/insights/alerts/{alert_id}` | 401 | 404 | 403 | 204 | 204 | 404 | đúng |
| `POST /api/v1/insights/alerts/{alert_id}/feedback` | 401 | 404 | 403 | 204 | 204 | 404 | đúng |
| `GET /api/v1/insights/cohort` | 401 | 404 | 404 | 404 | 404 | 404 | đúng |
| `POST /api/v1/insights/plans` | 401 | 422 | 409 | 409 | 409 | 404 | đúng |
| `GET /api/v1/insights/plans/basis` | 401 | 422 | 422 | 422 | 422 | 404 | đúng |
| `DELETE /api/v1/insights/plans/current` | 401 | 404 | 204 | 204 | 204 | 404 | đúng |
| `GET /api/v1/insights/plans/current` | 401 | 404 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/plans/history` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/plans/{plan_id}` | 401 | 404 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/watches` | 401 | 200 | 200 | 200 | 200 | 404 | đúng |
| `POST /api/v1/insights/watches` | 401 | 201 | 403 | 201 | 201 | 404 | đúng |
| `DELETE /api/v1/insights/watches/{watch_id}` | 401 | 404 | 403 | 404 | 204 | 404 | đúng |
| `GET /api/v1/users` | 401 | 403 | 403 | 403 | 403 | 200 | đúng |
| `DELETE /api/v1/users/me` | 401 | 204 | 204 | 204 | 204 | 204 | đúng |
| `GET /api/v1/users/me` | 401 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/users/me/preferences` | 401 | 200 | 200 | 200 | 200 | 200 | đúng |
| `PATCH /api/v1/users/me/preferences` | 401 | 200 | 200 | 200 | 200 | 200 | đúng |

| Ca ở mức database | Kết quả |
|---|---|
| Scope token của nhà A chỉ thấy dữ liệu nhà A | đạt |
| Token sai, lạ hoặc hết hạn: 0 dòng | đạt |
| Không có token: 0 dòng | đạt |
| Vai copilot không đọc được bảng gốc | đạt |
| Vai copilot không ghi được | đạt |
| Vai `wattprint_ai` chỉ đọc dữ liệu tham chiếu | đạt |

## Nhận xét trước khi sửa

- Không có ô nào để lộ dữ liệu nhà A cho chủ nhà B: mọi thao tác theo id đều trả 404.
- Khách demo đọc được; mọi thao tác thay đổi dữ liệu chung của nhà (thông tin nhà, cảnh báo, nhắc) đều 403. Những
  gì là của riêng họ vẫn làm được như thành viên: trò chuyện với Wappi, kế hoạch của mình, cài đặt, xóa tài khoản.
- Chủ nhà khác nhận 422 ở `POST /insights/plans` vì nhà B chưa có kế hoạch nên chạy tới bước kiểm dữ liệu của
  chính nhà B; các người khác nhận 409 vì đã có kế hoạch. Cả hai đều là sau bước kiểm quyền.
- Admin không đọc được dữ liệu của nhà nào; chỉ `GET /api/v1/users` là riêng của admin.
- Kế hoạch tiết kiệm của chủ nhà xem được bởi thành viên (`GET /insights/plans/{id}` 200) là chủ ý trong mã
  ("theirs or a home owner's").
- Chỗ còn thiếu so với spec chưa nằm trong bảng vì chưa có: thành viên "chỉ theo ngày" (R4.3), các thao tác chỉ
  chủ nhà được làm như xóa lịch sử, đổi thời hạn, mời và gỡ thành viên (R4.4). Bản "sau" thêm cột và dòng cho
  chúng.
