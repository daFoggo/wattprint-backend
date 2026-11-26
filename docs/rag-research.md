# RAG cho Wappi: nghiên cứu và bản đầu tiên

Ngày 2026-11-26. Số đo là số thật; chỗ chưa đo ghi "chưa đo".

## Kết luận

RAG ở đây chỉ trả lời **"văn bản nào nói gì, từ khi nào"**: quyết định giá điện, thuế GTGT, luật dữ liệu cá nhân và AI.
**Con số của nhà bạn vẫn do công cụ và dịch vụ tính**; RAG không thay công cụ. Lý do: bảng giá đã nằm trong
`tb_tariff_version` (hóa đơn tính từ đó), nên đưa số bậc giá qua mô hình đọc văn bản chỉ thêm chỗ sai.

## Dùng gì (và vì sao không dùng thứ khác)

- **Postgres một mình**: `tb_document`/`tb_chunk` đã có cột `vector(1024)` (HNSW cosine) và `tsv` (GIN). Không thêm
  vector DB: kho chỉ có vài chục đoạn, thêm một dịch vụ chỉ thêm chỗ hỏng.
- **Xếp hạng lai**: full text (OR các từ của câu hỏi, bỏ dấu) và vector, gộp bằng reciprocal rank fusion (hằng số 60).
- **Embedding: `baai/bge-m3`** qua OpenRouter, dự phòng AstralX (`astralx-embed`), cùng thứ tự với chat. Hai nơi trả **đúng một vector**
  (cosine 1,0000 trên 3 câu thử, kể cả `agentx_embed`), nên câu hỏi do nơi dự phòng nhúng vẫn khớp các đoạn đã lưu; không cần lưu hai bộ vector.
  Chọn theo bảng đo bên dưới: đa ngôn ngữ (Việt, Anh, cả Anh hỏi tài liệu Việt), 1024 chiều đúng cột, ngữ cảnh 8k, 0,01 USD cho một triệu token.
- **Đoạn**: theo đoạn văn, tối đa 900 ký tự, gối đầu 120 ký tự, để một điều khoản không bị cắt giữa chừng.
- **Quyết định mới nhất thắng**: biểu giá cũ (QĐ 1279) chỉ được trả khi câu hỏi nêu số hiệu, năm, hoặc hỏi về quá khứ.
- **Trích dẫn**: mỗi đoạn trả về là một nguồn trong danh sách "Nguồn" dưới câu trả lời.
- Graph-RAG và tri thức chuyên gia (ISO 7730, ASHRAE 55) trong pitch: **chưa làm**, kho hiện không có tài liệu đó.

## Kho hiện có (16 đoạn, 6 tài liệu, `docs/sources/`)

| Tài liệu | Trả lời được | Đọc đến đâu |
|---|---|---|
| QĐ 2892/QĐ-BCT (giá điện từ 1/11/2026) | bậc giá, ngày áp dụng, chưa gồm VAT | Nguyên văn quyết định và phụ lục sinh hoạt trên LuatVietnam; chưa đối chiếu PDF gốc (tải cần đăng nhập) |
| QĐ 1279/QĐ-BCT (giá điện 6 bậc từ 10/5/2025) | giá cũ để so sánh | Như trên |
| Luật Thuế GTGT + Nghị quyết 204/2025/QH15 | VAT 8% đến hết 31/12/2026 | Nguyên văn bản Công báo (bạn gửi); đoạn kết luận là suy luận, đã ghi rõ trong file |
| Luật 91/2025/QH15, NĐ 356/2025, Luật 134/2025/QH15, NĐ 142/2026 | số hiệu và ngày hiệu lực | **Chưa đọc nguyên văn**: chỉ có số hiệu và ngày; câu trả lời không được nêu nội dung điều |
| Luật 77/2025/QH15, QĐ 280/QĐ-TTg | dán nhãn năng lượng, mục tiêu chung | Tóm tắt từ nửa đầu văn bản; **không có điều khoản về hộ gia đình, chỉ tiêu cụ thể chưa đọc** |
| NĐ 30/2026/NĐ-CP (hướng dẫn Luật 77/2025), cùng file với dòng trên | số hiệu, ngày ban hành 21/01/2026, phạm vi áp dụng gồm hộ gia đình | Chỉ trang tin của Bộ Công Thương; bản PDF là ảnh quét 7,6 MB, chưa OCR; ngày hiệu lực chưa biết |
| Thông tư 60/2025/TT-BCT (2/12/2025), Điều 12 khoản 5 | người thuê nhà: mỗi địa chỉ một hợp đồng, chủ nhà không thu quá hóa đơn | Câu đầu của khoản là trích nguyên văn, phần còn lại theo bài LuatVietnam; toàn văn ở trang trả phí; ngày hiệu lực chưa xác nhận nên không nêu |

## Link đã gom từ các session cũ nhưng chưa nạp

Gom từ 55 session: các trang tin (VTV, Báo Chính phủ, CafeF, Tuổi Trẻ, MISA...), trang EVN, luatvietnam, caselaw, IEA, MIT.
Chưa nạp vì: (1) tin báo có bản quyền, chỉ nên dẫn link, không lưu nguyên văn; (2) `thuvienphapluat.vn` trả 403 khi
tải tự động; (3) trang EVN dựng bằng JavaScript, tải thẳng chỉ ra 65 ký tự; (4) Thông tư 60/2025/TT-BCT (người thuê
nhà): mới đọc bài báo, chưa đọc văn bản. Văn bản quy phạm pháp luật không có bản quyền, nên bước tiếp theo là nạp
nguyên văn Thông tư 60 khi có bản đọc được. Nghị định 174/2025 là nghị định hướng dẫn VAT (chỉ có bản quét, chưa nạp), không phải nghị định hướng dẫn Luật 77/2025; nghị định sau là 30/2026/NĐ-CP (đã nạp phần tin của Bộ Công Thương).

## Chọn model embedding (đo 2026-11-26)

Cùng 14 đoạn, 22 câu có đáp án (13 Việt, 9 Anh hỏi tài liệu Việt) và 6 câu không liên quan; trúng = đúng tài liệu trong 4 đoạn gần nhất:

| Model (1024 chiều) | Giá / 1M token | Việt trúng (top-1) | Anh trúng (top-1) | Tách liên quan / không (biên) | Thời gian 28 câu |
|---|---|---|---|---|---|
| **baai/bge-m3** (OpenRouter = AstralX) | 0,01 USD | 13/13 (9) | 9/9 (8) | +0,016 | 1,7 s |
| qwen3-embedding-8b | 0,01 USD | 13/13 (10) | 9/9 (8) | +0,023 | 7,3 s |
| multilingual-e5-large | 0,01 USD | 13/13 (8) | 9/9 (6) | −0,045 | 4,0 s |
| gemini-embedding-001 | 0,15 USD | 13/13 (10) | 9/9 (8) | −0,071 | 3,2 s |
| text-embedding-3-small | 0,02 USD | 13/13 (11) | 8/9 (7) | −0,317 | 1,1 s |
| qwen3-embedding-4b | 0,02 USD | không đo được (HTTP 429) | | | |

Chi phí không phải yếu tố phân biệt: cả kho (≈2.700 token) và mỗi câu hỏi (≈15 token) đều dưới 0,0001 USD. bge-m3 thắng vì
nhanh gấp 4 lần qwen3-8b với chất lượng gần bằng, biên tách dương, 1024 chiều nguyên bản, và có ở cả hai nơi. Hạn chế
chung: biên chỉ +0,016, nghĩa là câu Anh hỏi tài liệu Việt gần ngưỡng nhất.

## Đo truy xuất của bản đã làm (gọi embedding thật qua `documents.search`)

- **Việt 13/13, Anh 9/9** câu có đúng tài liệu trong kết quả (câu hỏi giá cũ nhờ luật "hỏi về quá khứ", cả "old"/"trước").
- **6/6 câu không liên quan trả rỗng** ("giá vàng", "Điều 99 Luật Điện lực", "nấu phở" và bản tiếng Anh).
- Khoảng cách cosine: liên quan 0,19–0,48, không liên quan ≥ 0,50; ngưỡng đặt 0,49.
- **Giới hạn**: ngưỡng chọn trên chính 28 câu này nên con số lạc quan; biên 0,016 là mỏng, kho chỉ 14 đoạn nên "trúng" dễ hơn kho
  thật. Ca "Điều 99" bị loại nhờ khoảng cách 0,499, sát ngưỡng: nạp văn bản Luật Điện lực thật thì phải đo lại.
- Câu trả lời cuối của Wappi (có đúng mã văn bản không, có bịa điều khoản không) đo ở nhóm `tariff_doc` của
  `scripts/wappi_eval.py`, xem `docs/chatbot-eval.md`.

## Chưa làm / việc còn lại

- Nạp thủ công (`scripts/ingest_documents.py`), chưa có lịch kiểm tra văn bản mới hoặc hết hiệu lực. Quyết định giá
  điện đổi mỗi vài tháng: cần nhắc kiểm tra mỗi khi `tb_tariff_version` thêm phiên bản.
- Mã văn bản chỉ nằm trong tiêu đề (bảng `Document` không có cột mã): lọc theo số hiệu dựa vào tiêu đề.
- Tài liệu không có trang riêng (nghị quyết VAT, luật dữ liệu cá nhân) dẫn về cổng `vanban.chinhphu.vn` ở danh sách Nguồn.
- Chạy lại (thư mục là cả kho: file đổi tên hoặc bị xóa thì tài liệu cũ bị xóa theo): `docker compose exec -T api rm -rf /tmp/sources && docker compose cp docs/sources api:/tmp/sources && docker compose exec -T api python -m scripts.ingest_documents /tmp/sources`.
