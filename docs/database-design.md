# Thiết kế database WattPrint

Tài liệu này dành cho người mới vào dự án: vì sao database được dựng như hiện tại, dữ liệu chạy qua
đâu, phải vận hành theo quy tắc nào, và bài audit với dữ liệu REFIT đã đo được gì. Chi tiết đầy đủ nằm
ở spec (`docs/superpowers/specs/2026-11-01-database-design-design.md`) và bản audit
(`docs/database-audit.md`, số liệu gốc trong `docs/audit-results.json`). Mọi con số trong tài liệu này
lấy từ hai file audit đó và được ghi rõ là **đo** (measured) hay **ngoại suy** (extrapolated).

> **Đang chuyển sang microservices.** Mục 1–6 mô tả database của code hiện tại: một database, nhiều schema. Kiến
> trúc đã chốt (`docs/architecture/README.md`) tách thành 4 service, mỗi service một database trên cùng PostgreSQL
> server. Thiết kế bảng, hypertable, aggregate, policy và các số đo bên dưới giữ nguyên; thứ thay đổi là bảng nào nằm
> ở database nào, phân quyền, và cách Copilot đọc dữ liệu. Xem **mục 7**. Thứ tự làm nằm trong
> `docs/superpowers/plans/2026-11-10-microservices-split.md`.

## 1. Vì sao chọn stack này

Toàn bộ dữ liệu nằm trong **một instance PostgreSQL 18 với TimescaleDB 2.31 và pgvector** (image pin
`timescale/timescaledb:2.31.0-pg18`; lên từ PG17 ngày 2026-11-10, xem mục 4). Lý do chính: billing, Copilot (Text-to-SQL) và các màn hình đều
cần join dữ liệu time series với dữ liệu quan hệ (home, device, tariff). Đặt chung một chỗ thì join làm
bằng SQL, chỉ có một hệ thống để backup và phân quyền, và con số kWh/VND chỉ được tính ở một nơi.

Các phương án bị loại:

- **InfluxDB cho readings + PostgreSQL cho phần còn lại**: hai hệ thống, join với billing/device phải
  làm trong code ứng dụng, Text-to-SQL khó hơn nhiều.
- **Vector DB riêng**: pgvector đủ cho knowledge base ở giai đoạn này (`public.tb_chunk.embedding` là
  `vector(1024)` với index HNSW), không cần thêm một dịch vụ nữa.
- **Redis cho luồng live + object storage cho dữ liệu lạnh**: chưa cần, xem quyết định bên dưới.

Các quyết định của người dùng định hình thiết kế:

- **Không có realtime waveform** hay stream dưới một giây. Màn hình "Now" **poll** API vài giây một lần
  và đọc từ database.
- **Nhiều tài khoản vào một home** bằng mã: meter có pairing code dùng một lần (chỉ lưu hash) để gắn vào
  home, thành viên khác vào bằng invite code (`public.tb_home_invite`, cũng chỉ lưu hash). Mỗi tài khoản
  thuộc đúng một home (`UNIQUE (user_id)` trên `public.tb_home_member`).
- **Chưa dùng Redis, object storage**. Schema không chặn việc thêm chúng sau này.

## 2. Hình dạng dữ liệu

Các bảng nghiệp vụ hiện cùng nằm trong schema `public`; data mart AI và hội thoại nằm trong schema `ai`. Trung tâm là `public.tb_series`: một dòng cho mỗi (home, kênh, metric), và
hai hypertable chỉ trỏ vào `series_id` (số nguyên nhỏ) chứ không lặp lại home hay device. Dữ liệu đo
(`main` = công tơ tổng, `plug` = thiết bị đo riêng) vào `public.tb_reading`; kết quả NILM vào
`public.tb_device_estimate` (upsert, lần chạy mới nhất thắng). Mọi màn hình đọc từ continuous aggregate,
không bao giờ quét raw. Tiền là `numeric`, công suất là `real` (W), năng lượng suy ra là
`double precision`, thời gian luôn là `timestamptz` UTC; ngày được cắt theo `Asia/Ho_Chi_Minh`.
Foreign key có ở mọi nơi trừ chiều đi vào hypertable (tính toàn vẹn của `series_id` do ingest path bảo
đảm).

| Schema | Bảng / view |
|---|---|
| `public` | Các bảng nghiệp vụ `tb_*`, catalog `cat_*`, gồm auth profile, home/device, energy raw và continuous aggregates, billing, insight, ops, knowledge, suggestions và scope token |
| `ai` | `ai_conversation`, `ai_message`, `ai_tool_call`; `dim_tariff_plan`, `dim_home`, `dim_device`; views `fact_reading_1m`, `fact_estimate_1m`, `fact_energy`; bảng `metric_definition` |
| `copilot_ro` | 15 view chỉ đọc cho Copilot: `home`, `device`, `series`, `bill`, `bill_item`, `alert`, `device_cycle`, `suggestion`, `forecast_snapshot` và 6 view bọc các aggregate; hàm `current_home()` |

## 3. Đường ghi và đường đọc

### Ingest

Mọi nguồn dữ liệu đi qua một hàm duy nhất, `app/services/ingest.py::ingest_readings`: nhận các dòng
`(meter serial, channel, ts, value, quality)`, tra `series_id` qua `series(meter_id, source_channel)`,
COPY các dòng hợp lệ vào một temp table staging, rồi `INSERT ... ON CONFLICT (series_id, ts) DO NOTHING`
và cập nhật `public.tb_ingest_checkpoint` theo từng series. Mỗi lần gọi ghi một dòng `public.tb_ingest_batch` với
`rows_in = rows_new + rows_dup + rows_bad`, nên nạp lại cùng một file không đổi dữ liệu (idempotent), nhưng mỗi lần gọi vẫn ghi một dòng `public.tb_ingest_batch`. Vì vòng phân
loại giữ mọi dòng trong bộ nhớ, caller phải chia nhỏ input (50k-500k dòng mỗi lần gọi). Endpoint cho
meter sau này sẽ gọi hàm này. Dữ liệu seed REFIT House 2 thì không đi qua đây: revision Alembic
`b2183c4aca1c` ghi thẳng vào `public.tb_reading` theo batch `INSERT ... SELECT unnest(...) ON CONFLICT DO
NOTHING` và lưu watermark từng đoạn (test trước, train sau) trong `etl.tb_watermark`.

### Continuous aggregates

Các aggregate xếp tầng 1m → 1h → 1d, mỗi tầng có `avg_w, min_w, max_w, last_w, n` và `energy_wh`; tầng
1h và 1d có thêm `covered_minutes`. Quy tắc năng lượng: ở tầng 1m, một phút có ít nhất một mẫu tốt
(`quality & 1 = 0`) được tính `avg_w × 60 / 3600`; tầng trên **cộng** `energy_wh` của các bucket con
đang có, thời gian thiếu tính là 0 Wh và không bao giờ được lấp. Bucket ngày cắt theo
`Asia/Ho_Chi_Minh` (17:00 UTC). Real-time aggregation bật, nên phần dữ liệu mới hơn watermark vẫn được
trả về đúng; người đọc dừng ở bucket đã đóng.

### Read model cho màn hình Meter

`app/services/meter.py` chọn bước nhỏ nhất trong thang `1m, 5m, 15m, 30m, 1h, 3h, 6h, 1d` sao cho chuỗi
không vượt `max_points` (tối đa 2000, cửa sổ tối đa 90 ngày). Các bước 5m-30m re-bucket từ `reading_1m`,
3h-6h từ `reading_1h`, 1d đọc `reading_1d`. `latest_power` lấy bucket 1 phút đã đóng mới nhất trong 7
ngày gần nhất.

### Billing

Home trỏ vào **mã** tariff plan; khi EVN đổi giá thì thêm một `tariff_version` có ngày hiệu lực, không
phải sửa home nào. Đã seed hai phiên bản biểu giá sinh hoạt: Quyết định **1279/QĐ-BCT** (6 bậc, từ
2025-05-10) và Quyết định **2892** (5 bậc, từ 2026-11-01). `compute_bill` tính lại `public.tb_bill` một
cách idempotent từ `reading_1d` theo `billing_cycle_day`, dùng phiên bản hiệu lực tại `period_start`;
chu kỳ vắt qua ngày đổi giá được đánh dấu `tariff_straddle` (chưa chia hóa đơn hay prorate bậc vì quy
tắc chính thức chưa được xác nhận). Coverage dưới 95% thì hóa đơn có trạng thái `partial` thay vì âm
thầm tính thiếu. Chi phí theo thiết bị = tỉ lệ kWh × tiền trước VAT. **Lưu ý VAT:** cả hai phiên bản
đang seed `vat_rate = 0.08` theo đợt giảm VAT 2025-2026, chưa được xác nhận từ văn bản chính thức cho
điện; nếu VAT trở lại 10% thì cần một version mới.

### Cô lập Copilot

> Cơ chế dưới đây (`copilot_ro`, scope token) bị thay khi tách service: Copilot không còn kết nối tới database dữ liệu
> tiêu thụ nữa mà gọi API truy vấn an toàn của public. Xem mục 7.3.

Copilot không đọc bảng mà chỉ đọc view `copilot_ro.*` (owner là migration owner, `security_barrier`)
cộng `public.*`, `public.*` và các bảng tariff. Phạm vi home do một **scope token** quyết định:
`wattprint_app` ghi một dòng `public.tb_scope_token` (uuid ngẫu nhiên, hết hạn sau 5 phút), session
Copilot đặt `app.copilot_token`, và hàm `SECURITY DEFINER` `copilot_ro.current_home()` phân giải nó.
Token thiếu, rỗng, sai định dạng, không tồn tại hoặc hết hạn trả về NULL, nên mọi view trả 0 dòng
(fail closed). Role `wattprint_copilot_ro` có `statement_timeout = 5s`. Backend phải đặt token qua bind
parameter (`set_config('app.copilot_token', $1, true)`), không bao giờ nhúng literal, và dùng
`is_local = true` để connection trong pool không mang token của home trước.

Giới hạn còn lại (đã ghi trong spec, mục 8): role có thể tự đổi session setting của nó; mọi session
Copilot dùng chung một role nên SQL tự do có thể đọc `pg_stat_activity` hoặc `pg_cancel_backend` session
bên cạnh; PUBLIC vẫn có TEMP và EXECUTE trên `public.set_policies` và `public.immutable_unaccent`; role đọc được metadata nội bộ của
TimescaleDB (tên hypertable, khoảng chunk, không có giá trị theo home); một vài cột `device_id` /
`alert_id` có thể trỏ sang id của home khác (chỉ lộ số ID, join không ra gì). Vì vậy executor SQL của
Copilot **phải** có login riêng (không `SET ROLE` từ login của app) và một validator chạy trên parse tree
chỉ cho phép một câu SELECT, chặn `set_config`, `current_setting` của `app.*` và các hàm admin `pg_*`.

## 4. Quy tắc vận hành

- **Chunk và compression:** hypertable chunk 1 ngày, compress sau 2 ngày, `segmentby series_id`. Hai
  aggregate 1m cũng được compress (migration `f3a9c1e5b7d2`), `compress_after` 14 ngày, luôn phải lớn
  hơn `start_offset` 7 ngày của refresh policy 1m. Aggregate 1h/1d nhỏ, không compress.
- **Retention:** raw `reading`, `device_estimate` và aggregate 1m giữ 400 ngày; 1h và 1d giữ vô thời
  hạn. Retention luôn là `drop_chunks` qua policy, không bao giờ `DELETE` từng dòng.
- **Refresh policy:** 1m mỗi phút (cửa sổ 7 ngày), 1h mỗi giờ (30 ngày), 1d mỗi giờ (60 ngày).
- **`public.set_policies(true|false)`** bật/tắt toàn bộ policy một cách idempotent. Chú ý: `alembic upgrade
  head` **bật tất cả policy** (14 job). Trước khi nạp lịch sử cũ hơn 400 ngày phải gọi
  `public.set_policies(false)`, nếu không retention sẽ xóa chính dữ liệu vừa nạp; nạp xong, backfill rồi mới
  bật lại. CLI nạp REFIT từ chối chạy (mã thoát 2, thông báo nêu `--shift-days` hoặc `set_policies(false)`) khi job retention hoặc compression của `public.tb_reading` đang bật và dữ liệu sau khi dời cũ hơn cửa sổ của chúng; `--allow-active-policies` để ghi đè.
- **Backfill:** dữ liệu trễ cũ hơn cửa sổ refresh được lấy bằng
  `app/services/aggregates.py::backfill_aggregates` (Python, async, connection AUTOCOMMIT, vì
  `refresh_continuous_aggregate` không chạy được trong transaction hay function). Hàm có **guard** mặc
  định: theo từng series và từng ngày địa phương, ngày nào có số dòng đã materialize (`n`) lớn hơn số raw
  còn lại thì bỏ qua và trả về dưới dạng `SkippedWindow`, vì refresh trên vùng raw đã bị drop sẽ xóa
  bucket 1h/1d đang có. `allow_missing_raw=True` chỉ dùng khi rebuild từ đầu. **Giới hạn đã biết:**
  guard so `n` với số raw còn lại, nên trên một ngày bị drop một phần, các dòng trễ của cùng series có
  thể đưa số raw về bằng hoặc vượt `n` và che mất phần đã mất; qua được guard không chứng minh raw còn
  nguyên. Quy tắc thực tế: không backfill cửa sổ cũ hơn retention của raw. Backfill lịch sử dài nên chạy
  từ mới về cũ (xem mục chi phí refresh 1d bên dưới).
- **Roles:** migration chạy bằng login owner của database (`POSTGRES_USER`); các role gồm
  `wattprint_app`, `wattprint_ingest`, `wattprint_copilot_ro` và `wattprint_ai` (login
  `wattprint_ai_user`). AI chỉ đọc dimensions/facts, đọc/ghi conversation; app cũng có quyền
  quản lý conversation và dimensions.
  Quyền của `wattprint_app` chỉ đến từ ma trận quyền (`4d7b1e9a3c52`) và các revision `ai`;
  `cf93b7d8a102` chỉ tạo role, không cấp `ALL PRIVILEGES` hay default privileges.
- **Migration** viết tay bằng Alembic, mỗi thay đổi một revision, DDL của TimescaleDB đặt trong
  `op.execute`, refresh trong `autocommit_block()`. Database phải dựng lại được từ volume rỗng.
- **Image** pin `timescale/timescaledb:2.31.0-pg18`; nâng cấp là một thay đổi có chủ đích. Lên PG18 ngày
  2026-11-10 vì I/O bất đồng bộ (`io_method`) cho quét tuần tự, refresh và vacuum; TimescaleDB
  hỗ trợ PG18 từ 2.23. Volume PG17 cũ không dùng tiếp: compose dùng volume mới `wattprint_pg18data` mount vào
  `/var/lib/postgresql` (PG18 để `PGDATA` ở `/var/lib/postgresql/18/docker`), dữ liệu nạp lại. Compose đặt
  `timescaledb.enable_cagg_reorder_groupby = off` để tránh timescale/timescaledb#10500 (lỗi chỉ có trên PG18 với
  một số truy vấn `DISTINCT`/`GROUP BY` + `ORDER BY` trên continuous aggregate).

## 5. Kết quả đo

Dữ liệu: REFIT house 1-3 nạp qua đúng ingest path, ngày được dời để kết thúc vào 2026-10-31, policy tắt
trong lúc nạp. Máy audit: PostgreSQL 17.11 (đo trước khi lên PG18, chưa đo lại), TimescaleDB 2.31.0, 16 CPU, `shared_buffers` 3GB.

| Hạng mục | Kết quả | Loại |
|---|---|---|
| Khối lượng | 196,881,280 reading + 177,193,152 dòng `device_estimate`, khoảng 5.1 home-year | đo |
| Tốc độ nạp | 49,583 reading/s một luồng (house 1); hai luồng song song 81,141 reading/s tổng (khoảng 44.7k mỗi luồng); batch 30k dòng CSV, policy tắt | đo (bulk load) |
| Idempotency | nạp lại 1,000,000 reading: 0 mới, 1,000,000 trùng, count và checksum `reading_1d` không đổi, cả trên chunk đã compress | đo, PASS |
| Compression raw | 17x trên cả hai hypertable (`reading` 18.8 GB → 1.1 GB, 5.6 byte/reading); kết quả theo ngày giống hệt trước và sau | đo |
| Aggregate | chưa compress 6.5 GB (3x raw đã compress); compress 1m trên bản sao một tháng của house 1: 19.1x (`reading_1m`) và 23.1x (`device_estimate_1m`); áp lên toàn bộ dữ liệu audit dự kiến còn khoảng 0.3 GB | đo trên bản sao; con số 0.3 GB là ngoại suy |
| Dung lượng mỗi home-year | 0.88 GB (`reading` + các aggregate của nó, chưa compress; **không** gồm `device_estimate` và aggregate của nó) | đo |
| Latency p95 (warm / cửa sổ thay đổi, ms) | series 1d/90 ngày 4.0 / 3.7; 6h/90 ngày 6.3 / 5.3; 1h/45 ngày 5.7 / 5.7; 5m/1 ngày 4.4 / 10.8; Week (15m/7 ngày) 11.6 / 52.3; `latest_power` 2.5 / 4.3; device breakdown 1 ngày 3.1 / 2.8, 30 ngày 3.9 / 3.4; `compute_bill` 16.3 / 17.0 | đo, PASS (mục tiêu 100 ms, `latest_power` 20 ms) |
| Điều kiện đo latency | đo **trước** 10c: aggregate 1m chưa compress, policy tắt; đọc trên 1m đã compress chỉ đo trên bản sao một tháng (1.4-2.0 ms p95), chưa đo trên toàn bộ dữ liệu | đo |
| Latency khi watermark tụt | 772 dòng raw mới hơn cả ba watermark: điểm cuối của mọi tầng hiển thị giá trị mới; p95 1.9 (`latest_power`), 5.0 (1d), 5.7 (1h), 4.4 (5m), 11.3 (Week) | đo |
| Plan | aggregate đọc 0-11 chunk relation, 0 shared read; sau khi restart server, lần gọi đầu 2.6-48 ms (page cache của OS vẫn ấm) | đo |
| Failure drill | trùng batch, dữ liệu trễ và sai thứ tự, khoảng trống 90 phút, dòng gắn cờ `Issues`, refresh job dừng: 5/5 PASS | đo |
| Isolation | 2 home, 15 view, 4 biến thể token xấu, không truy cập bảng trực tiếp, không ghi được | đo, PASS |
| Rebuild | DB rỗng → `alembic upgrade head` → nạp 100,000 reading (10 series, 22 device type, 11 tariff tier seed), 0 bước tay, 14 policy job sau migration | đo, PASS |
| Retention drill | raw drop không chạm bucket 1m/1h/1d; job retention 1m xóa bucket 1m (71,280 → 0), 1h (1,200) và 1d (50) còn nguyên; backfill không guard trên vùng đã drop xóa 1h/1d về 0, backfill mặc định (có guard) bỏ qua 2 cửa sổ và giữ nguyên | đo trên bản sao |

**Caveat của drill refresh dừng:** khi job refresh dừng, dòng trễ rơi vào vùng đã materialize nằm trong
raw (180 dòng) nhưng **không** hiện qua aggregate (0 điểm) cho tới khi có refresh; refresh tay xong thì
ra đúng 300 Wh. Chỉ dữ liệu mới hơn watermark là luôn tươi.

**Chi phí refresh 1d.** Khi backfill toàn bộ lịch sử, refresh 1d mất 1,478-1,621 s so với khoảng 21 s
cho 1h trên cùng dữ liệu. Ở trạng thái ổn định thì không đáng kể: refresh cưỡng bức 30 ngày tốn 0.09 s
cho 1d và 1.2 s cho 1h, một ngày bị invalidate refresh trong 13-17 ms (1h, 1d). Trên bản sao, refresh
1d của cửa sổ 30 ngày tốn 0.07 s khi đứng một mình, 6.5 s khi có thêm bốn tháng raw mới hơn chưa
materialize, và 0.04 s khi `reading_1m` và `reading_1h` được đặt `materialized_only`. Giải thích (suy ra
từ thời gian đo, **chưa chứng minh**): nhánh real-time của view nguồn bị tính trong lúc refresh. Vì vậy
backfill lịch sử dài nên chạy từ mới về cũ, hoặc chuyển 1m/1h sang `materialized_only` trong lúc chạy
(chưa test).

**Ngoại suy cho 10,000 home.** Spec không nêu tần số lấy mẫu nên có ba kịch bản (toàn bộ là **ngoại
suy** từ house 1-3):

| Kịch bản | Dòng/ngày | Trung bình dòng/s | TB/năm (1m compress / không compress) |
|---|---|---|---|
| Giống REFIT: 10 series, 7 s | 1.23 tỉ | 14.3k | 3.1 / 10.6 |
| Chỉ công tơ tổng, 1 Hz | 864 triệu | 10k | 1.8 / 2.6 |
| 10 series, 30 s, kèm 9 device estimate | 288 triệu | 3.3k | 2.1 / 16.3 |

Giả định: chỉ là trung bình (không có peak factor), chưa áp retention raw, compression 17x cho mọi tần
số, mọi phút đều có dữ liệu (cận trên; REFIT đo được 0.88 GB/home-year so với 1.06 dự đoán). Con số
49.6k dòng/s là bulk load một luồng; ingest batch nhỏ từ nhiều meter đồng thời **chưa được test**, nên
không có khẳng định nào rằng hệ thống giữ được các mức trung bình trên.

## 6. Việc còn mở

- **Gate năng lượng 1% theo từng home-day: FAIL như đã đo, với cả hai tham chiếu.** `test_energy_gate_one_percent` đo tham chiếu **đã sửa** của spec (giữ qua mẫu gắn cờ, cap 120 s): 19/512, 16/432, 30/415 ngày vượt 1% (max 3.7 / 2.4 / 4.4%, p95 0.80 / 0.92 / 1.22%). Tham chiếu ban đầu chỉ còn là chẩn đoán được ghi lại. Với tham chiếu ban đầu (giữ mẫu tối đa 5 ×
  cadence trung vị = 35 s, mẫu gắn cờ tính là thời gian thiếu), 507 trên 1,359 ngày có coverage ≥ 95%
  lệch hơn 1% (max 54%, p95 1.9-5.4%), view gần như luôn cao hơn. Nguyên nhân: meter REFIT thường log
  khoảng 62 s một lần, cap 35 s coi đó là thiếu trong khi `energy_wh` tính trọn phút; và mẫu gắn cờ
  `Issues` là thời gian thiếu ở tham chiếu nhưng được phủ ở view. Với tham chiếu đã sửa trong spec (giữ
  qua mẫu gắn cờ, cap 120 s): p95 0.8-1.2%, max 2.4-4.4%, vẫn còn 16-30 ngày mỗi house vượt 1% (chưa
  điều tra). **Cần chủ spec quyết định:** giữ gate 1% cho mọi ngày, hay chấp nhận cách phát biểu theo
  p95 ("p95 khoảng 1%, max 4.4%"). Đến lúc đó `test_energy_gate_one_percent` vẫn là xfail mang số đo.
- **Read model của device và billing chỉ đọc series `kind = 'device'` (NILM).** Nhà chỉ có series `plug` (REFIT) sẽ có device breakdown rỗng và các kênh plug không xuất hiện trong bill item. Cần quyết định (đọc cả `plug`, hay dựng series `device` từ plug) trước khi làm API.
- **Ingest dùng bảng TEMP staging nên phụ thuộc quyền `TEMP` của `PUBLIC`.** Nếu sau này chạy `REVOKE TEMPORARY ON DATABASE ... FROM PUBLIC` thì ingest hỏng, trừ khi `wattprint_ingest` được cấp `TEMP` riêng.
- **Migration nền tảng đặt mật khẩu role dưới dạng literal trong `ALTER ROLE`,** nên nhìn thấy được trong log khi `log_statement = ddl|all`. Cần đổi cách đặt mật khẩu (hoặc tắt log DDL) ở môi trường thật.
- **House 4-20 chưa nạp.** Tăng trưởng được ngoại suy từ house 1-3; nạp đủ 20 house là quyết định sau.
- **Ingest đồng thời chưa test:** chưa đo ingest batch nhỏ từ nhiều meter cùng lúc, cùng với compression
  và refresh chạy song song.
- **Giới hạn của guard backfill:** dòng trễ cùng series trên một ngày địa phương bị drop một phần có thể
  che mất phần đã mất (xem mục 4). Chi phí của guard ở quy mô audit chưa đo.
- **VAT 8%** trên cả hai tariff version cần xác nhận từ văn bản chính thức.
- **Executor SQL của Copilot** cần login riêng và validator SELECT-only trên parse tree trước khi cho
  chạy SQL tự do.
- **Các điểm nhỏ đã hoãn nên biết:** migration `f3a9c1e5b7d2` dùng tên option `timescaledb.compress*`
  cũ (xem lại khi nâng image); tên index trong model và migration lệch nhau nên `alembic check` /
  autogenerate không dùng được; `device_breakdown` vẫn trả thiết bị đã xóa/merge (lọc ở tầng API); chưa
  có `bill_item` cho `always_on` và chưa có ràng buộc chống chồng lấn ngày hiệu lực của tariff version;
  `public.stale_series` dựa vào checkpoint nên series chưa bao giờ báo dữ liệu không xuất hiện; view "khoảng
  trống dài hơn N phút" của spec mục 6.8 chưa làm; `public.tb_scope_token` không có job dọn, backend phải
  tự prune.

## 7. Khi tách thành microservices

### 7.1 Một server, năm database

Vẫn đúng server ở mục 1 và 4 (PostgreSQL 18, TimescaleDB 2.31, pgvector). ID của bản ghi mới dùng số nguyên tự tăng.
Lỗi #10500 (mục 4) đáng chú ý vì Text-to-SQL có thể sinh ra đúng dạng truy vấn đó.
Mỗi service một database và một role; role của service này không có quyền `CONNECT` vào database của service khác.
Keycloak cũng dùng một database trên server này thay cho container `keycloak-db` riêng.

| Database | Chủ | Nội dung (lấy từ schema hiện tại) | Extension |
|---|---|---|---|
| `core_db` | core | `public.tb_users`; `public.tb_home`, `home_member`, `home_invite`, `meter`, `device`; `public.*`; `public.tb_series`, `reading`, `device_estimate` và 6 continuous aggregate; `public.*`; `public.*`; thêm `outbox` | TimescaleDB |
| `nilm_db` | nilm | `public.tb_inference_run`; thêm danh mục phiên bản model và tham số hiệu chỉnh theo hộ | |
| `insight_db` | insight | `public.tb_device_cycle`, `alert`, `forecast_snapshot`, `cohort_stat`; `public.tb_savings_measure`; `public.tb_weather_hourly`; `public.tb_device_alert_rule`; thêm read model tiêu thụ theo giờ (hypertable), bản sao danh mục thiết bị, view cho truy vấn an toàn, `inbox`, `outbox` | TimescaleDB |
| `copilot_db` | copilot | `ai.ai_conversation`, `ai.ai_message`, `ai.ai_tool_call`; `public.tb_suggestion`, `public.tb_suggestion_feedback`; thêm bảng saga, `inbox`, `outbox` | pgvector, unaccent, pg_trgm |
| `keycloak_db` | Keycloak | Do Keycloak tự quản | |

Bỏ hẳn: schema `copilot_ro`, `public.tb_scope_token`, role `wattprint_copilot_ro`.

### 7.2 Không còn join chéo giữa các database

Lý do ở mục 1 ("join bằng SQL, số kWh/VND chỉ tính ở một nơi") vẫn đúng **bên trong** core: billing, reading,
aggregate, tariff cùng nằm ở `core_db`, nên hóa đơn vẫn tính bằng một câu SQL ở một nơi. Phần cần dữ liệu của service
khác đi theo hai cách:

- **Sự kiện:** core phát `public.usage.updated` (tổng theo giờ từng thiết bị) và `public.tb_device.changed`; insight lưu
  bản sao vào read model của nó. Đây là pattern CQRS: insight đọc nhanh, không chạm database ghi của public.
- **Gọi API:** insight hỏi core biểu giá khi dự báo hóa đơn; copilot hỏi insight số liệu qua tool.

Hệ quả: read model của insight có độ trễ (thường vài giây sau khi batch xong), và có thể lệch tạm thời khi một
message nằm trong DLQ. Màn hình nào cần số chính xác tuyệt đối (hóa đơn) thì đọc từ public.

### 7.3 Copilot đọc dữ liệu thế nào

Thay cho `copilot_ro` + scope token: copilot gọi `POST /queries` của public. Insight chạy câu SQL do LLM sinh trên
các view của `insight_db`, với các yêu cầu đã nêu ở mục 3 (Cô lập Copilot) chuyển sang SQL guard của insight:

- chỉ một câu `SELECT`, kiểm trên parse tree; chặn `set_config`, `current_setting`, hàm `pg_*`;
- `home_id` lấy từ header `X-User-Id` đã qua gateway (không lấy từ câu hỏi), ép vào mọi view;
- chạy bằng một login riêng chỉ có `SELECT` trên các view đó, `statement_timeout = 2s`;
- sai bất kỳ điều nào → 400, không chạy.

### 7.4 Migration

Mỗi service có thư mục Alembic riêng và một migration nền mới cho database của nó, gộp phần tương ứng của 26 revision
hiện tại. Hiện tại các revision vẫn chạy thành một chuỗi Alembic tuyến tính chung; `versions/public/` và
`versions/ai/` phân loại revision tạo đối tượng mới theo schema, còn `versions/updates/` dành cho thay đổi đối tượng
đã có hoặc luồng chung. Các thư mục này chưa tạo hai nhánh Alembic độc lập. Chuỗi revision cũ dừng ở `a7c2e9f4b1d6`
và không chạy tiếp. Các quy tắc ở mục 4 (DDL TimescaleDB trong
`op.execute`, refresh trong `autocommit_block()`, dựng lại được từ volume rỗng, `public.set_policies`) áp dụng nguyên
cho `core_db` và `insight_db`.

### 7.5 Việc mở thêm khi tách

- Kết quả đo ở mục 5 là của một database trên PostgreSQL 17.11; sau khi tách và lên PG18 cần chạy lại ít nhất bài idempotency, failure drill và
  latency trên `core_db`.
- Cột `device_id`, `home_id` ở `insight_db` và `copilot_db` không còn foreign key tới `core_db`; tính đúng dựa vào sự
  kiện `public.tb_device.changed`. Thiết bị bị xóa ở core phải phát sự kiện để insight dọn theo.
