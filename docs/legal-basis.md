# Căn cứ pháp lý của WattPrint

Ngày 2026-11-25. Trả lời câu hỏi "thông tư, nghị định nào hỗ trợ sản phẩm?". Mỗi dòng nói rõ **đã kiểm chứng đến đâu**:
"tra được" nghĩa là văn bản có thật theo kết quả tìm kiếm trên các trang luật và báo; **chưa dòng nào đối chiếu với file
PDF gốc của cơ quan ban hành**. Đây không phải tư vấn pháp lý; luật sư cần xem lại trước khi trích trong tài liệu chính thức.

## Giá điện (cho phần hóa đơn và dự báo)

| Văn bản | Nội dung | WattPrint dùng ở đâu | Kiểm chứng |
|---|---|---|---|
| Quyết định 1279/QĐ-BCT (9/5/2025, hiệu lực 10/5/2025) | Quy định giá bán điện, giá bán lẻ bình quân 2.204,07 đ/kWh | Bảng giá 6 bậc trong `tb_tariff_version` (từ 2025-05-10 đến 2026-10-31) | Tra được, hiệu lực và giá bình quân khớp nguồn. Các mức bậc 5 (3.350) và bậc 6 (3.460) khớp dữ liệu. Mức bậc 1 (1.984) một nguồn gắn với Quyết định 14/2025/QĐ-TTg: cần đối chiếu phụ lục gốc |
| Quyết định 2892/QĐ-BCT (ban hành 31/10/2026, áp dụng từ 1/11/2026) | Biểu giá sinh hoạt rút còn 5 bậc, giá bình quân 2.159,9037 đ/kWh | Bảng giá 5 bậc từ 2026-11-01 | Tra được. Giá chưa VAT theo báo: 1.901; 2.289; 2.894; 3.456; 3.844 đ/kWh, các mốc 100/200/400/700 kWh: **khớp đúng với dữ liệu trong DB** |
| Thông tư 60/2025/TT-BCT (hiệu lực 2/12/2025) | Thực hiện giá bán điện, kể cả cách tính tiền điện cho người thuê nhà (định mức theo số người; thuê dưới 12 tháng mà không kê khai đủ thì tính giá bậc 2) | Chưa dùng: WattPrint chưa tính tiền điện cho từng người thuê | Tra được; đang có dự thảo sửa đổi, cần xem bản hiện hành |
| VAT 8% trên tiền điện | Thuế suất dùng để tính tổng hóa đơn | `tb_tariff_version.vat_rate` | **Chưa xác nhận** từ văn bản chính thức: chính DB đã ghi "verify before 2027" |

Hệ quả cho sản phẩm: hóa đơn đang tính theo đúng biểu giá hiện hành (kiểm bằng đối chiếu số), nhưng giao diện chưa nêu văn
bản nào là căn cứ. Việc có thể làm: hiện "Theo Quyết định 2892/QĐ-BCT" ở trang hóa đơn, lấy từ `source_doc` của phiên bản đang
áp dụng (hiện `source_doc` là câu tiếng Anh tự do, cần chuẩn hóa thành mã văn bản trước khi hiển thị).

## Dữ liệu cá nhân và AI

Các số hiệu dưới đây lấy từ nguồn của skill `vn-law-check` (`.agents/skills/vn-law-check/sources/legal-references.md`); skill
đó dặn không khẳng định số điều khi chưa chắc.

| Văn bản | WattPrint dùng ở đâu |
|---|---|
| Luật Bảo vệ dữ liệu cá nhân, Luật số 91/2025/QH15 (hiệu lực 1/1/2026) | Chính sách quyền riêng tư; che thông tin cá nhân trước khi lưu hoặc gửi cho mô hình; xóa tài khoản |
| Nghị định 356/2025/NĐ-CP (1/1/2026, thay Nghị định 13/2023) | Hướng dẫn thi hành luật trên |
| Luật Trí tuệ nhân tạo, Luật số 134/2025/QH15 (1/3/2026) | Wappi là hệ thống tự động, nhãn "Nội dung do AI tạo" |
| Nghị định 142/2026/NĐ-CP (1/5/2026), Điều 18 | Gắn nhãn nội dung do AI tạo |

## Chính sách khuyến khích tiết kiệm điện (lấy từ pitch deck, chưa tra lại)

- Quyết định 280/QĐ-TTg (13/3/2019): Chương trình quốc gia về sử dụng năng lượng tiết kiệm và hiệu quả giai đoạn 2019-2030.
- Quyết định 896/QĐ-TTg (26/7/2022): Chiến lược quốc gia về biến đổi khí hậu giai đoạn đến năm 2050.

Hai văn bản này nằm trong danh mục tham khảo của `docs/WattPrint Pitch Deck.md`; tôi chưa tra lại số hiệu.

## Nguồn đã dùng để tra

- [Quyết định 1279/QĐ-BCT, luatvietnam.vn](https://luatvietnam.vn/dien-luc/quyet-dinh-1279-qd-bct-cua-bo-cong-thuong-quy-dinh-ve-gia-ban-dien-399752-d1.html)
- [Quyết định 2892/QĐ-BCT, luatvietnam.vn](https://luatvietnam.vn/dien-luc/quyet-dinh-2892-qd-bct-2026-quy-dinh-gia-ban-dien-453837-d1.html)
- [Giá điện sinh hoạt còn 5 bậc, cao nhất 3.844 đ/kWh, VTV](https://vtv.vn/chinh-thuc-gia-dien-sinh-hoat-con-5-bac-cao-nhat-3844-dong-kwh-100261104115102741.htm)
- [Thông tư 60/2025/TT-BCT về thực hiện giá bán điện, luatvietnam.vn](https://luatvietnam.vn/tin-van-ban-moi/da-co-thong-tu-60-2025-tt-bct-ve-thuc-hien-gia-ban-dien-tu-02-12-2025-186-105690-article.html)
