# Review Đ3 backend (lane L): đồng ý, cửa ra chung, nhật ký

Một vòng (chủ dự án yêu cầu). `sdlc:reviewer`, opus, mode full. Package từ `11a22ed` (snapshot `d7f286f`).
Phần web review riêng trong `wattprint-web/docs/work/2026-11-28-privacy-consent-ui/`.

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Must | Tài khoản cũ chưa lưu cài đặt mất mail cảnh báo | Revision `8c1e47aa2d90` ghi `true, true` cho tài khoản chưa có dòng; chỉ tài khoản mới tắt |
| 2 | Must | 👎 gửi nội dung qua Telegram không hiện trong nhật ký của người đó | `tell_maintainers` nhận `user_id`, `home_id`; test |
| 3 | Should | Dòng thời tiết không bao giờ hiện cho ai, test dựng dữ liệu không mã nào tạo | Thời tiết chỉ mang tên tỉnh, dùng chung mọi nhà: bỏ nhánh "dòng của nhà tôi", nhật ký chỉ theo người |
| 4 | Should | Gọi qua text2sql ghi "text2sql", người dùng không biết dữ liệu tới OpenRouter | Ghi `openrouter` |
| 5 | Should | Không test lọc đồng ý `email` | Test: đồng ý, đã rút, chưa hỏi |
| 6 | Minor | Cắt 500 dòng im lặng | Tăng 5000, ghi `shortcut:` |
| 7 | Minor | Lỗi ghi nhật ký làm thời tiết trả 500 | Bắt `SQLAlchemyError`, trả 503 như lỗi OpenWeather |

Thêm sau khi chạy cả bộ: hai bảng mới có index mà không khai model → thêm `app/models/privacy.py`.

Còn mở: `consent_enforced` đang tắt (ghi trong `wattprint-web/docs/debt.md`).

Kiểm: toàn bộ 792 test qua (1 lỗi index đã sửa), 9 round trip `-m migrations` qua; sau khi sửa, 198 test các phần bị
chạm qua. Bảng thử quyền 48 thao tác khớp mong đợi.
