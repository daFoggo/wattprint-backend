# Audit trước khi sửa: thêm service text2sql, chỉ dùng Qdrant

Kiến trúc đã chốt (2026-11-17):
- 5 service, xếp theo luồng nghiệp vụ: `core`, `nilm`, `insight`, `copilot`, `text2sql`.
- Call đồng bộ: `core → nilm`, `insight → core`, `copilot → insight`, `copilot → text2sql`. Không có vòng.
- `text2sql` lấy từ repo `ai-agent-superset-standalone`. LLM lập plan theo ID trong catalog, compiler (sqlglot) dựng SQL,
  executor chạy chỉ đọc trên **view do insight công bố** trong `insight_db` (role `text2sql_ro`, chỉ `SELECT`),
  view lọc theo `current_setting('app.home_id')`. Bỏ `POST /queries` và `SQL guard` của insight.
- Chỉ dùng Qdrant làm vector store: collection `text2sql_semantics_v1` (text2sql) và `copilot_knowledge_v1` (copilot).
  Bỏ pgvector. Chữ của tri thức vẫn nằm ở `copilot_db`, vector dựng lại được.
- PostgreSQL: 6 database (thêm `text2sql_db`), chỉ TimescaleDB. 10 container (thêm `text2sql`, `qdrant`).
- Event RabbitMQ giữ nguyên 3 routing key; text2sql không phát, không nhận event.

## Điểm phát sinh khi audit (cần anh xác nhận)

| # | Vấn đề | Đề xuất |
|---|---|---|
| D1 | Catalog của text2sql (metric, glossary, mô tả cột) cần người quản trị. Nếu text2sql không có route nào qua gateway thì không ai sửa được catalog | Mở `/api/text2sql/*` **chỉ cho admin**, giống `/api/nilm/*`. Người dùng cuối vẫn chỉ đi qua copilot |
| D2 | Báo cáo có sơ đồ Component cho từng service. Thêm service thứ 5 thì thiếu một sơ đồ | Thêm `07-component-text2sql` (Hình 3.11) dựng từ module thật của repo |
| D3 | Xếp theo luồng nghiệp vụ thì `insight → core` phải vòng qua `nilm` | Sơ đồ: mũi tên đi vòng dưới hàng service. Slide 4: chỉ vẽ route gateway tới 3 service công khai (core, insight, copilot), hai route admin ghi ở slide 5 để mũi tên không cắt nhau |
| D4 | Bảng 3.4 ghi Python 3.12, README ghi 3.14, repo agent dùng 3.14 | Sửa thành 3.14 (dòng này đằng nào cũng phải sửa) |
| D5 | `database-design.md` §7.1-7.3 có tên bị thay hỏng (`public.usage.updated`, `POST /queries của public`) | Sửa luôn trong §7.2 và §7.3 vì đằng nào cũng viết lại. §7.1 cột "Nội dung" có `public.*; public.*` không suy ra được tên gốc nên để nguyên |
| D6 | Biểu giá 5 bậc so với 6 bậc, câu về thí nghiệm 45.000 hộ ở §1.1 | **Không sửa** trong đợt này (không thuộc kiến trúc), anh quyết riêng |

## Danh sách chỗ sửa

### `docs/architecture/README.md`
- Đầu file: bảng sơ đồ thêm `07-component-text2sql`.
- §1: 4 service thành 5. Câu "Lời gọi đồng bộ chỉ đi một chiều copilot → insight → core → nilm" viết lại theo 4 cạnh mới.
  Bảng service: `insight` bỏ "truy vấn an toàn cho Text-to-SQL", thêm "view công bố cho text2sql". `copilot` đổi `copilot_db (pgvector)`
  thành `copilot_db`, gọi tới thêm `text2sql`, Qdrant. Thêm dòng `text2sql`.
- Phần mềm có sẵn: thêm Qdrant.
- Stack: "8 container" thành 10. Dòng Database bỏ pgvector, 5 database thành 6. Thêm dòng Vector store (Qdrant 1.20).
  Dòng Service: thêm `text2sql` tái sử dụng repo agent. Dòng Mã nguồn: `services/{core,nilm,insight,copilot,text2sql}`.
- "Vì sao chia như vậy": câu CQRS và Text-to-SQL viết lại. Thêm lý do tách text2sql khỏi copilot.
- §2b Dữ liệu: 5 database thành 6, thêm Qdrant theo collection, `copilot_ro` thay bằng view công bố.
- §4: thêm route `/api/text2sql/` (admin).
- §5: thêm breaker `copilot → text2sql`, timeout cho call này.
- §8 Đối chiếu yêu cầu: "4 service, 4 database" thành 5 và 5.

### `docs/database-design.md` §7
- §7.1: 5 database thành 6, bỏ pgvector ở `copilot_db`, thêm dòng `text2sql_db`, thêm view công bố trong `insight_db`. Ghi Qdrant.
- §7.2: sửa tên event.
- §7.3: viết lại: text2sql đọc view qua role `text2sql_ro`, `app.home_id`, timeout. Bỏ `POST /queries`.
- §7.5: thêm việc mở: bỏ cột `tb_chunk.embedding`, nạp vector sang Qdrant khi tách copilot.

### `docs/soa/draft/content.py`
- SUMMARY, KEYWORDS: 4 service thành 5, thêm Text-to-SQL, Qdrant.
- ABBR: thêm SSE.
- §1.2 khối Energy Copilot: thêm Text-to-SQL không để LLM viết SQL.
- §1.3 phạm vi: thêm ý text2sql tái sử dụng ứng dụng Text-to-SQL sẵn có, chỉ viết phần kết nối.
- §1.5 cấu trúc báo cáo: không đổi.
- Bảng 2.1: Nhóm vận hành thêm "quản lý catalog Text-to-SQL". LLM thêm "lập plan truy vấn".
- Bảng 2.2 nhóm 6: dữ liệu tạo ra thêm catalog metric.
- §2.3 câu cuối: BR6-BR9 thuộc copilot và text2sql.
- §3.1: câu chiều gọi, "bốn service" thành năm.
- §3.3.1: thêm lý do tách text2sql (dữ liệu catalog riêng, workload embedding, fault isolation, tái sử dụng).
- Bảng 3.1: phương án B thành "Năm service". Câu dẫn đổi.
- §3.3.3, Bảng 3.2: thêm dòng text2sql, sửa insight và copilot. 3 câu quyết định đi kèm và câu chiều gọi.
- §3.4: tám thành mười container, phần mềm có sẵn thêm Qdrant.
- §3.5.1: thêm call `copilot → text2sql`.
- §3.7: bỏ pgvector, 5 thành 6 database, viết lại đoạn Text-to-SQL, thêm Qdrant.
- §3.8: thêm route `/api/text2sql/` (admin).
- Bảng 3.4: dòng Database, thêm Vector store, dòng Service Python 3.14, thêm dòng Text-to-SQL.
- §3.10: copilot đoạn mô tả (RAG ở Qdrant, gọi text2sql), insight bỏ SQL guard, thêm đoạn text2sql, thêm hình 07.
- Bảng 4.1: dòng "bốn service" thành năm, thêm 2 dòng: text2sql đọc view của insight, thêm Qdrant ngoài PostgreSQL.
- Bảng 4.2: dòng Text-to-SQL viết lại, thêm dòng Qdrant ngừng, dòng text2sql hiểu sai câu hỏi.

### `docs/architecture/gen_excalidraw.py`
- `overview` (00): 5 service theo thứ tự nghiệp vụ, Qdrant trong hạ tầng, bỏ pgvector.
- `container` (02): thêm text2sql, Qdrant, `text2sql_db`, đổi thứ tự cột, route admin, ghi chú.
- `deployment` (x1): 10 container, qdrant, text2sql, bỏ pgvector.
- `qa` (x4): thay `POST /queries` bằng call text2sql.
- `comp_insight` (05): bỏ Safe query API, SQL guard, thêm view công bố và text2sql đọc view.
- `comp_copilot` (06): InsightClient bỏ "truy vấn an toàn", thêm Text2sqlClient, RAG retriever đổi sang Qdrant.
- Thêm `comp_text2sql` (07).
- Sinh lại `.excalidraw`, xuất PNG vào `docs/soa/draft/figures/` (Playwright và Chromium có sẵn).

### `docs/soa/slide/build_slides.py`
- Slide 1: 5 service theo thứ tự nghiệp vụ.
- Slide 3: thêm cột text2sql, copilot đổi `copilot_db · Qdrant`.
- Slide 4: 5 service, Qdrant trong hạ tầng, ghi chú chiều gọi.
- Slide 5: mười container, thêm text2sql, qdrant, route admin.
- Slide 6: chuỗi gọi mới.
- Slide 7: bỏ pgvector, 6 database, khối "Vì sao Copilot đi qua insight" viết lại.
- Slide 10: nhóm BR6-BR9 thuộc copilot và text2sql.
- Slide 11: 5 service, 6 database.

### Không sửa
- Pitch deck, `PROJECT_CONTEXT.md`, `database-design-guide.md` (mô tả monolith hiện tại), plan tách service, code monolith.
