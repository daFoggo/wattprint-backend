Thử phá các chốt bảo vệ dữ liệu (Đ9-1, Đ9-4, Đ9-5), 2026-11-28. Mã thử: `tests/test_privacy_attacks.py`
(mọi lời gọi ra ngoài đều giả lập, chạy trên database thử). Bảng thử quyền theo route ở
[permission-matrix-after.md](permission-matrix-after.md).

| Đã thử | Kết quả | Test |
|---|---|---|
| SQL của Wappi đổi scope token sang mã nhà khác hoặc một mã đoán bừa | Không thấy dòng nào | `test_sql_cannot_switch_to_another_home_or_steal_its_token` |
| Đọc token của phiên nhà khác qua `pg_stat_activity` | Không có: token đi dưới dạng tham số | như trên |
| Đọc thẳng bảng token, bảng thiết bị, số theo phút, lượt chạy thiết bị | Bị từ chối (permission denied) | như trên |
| Cảnh báo tự đặt chạy câu lệnh xóa, nối thêm câu lệnh, `WITH ... DELETE` | Bị từ chối, dữ liệu nhà khác còn nguyên | `test_a_custom_watch_cannot_write` |
| Nhà "theo ngày": viết tên view theo giờ kiểu khác (`U&"reading\005f1h"`) để lọt qua kiểm tra tên | Lọt qua kiểm tra tên nhưng view trả 0 dòng; theo ngày vẫn đọc được | `test_a_daily_home_reads_no_hour_even_past_the_name_check` |
| Thành viên "theo ngày" đọc giờ của cảnh báo từ mã cảnh báo (mã UUIDv7 chứa thời điểm tạo) | **Lỗ, đã vá**: cảnh báo mới dùng mã ngẫu nhiên, API và SQL không suy ra được giờ | `test_an_alert_id_does_not_tell_its_time` |
| Wappi "theo ngày": hỏi "hôm nay so với hôm qua đến giờ này" mỗi giờ một lần để dựng lại từng giờ | **Lỗ, đã vá**: ở mức theo ngày Wappi không so phần của một ngày, so kỳ thì chỉ tính những ngày đã qua hết | `test_wappi_at_daily_does_not_compare_part_of_a_day` |
| Người bị gỡ và người tự rời nhà dùng lại phiên cũ, chờ email cảnh báo và tóm tắt tuần | Không đọc được gì (404), không nhận email nào; chủ nhà vẫn nhận | `test_a_removed_or_departed_member_gets_nothing_more` |
| Email cảnh báo các loại (bật/tắt thiết bị, chạy giờ lạ, dùng cao bất thường...) có ghi giờ | **Lỗ, đã vá**: trước ghi "lúc 06:42", "lúc 6 giờ", "Từ 14:00"; nay không email nào ghi giờ, giờ xem trong ứng dụng | `test_an_alert_mail_names_no_clock_time` |
| Lời gọi ghi log in ra token, mật khẩu, email, câu hỏi, nội dung phản hồi | Quét toàn bộ `app/`: không còn chỗ nào | `test_no_log_call_prints_a_token_or_personal_data` |
| Keycloak từ chối tạo khách demo, log in nguyên nội dung trả về (có email) | **Lỗ, đã vá**: chỉ ghi mã trạng thái | `test_a_keycloak_refusal_logs_no_response_body` |

Còn mở:

| Chỗ | Vì sao còn | Hướng sửa |
|---|---|---|
| Người "theo ngày": số hôm nay của từng thiết bị, tiền điện hôm nay (`/energy/devices`, `/billing/current`, cảnh báo `bill_*`) vẫn chạy liên tục | Đọc ô ngày của `*_1d`, chưa cắt theo mốc 6 giờ | đọc phần hôm nay từ `*_1h` tới `daily_now` |

Đã vá 28/11 (trước là "còn mở"):

| Chỗ | Cách vá | Test |
|---|---|---|
| Mức theo giờ: `copilot_ro.alert` và công cụ `alerts` của Wappi đưa giờ phút của cảnh báo (`ts`, `at`) | View cắt `ts` về giờ, bỏ `at` (revision `b7d3e1a9c625`); công cụ làm như view | `tests/db/test_roles.py::test_a_daily_token_sees_days_not_hours`, `tests/test_copilot_tools.py::test_at_daily_alerts_give_the_day_only` |
| Cảnh báo cũ còn mã UUIDv7 | Đổi một lần sang mã ngẫu nhiên, giữ phản hồi, gợi ý, nhật ký mail trỏ đúng; mặc định cột là `gen_random_uuid()` (revision `a4f9c2e7b318`) | `tests/db/test_domain_tables.py::test_old_alerts_get_random_ids_and_keep_what_points_at_them` |
| Tổng "hôm nay" hỏi liên tục cho ra đường cộng dồn trong ngày | Người "theo ngày": tổng hôm nay và cảnh báo `today_kwh`, `device_kwh_today` tính tới mốc 6 giờ gần nhất (0, 6, 12, 18 giờ); `/energy/series` chỉ trả những ngày đã qua | `tests/test_energy_api.py::test_a_daily_member_reads_today_as_of_the_last_6_hour_block`, `test_a_daily_member_gets_the_series_by_day_only` |
| Hội thoại cũ của thành viên bị hạ xuống "theo ngày" vẫn mở được | Hạ xuống "theo ngày" xóa trò chuyện của người đó ở nhà này, như khi gỡ; màn đổi mức báo trước | `tests/test_members.py::test_cutting_a_member_to_daily_deletes_their_chats_here` |

Bổ sung 28/11: ở mức theo ngày, hai view theo ngày không còn trả `last_w` (công suất đang dùng); revision
`e7a3c91b5d40`, test `tests/db/test_roles.py::test_a_daily_token_sees_days_not_hours`.
