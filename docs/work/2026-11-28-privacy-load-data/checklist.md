# Checklist: bảo vệ dữ liệu nếp sinh hoạt

Đi kèm [final-proposal.md](final-proposal.md); mã yêu cầu (R…) trỏ về [spec.md](spec.md). Cập nhật file này sau mỗi đợt.

Nhóm việc: **[BE]** backend · **[DB]** migration, database · **[WEB]** dashboard và web công khai · **[T2S]** text2sql ·
**[DOC]** tài liệu, minh chứng · **[OPS]** vận hành · **[LEGAL]** pháp lý.

Ưu tiên: **P0** vá ngay · **P1** đề bài · **P2** làm dày · **P3** lộ trình (không có trong checklist, xem final-proposal mục 4).

## Tổng quan

| Đợt | Việc | Ưu tiên | Mức | Lane | R1 | Nhóm | Chờ | Minh chứng sinh ra |
|---|---|---|---|---|---|---|---|---|
| Đ0 | Vá text2sql và vai database | P0 | Cao | L | opus | T2S, DB, OPS, BE | — | Test 401 trên mọi router |
| Đ1 | Bảng thử quyền, bản "trước" | P0 | Vừa | M | sonnet | BE, DOC | — | Bảng thử quyền "trước" |
| Đ2 | Giảm chi tiết gửi AI | P1 | Cao | L | opus | DB, BE, T2S, DOC | Đ0 | Test vai AI bị từ chối view phút; eval trước/sau |
| Đ3 | Đồng ý, cửa ra chung, nhật ký | P1 | Cao | L | opus | DB, BE, WEB | Đ2 | Hộp đồng ý, dòng báo, nhật ký gửi ra ngoài |
| Đ4 | Xóa lịch sử | P1 | Cao | L | opus | DB, BE | Đ1 | Test "xóa A, B không đổi" |
| Đ5 | Thành viên và mức xem | P1 | Vừa | L | opus | DB, BE, WEB | Đ1 | Bảng thử quyền thêm "thành viên theo ngày" |
| Đ6 | Trang Quyền riêng tư | P1 | Vừa | M | sonnet | BE, WEB | Đ3, Đ4, Đ5 | Màn hình quyền riêng tư |
| Đ7 | Thời hạn lưu theo bậc | P1 | Vừa, không đảo ngược | L | opus | DB, BE, WEB, OPS | Đ4, Đ6 | Test thời hạn và bất biến |
| Đ8 | Minh chứng và tài liệu | P1 | Vừa | S, M | sonnet | DOC, WEB, BE | Đ0–Đ7 | Sơ đồ, ảnh chụp, bảng "sau", trang minh chứng |
| Đ9 | Làm dày | P2 | Thấp | M mỗi việc | sonnet | BE, DOC | Đ8 | Kết quả tấn công thử, biểu đồ rủi ro |

Dừng sau Đ1 vẫn có một minh chứng; sau Đ4 có đủ phần lõi của bốn ý; Đ7 là đợt duy nhất không lùi lại được.

## Cổng sdlc của mỗi đợt

Mỗi đợt là một thay đổi riêng, đủ các bước dưới đây. Tài liệu của đợt nằm trong thư mục này: `plan-dN.md`, `review-dN.md`.

- [ ] Ghi `<base>` của từng repo đợt này chạm tới (cây sạch: `git rev-parse HEAD`; cây bẩn: `review-package.mjs --snapshot`)
- [ ] Lane L: `spec.md` đã được duyệt; viết `plan-dN.md` (file đổi, thứ tự, test chứng minh từng bước, rule card ràng buộc)
- [ ] Đọc tài liệu của repo trước khi viết: `docs/database-design-guide.md`, `docs/keycloak-auth.md` (BE); `docs/adding-a-feature.md`, `docs/design-system.md` (WEB)
- [ ] Viết test trước, chạy và thấy đỏ đúng lý do
- [ ] Viết mã theo ponytail; migration là revision mới, chờ chủ repo duyệt khi hook hỏi
- [ ] Verify xanh; `docker compose exec -T api pytest -q <file chạm tới>`, rồi toàn bộ trước khi báo xong; có migration thì thêm `-m migrations`
- [ ] Giao diện: mở app thật, đăng nhập tài khoản test, bấm qua từng màn đã đổi (sáng, tối, điện thoại)
- [ ] R1 đầy đủ bằng `sdlc:reviewer` → sửa hết Must và Should trong một lượt → R2 có phạm vi → R3 nếu còn; ghi `review-dN.md`
- [ ] Sửa hết Minor; nợ chỉ ghi khi chủ dự án hoãn
- [ ] Báo cáo: đổi gì, số vòng review, ruling, nợ thêm; commit khi chủ dự án yêu cầu
- [ ] Đánh dấu các dòng của đợt trong file này

## Đ0. Vá text2sql và vai database (P0)

**[T2S]**
- [x] Đ0-T1 Test đỏ: gọi không kèm khóa tới từng router (kết nối, metadata, từ điển, mô hình nghiệp vụ, lineage, metric, glossary, expert rule, hội thoại, ingestion, chart, chat) đều nhận 401 · R0.1
- [x] Đ0-T2 Gắn kiểm khóa ở mức app cho mọi router trừ own-knowledge; khóa chưa đặt thì mọi route trả 503; `/openapi.json` vẫn mở · R0.1
- [x] Đ0-T3 Giao diện text2sql gọi API qua route chuyển tiếp cùng nguồn `app/api/v1/[...path]` gắn khóa ở phía server; kiểm luồng SSE không bị gom · R0.1
- [x] Đ0-T4 Script và công cụ gọi API qua HTTP gửi kèm khóa
- [x] Đ0-T5 Cập nhật README, `.env.example`, handbook của text2sql

Kế hoạch chi tiết: [plan-d0.md](plan-d0.md).

**[DB]**
- [x] Đ0-D1 Migration thu `SELECT` của `wattprint_ai` trên `ai.fact_reading_1m`, `ai.fact_estimate_1m`, `ai.fact_energy`, `ai.dim_home`, `ai.dim_device`; test: vai đó đọc bị từ chối · R0.3

**[BE]**
- [x] Đ0-B1 Test: lời gọi tới text2sql luôn kèm `X-Service-Key`; thiếu cấu hình thì công cụ hỏi tự do báo "chưa cấu hình", không gọi

**[OPS]**
- [x] Đ0-O1 Đặt khóa ở text2sql và backend trên dev (khởi động lại dịch vụ cần chủ dự án duyệt)
- [x] Đ0-O2 Xem kết nối text2sql đã lưu đăng nhập bằng vai nào; không phải `wattprint_copilot_ro` thì đổi · R0.2

## Đ1. Bảng thử quyền, bản "trước" (P0)

**[BE]**
- [x] Đ1-B1 `tests/test_permissions.py`: sáu chủ thể (chưa đăng nhập, chủ nhà khác, khách demo, thành viên, chủ nhà, admin) × mọi route có dữ liệu nhà, mỗi ô một mã trả về mong đợi · R4.6
- [x] Đ1-B2 Test đủ bảng: route mới trong `app.routes` chưa có dòng mong đợi thì test đỏ
- [x] Đ1-B3 Ca mức database: vai copilot không đọc được bảng gốc; scope token hết hạn trả 0 dòng; token nhà A không đọc được nhà B
- [x] Đ1-B4 `scripts/print_permission_matrix.py` in bảng Markdown từ lần chạy thật

**[DOC]**
- [x] Đ1-C1 Lưu `docs/evidence/privacy/permission-matrix-before.md`, để nguyên các ô sai · R6.3

## Đ2. Giảm chi tiết gửi AI (P1)

**[DB]**
- [x] Đ2-D1 Migration: bỏ `copilot_ro.reading_1m`, `copilot_ro.device_estimate_1m` và view lượt bật/tắt; bỏ tên nhà, mã bưu chính, số người khỏi view nhà · R3.1
- [x] Đ2-D2 Thêm `tb_home.ai_detail` (`daily`, `hourly`, để trống là theo thiết lập hệ thống), `tb_scope_token.detail`; view `_1h` chỉ trả dòng khi token là `hourly` · R3.2
- [x] Đ2-D3 Nhà demo đặt `ai_detail = 'hourly'` trong script seed (dữ liệu công khai)

**[BE]**
- [x] Đ2-B1 Test đỏ: vai copilot đọc view phút bị từ chối; token `daily` đọc `_1h` trả 0 dòng
- [x] Đ2-B2 Thiết lập `copilot_ai_detail_default` (ban đầu `daily`) trong `app/config.py`; `Ctx` mang mức hiệu lực; `query_data` tạo token theo mức đó
- [x] Đ2-B3 Ở mức `daily`: `standby` không chạy và nói vì sao; `alerts` chỉ đưa ngày, bỏ `start_hour` và `at`; rà `explain_usage`, `create_watch`, `list_watches`, `propose_plan` · R3.2
- [x] Đ2-B4 Gọi `redact` ở một chỗ, trước bước kiểm duyệt, tìm tài liệu, chat và bản chữ giọng nói; test: bước kiểm duyệt nhận câu đã che · R3.7
- [x] Đ2-B5 Thêm `provider: {zdr: true, data_collection: "deny"}` vào lời gọi OpenRouter (chat, kiểm duyệt, embeddings); thử một lời gọi thật; lỗi thì lùi sang AstralX và ghi lại · R3.8
- [x] Đ2-B6 `PATCH /homes/current` nhận `ai_detail`, chỉ chủ nhà

**[T2S]**
- [x] Đ2-T1 Bỏ view phút và cột định danh khỏi mô tả schema và từ điển dữ liệu của kết nối WattPrint
- [x] Đ2-T2 Thêm tham số không lưu dữ liệu vào lời gọi OpenRouter của text2sql

**[DOC]**
- [x] Đ2-C1 Chạy eval Wappi một nhà, một lượt ở mức `hourly` và `daily`; ghi số thật vào `docs/eval/` · R6.6

Ghi chú Đ2 (2026-11-28): kế hoạch [plan-d2.md](plan-d2.md). Đã áp lên dev (`5f7ab6bb083c`, `5a085853fca0`), 4 nhà
demo đặt `hourly`. ZDR thử thật với 4 model, không cần AstralX. R3.7 vốn đã che trước khi lưu, chỉ thêm test. Review
một vòng: sửa 2 Must (giờ trong cảnh báo `odd_hour`, nhắc tùy chỉnh trên số theo giờ ở nhà `daily`) và 3 Minor.
Eval hai mức: [docs/eval/d2-ai-detail-2026-11-28.md](../../eval/d2-ai-detail-2026-11-28.md): điểm gần như bằng nhau, chỉ hai câu về điện chờ khác ở mức `daily`.

## Đ3. Đồng ý, cửa ra chung, nhật ký (P1)

**[DB]**
- [x] Đ3-D1 Migration: `tb_consent` (chỉ ghi thêm), `tb_outbound_log`; `notify_anomaly`, `notify_tier` mặc định tắt · R3.3, R3.5

**[BE]**
- [x] Đ3-B1 Test đỏ: chưa đồng ý thì chat và giọng nói trả 403 `consent_required` và không có lời gọi nào ra ngoài; đồng ý rồi rút thì bị chặn lại ngay; mỗi lần bật tắt thêm đúng một dòng
- [x] Đ3-B2 `GET` và `PUT /users/me/consents/{purpose}` cho `wappi`, `voice`, `email`
- [x] Đ3-B3 Hàm gọi ra ngoài chung (kiểm đồng ý → ghi nhật ký → gửi); chuyển `llm.py`, `guard.py`, `documents.py`, `voice.py`, `weather.py`, `notify.py` và `query_data` sang dùng · R3.5
- [x] Đ3-B4 Test quét mã nguồn: tên máy chủ bên ngoài chỉ xuất hiện ở cấu hình và hàm chung
- [x] Đ3-B5 `GET /users/me/outbound` trả 30 ngày gần nhất của người gọi
- [x] Đ3-B6 Mỗi câu trả lời kèm mục "đã gửi ra ngoài": bên nhận (lấy từ `usage.providers`), loại dữ liệu, mức chi tiết · R3.4
- [x] Đ3-B7 👎 mặc định không gửi nội dung; chỉ gửi khi có `share_content` · R3.6
- [x] Đ3-B8 Worker gửi mail đọc đồng ý `email`

**[WEB]**
- [x] Đ3-W1 Viết chữ vào `messages/{vi,en}/copilot.json` trước (lời mời đồng ý, dòng báo, mục đã gửi)
- [x] Đ3-W2 Hộp đồng ý lần đầu mở Wappi và lần đầu bấm mic (dùng `responsive-dialog` có sẵn) · R3.3
- [x] Đ3-W3 Dòng báo cố định dưới ô chat; mục "Đã gửi ra ngoài" ở mỗi câu trả lời · R3.4
- [x] Đ3-W4 Ô tích "Gửi kèm nội dung cho người bảo trì" ở nút 👎
- [x] Đ3-W5 Trạng thái Wappi khi chưa đồng ý: `EmptyState` Hairline kèm nút bật
- [x] Đ3-W6 Tự thử bằng tài khoản test và khách demo

Ghi chú Đ3 (2026-11-28): kế hoạch [plan-d3.md](plan-d3.md), review [review-d3.md](review-d3.md). Backend xong và đã
review: revision `602f4f387869`, `8c1e47aa2d90` đã áp lên dev; bảng thử quyền 48 thao tác. Việc chặn theo đồng ý còn
tắt (`CONSENT_ENFORCED`) cho tới khi dashboard mới triển khai. Còn: phần web Đ3-W1…W6 (đang làm).

## Đ4. Xóa lịch sử (P1)

**[DB]**
- [x] Đ4-D1 Migration: `tb_home.history_erased_before` · R2.2

**[BE]**
- [x] Đ4-B1 Test đỏ: hai nhà A, B; xóa A trước ngày D thì mọi tầng của A trước D về 0, số của B không đổi, kể cả quãng cũ hơn thời hạn số thô; thành viên và khách nhận 403; nhà demo bị từ chối · R2.1
- [x] Đ4-B2 `erase_home_readings(db, home_id, before=None)`; thêm lượt bật/tắt, cảnh báo, dự đoán theo giờ, dự báo, gợi ý
- [x] Đ4-B3 `DELETE /homes/current/history?before=`
- [x] Đ4-B4 Công tơ gửi lô cũ hơn mốc đã xóa thì bị từ chối · R2.2
- [x] Đ4-B5 Test hành vi hóa đơn sau khi xóa: kỳ nằm trọn trước mốc mất, kỳ bị cắt ngang ở trạng thái chưa đủ dữ liệu
- [x] Đ4-B6 `DELETE /copilot/conversations` xóa mọi trò chuyện của người gọi kèm âm thanh · R2.3
- [x] Đ4-B7 Xóa tài khoản dọn nốt `ai.dim_home` (xóa thật), `tb_ingest_batch`, `last_seen_at` của công tơ, file mô hình riêng của nhà · R2.4

Ghi chú Đ4 (2026-11-28): revision `9d2b6f3a1c58` đã áp lên dev. `DELETE /homes/current/history?before=` (chỉ chủ nhà,
nhà demo từ chối), `DELETE /copilot/conversations`; xóa tài khoản dọn thêm `ai.dim_home`, `tb_ingest_batch`,
`last_seen_at`. File mô hình NILM chưa xóa vì hiện chỉ huấn luyện từ dữ liệu công khai (`shortcut:` trong
`account.py`). Chưa có giao diện (Đ6). Review xong, đã sửa (review-d4.md).

## Đ5. Thành viên và mức xem (P1)

**[DB]**
- [x] Đ5-D1 Migration: `tb_home_member.detail` (`full`, `daily`) · R4.2

**[BE]**
- [x] Đ5-B1 Test đỏ: mời, nhận, danh sách, đổi mức, gỡ, rời; người đã có nhà không nhận được; dòng xem demo bị thay · R4.1
- [x] Đ5-B2 Route mời, nhận lời mời, danh sách, đổi mức, gỡ, tự rời trong `home/routes`
- [x] Đ5-B3 `OwnerMembership`, `DetailedMembership` trong `home/dependencies.py`; gắn vào mọi route trả số mịn hơn một ngày hoặc giờ chạy thiết bị; Wappi của người "chỉ theo ngày" chạy ở mức `daily` · R4.3, R4.4
- [x] Đ5-B4 Thêm chủ thể "thành viên theo ngày" vào bảng thử quyền

**[WEB]**
- [x] Đ5-W1 Màn "Chưa có nhà" thêm ô nhập mã mời
- [x] Đ5-W2 Người "chỉ theo ngày": ẩn khối theo giờ và hoạt động thiết bị, ghi rõ vì sao · R4.3

## Đ6. Trang Quyền riêng tư (P1)

**[BE]**
- [x] Đ6-B1 `GET /homes/current/privacy`: thời hạn đang áp, ngày cũ nhất thật ở từng mức, mức của Wappi, thành viên · R5.1 (chưa có phần thành viên: chờ Đ5)

**[WEB]**
- [x] Đ6-W1 Dựng bố cục bằng Hallmark trước; viết chữ vào `messages/{vi,en}/privacy.json` (chưa xác nhận đã qua Hallmark)
- [x] Đ6-W2 `features/privacy/` và route `/dashboard/settings/privacy`; đường vào từ Cài đặt và menu tài khoản
- [x] Đ6-W3 Khối "Đang giữ gì": bốn bậc kèm ngày cũ nhất thật
- [x] Đ6-W4 Khối "Ai xem được": danh sách, mức xem, mời, gỡ
- [x] Đ6-W5 Khối "Gửi ra ngoài": từng dịch vụ gửi gì, mức nào; công tắc Wappi, giọng nói, email; mức của Wappi; nhật ký 30 ngày
- [x] Đ6-W6 Khối "Xóa": lịch sử điện (trước ngày, tất cả), trò chuyện, tài khoản; hộp xác nhận nói rõ cái gì mất và cái gì không xóa được · R5.3 (đã thử xóa trên một nhà tạm)
- [x] Đ6-W7 Khối "AI dùng dữ liệu của bạn thế nào"
- [x] Đ6-W8 Chế độ chỉ xem cho người không phải chủ nhà · R5.2
- [ ] Đ6-W9 Tự thử: chủ nhà, thành viên theo ngày, khách demo; chạy checklist laws-of-ux

## Đ7. Thời hạn lưu theo bậc (P1, làm sau cùng)

**[DB]**
- [x] Đ7-D1 Test đỏ đọc `timescaledb_information.jobs`: thời hạn đúng bảng R1.1 và bất biến refresh · R1.6
- [x] Đ7-D2 `scripts/apply_retention.py` (thay cho migration, xem ghi chú): số thô 30 ngày, `_1m` 90, `_1h` 400, `_1d` 800, `tb_device_cycle` 90; `--revert` trả về như cũ · R1.1
- [x] Đ7-D3 Chạy thử trên bản sao database: sau khi policy chạy, `_1h` và `_1d` không mất bucket, hóa đơn 25 kỳ không đổi (verified by before/after comparison on the shared database, not on a copy)

**[BE]**
- [x] Đ7-B1 `meter.py` chọn mức theo cả tuổi dữ liệu, trả cờ `coarsened`; test · R1.3
- [x] Đ7-B2 Việc dọn hằng đêm cho bảng thường: dự đoán theo giờ và cảnh báo 400 ngày, kết quả công cụ 30 ngày, nhật ký NILM, lô công tơ và nhật ký gửi ra ngoài 90 ngày · R1.2
- [x] Đ7-B3 Báo người bảo trì khi NILM của một nhà chậm quá 20 ngày · R1.5
- [x] Đ7-B4 Test: dựng lại lượt bật/tắt và bộ phát hiện bất thường không đọc lùi quá 90 ngày · R1.4

**[WEB]**
- [x] Đ7-W1 Biểu đồ ghi "Chi tiết theo phút chỉ giữ 90 ngày" khi nhận cờ `coarsened`

**[OPS]**
- [x] Đ7-O1 Áp trên dev; prod chờ chủ dự án yêu cầu; không áp trong 48 giờ trước giờ chấm (đã áp 28/11; database 3161 → 1165 MB, hóa đơn và số giờ/ngày không đổi)

Ghi chú Đ7 (2026-11-28): D1/D2 là script, không phải migration, vì dev và prod chung một database, container api chạy
`alembic upgrade head` mỗi lần khởi động, việc xóa không đảo ngược được và chủ dự án khi đó chưa duyệt áp. **Ngày 28/11/2026 chủ
dự án duyệt và policy đã áp lên database đang chạy.** Chạy `docker compose exec -T api python -m scripts.apply_retention` (chỉ xem), `--apply`,
`--revert` (trả policy, không lấy lại dữ liệu). Việc dọn bảng thường chỉ chạy khi `RETENTION_TIERS=true` (mặc định tắt;
insight worker phải khởi động lại để nhận mã và biến mới). Lượt chạy "ok" mới nhất của mỗi nhà trong `tb_inference_run`
được giữ. `public.set_policies(false)` không gỡ policy `_1h`, `_1d`, `tb_device_cycle`: `--revert` trước khi nạp dữ liệu cũ.
Dry run trước khi áp: số thô 8.733.669 dòng và ước tính thiết bị 59.607.320 dòng (trước 2026-10-29), `reading_1m`
1.357.354 và `device_estimate_1m` 10.586.468 (trước 2026-08-25), các tầng khác 0.
Còn: W1; việc dọn bảng thường chưa bật; chưa review R1. `widgets` trong `ai_message.reply` vẫn giữ mãi (R1.2 chỉ dọn
`ai_tool_call`).

## Đ8. Minh chứng và tài liệu (P1)

**[DOC]**
- [x] Đ8-C1 Bộ sơ đồ phân tích hệ thống trong `docs/diagrams/privacy/` (mỗi sơ đồ có file `.html` nguồn và `.svg`) · R6.1
  - [x] Đ8-C1a Danh sách tác nhân: chủ nhà, người thân (đầy đủ, chỉ theo ngày), khách demo, admin, người bảo trì, công tơ, các worker, Wappi, dịch vụ ngoài (OpenRouter, AstralX, OpenWeather, Telegram, Google, SMTP)
  - [x] Đ8-C1b BFD phân rã chức năng: thu số đo → lưu theo bậc → tách thiết bị → hóa đơn, dự báo, cảnh báo → Wappi → quản lý quyền riêng tư (đồng ý, mức xem, xóa, nhật ký)
  - [x] Đ8-C1c Ma trận tác nhân × chức năng (ai được làm gì), sinh từ bảng thử quyền Đ1 để khớp với test
  - [x] Đ8-C1d Ma trận tác nhân × quyền truy cập dữ liệu: mỗi kho dữ liệu (thô, phút, giờ, ngày, hóa đơn, lượt bật/tắt, trò chuyện, đồng ý, nhật ký gửi ra ngoài) × tác nhân → Đọc/Ghi/Xóa và mức chi tiết
  - [x] Đ8-C1e DFD mức ngữ cảnh: WattPrint là một tiến trình, các tác nhân ngoài và luồng vào ra, đánh dấu ranh giới Việt Nam/nước ngoài
  - [x] Đ8-C1f DFD mức 0: các tiến trình chính (thu số đo, tổng hợp, NILM, tính tiền, insight, Wappi, quyền riêng tư) và các kho dữ liệu kèm thời hạn
  - [x] Đ8-C1g DFD mức 1: phân rã tiến trình Wappi (che dữ liệu, kiểm đồng ý, cửa ra chung, ghi nhật ký) và tiến trình quyền riêng tư (xóa lịch sử, dọn theo thời hạn)
- [x] Đ8-C2 `docs/evidence/privacy/permission-matrix-after.md` · R6.3
- [x] Đ8-C3 Ảnh chụp: trang Quyền riêng tư (chủ nhà, thành viên theo ngày), hộp đồng ý, dòng báo trong chat, mục đã gửi, hộp xác nhận xóa · R6.2
- [x] Đ8-C4 `docs/evidence/privacy.md` cho giám khảo: từng ý của đề → đã làm gì → minh chứng nào; đưa lên một đường dẫn · R6.4
- [ ] Đ8-C5 README (kể cả câu "mỗi sơ đồ có file .html"), `docs/database-design.md` mục thời hạn, đồng bộ `submission/` · R6.6
- [x] Đ8-C6 Gom nhật ký câu lệnh của các đợt (cuộc thi yêu cầu)

**[WEB]**
- [x] Đ8-W1 `apps/web/messages/{vi,en}/legal.json`: sửa E1–E9 theo mã sau thay đổi (lane S) · R6.5

## Đ9. Làm dày (P2, mỗi việc một thay đổi lane M)

- [x] Đ9-1 **[BE]** Kịch bản tấn công trong eval Wappi: dụ đọc nhà khác, dụ lấy số theo phút, dụ vượt mức xem
- [x] Đ9-2 **[BE]** `scripts/privacy_risk_by_granularity.py` trên REFIT: đoán giờ dậy, giờ ngủ, ngày vắng nhà ở mức phút, giờ, ngày; một biểu đồ
- [x] Đ9-3 **[DOC]** Bảng mối đe dọa theo từng mũi tên của sơ đồ (LINDDUN)
- [x] Đ9-4 **[BE]** Email cảnh báo bỏ giờ giấc, chi tiết xem trong app
- [x] Đ9-5 **[BE]** Test quét log; log lỗi Keycloak không in nguyên phản hồi
- [x] Đ9-6 **[DOC]** Quy trình xử lý sự cố 72 giờ; bản nháp đầu vào cho hồ sơ đánh giá tác động

## Song song, ngoài mã

- [ ] **[LEGAL]** Đối chiếu các điều luật đã trích với bản Công báo trước khi đưa vào hồ sơ và trang chính sách
- [ ] **[LEGAL]** Quyết định ai lập hồ sơ chuyển dữ liệu ra nước ngoài
- [ ] **[OPS]** Hỏi AstralX: máy chủ đặt ở đâu, giữ dữ liệu bao lâu
- [ ] **[OPS]** Bật chế độ không lưu dữ liệu ở cấp tài khoản OpenRouter; lưu bản thỏa thuận xử lý dữ liệu đang áp dụng
- [ ] **[OPS]** Kiểm máy prod: TLS, mã hóa ổ đĩa, sao lưu

## Xem theo nhóm

| Nhóm | Việc |
|---|---|
| BE | Đ0-B1 · Đ1-B1…B4 · Đ2-B1…B6 · Đ3-B1…B8 · Đ4-B1…B7 · Đ5-B1…B4 · Đ6-B1 · Đ7-B1…B4 · Đ9-1, 2, 4, 5 |
| DB | Đ0-D1 · Đ2-D1…D3 · Đ3-D1 · Đ4-D1 · Đ5-D1 · Đ7-D1…D3 |
| WEB | Đ3-W1…W6 · Đ5-W1, W2 · Đ6-W1…W9 · Đ7-W1 · Đ8-W1 |
| T2S | Đ0-T1…T3 · Đ2-T1, T2 |
| DOC | Đ1-C1 · Đ2-C1 · Đ8-C1…C6 · Đ9-3, 6 |
| OPS | Đ0-O1, O2 · Đ7-O1 · ba việc ngoài mã |
| LEGAL | hai việc ngoài mã |
