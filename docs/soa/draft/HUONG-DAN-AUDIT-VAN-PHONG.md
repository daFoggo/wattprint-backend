# Hướng dẫn cho agent audit và viết lại văn phong báo cáo SOA WattPrint

Bạn nhận một báo cáo bài tập lớn đã đủ nội dung và đã dựng xong định dạng. Việc của bạn chỉ là **audit và sửa văn phong** cho tự nhiên, mạch lạc, đọc như người viết, không đổi kiến trúc hay số liệu.

## 1. Bối cảnh

- Môn: Phát triển phần mềm hướng dịch vụ (Service-Oriented Architecture), INT1448-20261-01, Nhóm 6, giảng viên Nguyễn Việt Dũng.
- Đề: WattPrint, hệ thống theo dõi điện năng gia đình (NILM tách tải thiết bị, insight, Energy Copilot trả lời bằng ngôn ngữ tự nhiên). Báo cáo chỉ gồm từ bài toán đến phân tích chốt kiến trúc: 4 service (core, nilm, insight, copilot), Envoy gateway, Keycloak, RabbitMQ, một PostgreSQL 18 + TimescaleDB + pgvector với 5 database, transactional outbox/inbox, saga, C4 mức 1 đến 3.
- Đề bài gốc: `C:\Users\Foggo\Downloads\bai-tap-lon-yeu-cau-gui-sinh-vien_1.docx` (đọc để biết giảng viên chấm gì).
- Người đọc: giảng viên môn SOA và bạn học. Cần dễ hiểu, không quá kỹ thuật.

## 2. File cần đọc, theo thứ tự

Gốc repo: `D:\Dev_Projects\project-wattprint\wattprint-fastapi`

1. `docs/soa/draft/README.md`: cấu trúc thư mục, cách dựng lại.
2. `docs/soa/draft/content.py`: **toàn bộ chữ của báo cáo nằm ở đây** (REFS, ABBR, SUMMARY, KEYWORDS, BODY). Đây là file duy nhất bạn sửa.
3. `docs/soa/BaoCao-SOA-WattPrint.pdf`: bản đã dựng, để đọc liền mạch như người đọc thật.
4. Nguồn sự thật để đối chiếu khi cần kiểm chứng một câu: `docs/architecture/README.md`, `docs/PROJECT_CONTEXT.md`, `docs/WattPrint Pitch Deck.md`, `docs/database-design.md`, `docs/keycloak-auth.md`, `docs/superpowers/plans/2026-11-10-microservices-split.md`.
5. Chỉ đọc `docs/soa/draft/build_report.py` nếu cần hiểu markup hoặc lỗi dựng. Không sửa.

## 3. Quy tắc đã chốt với người dùng (bắt buộc giữ)

**Văn phong**
- Ngắn gọn, súc tích, nhưng không cụt ngủn. Các câu và các phần phải liên kết nhau bằng ý, có chuyển ý tự nhiên.
- Trộn đoạn văn, ý ngắn và danh sách cho tự nhiên. Không dùng dấu `;` để liệt kê ý.
- Tiếng Việt kèm thuật ngữ tiếng Anh phổ biến của SOA (service, gateway, event, saga, outbox, idempotent, ...), không dịch gượng.
- Chỉ giữ thông tin hữu ích. Câu nào bỏ đi mà người đọc không thiếu gì thì bỏ.
- Xưng **"Nhóm"**, tuyệt đối không "chúng tôi", "chúng em". Giọng là nhóm đề xuất và chọn giải pháp, không viết như AI đang tư vấn cho người dùng.
- Tránh dấu hiệu văn AI (tham khảo https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing#Content), với tiếng Việt cụ thể:
  - Câu mở đầu tuyên bố ý nghĩa ("đóng vai trò quan trọng", "không chỉ... mà còn...", "trong bối cảnh...") và câu kết tổng kết sáo rỗng.
  - Cấu trúc ba ý đều đặn, cụm tính từ hoa mỹ ("toàn diện", "mạnh mẽ", "linh hoạt", "tối ưu", "đột phá") khi không có số liệu đi kèm.
  - Gạch đầu dòng có tiêu đề in đậm rồi dấu hai chấm lặp lại mọi mục, đoạn nào cũng cùng nhịp và độ dài câu.
  - Dấu gạch ngang dài (—), lặp từ nối ("Ngoài ra", "Bên cạnh đó", "Hơn nữa") dày đặc.
  - Khẳng định chung chung không có căn cứ trong dự án.
- Không hedge ("có thể", "có lẽ") với điều đã quyết. Nêu rõ lý do chọn và đánh đổi.
- Không dùng chữ "mock" trong phần kiến trúc.

**Kỹ thuật, không được đổi**
- Số liệu, tên service, tên bảng, tên queue, luồng (copilot → insight → core → nilm), các business rule BR1 đến BR9, mã hình và bảng.
- Không thêm tuyên bố mới không có trong các file nguồn ở mục 2. Muốn thêm thì phải tìm được căn cứ trong nguồn.
- Không xóa trích dẫn `[@key]`. Có thể di chuyển nếu câu đổi chỗ, miễn nó vẫn đứng cạnh câu nó chứng minh.

## 4. Markup trong content.py (giữ nguyên cú pháp)

- `**đậm**`, `//nghiêng//`, `` `code` ``, `[@key]` là trích dẫn tự đánh số theo thứ tự xuất hiện đầu tiên.
- Các block trong BODY: `"h1","h2","h3","p","ul","ol","table","fig"`. Không đổi loại block, không đổi tên key của hình, bảng.
- Chuỗi Python: cẩn thận dấu nháy và ký tự `\`. Sau khi sửa phải chạy được `python -c "import content"`.

## 5. Quy trình làm

1. Đọc PDF một lượt từ đầu đến cuối như người đọc, ghi lại chỗ nghe máy móc, lặp, đứt mạch.
2. Sửa trong `content.py` theo từng chương. Ưu tiên: Tóm tắt, Chương 1, mở đầu và kết mỗi mục lớn của Chương 3, Chương 4. Bảng chỉ sửa chữ trong ô cho rõ, giữ cấu trúc.
3. Mỗi đoạn tự hỏi: đoạn này trả lời câu hỏi gì của người đọc, có nối được với đoạn trước không, có câu nào chỉ để cho đủ chữ không.
4. Giữ độ dài tổng gần như cũ (hiện 32 trang, đề yêu cầu tối thiểu 30). Cắt chữ sáo rỗng thì không được kéo tụt dưới 30 trang. Nếu hụt, bổ sung nội dung có căn cứ chứ không độn chữ.
5. Dựng lại và kiểm tra (xem mục 6). Không sửa tay trong file docx vì lần dựng sau sẽ ghi đè.

## 6. Dựng lại và kiểm chứng

Chạy trong `docs/soa/draft`:

```bash
rm -f build/raw.docx ../BaoCao-SOA-WattPrint.docx ../BaoCao-SOA-WattPrint.pdf
PYTHONIOENCODING=utf-8 python build_report.py nguon/ref_style.docx nguon/template.docx build/raw.docx
powershell -File update_fields.ps1
```

(Xem `README.md` nếu đường dẫn đầu ra khác. Script Word COM cập nhật mục lục, số hình, số bảng và xuất PDF, in ra số trang.)

Sau khi dựng, tự kiểm và báo kết quả thật:
- Số trang ≥ 30, tất cả trang khổ dọc, không có trang ngang.
- `grep -c "chúng tôi"`, `grep -c "mock"`, số dấu `;` trong văn xuôi, dấu "—": đều 0.
- Tham chiếu "Hình x.y", "Bảng x.y", "mục x.y" trong chữ khớp với số thật trong PDF. Đủ 16 trích dẫn, không mồ côi.
- Đọc lại PDF các trang đã sửa, xem layout không vỡ (bảng không tràn, hình không bị đẩy trống nửa trang).

## 7. Không làm

- Không sửa kiến trúc, sơ đồ Excalidraw, `build_report.py`, các file trong `nguon/`.
- Không thêm mục khai báo sử dụng AI, không thêm ghi chú kiểu "AI đề xuất".
- Không commit, không push, không thêm attribution.
- Không viết các chương chưa có (API, độ tin cậy có số liệu, triển khai, đánh giá). Nếu thấy văn phong của phần hiện có phụ thuộc vào các chương đó thì ghi lại ở báo cáo cuối, không tự viết.

## 8. Báo cáo cuối

Trả về ngắn: đã sửa những phần nào, kiểu lỗi văn phong chính tìm thấy, kết quả các lệnh kiểm ở mục 6, và những chỗ nghi ngờ về nội dung (không chắc đúng với nguồn) để người dùng quyết.
