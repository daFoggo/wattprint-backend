# Intent: bảo vệ dữ liệu nếp sinh hoạt

Author: chủ dự án (đội thi Sáng tạo trẻ Quốc gia, lĩnh vực AI, 2026). Status: draft.
Source: "Đề cải tiến · Phiên bản 1", yêu cầu 1, nhận khi nộp sản phẩm. Record: none.
Hiện trạng đã rà: [audit.md](audit.md) (các mã A1…H trong tài liệu này trỏ về đó).

## Problem

Lời ban giám khảo: "Dữ liệu phụ tải theo giờ có thể tiết lộ lịch sinh hoạt gia đình. Giảm độ chi tiết phải
lưu/chia sẻ, giới hạn quyền truy cập và cho phép xóa lịch sử; nêu rõ khi gọi dịch vụ ngoài. Minh chứng: sơ đồ
luồng dữ liệu, màn hình quyền riêng tư và thử phân quyền."

WattPrint hiện giữ số đo khoảng 10 giây trong 400 ngày và bản tổng theo giờ mãi mãi, cho Wappi (AI bên ngoài)
đọc tới từng phút, chỉ xóa được cả tài khoản, và chỉ nêu tên dịch vụ ngoài ở trang chính sách ngoài web công khai.

## Proposed outcome

Chủ dự án: "cải thiện để điểm số tốt nhất có thể, không quan tâm đến thời gian". Nghĩa là làm đủ cả bốn ý và
ba minh chứng, không cắt phạm vi theo thời gian. Quan sát được:

1. Dữ liệu càng chi tiết thì giữ càng ngắn, và chủ nhà chọn được mức ngắn hơn.
2. Chủ nhà xóa được lịch sử điện và trò chuyện mà không phải xóa tài khoản.
3. AI bên ngoài không còn nhận số theo phút; chủ nhà hạ được xuống chỉ theo ngày, tắt được từng dịch vụ.
4. Mỗi lần dữ liệu ra ngoài đều được báo tại chỗ và ghi vào một nhật ký người dùng xem được.
5. Mời được người thân với mức xem do chủ nhà đặt; có bảng thử quyền chạy được cho mọi vai trò.
6. Một trang "Quyền riêng tư" trong Cài đặt gom các mục trên.
7. Ba minh chứng nằm trong bản nộp, và trang chính sách nói đúng những gì mã làm.

## Affected users and systems

- Chủ nhà, người thân được mời, khách xem demo (giám khảo dùng vai trò này), người bảo trì.
- `wattprint-backend` (energy, home, auth, copilot, insight, expect, alembic), `wattprint-web` (dashboard, web),
  `wattprint-text2sql-mcp` (xác thực), `submission/` (bản nộp).

## Constraints

- Khách demo vẫn xem được đầy đủ các nhà demo (dữ liệu công khai REFIT, Plegma, ENERTALK).
- Không nêu trên trang chính sách điều mã không làm; không bịa số liệu.
- Mức chắc chắn chỉ hiện Cao/Vừa/Thấp; chữ trên giao diện là tiếng Việt thường ngày.
- Prod chỉ triển khai khi chủ dự án yêu cầu; migration cần chủ repo duyệt (hook `approve`).
- Chất lượng Wappi không được giảm mà không đo: chạy lại eval một nhà, một lượt.

Ngoài phạm vi: tách thiết bị ngay tại nhà (không có phần cứng), differential privacy, mã hóa lại dữ liệu lưu,
xuất dữ liệu, nhận diện tên và địa chỉ trong câu hỏi (nợ #14 đã có), luật sư đọc chính sách, một người nhiều nhà.

## Open questions

- Áp thời hạn mới lên DB prod sẽ xóa chi tiết cũ của các nhà đang có: khi nào chạy. Chủ dự án.
- Kết nối text2sql đã lưu đăng nhập bằng vai DB nào (audit mục H). Người xây kiểm khi làm phần 4.
