# Review Đ5 và backend Đ6 (R1, opus, một vòng, 2026-11-28)

Package từ `ebfc415` đến `7bbe5d2`. Kết luận của reviewer: sửa 1–5.

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Must | Khách demo nhận được lời mời; việc dọn khách cũ sau đó kẹt khóa ngoại, mọi lượt tạo khách mới lỗi | Từ chối tài khoản khách; việc dọn gỡ `used_by` trước |
| 2 | Must | Cảnh báo bằng truy vấn riêng chạy ở mức của nhà, người "chỉ theo ngày" đọc được giờ | Token lấy mức thấp hơn giữa nhà và người đặt |
| 3 | Must | Trang riêng tư quét mọi khối của `tb_reading` | Lọc theo series của nhà bằng chỉ mục; ghi `shortcut:` vì đọc bảng thô |
| 4 | Should | Chưa test thiết bị của người "chỉ theo ngày" | Thêm test |
| 5 | Should | Chưa test luồng trực tiếp đóng khi bị hạ mức | Thêm test |
| 6 | Minor | Cảnh báo của người đã gỡ bị gửi cho cả nhà | Cảnh báo tự đặt đã xóa thì không gửi cho ai |
| 7 | Minor | Thời hạn viết theo tháng sẽ hiện 0 ngày | Tính theo số giây |

Ruling: route trộn số ngày với số tức thời bỏ trường mịn thay vì 403 (plan-d5.md), vì 403 mất cả số ngày. Sai thì
phải thêm 403 và giao diện riêng cho người theo ngày.

Kiểm sau sửa: ruff, ranh giới mô-đun, 156 test của phần bị đụng đạt. Không chạy full suite.
