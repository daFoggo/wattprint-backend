# Thư mục nháp của báo cáo SOA

File chính: `../BaoCao-SOA-WattPrint.docx` (và bản PDF cùng tên). Mọi thứ trong thư mục này là phần phụ.

| Mục | Dùng để |
|---|---|
| `content.py` | Toàn bộ nội dung báo cáo (chữ, bảng, nguồn trích dẫn). Sửa nội dung ở đây |
| `build_report.py` | Dựng docx: lấy `nguon/ref_style.docx` làm nền (style, mục lục, bảng, chú thích), thay bìa bằng bìa của `nguon/template.docx` |
| `update_fields.ps1` | Mở Word để cập nhật mục lục, danh mục bảng/hình, rồi xuất PDF |
| `figures/` | Sơ đồ PNG xuất từ `docs/architecture/*.excalidraw` (`x2`, `x5`, `x6` sinh bằng `gen_excalidraw.py --all`) |
| `nguon/` | File gốc: `template.docx` (khung bìa), `ref_style.docx` (mẫu style) |

Dựng lại (từ thư mục này):

```bash
python build_report.py nguon/ref_style.docx nguon/template.docx build/raw.docx
powershell -NoProfile -File update_fields.ps1 -in <đường dẫn tuyệt đối build/raw.docx> -out <...>/BaoCao-SOA-WattPrint.docx -pdf <...>/BaoCao-SOA-WattPrint.pdf
```

Cần `python-docx`, `pillow`, và Microsoft Word (để cập nhật mục lục).

## Việc còn lại
- Bản này gồm Chương 1 đến 4 (bài toán, phân tích, kiến trúc, đánh đổi). Còn thiếu: thiết kế API, độ tin cậy và xử lý lỗi có số liệu, triển khai và kiểm thử, đánh giá, hạn chế.
- Đề bài yêu cầu tối thiểu 30 trang: hiện 32 trang tính cả bìa và mục lục. Toàn bộ tài liệu dùng một khổ dọc duy nhất của template, sơ đồ đặt xen trong thân bài.
- Chữ trong các sơ đồ lớn (container, sequence) nhỏ khi in vì phải thu về bề rộng trang dọc; xem rõ hơn ở bản PDF (phóng to) hoặc mở file `.excalidraw`.

## Ghi chú audit sơ đồ (khi lồng vào báo cáo)
- `00-overview`: có mũi tên "sự kiện" từ nilm sang core, trái với sơ đồ Container (nilm trả kết quả ngay trong response). Đã bỏ mũi tên, dời ô Keycloak để nhãn JWKS không đè.
- `x2`, `x5`: các khung `alt` liền nhau đè nhãn lên viền. Đã chừa khe.
- Container, component core/insight/copilot, context, x6: nhất quán với README kiến trúc. Còn một đường nối chéo qua ô Notifier ở sơ đồ copilot, chấp nhận được.

## Từ điển và theo dõi văn phong
- `tracking/glossary.py` là nguồn duy nhất cho thuật ngữ thống nhất và các dấu hiệu văn slop. `python tracking/check_terms.py` đếm vi phạm trong `content.py` và `../slide/build_slides.py` (dấu `;` ở slide là cú pháp Python, bỏ qua). `--md` sinh lại `../TU-DIEN-THUAT-NGU.md`. `apply_glossary.py` thay tự động các mục auto (có file `.bak`).
- Slide nằm ở `../slide/`: `build_slides.py` dựng, `render.sh` nhúng font Geist, xuất PDF và contact sheet. Bản chính: `../SOA-WattPrint-Slide.pptx` và `.pdf`.
