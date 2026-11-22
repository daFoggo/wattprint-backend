# Watch: cảnh báo do người dùng tự đặt bằng giọng nói

Ngày 2026-11-20. Người dùng nói với Wappi "khi nào tiền điện tháng này trên 1 triệu báo tôi nhé", Wappi hiểu,
lưu thành một watch, worker kiểm tra định kỳ và báo khi vượt ngưỡng.

Nguồn đã đọc: `docs/architecture/README.md`, `docs/database-design-guide.md` (3.4 quyền Copilot, 5.5, 5.6),
plan `2026-11-19-real-dashboard-apis.md`, skill `fastapi`, `supabase-postgres-best-practices`; code `copilot`
(tools, chat, voice), `insight` (worker, jobs, detectors, mail), text2sql `schema_text2sql.py`,
`source_query_repository.py`; web `features/insight`.

## 1. Quyết định (đã chốt với người dùng)

- Không dùng Airflow. Mỗi yêu cầu là một dòng `tb_watch` có `next_check_at`; một job trong worker `insight`
  chạy mỗi 60 s, lấy watch đến hạn bằng `FOR UPDATE SKIP LOCKED` (chạy nhiều worker không trùng).
- Kênh báo: alert trên dashboard (`tb_alert`, kind `watch_hit`) và mail (job `mail` sẵn có), chỉ gửi người tạo.
- Báo một lần rồi watch chuyển `fired`.
- Lưu luôn, Wappi đọc lại cách hiểu kèm giá trị hiện tại; sai thì người dùng huỷ.
- Tần suất do hệ thống đặt theo chỉ số. Job `mail` chuyển từ 300 s xuống 60 s để mail đến trong vòng một phút sau
  khi watch vượt ngưỡng (job rẻ: một truy vấn alert chưa gửi).
- Kiểm chứng 2026-11-20 trên app thật (đăng nhập, chat với Wappi): đặt cảnh báo tiền điện, câu tự do qua text2sql
  (bị từ chối vì đã vượt ngưỡng, đúng thiết kế), liệt kê cảnh báo; ép vượt ngưỡng thì worker tạo alert trên
  dashboard và mail chỉ người tạo (nhà có 4 thành viên).

## 2. Luồng

```
voice → transcribe → copilot chat → LLM gọi create_watch(metric|question, op, threshold, ends_on?)
   metric có sẵn  → tính bằng billing/energy service
   question       → text2sql /chat → SQL của bước cuối chạy sạch
                    → chạy thử bằng role wattprint_copilot_ro, phải ra đúng 1 dòng, cột đầu là số
   → lưu tb_watch, trả giá trị hiện tại → Wappi đọc lại
worker insight, job "watches" mỗi 60 s: watch đến hạn → tính → so ngưỡng
   → vượt: tb_alert(kind=watch_hit, dedup_key=watch:{id}), watch = fired → job mail gửi người tạo
```

Không thêm endpoint `/compile` cho text2sql: `/chat` đã trả SQL từng bước (`answers[].steps[].sql`).

## 3. Chỉ số

| metric | Giá trị | Đơn vị | Kiểm tra mỗi | Hết hạn mặc định |
|---|---|---|---|---|
| `bill_vnd` | `current_bill.amount_total` (kỳ đang chạy, gồm VAT) | vnd | 1 h | cuối kỳ |
| `bill_kwh` | `current_bill.kwh` | kwh | 1 h | cuối kỳ |
| `forecast_vnd` | `forecast_bill.amount` | vnd | 1 h | cuối kỳ |
| `today_kwh` | kWh công tơ tổng hôm nay | kwh | 10 phút | nửa đêm |
| `power_w` | `latest_power.watts` | w | 1 phút | 30 ngày |
| `device_kwh_today` | kWh ước tính của một thiết bị hôm nay | kwh | 10 phút | nửa đêm |
| `sql` | cột đầu của dòng duy nhất | do LLM ghi | 10 phút | 30 ngày |

`ends_on` do người dùng nói thì ghi đè, tối đa 90 ngày. "Tháng này" về tiền điện là kỳ hoá đơn.

## 4. Dữ liệu

`public.tb_watch`: `id uuidv7`, `user_id → tb_users CASCADE`, `home_id → tb_home CASCADE`,
`device_id → tb_device CASCADE` *null*, `metric`, `label` (người dùng đọc), `sql_text` *null*, `op` (`gt`/`lt`),
`threshold numeric(14,3)`, `unit`, `every_s int`, `ends_at`, `next_check_at`, `status`
(`active/fired/expired/cancelled/broken`), `last_value numeric(14,3)` *null*, `last_checked_at` *null*,
`fails smallint`, `fired_at` *null*, `utterance`, `created_at`.

CHECK: `metric` trong danh sách; `(metric = 'sql') = (sql_text IS NOT NULL)`;
`(metric = 'device_kwh_today') = (device_id IS NOT NULL)`; `every_s >= 60`. Index một phần
`(next_check_at) WHERE status = 'active'`, index `(home_id, user_id)`. Tối đa 10 watch `active` mỗi người mỗi nhà.
Quyền: DML cho `wattprint_app`; `wattprint_copilot_ro` không đọc (bảng chứa SQL).

`tb_alert.kind` thêm `watch_hit`; payload `{watch_id, label, value, threshold, op, unit}`.

## 5. An toàn của SQL lưu lâu dài

- Chạy trên kết nối **đăng nhập bằng `wattprint_copilot_ro`** (`COPILOT_DATABASE_URL`), không phải
  `SET ROLE` trên kết nối superuser (một `set_config('role', …)` trong SELECT sẽ lấy lại quyền).
- Mỗi lần chạy: scope token mới (xoá ngay sau đó), `SET TRANSACTION READ ONLY`, token đặt bằng bind parameter
  `is_local = true`, `statement_timeout` 5 s của role.
- Lỗi 3 lần liên tiếp → `broken`, tạo alert báo người tạo để đặt lại.

## 6. API và giao diện

- `GET /insights/watches` (của người dùng trong nhà, đang chạy trước), `DELETE /insights/watches/{id}` (huỷ).
- Tool copilot `create_watch`, `list_watches`, `cancel_watch`.
- Web: thêm `watch_hit` vào schema alert, câu chữ vi/en. Màn hình quản lý watch để sau.

## 7. Các bước (audit sau mỗi bước)

1. Migration + model + test quyền.
2. Service watch (tính, chạy thử SQL, tạo/huỷ/kiểm tra) + job worker + mail + test.
3. Tool copilot + prompt + test.
4. Route + web alert + tự kiểm tra trên trình duyệt khi đăng nhập.
