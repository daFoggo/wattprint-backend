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
| VAT 8% trên tiền điện | Thuế suất dùng để tính tổng hóa đơn | `tb_tariff_version.vat_rate` | **Đã xác nhận từ văn bản gốc (Công báo), 2026-11-26.** Luật Thuế GTGT (114/VBHN-VPQH) Điều 9 khoản 3: mặc định 10%, điện không thuộc nhóm 0% hay 5%. **Nghị quyết 204/2025/QH15** (Công báo số 849+850, 1/7/2025) Điều 1 khoản 1: giảm 2% (còn 8%) cho các nhóm tại khoản 3 Điều 9 Luật, "trừ một số nhóm: viễn thông, hoạt động tài chính, ngân hàng, chứng khoán, bảo hiểm, kinh doanh bất động sản, sản phẩm kim loại, sản phẩm khai khoáng (trừ than), sản phẩm hàng hóa và dịch vụ chịu thuế tiêu thụ đặc biệt (trừ xăng)"; điện không nằm trong danh sách loại trừ. Điều 2: hiệu lực **từ 1/7/2025 đến hết 31/12/2026**. Phụ lục I của Nghị định 174/2025 (bản quét đã xem) cũng không có ngành điện. Chưa thấy văn bản gia hạn sau 31/12/2026 (bài mới nhất tra được ngày 17/11/2026; đến 26/11/2026 không thấy tin gia hạn): nếu không có thì thuế về 10%. Biểu giá trong DB đã có phiên bản từ 2027-01-01 ở 10% (migration `f4b8c2e6a913`); nếu có gia hạn, thêm một revision dời hoặc thay phiên bản đó. Còn thiếu: chưa đọc nguyên văn các điều của Nghị định 174/2025, và chưa thấy trang EVN ghi rõ "VAT 8%" (EVN chỉ ghi giá "chưa bao gồm thuế GTGT") |

Hệ quả cho sản phẩm: hóa đơn tính theo đúng biểu giá hiện hành (kiểm bằng đối chiếu số) và giao diện nêu mã văn bản ("giá theo QĐ 2892/QĐ-BCT", từ `tb_tariff_version.doc_code`). Từ 2027-01-01 biểu giá trong DB dùng VAT 10% (xem dòng VAT bên trên); một kỳ vắt qua 31/12/2026 tính 8% cho các ngày trước và 10% cho các ngày sau.

### Danh sách văn bản thuế bạn đưa (2026-11-26) và kiểm tra

Danh sách đến từ ChatGPT; các link kèm theo chỉ trỏ về trang chủ các cổng tra cứu (có `utm_source=chatgpt.com`), không phải link tới từng văn bản. Tôi tra từng số hiệu:

| Văn bản | Kết quả tra | Nói gì về thuế suất điện |
|---|---|---|
| Nghị định 144/2026/NĐ-CP | Có thật, ban hành **06/5/2026** (danh sách ghi 05/05), hiệu lực 20/6/2026, sửa Nghị định 181/2025 (đối tượng không chịu thuế bảo hiểm, khấu trừ đầu vào) | Không thấy nói về điện |
| Nghị định 359/2025/NĐ-CP | Có thật, 31/12/2025, hiệu lực 1/1/2026, sửa Nghị định 181/2025 (nông sản sơ chế, hoàn thuế) | Không thấy nói về điện |
| Văn bản hợp nhất 03/VBHN-BTC (2026) | Có thật, hợp nhất Nghị định 181/2025 đã sửa bởi 359/2025; có nêu giá tính thuế của điện bán cho EVN (thủy điện, nhiệt điện) | Không nêu thuế suất điện sinh hoạt trong phần đọc được |
| Nghị định 174/2025/NĐ-CP | Có thật, 30/06/2025, giảm 2% theo Nghị quyết 204/2025/QH15 | Cơ sở trực tiếp của 8%; Phụ lục I (bản quét) đã xem, không có ngành điện; chưa đọc nguyên văn các điều |
| Văn bản hợp nhất 114/VBHN-VPQH (Luật Thuế GTGT) | Có thật (bản Công báo số 305, đã đọc nguyên văn, xem mục dưới) | Mặc định 10%, điện không thuộc nhóm 0% hay 5% |

Kết luận: không văn bản nào nói thẳng "điện sinh hoạt chịu 8%"; kết luận được đọc từ hai văn bản gốc: Luật VAT (điện ở nhóm 10% mặc định) và Nghị quyết 204 Điều 1 (giảm nhóm 10% xuống 8%, danh sách loại trừ không có điện), khớp với Phụ lục I của Nghị định 174/2025 (bản quét, không có ngành điện). Cần theo dõi văn bản gia hạn cho 2027. Bản Công báo của Luật VAT (114/VBHN-VPQH) xác nhận mức mặc định là 10% (Điều 9 khoản 3). Phụ lục I đọc từ bản quét đăng trên fast.com.vn, chưa đối chiếu với bản trên cổng của Chính phủ.

### Hai văn bản hợp nhất bạn gửi (bản Công báo, đã đọc nguyên văn, 2026-11-26)

- **114/VBHN-VPQH** (Luật Thuế GTGT 48/2024/QH15 hợp nhất đến Luật 09/2026/QH16, xác thực 20/5/2026, Công báo số 305).
  - Điều 9 khoản 3: "Mức thuế suất 10% áp dụng đối với hàng hóa, dịch vụ không quy định tại khoản 1 và khoản 2 Điều này". Điện không có trong khoản 1 (0%), khoản 2 (5%: nước sạch, phân bón, thuốc, sách...) hay Điều 5 (không chịu thuế). **Theo luật, điện sinh hoạt chịu 10%.**
  - Luật không có mức 8%: mức 8% đến từ Nghị quyết 204/2025/QH15 (đã đọc bản Công báo, xem bullet dưới) và Nghị định 174/2025/NĐ-CP (chưa đọc các điều).
  - Điều 7 khoản 1 điểm m: giá tính thuế hoạt động sản xuất điện của EVN là giá bán chưa có VAT. Điều 8 khoản 2 điểm d: thời điểm xác định thuế của hoạt động cung cấp điện do Chính phủ quy định.
- **03/VBHN-BTC** (Nghị định 181/2025/NĐ-CP hợp nhất với 359/2025/NĐ-CP, xác thực 12/02/2026, Công báo số 130). Điều 16 khoản 2 điểm b: bán điện xác định thuế khi đối soát xong, chậm nhất ngày 07 tháng sau. Điều 11: giá tính thuế điện của EVN. **Phụ lục I, II của văn bản này là danh mục tài nguyên, khoáng sản xuất khẩu, không phải danh mục loại trừ giảm thuế** (danh mục đó nằm ở Nghị định 174/2025).
- **Nghị quyết 204/2025/QH15** (Công báo số 849+850, bạn gửi sau; đã đọc nguyên văn): Điều 1 khoản 1 giảm 2% (còn 8%) cho các nhóm tại khoản 3 Điều 9 Luật, trừ viễn thông, tài chính, ngân hàng, chứng khoán, bảo hiểm, bất động sản, sản phẩm kim loại, sản phẩm khai khoáng (trừ than), hàng chịu thuế tiêu thụ đặc biệt (trừ xăng); Điều 2 hiệu lực 1/7/2025 đến hết 31/12/2026. Điện không bị loại trừ.
- Không file nào nói gia hạn mức 8% sau 31/12/2026. Luật 09/2026/QH16 chỉ sửa khoản 25 Điều 5 (ngưỡng doanh thu hộ kinh doanh).

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

- [EVN: Điều chỉnh giá bán lẻ điện bình quân từ 01/11/2026](https://www.evn.com.vn/d/vi-VN/news/Dieu-chinh-gia-ban-le-dien-binh-quan-tu-ngay-01-thang-11-nam-2026-60-142-510169)
- [Phụ lục I Nghị định 174/2025/NĐ-CP, bản PDF, fast.com.vn](https://fast.com.vn/wp-content/uploads/2025/07/phu-luc-1.pdf)
- [Giảm thuế GTGT điện sinh hoạt 8%, apluslaw.vn](https://apluslaw.vn/doanh-nghiep/thue-gtgt-tien-dien.html)
- [Nghị quyết 204/2025/QH15, MISA](https://sme.misa.vn/345425/nghi-quyet-204-2025-qh15/)
- [Quyết định 1279/QĐ-BCT, luatvietnam.vn](https://luatvietnam.vn/dien-luc/quyet-dinh-1279-qd-bct-cua-bo-cong-thuong-quy-dinh-ve-gia-ban-dien-399752-d1.html)
- [Quyết định 2892/QĐ-BCT, luatvietnam.vn](https://luatvietnam.vn/dien-luc/quyet-dinh-2892-qd-bct-2026-quy-dinh-gia-ban-dien-453837-d1.html)
- [Giá điện sinh hoạt còn 5 bậc, cao nhất 3.844 đ/kWh, VTV](https://vtv.vn/chinh-thuc-gia-dien-sinh-hoat-con-5-bac-cao-nhat-3844-dong-kwh-100261104115102741.htm)
- [Thông tư 60/2025/TT-BCT về thực hiện giá bán điện, luatvietnam.vn](https://luatvietnam.vn/tin-van-ban-moi/da-co-thong-tu-60-2025-tt-bct-ve-thuc-hien-gia-ban-dien-tu-02-12-2025-186-105690-article.html)
