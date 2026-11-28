# Review Đ1 (lane M): bảng thử quyền, bản "trước"

Một vòng (chủ dự án yêu cầu). `sdlc:reviewer`, sonnet, mode full. Package `review-package.mjs 2c297f9 --since
051aa2d` (snapshot `9ba33ee`), gồm cả mấy sửa nhỏ sau review Đ0. Kết luận: fix 1.

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Should | Ô kế hoạch của khách demo và thành viên (422 ở tạo, 404 ở `plans/current`) do thiếu dữ liệu, không phải kiểm quyền; câu "mọi thao tác thay đổi nhà đều 403" sai với bảng | Thành viên và khách demo có kế hoạch riêng trong dữ liệu mẫu: tạo 409, xem 200, xóa 204 của chính họ. Viết lại nhận xét: chỉ dữ liệu chung của nhà bị 403; việc của riêng mình vẫn làm được |
| 2 | Minor | Script in bảng im lặng khi pytest lỗi; file tạm rò khi có lỗi | Thoát mã khác 0 khi số dòng ít hơn số ô chạy; `try/finally` xóa file tạm |

Kiểm: `tests/test_permissions.py` 46 pass; script in 45 dòng, 45 "đúng", 6 ca database "đạt".
