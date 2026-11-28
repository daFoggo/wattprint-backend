Chạy lúc 2026-11-28 03:30 UTC, 57 thao tác API.

| Thao tác | Chưa đăng nhập | Chủ nhà khác | Khách demo | Thành viên theo ngày | Thành viên | Chủ nhà | Admin | Khớp mong đợi |
|---|---|---|---|---|---|---|---|---|
| `GET /api/v1/billing/current` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/billing/devices/forecast` | 401 | 404 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/billing/forecast` | 401 | 404 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/billing/history` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `POST /api/v1/copilot/chat` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `DELETE /api/v1/copilot/conversations` | 401 | 204 | 204 | 204 | 204 | 204 | 404 | đúng |
| `GET /api/v1/copilot/conversations` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `DELETE /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 404 | 204 | 404 | đúng |
| `GET /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 404 | 200 | 404 | đúng |
| `PATCH /api/v1/copilot/conversations/{conversation_id}` | 401 | 404 | 404 | 404 | 404 | 200 | 404 | đúng |
| `PUT /api/v1/copilot/messages/{message_id}/feedback` | 401 | 404 | 404 | 404 | 404 | 204 | 404 | đúng |
| `GET /api/v1/copilot/messages/{message_id}/speech` | 401 | 404 | 404 | 404 | 404 | 200 | 404 | đúng |
| `POST /api/v1/copilot/voice/transcribe` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/demo/homes` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `POST /api/v1/demo/homes/{key}/guest` | 403 | 403 | 403 | 403 | 403 | 403 | 403 | đúng |
| `POST /api/v1/demo/homes/{key}/view` | 401 | 404 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/energy/activity` | 401 | 200 | 200 | 403 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/devices` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/devices/{device_id}` | 401 | 404 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/overview` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/series` | 401 | 200 | 200 | 200 (theo ngày) | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/stream` | 401 | 200 | 200 | 403 | 200 | 200 | 404 | đúng |
| `GET /api/v1/energy/weather` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/expected` | 401 | 200 | 200 | 403 | 200 | 200 | 404 | đúng |
| `GET /api/v1/health` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/homes/current` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `PATCH /api/v1/homes/current` | 401 | 200 | 403 | 403 | 403 | 200 | 404 | đúng |
| `DELETE /api/v1/homes/current/history` | 401 | 204 | 403 | 403 | 403 | 204 | 404 | đúng |
| `POST /api/v1/homes/current/invites` | 401 | 201 | 403 | 403 | 403 | 201 | 404 | đúng |
| `GET /api/v1/homes/current/members` | 401 | 200 | 403 | 200 | 200 | 200 | 404 | đúng |
| `DELETE /api/v1/homes/current/members/{user_id}` | 401 | 404 | 403 | 403 | 403 | 204 | 404 | đúng |
| `PATCH /api/v1/homes/current/members/{user_id}` | 401 | 404 | 403 | 403 | 403 | 204 | 404 | đúng |
| `DELETE /api/v1/homes/current/membership` | 401 | 403 | 403 | 204 | 204 | 403 | 404 | đúng |
| `GET /api/v1/homes/current/privacy` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `POST /api/v1/homes/invites/accept` | 401 | 404 | 404 | 404 | 404 | 404 | 404 | đúng |
| `GET /api/v1/homes/provinces` | 200 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/insights/alerts` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `PATCH /api/v1/insights/alerts/{alert_id}` | 401 | 404 | 403 | 204 | 204 | 204 | 404 | đúng |
| `POST /api/v1/insights/alerts/{alert_id}/feedback` | 401 | 404 | 403 | 204 | 204 | 204 | 404 | đúng |
| `GET /api/v1/insights/cohort` | 401 | 404 | 404 | 404 | 404 | 404 | 404 | đúng |
| `POST /api/v1/insights/plans` | 401 | 422 | 409 | 409 | 409 | 409 | 404 | đúng |
| `GET /api/v1/insights/plans/basis` | 401 | 422 | 422 | 422 | 422 | 422 | 404 | đúng |
| `DELETE /api/v1/insights/plans/current` | 401 | 404 | 204 | 204 | 204 | 204 | 404 | đúng |
| `GET /api/v1/insights/plans/current` | 401 | 404 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/plans/history` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/plans/{plan_id}` | 401 | 404 | 200 | 200 | 200 | 200 | 404 | đúng |
| `GET /api/v1/insights/watches` | 401 | 200 | 200 | 200 | 200 | 200 | 404 | đúng |
| `POST /api/v1/insights/watches` | 401 | 201 | 403 | 201 | 201 | 201 | 404 | đúng |
| `DELETE /api/v1/insights/watches/{watch_id}` | 401 | 404 | 403 | 404 | 404 | 204 | 404 | đúng |
| `GET /api/v1/users` | 401 | 403 | 403 | 403 | 403 | 403 | 200 | đúng |
| `DELETE /api/v1/users/me` | 401 | 204 | 204 | 204 | 204 | 204 | 204 | đúng |
| `GET /api/v1/users/me` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/users/me/consents` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `PUT /api/v1/users/me/consents/{purpose}` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/users/me/outbound` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `GET /api/v1/users/me/preferences` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |
| `PATCH /api/v1/users/me/preferences` | 401 | 200 | 200 | 200 | 200 | 200 | 200 | đúng |

| Ca ở mức database | Kết quả |
|---|---|
| Scope token của nhà A chỉ thấy dữ liệu nhà A | đạt |
| Token sai, lạ hoặc hết hạn: 0 dòng | đạt |
| Không có token: 0 dòng | đạt |
| Vai copilot không đọc được bảng gốc | đạt |
| Vai copilot không ghi được | đạt |
| Vai `wattprint_ai` chỉ đọc dữ liệu tham chiếu | đạt |
