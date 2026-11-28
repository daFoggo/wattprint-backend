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

Còn mở (cần migration hoặc quyết định của chủ dự án):

| Chỗ | Vì sao còn | Hướng sửa |
|---|---|---|
| Mức theo ngày: `reading_1d.last_w` và `device_estimate_1d.last_w` của ngày đang chạy là công suất lúc này | Sửa view cần migration | view trả `last_w` chỉ khi token theo giờ |
| Mức theo giờ: `copilot_ro.alert` vẫn đưa giờ phút của cảnh báo bật/tắt thiết bị (`ts`, `at`) | Cần migration, và test cũ chủ ý giữ phút | cắt `ts` về giờ, bỏ `at` ở mức theo giờ |
| Cảnh báo cũ còn mã UUIDv7 | Dữ liệu đã có; cảnh báo hiện chưa tự xóa (`RETENTION_TIERS=false`) | bật dọn hằng đêm (hạn 400 ngày), hoặc đổi mã một lần |
| Tổng "hôm nay" (trang tổng quan, cảnh báo `today_kwh`) hỏi liên tục cho ra đường cộng dồn trong ngày | Thiết kế cho phép thành viên theo ngày xem số hôm nay | chấp nhận, hoặc chỉ cập nhật theo giờ |
| Hội thoại cũ của thành viên bị hạ xuống "theo ngày" vẫn mở được, câu trả lời cũ có thể nêu giờ | Xóa thì mất hội thoại của họ | ẩn biểu đồ theo giờ trong hội thoại cũ |

Bổ sung 28/11: ở mức theo ngày, hai view theo ngày không còn trả `last_w` (công suất đang dùng); revision
`e7a3c91b5d40`, test `tests/db/test_roles.py::test_a_daily_token_sees_days_not_hours`.
