# Pipeline NILM và nhiều hộ demo

Ngày: 2026-11-17. Phạm vi: backend monolith hiện tại (chưa tách microservice), giữ đúng các quy tắc xử lý trong
`docs/database-design.md`, `2026-11-12-data-pipeline-live-dashboard.md` và `docs/architecture/README.md`, để khi tách
service chỉ đổi chỗ chạy, không đổi contract.

Mục tiêu: số đo công tơ tổng của **nhiều hộ** chảy liên tục vào `tb_reading`, NILM phân rã thành công suất từng thiết
bị, ghi vào `tb_device_estimate`, gộp qua `device_estimate_1m/1h/1d`, và dashboard, hoá đơn, text2sql đọc được số thật
thay cho dữ liệu mẫu. Mỗi hộ có tài khoản đăng nhập riêng.

## Cập nhật khi triển khai (2026-11-17)

Những điểm dưới đây thay cho phần tương ứng phía sau:

- **Mỗi nhà một model** (chốt với nhóm): model hiện tại kém generalize và fine-tune không ăn thua, nên demo
  dùng model riêng từng nhà. `public.tb_nilm_model` gán model cho từng nhà (`home_id`), model dùng chung có
  `home_id` NULL làm dự phòng; worker chọn model của nhà, không có thì dùng model chung. Báo cáo nên trình bày là
  "model nền + hiệu chỉnh theo hộ", vì nhà thật mới đăng ký không có dữ liệu đo riêng từng thiết bị để train.
- **Bắt đầu với 2 nhà: REFIT 2 và 5.** Nhà 5 chạy model chung (của nhà 2) cho đến khi có model riêng.
- **Tên gốc REFIT:** nhà tên `REFIT House <n>`, thiết bị mang tên trong `CLEAN_READ_ME_081116.txt`
  (Fridge-Freezer, Washing Machine…), không đặt hồ sơ tự chế (tỉnh, diện tích, số người để trống).
- **D7:** image API cố ý không có torch, nên worker chạy thành **container `nilm` riêng** (cùng mã nguồn, torch
  CPU), lệnh `python -m app.modules.nilm.worker`. Khi tách service, container này thành service `nilm`.
- **Đo thực tế:** một model khoảng 0,55 GB RAM (python + torch), 27–29 ms mỗi cửa sổ trên 4 luồng CPU; chạy lùi
  90 ngày một nhà khoảng 3,5 phút (26 ngày/phút), live trễ khoảng 1 phút. Lấp lỗ 60 s đưa phần dữ liệu dùng
  được của House 2 từ 69,4 % lên 73,9 % (tối đa 74,9 %).
- **API mới:** `GET /api/v1/energy/devices`, `/devices/{id}`, `/activity`; SSE `/energy/stream` có thêm
  `nilm.updated` (data `analyzed_until`). Ngưỡng bật/tắt theo loại thiết bị lấy từ `on_threshold_w` của bundle
  (hằng số trong `energy/services/devices.py`); lần chạy dưới 5 Wh bị bỏ (nhiễu NILM).
- **Đã gặp:** pandas 3 mặc định lưu thời gian theo micro giây, nên `asi8` phải ép `as_unit("ns")`; bản lỗi
  từng đẩy checkpoint đi mà không ghi estimate nào. Test "chạy từng phần bằng chạy một lần" bắt được lỗi này.

Chạy: `uv run python -m scripts.seed_demo_homes` (trên host, đọc `.env`), rồi
`docker compose exec -d api python -m scripts.replay_refit` và `docker compose up -d nilm`.

---

## 1. Câu hỏi: mỗi hộ một model?

**Không.** Cả paper NILMFormer lẫn các nghiên cứu cùng nhóm đều train **một model dùng chung cho mọi hộ** và đánh giá
trên **hộ chưa thấy khi train**.

| Nguồn | Cách làm |
|---|---|
| NILMFormer (Petralia và cộng sự, KDD 2025) | Một model cho mỗi **loại thiết bị**, train trên nhiều hộ. REFIT: 2 hộ để test, 1 hộ để validation, các hộ còn lại để train. UK-DALE: train hộ 1, 3, 4, 5, test hộ 2. REFIT và UK-DALE dùng bước 1 phút, cửa sổ 128/256/512 điểm. |
| NILMFormer ở EDF ("Mon Suivi Conso") | Chạy hàng tuần cho khoảng 3,6 triệu khách hàng, dữ liệu 30 phút, một model mỗi thiết bị. Paper không nhắc hiệu chỉnh riêng cho từng hộ. |
| seq2point transfer (D'Incecco, Squartini, Zhong 2019) | Model train trên REFIT chạy sang UK-DALE (cùng nước) gần như không cần fine-tune. Sang REDD (khác nước) thì fine-tune riêng các lớp dense là đủ. |
| One-shot transfer (TU Delft 2023) và các bài gần đây | Fine-tune theo hộ có giúp, nhưng cần dữ liệu có nhãn của chính hộ đó, và hiệu quả dao động mạnh theo từng hộ. |

Kết luận cho WattPrint:
- Kiến trúc đúng là **một model chung**. "Hiệu chỉnh theo hộ" (đã ghi trong `docs/architecture/README.md`) là bước tuỳ
  chọn, nhẹ, làm sau: chỉnh hệ số công suất theo phản hồi của người dùng hoặc theo một thiết bị đo riêng bằng ổ cắm.
  Không train một model cho mỗi nhà, vì nhà thật không có dữ liệu đo riêng từng thiết bị để train.
- **Vấn đề hiện tại:** `nilm_pipeline.pt` chỉ train trên **REFIT House 2**, cắt theo thời gian (`dataset/training/data.py`,
  `trained_until 2015-01-24`). Thực chất đây là model của riêng một nhà. Chạy sang nhà khác sẽ kém hơn số trong
  `test_summary` (energy F1 0,57, sai số kWh tổng 11,9 %) với mức chưa đo được. Bước 6 đo con số này, và
  train lại theo nhiều hộ nếu cần.

Nguồn: [NILMFormer, arXiv 2506.05880](https://arxiv.org/html/2506.05880v1),
[Transfer learning NILM, arXiv 1902.08835](https://arxiv.org/pdf/1902.08835.pdf),
[One-shot transfer, TU Delft](https://repository.tudelft.nl/record/uuid:12b6ff8d-28ed-4741-9b30-2a2da33ca779),
[REFIT README (danh sách thiết bị từng nhà)](https://pure.strath.ac.uk/ws/portalfiles/portal/62090183/CLEAN_READ_ME_081116.txt).

---

## 2. Những điểm sai hoặc thiếu đã phát hiện (phải sửa trước khi chạy NILM)

1. **Đặc trưng thời gian lệch so với lúc train.** Model nhận 8 đặc trưng sin/cos của phút, giờ, thứ, tháng, tính trên
   cột `Time` của REFIT, tức **giờ địa phương Anh**. Trong DB, seed dời dữ liệu `4179` ngày (597 tuần). Cách dời này giữ
   đúng thứ trong tuần nhưng **lệch tháng khoảng 5 tháng** (4179 ngày ≈ 11,44 năm). Ngoài ra `ts` lưu theo UTC còn
   dashboard hiển thị giờ Việt Nam, nên hoạt động lúc 7 giờ sáng ở Anh hiện ra lúc 14 giờ. Nếu worker tính đặc trưng từ
   `ts` trong DB, model nhận sai tháng và sai giờ.
2. **Có nguy cơ đếm trùng năng lượng.** House 2 đang có 9 chuỗi `plug`, là số đo thật từng thiết bị của REFIT. Khi NILM
   tạo thiết bị `origin='nilm'`, `ai.fact_energy` sẽ cộng cả thiết bị plug lẫn thiết bị NILM, vì đó là các `device_key`
   khác nhau. Kết quả là text2sql đếm hai lần.
3. **Tổng các thiết bị có thể vượt công tơ tổng.** `inference.py` chặn `Other ≥ 0` nhưng không chặn tổng các thiết bị.
   Khi tổng thiết bị lớn hơn aggregate, các phần chia trong hoá đơn (`bill_item.share`) sẽ cộng lại vượt 100 %.
4. **Seed cố định một nhà và nằm trong migration.** Revision `b2183c4aca1c` hard-code House 2 và tạo `admin@gmail.com`
   với `keycloak_sub` rỗng. Tài khoản này không đăng nhập được: `provision_user` tạo user mới theo `sub` và đụng email
   trùng.
5. **Test đang ghi vào DB dev.** `tb_users` có khoảng 150 tài khoản `user-*@example.com` và `dup-*@example.com`. Nên tách
   một DB riêng cho test trước khi seed nhiều hộ, để dữ liệu demo sạch.
6. **Aggregate không tự refresh phần lịch sử.** Policy 1m chỉ quét 7 ngày gần nhất. Chạy NILM lùi về 90 ngày thì
   `device_estimate_1m/1h/1d` vẫn trống cho phần cũ, trừ khi gọi `backfill_aggregates` (đã gặp đúng lỗi này ở seed REFIT,
   xem revision `5d0c9a3e7f21`).

---

## 3. Quyết định

| # | Câu hỏi | Chốt (đề xuất) | Lý do |
|---|---|---|---|
| D1 | Nhà demo | REFIT **2, 3, 5, 6**: cả bốn có đủ 6 thiết bị của model (tủ lạnh/tủ đông, máy giặt, máy rửa bát, lò vi sóng, máy nướng bánh, ấm đun). Có thể thêm 9 và 19 (thiếu máy nướng bánh hoặc máy rửa bát) để demo có nhà "không khớp". | Đánh giá được trên nhà chưa train, demo đa dạng |
| D2 | Lưu số đo riêng từng thiết bị (ground truth) | **Không** đưa vào bảng sản phẩm. Nhà demo chỉ có chuỗi `main`, giống nhà thật. Ground truth đọc thẳng từ CSV trong script đánh giá. | Tránh đếm trùng (mục 2.2), demo trung thực |
| D3 | Lịch sử mỗi nhà | 90 ngày trước "bây giờ", sau đó replayer chạy tiếp | Đủ cho các luật nghiệp vụ: dự báo ≥ 7 ngày, M&V ≥ 14 ngày, biểu đồ 30 ngày. Khoảng 0,25 GB mỗi nhà. |
| D4 | Cách dời thời gian | Dời theo **bội của 52 tuần**, rồi đặt giờ địa phương Anh vào giờ `Asia/Ho_Chi_Minh` (mục 5.2) | Giữ đúng thứ, lệch tháng tối đa khoảng 15 ngày, giờ sinh hoạt khớp giờ Việt Nam, đặc trưng thời gian khớp lúc train |
| D5 | Seed nằm ở đâu | Script CLI `scripts/seed_demo_homes.py`, đi qua `ingest_readings`. Migration chỉ còn schema. | Theo docs: "mọi nguồn dữ liệu đi qua một hàm duy nhất". Migration không nên chứa dữ liệu demo. |
| D6 | DB dev | **Dựng lại từ volume rỗng** (dump trước nếu cần) | Seed và cách dời đổi. Plan tách microservice cũng dựng lại DB ở phase 2. |
| D7 | Worker chạy ở đâu | Module `app/modules/nilm/`. Runner chạy như background task trong lifespan của API, bật bằng `NILM_WORKER=1`. Inference chạy trong `asyncio.to_thread`. | Đúng mẫu "mỗi service một container, job chạy trong lifespan". Khi tách, module chuyển nguyên sang service `nilm`. |
| D8 | Model | Bước đầu dùng `nilm_pipeline.pt` hiện tại. Sau đó train lại theo nhiều hộ (bước 6) nếu đánh giá kém. | Có pipeline chạy thật trước, rồi mới tối ưu độ chính xác |

---

## 4. Thiết kế pipeline NILM

### 4.1 Luồng

```
tb_reading (chuỗi main của mỗi nhà, khoảng 8 s, có lỗ)
  │  worker, mỗi 60 s, từng nhà (khoá advisory theo home_id)
  │  1. pending = điểm sau checkpoint('nilm', main) đến max(ts) của main
  │  2. đọc [checkpoint − ngữ cảnh, max(ts)] → lưới 15 s (mean) → lấp lỗ ≤ 60 s → đánh dấu đoạn liền mạch
  │  3. cắt cửa sổ 256 điểm, bước 128 (chồng 50 %) + một cửa sổ đuôi kết thúc ở điểm mới nhất
  │  4. model.predict theo lô → ghép chồng lấn (trung bình) → cân bằng năng lượng (mục 4.4)
  │  5. MỘT transaction: tb_inference_run(ok) + ingest_estimates + nâng checkpoint('nilm') đến điểm "đã chốt"
  ▼
tb_device_estimate (7 chuỗi device mỗi nhà: 6 thiết bị + "Khác")
  ▼ policy refresh 1m/1h/1d (+ backfill_aggregates khi chạy lùi lịch sử)
device_estimate_1m/1h/1d → device_breakdown, bill_item, ai.fact_energy, copilot_ro
  ▼
SSE `nilm.updated` (theo tb_inference_run.finished_at mới) → web gọi router.refresh()
```

### 4.2 Tiền xử lý phải **giống hệt** lúc train

Dựa trên `dataset/training/data.py` và `inference.py`:

- **Lưới 15 s:** `resample('15s').mean()`, mốc lưới căn theo epoch. Lệch múi giờ giữa Anh và Việt Nam là bội số phút,
  nên lưới không đổi.
- **Kẹp như dữ liệu train** (`dataset/scripts/eda.ipynb`): dưới 5 W thành 0, trên 10 kW thành 10 kW. Chỉ áp cho
  đầu vào model; cân bằng năng lượng vẫn dùng số đo thật.
- **Đặc trưng thời gian** tính trên **giờ địa phương của nhà** (`tb_home.timezone`). Theo D4, giờ đó trùng giờ địa
  phương Anh của bản ghi gốc.
- **Lỗ dữ liệu:** lúc train chỉ dùng đoạn liền mạch, không lấp lỗ. Khi suy luận, lấp tiến tối đa 4 ô (60 s), vì REFIT
  thường có mẫu cách nhau khoảng 62 s. Cửa sổ có lỗ dài hơn thì bỏ, đoạn đó không có estimate (coverage thấp). Ngưỡng
  60 s là tham số. Bước 2 đo tỉ lệ dữ liệu bị bỏ với vài ngưỡng rồi chốt.
- **Bỏ các mẫu gắn cờ** (`quality & 1`, tức `Issues` của REFIT): dữ liệu train đã bỏ chúng, và các aggregate
  cũng tính chúng là thời gian thiếu. (Bản plan đầu ghi ngược lại: sai, đã sửa khi đọc `eda.ipynb`.)

### 4.3 Cửa sổ, chồng lấn và điểm "đã chốt"

- Mỗi cửa sổ có L = 256 điểm (64 phút), bước S = 128. Các cửa sổ bám lưới cố định từ đầu mỗi đoạn liền mạch, nên chạy
  lại luôn cho cùng một kết quả.
- Điểm bị nhiều cửa sổ phủ thì lấy trung bình. Điểm ở mép đoạn liền mạch chỉ có một cửa sổ.
- **Điểm đã chốt** là điểm mà mọi cửa sổ có thể phủ nó đều đã chạy, tức `t < start(cửa sổ cuối trên lưới) + S`.
  Checkpoint `'nilm'` chỉ tiến tới điểm đã chốt. Lần chạy sau đọc lùi `L − S` điểm làm ngữ cảnh.
- **Đuôi tạm:** thêm một cửa sổ kết thúc ở ô 15 s mới nhất. Kết quả cho phần chưa chốt vẫn được ghi để dashboard
  tươi. Lần chạy sau ghi đè (upsert, lần mới thắng). Độ trễ dashboard khoảng 1 phút, không phải 64 phút.
- Đoạn liền mạch ngắn hơn 256 điểm thì không có estimate. Giữ checkpoint ở đầu đoạn đó cho đến khi đủ 256 điểm, hoặc
  quá 64 phút mà đoạn đã đóng (có lỗ phía sau) thì bỏ qua.

### 4.4 Cân bằng năng lượng

Với mỗi điểm: nếu `Σ thiết bị > aggregate` thì nhân mọi thiết bị với `aggregate / Σ`, và đặt
`Other = aggregate − Σ thiết bị` (≥ 0).

Bất biến: tại mọi điểm, `Σ thiết bị + Other = aggregate`, sai số làm tròn float4. Nhờ đó tổng các dòng hoá đơn bằng hoá
đơn, và tổng trong `ai.fact_energy` bằng tổng công tơ.

### 4.5 Thiết bị và chuỗi của NILM

- Khi một nhà có chuỗi `main`, hàm `ensure_nilm_devices(home_id, labels)` tạo idempotent các thiết bị
  `tb_device(origin='nilm')` và chuỗi `tb_series(kind='device', meter_id NULL)`. Ánh xạ nhãn:
  Fridge→`fridge_freezer`, WashMach→`washing_machine`, Dishwash→`dishwasher`, Microwave→`microwave`,
  Toaster→`toaster`, Kettle→`kettle`, Other→`other` (tên "Khác").
- Ràng buộc `uq_series_home_kind_device_metric` đã chặn trùng chuỗi. Thiết bị nhận diện theo `(home_id, name)`.

### 4.6 Quy tắc xử lý lỗi và đồng bộ

| Quy tắc (nguồn) | Cách áp trong monolith |
|---|---|
| `tb_reading` là nguồn sự thật, NILM là bước dẫn xuất chạy lại được (`2026-11-12`) | Worker không bao giờ sửa hay xoá `tb_reading`. Muốn chạy lại một khoảng thì chỉ cần lùi checkpoint `'nilm'`. |
| NILM lỗi thì không rollback số đo, batch ở trạng thái chờ (`PENDING_INFERENCE`) | Mở `tb_inference_run(status='running')` trong một transaction riêng. Lỗi thì transaction ghi dữ liệu rollback, run chuyển `failed` kèm lỗi (transaction thứ ba), checkpoint đứng yên. Lần sau thử lại với backoff 1 → 2 → 4 … tối đa 10 phút cho riêng nhà đó. |
| Ghi dữ liệu và nâng mốc trong cùng transaction (outbox/checkpoint) | `ingest_estimates` và nâng checkpoint `'nilm'` (`tb_ingest_checkpoint(source='nilm', series_id=<main>)`, dùng `GREATEST`) nằm trong một transaction. |
| Idempotent: gửi lại không tạo trùng | Cửa sổ bám lưới cố định, ghi bằng upsert theo `(series_id, ts)`. Chạy hai lần trên cùng khoảng cho cùng số dòng và cùng giá trị. |
| Không xử lý một việc hai lần khi có nhiều consumer | `pg_try_advisory_xact_lock(hash(home_id))`: nhà đang được xử lý thì bỏ qua. An toàn khi chạy `uvicorn --workers N` hoặc chạy tay song song. |
| Timeout và bulkhead (`libs/common`) | Mỗi lần chạy một nhà có hạn 120 s. Số nhà suy luận đồng thời giới hạn bằng `asyncio.Semaphore(1)` và `torch.set_num_threads` cố định, để API vẫn trả lời nhanh. Breaker và retry qua HTTP để dành cho lúc tách service. |
| Retention bằng `drop_chunks`, không `DELETE` | Giữ nguyên. Estimate giữ 400 ngày như raw. |
| Không backfill aggregate cũ hơn retention raw | Sau một lần chạy lùi lịch sử, gọi `backfill_aggregates` (có guard) cho khoảng vừa ghi. Chạy live thì để policy tự lo. |
| Phiên bản model | `model_name='nilmformer-gru'`, `model_version` = 12 ký tự đầu của sha256 file `.pt`. Đổi model thì lùi checkpoint để chạy lại, lần mới thắng. |

**Giới hạn còn lại:** dữ liệu đến trễ nằm trước checkpoint `'nilm'` không tự được chạy lại. Replayer không sinh ra trường
hợp này. Khi có API ingest thật thì thêm bước: `ingest_readings` ghi `min(ts)` của batch, worker thấy
`min(ts) < checkpoint` thì lùi checkpoint.

### 4.7 Chi phí

Mỗi nhà một ngày có 5.760 điểm 15 s, tức khoảng 45 cửa sổ (bước 128). 90 ngày là khoảng 4.000 cửa sổ, nhân với tổ hợp 5
seed (GRU + NILMFormer). Bước 3 đo thời gian chạy lùi trên CPU. Chế độ live chỉ có 1–3 cửa sổ mỗi phút mỗi nhà, rất nhẹ.

---

## 5. Nhiều hộ demo

### 5.1 Tài khoản

- Mỗi nhà có một chủ nhà (`owner`). Nhà 2 có thêm một thành viên (`member`) để demo tính năng chia sẻ nhà. Ràng buộc
  hiện tại là mỗi tài khoản thuộc tối đa một nhà, nhưng một nhà có nhiều thành viên.
- Script tạo user trên Keycloak qua Admin REST API: email đã xác minh, mật khẩu đúng chính sách của realm. Script lấy
  `id` của user Keycloak (chính là `sub`), ghi `tb_users(keycloak_sub=…)` rồi ghi `tb_home_member`. Nhờ vậy đăng nhập
  lần đầu không đụng `EmailTakenError` (mục 2.4).
- Danh sách tài khoản và hồ sơ nhà nằm trong một file cấu hình (`scripts/demo_homes.toml`). Hồ sơ gồm tên, tỉnh, loại
  nhà, số người, ngày chốt hoá đơn. Mỗi nhà một tỉnh và hồ sơ khác nhau để so sánh nhóm có dữ liệu. Mật khẩu lấy từ
  `.env`, không commit.

### 5.2 Dời thời gian (D4)

```
uk_wall  = Unix → Europe/London → bỏ múi giờ               (giờ sinh hoạt gốc của bản ghi)
vn_wall  = uk_wall + k × 364 ngày                          (k chọn riêng cho từng nhà)
ts_db    = vn_wall gắn Asia/Ho_Chi_Minh → UTC
```

- Chọn `k` nhỏ nhất sao cho khoảng `[bây giờ − 90 ngày, bây giờ + 60 ngày]` nằm trong bản ghi. Nếu nhà không có đủ
  bản ghi thì replayer quay vòng tuần cuối, như hiện tại.
- Lúc Anh lùi giờ mùa đông, giờ địa phương lặp một tiếng, khiến `ts` trùng: ingest coi là `dup`, giữ mẫu đầu. Lúc Anh
  nhảy giờ mùa hè thì mất một tiếng, thành lỗ dữ liệu.
- `k` và độ dời của từng nhà lưu trong `etl.tb_watermark` (cột `shift_days` = `k × 364`). Replayer đọc lại từ đó.

### 5.3 Seed và replay

- `scripts/seed_demo_homes.py --config scripts/demo_homes.toml [--house 3]` chạy idempotent theo thứ tự:
  1. Tắt policy bằng `set_policies(false)`.
  2. Tạo nhà, công tơ `REFIT-H{n}`, chuỗi `main`, thiết bị và chuỗi NILM, tài khoản.
  3. Nạp 90 ngày bằng `ingest_readings` theo khối khoảng 200 nghìn dòng. Ghi watermark từng khối nên chạy lại được
     từ chỗ dừng.
  4. Gọi `backfill_aggregates`, rồi bật lại policy bằng `set_policies(true)`.
- `scripts/replay_refit.py` chạy tiếp cho mọi công tơ `REFIT-H*`: một process, mỗi nhà một CSV và một độ dời riêng,
  chỉ đẩy kênh `Aggregate`.
- CSV tải từ bản REFIT Cleaned (CC BY 4.0) vào `dataset/` và không commit, như House 2 hiện nay. Mỗi file khoảng
  300 MB.

---

## 6. Đánh giá và train lại theo nhiều hộ

1. **Đánh giá model hiện tại:** script `scripts/eval_nilm.py --house N` chạy **cùng đường code của worker** trên CSV và
   so với kênh thiết bị thật. Script dùng đúng các chỉ số trong `test_summary`: energy F1/P/R, F1 bật/tắt, sai số kWh
   theo ngày. Kết quả ghi vào `docs/nilm-eval.md`.
2. **Train lại theo nhiều hộ** (nếu nhà 3, 5, 6 kém rõ rệt so với nhà 2):
   - Chia theo nhà, giống paper NILMFormer: test trên 2 nhà chưa thấy (đề xuất 5 và 6), validation 1 nhà (3), train
     trên các nhà còn lại có thiết bị tương ứng (2, 4, 7, 8, 9, 10, 11, 13, 15, 17, 19, 20, 21).
   - **Mask loss** cho thiết bị mà nhà đó không gắn đo. Không gắn đo không có nghĩa là công suất bằng 0: ví dụ nhà 9
     không đo máy nướng bánh nhưng có thể vẫn có.
   - Ánh xạ kênh theo README: mỗi nhà một vị trí cột khác nhau, nhà 6 dùng "Freezer" thay cho tủ lạnh.
   - Xuất cùng định dạng `wattprint-nilm/2`, nên worker không phải sửa. Đổi `model_version`, lùi checkpoint, chạy lại.
3. **Hiệu chỉnh theo hộ** (làm sau, tuỳ chọn): hệ số nhân công suất cho từng thiết bị của mỗi nhà, lấy từ phản hồi
   người dùng hoặc từ một ổ cắm đo. Lưu ở `nilm_db` khi tách service, đúng như `docs/database-design.md` mục 7 đã ghi.

---

## 7. Thứ tự làm và tiêu chí xong

| Bước | Việc | Xong khi |
|---|---|---|
| 0 | Dump DB dev nếu cần giữ. Tách DB test khỏi DB dev. | `pytest` không còn ghi `tb_users` của DB dev |
| 1 | `demo_homes.toml`, `seed_demo_homes.py` (dời thời gian D4, Keycloak, ingest), replayer cho nhiều nhà. Bỏ phần seed House 2 trong migration (giữ revision, chỉ không nạp dữ liệu, hoặc gắn cờ). | Dựng từ volume rỗng: 4 nhà × 90 ngày, đăng nhập từng tài khoản thấy đúng nhà mình, giờ cao điểm hiện vào khoảng 18–21 giờ Việt Nam |
| 2 | `app/modules/nilm/services/`: các hàm thuần (lưới 15 s, đặc trưng, cửa sổ, ghép chồng lấn, cân bằng). Tải model một lần. | **Test khớp số:** trên một ngày test của House 2, đầu ra worker khớp `inference.py` chạy trên đúng đoạn CSV đó (sai số ≤ 1e-4 W). Test bất biến cân bằng năng lượng. |
| 3 | Runner: checkpoint, advisory lock, transaction, `tb_inference_run`, backoff, chạy lùi lịch sử + `backfill_aggregates`, cờ `NILM_WORKER`. | Có test cho: chạy hai lần cùng kết quả; model lỗi thì run `failed`, checkpoint đứng yên, `tb_reading` không đổi, lần sau tự hồi phục; hai runner song song không trùng việc; `device_estimate_1h` có số cho 90 ngày |
| 4 | SSE `nilm.updated` và `analyzed_until`; API thiết bị (breakdown, chuỗi theo thiết bị). Web thay `energy/demo.ts` ở phần thiết bị. | Dashboard từng tài khoản hiện thiết bị thật, cập nhật khoảng 1 phút |
| 5 | `eval_nilm.py` cho nhà 2, 3, 5, 6, ghi `docs/nilm-eval.md`. | Có bảng chỉ số theo từng nhà |
| 6 | (Nếu cần) train lại nhiều hộ, đổi model, chạy lại. | Chỉ số trên nhà 5, 6 (chưa thấy) được ghi lại cạnh model cũ |

Bước 1 và bước 2 làm song song được. Bước 3 cần cả hai.

---

## 8. Rủi ro và câu hỏi mở

- **Độ chính xác trên nhà khác House 2 chưa biết** cho đến bước 5. Demo vẫn chạy, nhưng số có thể lệch nhiều. Đây là lý
  do bước 6 tồn tại.
- **Thời gian chạy lùi trên CPU** chưa đo (mục 4.7). Nếu quá lâu: giảm lịch sử chạy NILM (ví dụ 30 ngày) hoặc dùng
  `nilm_pipeline.pt2`.
- **Dữ liệu ground truth không nằm trong DB (D2)** nên demo không có màn "NILM so với đo thật". Nếu muốn có màn này, đặt
  ground truth trong schema riêng `eval` và để ngoài `ai.fact_energy` và `copilot_ro`.
- **Lỗ dữ liệu REFIT** (tháng 2/2014 thiếu nhiều, các khoảng 62 s): ngưỡng lấp 60 s có thể bỏ quá nhiều cửa sổ ở một
  số nhà. Bước 2 cần đo.
