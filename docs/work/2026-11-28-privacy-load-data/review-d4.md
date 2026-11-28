# Review Đ4 (R1, opus, một vòng, 2026-11-28)

Base `d7f286f`, snapshot `44c71a2`. Kết luận của reviewer: sửa 1, 2, 3.

| # | Mức | Lỗi | Đã sửa |
|---|---|---|---|
| 1 | Must | Xóa cả kế hoạch tiết kiệm theo ngày tạo: mất kế hoạch đang chạy, còn số của ngày đã xóa | Giữ kế hoạch, bỏ `days` trước mốc; ghi thêm vào spec R2.1 |
| 2 | Should | Việc hằng đêm viết lại dự đoán của ngày đã xóa | `refresh_home` không tính trước `history_erased_before` |
| 3 | Should | Chưa chứng minh số tổng hợp của nhà khác còn khi số thô đã hết hạn | Thêm test |
| 4 | Minor | Test thiếu bản tổng hợp `device_estimate_1h` | Đủ 6 bản |
| 5 | Minor | Hai nơi tự đọc file nhà demo | `app/common/demo.py` |
| 6 | Minor | Tính `min(cut, now)` hai lần | Một biến |
| 7 | Minor | Ba lệnh xóa chạy trên bảng trống trong test | Seed một dòng mỗi phía mốc |

Kiểm sau sửa: ruff, ranh giới mô-đun, 171 test của các phần bị đụng đạt. Không chạy full suite theo yêu cầu.

Reviewer không xét: lô công tơ gửi lại đúng lúc đang xóa vẫn có thể lọt (cửa sổ hẹp). Reviewer cũng báo đã chạy một
câu `SELECT` chỉ đọc trên DB dev, trái chỉ dẫn; không ghi gì.
