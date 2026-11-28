# Review Đ2 (lane L): giảm chi tiết gửi AI

Một vòng (chủ dự án yêu cầu). `sdlc:reviewer`, opus, mode full, một reviewer cho hai repo.

| Repo | Base | Snapshot R1 |
|---|---|---|
| wattprint-backend | `9886d8e` | `11a22ed` |
| wattprint-text2sql-mcp | `000c681` | `5d80cdb` |

| # | Mức | Phát hiện | Xử lý |
|---|---|---|---|
| 1 | Must | Cảnh báo `odd_hour` để giờ bắt đầu trong `value`; mức `daily` vẫn lộ giờ chạy thiết bị | Bỏ `value` khi `signal = odd_hour` ở công cụ `alerts` và ở view `copilot_ro.alert` (revision mới `5a085853fca0`, vì `5f7ab6bb083c` đã áp) |
| 2 | Must | Nhắc tùy chỉnh viết trên `_1h` ở nhà `daily` lưu được nhưng không bao giờ báo | `run_sql` báo `needs_hourly` khi token `daily` mà SQL đọc view theo giờ: tạo nhắc thì Wappi nói rõ, nhắc cũ thành `broken` và báo người dùng |
| 3 | Should | Không có test cho giờ nằm trong `value` | Test công cụ và test view có payload `odd_hour` |
| 4 | Minor | `JevReranker` của text2sql thiếu cờ ZDR | Thêm `provider` + test |
| 5 | Minor | `read_home` dùng `hasattr` có thể giấu lỗi đổi tên cột | Loại trừ rõ hai trường tính ra |

Thêm ngoài review, phát hiện khi trả lời chủ dự án: nhắc tùy chỉnh dùng token mặc định `daily` cho mọi nhà → sửa
lấy mức của nhà; mô tả công cụ `query_data` còn hứa "lượt chạy thiết bị" → sửa; ở `daily` câu trả lời của
text2sql thêm `detail_note` để Wappi nói vì sao thiếu số theo giờ.

Kiểm: test vai và round trip `-m migrations` pass; text2sql `verify.sh` xanh; metadata text2sql đồng bộ lại còn 12
view, Qdrant 12 bảng/114 cột, không tri thức nào còn trỏ tới đối tượng đã bỏ. Thử thật: cùng một câu hỏi theo giờ,
mức `hourly` trả 12:00, mức `daily` không đọc được số theo giờ.
