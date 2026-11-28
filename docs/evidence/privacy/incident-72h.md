# Xử lý sự cố dữ liệu trong 72 giờ (bản nháp)

Ngày 28/11/2026. Chưa diễn tập. **Căn cứ pháp lý dưới đây chép từ
[legal.md](../../work/2026-11-28-privacy-load-data/legal.md), đọc từ bản chép trên web, CHƯA ĐỐI CHIẾU CÔNG BÁO,
không phải tư vấn pháp lý.** Chỗ `[ĐIỀN: …]` phải do người chịu trách nhiệm điền.

## Căn cứ

Luật 91/2025/QH15 Điều 23 và Nghị định 356/2025/NĐ-CP Điều 28: báo cơ quan chuyên trách trong 72 giờ với vi phạm
thuộc diện luật định (chưa đối chiếu Công báo). Diện nào phải báo, mẫu và nội dung báo cáo: `[ĐIỀN sau khi đọc bản gốc]`.

## Vai trò

| Việc | Người |
|---|---|
| Chịu trách nhiệm dữ liệu, quyết định có báo cơ quan không | `[ĐIỀN]` |
| Xử lý kỹ thuật | `[ĐIỀN]` |
| Người thay khi vắng | `[ĐIỀN]` |
| Cơ quan chuyên trách và kênh nộp | `[ĐIỀN]` |

## Các bước

Giờ 0 là lúc phát hiện. Các mốc 1, 24, 48 giờ là mốc nội bộ đề xuất, không phải mốc luật.

**Trong 1 giờ: ghi nhận và giữ bằng chứng**

1. Ghi: lúc phát hiện, ai phát hiện, dấu hiệu, hệ thống liên quan.
2. Lưu ngay log của các container. Sự kiện đăng nhập Keycloak chỉ giữ 7 ngày, `tb_outbound_log` chỉ giữ 90 ngày:
   xuất ra nơi chỉ người xử lý đọc được.

**Trong 24 giờ: chặn**

3. Theo đúng đường bị lộ (mỗi lần đổi biến phải tạo lại container; dev và prod dùng chung `api`):

| Đường lộ | Cách chặn |
|---|---|
| Khóa OpenRouter, AstralX, OpenWeather, Telegram | Thu hồi ở nhà cung cấp, đặt khóa mới hoặc để trống |
| text2sql | Đổi `TEXT2SQL_SERVICE_KEY` ở cả hai bên; dừng dịch vụ nếu cần |
| Tài khoản bị chiếm | Khóa người dùng và hủy phiên trong Keycloak; token truy cập còn hiệu lực tới 15 phút |
| Mật khẩu database, bí mật client, SMTP | Đổi và tạo lại container |
| Lỗi mã làm lộ chéo | Dừng route hoặc dịch vụ, sửa, thêm test vào `tests/test_permissions.py` |

**Trong 48 giờ: đánh giá**

4. Xác định: loại dữ liệu (số điện theo phút/giờ/ngày, trò chuyện, email, âm thanh), số nhà và số người, khoảng thời
   gian, bên đã nhận. `tb_outbound_log` cho biết bên nhận và loại dữ liệu, không có nội dung. Không có nhật ký ai đã
   đọc database, nên chỗ không xác định được thì ghi "không xác định".

**Trước 72 giờ: báo**

5. Người chịu trách nhiệm quyết định và ghi lý do, kể cả khi không báo. Chưa đủ thông tin thì không đợi quá hạn.
6. Báo người bị ảnh hưởng: `[ĐIỀN: khi nào bắt buộc, kênh gửi]`. Hệ thống chưa có chức năng gửi thông báo hàng loạt.
7. Yêu cầu bên nhận xóa dữ liệu đã tới tay họ, ghi lại trả lời.

**Sau sự cố:** ghi nguyên nhân, việc sửa; cập nhật [threats.md](threats.md) và hồ sơ đánh giá tác động.

## Nội dung ghi cho mỗi sự cố

Thời điểm xảy ra và phát hiện; mô tả; loại và lượng dữ liệu; số người; hậu quả có thể; việc đã làm; đầu mối liên hệ
`[ĐIỀN]`; quyết định báo hay không và lý do.

## Bản nháp đầu vào cho hồ sơ đánh giá tác động

Theo legal.md (**chưa đối chiếu Công báo**): đánh giá tác động xử lý (Luật 21, 22; NĐ 19, 20; Mẫu 10) và chuyển ra
nước ngoài (Luật 20; NĐ 17, 18; Mẫu 09, có sơ đồ luồng dữ liệu), nộp trong 60 ngày. Đây là thông tin đầu vào, không
theo bố cục của mẫu (chưa đọc mẫu). Còn bỏ ngỏ: dữ liệu điện có phải dữ liệu nhạy cảm không; có được miễn không.

| Mục | Hiện trạng theo mã |
|---|---|
| Bên kiểm soát, người phụ trách, liên hệ | `[ĐIỀN]` |
| Ngày bắt đầu xử lý, ngày chuyển ra nước ngoài đầu tiên | `[ĐIỀN]` |
| Có người dùng thật ngoài demo không, số chủ thể | `[ĐIỀN]` |
| Hồ sơ đã nộp trước đây | `[ĐIỀN]` |
| Mục đích | Theo dõi điện, tách thiết bị, hóa đơn, dự báo, cảnh báo, trợ lý hỏi đáp |
| Chủ thể | Chủ nhà, người thân được mời, khách demo |
| Loại dữ liệu | Email, họ tên; thông tin nhà; số đo khoảng 10 giây và các tổng; ước tính thiết bị, lượt bật/tắt; trò chuyện, âm thanh đọc; đồng ý, nhật ký gửi ngoài |
| Thời hạn lưu | Thô 30 ngày, phút 90, giờ 400, ngày 800, lượt bật/tắt 90 (áp 28/11/2026); bảng thường dọn hằng đêm (cảnh báo 400 ngày, chi tiết tra cứu 30, nhật ký xử lý 90). Chi tiết: [database-design.md](../../database-design.md) |
| Bên nhận và nước | OpenRouter (ngoài Việt Nam); AstralX `[ĐIỀN nơi đặt máy chủ]`; OpenWeather, Telegram, Google `[ĐIỀN]`; SMTP `[ĐIỀN nhà cung cấp prod]` (dev: Mailpit cục bộ) |
| Thỏa thuận với bên xử lý | `[ĐIỀN]` |
| Đồng ý | Theo mục đích `wappi`, `voice`, `email`; chặn khi chưa đồng ý (bật trên prod); chưa có đồng ý riêng cho việc thu số đo trong các mục đích này |
| Quyền của chủ thể | Xem, xóa lịch sử điện và trò chuyện, xóa tài khoản, rút đồng ý. Chưa có xuất dữ liệu |
| Biện pháp, rủi ro còn lại | [threats.md](threats.md), [bằng chứng chung](../privacy.md) |
| Mã hóa khi lưu, sao lưu, TLS prod | `[ĐIỀN sau khi kiểm máy prod]` |
| Sơ đồ luồng dữ liệu | [privacy-data-flow.svg](../../diagrams/privacy-data-flow.svg) |
