# Thiết kế database WattPrint

Tài liệu này dành cho người mới vào dự án: vì sao database được dựng như hiện tại, dữ liệu chạy qua
đâu, phải vận hành theo quy tắc nào, và bài audit với dữ liệu REFIT đã đo được gì. Chi tiết đầy đủ nằm
ở spec (`docs/superpowers/specs/2026-11-01-database-design-design.md`) và bản audit
(`docs/database-audit.md`, số liệu gốc trong `docs/audit-results.json`). Mọi con số trong tài liệu này
lấy từ hai file audit đó và được ghi rõ là **đo** (measured) hay **ngoại suy** (extrapolated).

## 1. Vì sao chọn stack này

Toàn bộ dữ liệu nằm trong **một instance PostgreSQL 17 với TimescaleDB 2.31 và pgvector** (image pin
`timescale/timescaledb:2.31.0-pg17`). Lý do chính: billing, Copilot (Text-to-SQL) và các màn hình đều
cần join dữ liệu time series với dữ liệu quan hệ (home, device, tariff). Đặt chung một chỗ thì join làm
bằng SQL, chỉ có một hệ thống để backup và phân quyền, và con số kWh/VND chỉ được tính ở một nơi.

Các phương án bị loại:

- **InfluxDB cho readings + PostgreSQL cho phần còn lại**: hai hệ thống, join với billing/device phải
  làm trong code ứng dụng, Text-to-SQL khó hơn nhiều.
- **Vector DB riêng**: pgvector đủ cho knowledge base ở giai đoạn này (`knowledge.chunk.embedding` là
  `vector(1024)` với index HNSW), không cần thêm một dịch vụ nữa.
- **Redis cho luồng live + object storage cho dữ liệu lạnh**: chưa cần, xem quyết định bên dưới.

Các quyết định của người dùng định hình thiết kế:

- **Không có realtime waveform** hay stream dưới một giây. Màn hình "Now" **poll** API vài giây một lần
  và đọc từ database.
- **Nhiều tài khoản vào một home** bằng mã: meter có pairing code dùng một lần (chỉ lưu hash) để gắn vào
  home, thành viên khác vào bằng invite code (`core.home_invite`, cũng chỉ lưu hash). Mỗi tài khoản
  thuộc đúng một home (`UNIQUE (user_id)` trên `core.home_member`).
- **Chưa dùng Redis, object storage**. Schema không chặn việc thêm chúng sau này.

## 2. Hình dạng dữ liệu

Mỗi domain có một schema riêng. Trung tâm là `energy.series`: một dòng cho mỗi (home, kênh, metric), và
hai hypertable chỉ trỏ vào `series_id` (số nguyên nhỏ) chứ không lặp lại home hay device. Dữ liệu đo
(`main` = công tơ tổng, `plug` = thiết bị đo riêng) vào `energy.reading`; kết quả NILM vào
`energy.device_estimate` (upsert, lần chạy mới nhất thắng). Mọi màn hình đọc từ continuous aggregate,
không bao giờ quét raw. Tiền là `numeric`, công suất là `real` (W), năng lượng suy ra là
`double precision`, thời gian luôn là `timestamptz` UTC; ngày được cắt theo `Asia/Ho_Chi_Minh`.
Foreign key có ở mọi nơi trừ chiều đi vào hypertable (tính toàn vẹn của `series_id` do ingest path bảo
đảm).

| Schema | Bảng / view |
|---|---|
| `public` | `users`, `refresh_tokens` (có từ trước), `alembic_version` |
| `core` | `home`, `home_member`, `home_invite`, `meter`, `device`, `device_alert_rule` |
| `catalog` | `metric`, `device_type` (dữ liệu tham chiếu, seed sẵn) |
| `energy` | `series`, `reading` (hypertable), `device_estimate` (hypertable), `inference_run`, `weather_hourly`; continuous aggregate `reading_1m` → `reading_1h` → `reading_1d` và `device_estimate_1m` → `device_estimate_1h` → `device_estimate_1d` |
| `billing` | `tariff_plan`, `tariff_version`, `tariff_tier`, `bill`, `bill_item` |
| `insight` | `device_cycle` (hypertable), `alert`, `forecast_snapshot`, `cohort_stat` |
| `copilot` | `conversation`, `message`, `tool_call`, `suggestion`, `suggestion_feedback`, `savings_measure`, `scope_token` |
| `copilot_ro` | 15 view chỉ đọc cho Copilot: `home`, `device`, `series`, `bill`, `bill_item`, `alert`, `device_cycle`, `suggestion`, `forecast_snapshot` và 6 view bọc các aggregate; hàm `current_home()` |
| `knowledge` | `document`, `chunk` (pgvector HNSW + GIN full-text với `unaccent`) |
| `ops` | `ingest_batch`, `ingest_checkpoint`, view `series_daily_coverage`, `stale_series`; hàm `set_policies` |

## 3. Đường ghi và đường đọc

### Ingest

Mọi nguồn dữ liệu đi qua một hàm duy nhất, `app/services/ingest.py::ingest_readings`: nhận các dòng
`(meter serial, channel, ts, value, quality)`, tra `series_id` qua `series(meter_id, source_channel)`,
COPY các dòng hợp lệ vào một temp table staging, rồi `INSERT ... ON CONFLICT (series_id, ts) DO NOTHING`
và cập nhật `ops.ingest_checkpoint` theo từng series. Mỗi lần gọi ghi một dòng `ops.ingest_batch` với
`rows_in = rows_new + rows_dup + rows_bad`, nên nạp lại cùng một file là no-op (idempotent). Vì vòng phân
loại giữ mọi dòng trong bộ nhớ, caller phải chia nhỏ input (50k-500k dòng mỗi lần gọi). Loader REFIT
(`app.cli.load_refit`) chỉ là một CLI gọi đúng hàm này, mặc định 30.000 dòng CSV (mười reading mỗi dòng)
mỗi batch, nên REFIT thật sự chạy qua đường production; endpoint cho meter sau này cũng sẽ gọi hàm đó.

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
2025-05-10) và Quyết định **2892** (5 bậc, từ 2026-11-01). `compute_bill` tính lại `billing.bill` một
cách idempotent từ `reading_1d` theo `billing_cycle_day`, dùng phiên bản hiệu lực tại `period_start`;
chu kỳ vắt qua ngày đổi giá được đánh dấu `tariff_straddle` (chưa chia hóa đơn hay prorate bậc vì quy
tắc chính thức chưa được xác nhận). Coverage dưới 95% thì hóa đơn có trạng thái `partial` thay vì âm
thầm tính thiếu. Chi phí theo thiết bị = tỉ lệ kWh × tiền trước VAT. **Lưu ý VAT:** cả hai phiên bản
đang seed `vat_rate = 0.08` theo đợt giảm VAT 2025-2026, chưa được xác nhận từ văn bản chính thức cho
điện; nếu VAT trở lại 10% thì cần một version mới.

### Cô lập Copilot

Copilot không đọc bảng mà chỉ đọc view `copilot_ro.*` (owner là migration owner, `security_barrier`)
cộng `knowledge.*`, `catalog.*` và các bảng tariff. Phạm vi home do một **scope token** quyết định:
`wattprint_app` ghi một dòng `copilot.scope_token` (uuid ngẫu nhiên, hết hạn sau 5 phút), session
Copilot đặt `app.copilot_token`, và hàm `SECURITY DEFINER` `copilot_ro.current_home()` phân giải nó.
Token thiếu, rỗng, sai định dạng, không tồn tại hoặc hết hạn trả về NULL, nên mọi view trả 0 dòng
(fail closed). Role `wattprint_copilot_ro` có `statement_timeout = 5s`. Backend phải đặt token qua bind
parameter (`set_config('app.copilot_token', $1, true)`), không bao giờ nhúng literal, và dùng
`is_local = true` để connection trong pool không mang token của home trước.

Giới hạn còn lại (đã ghi trong spec, mục 8): role có thể tự đổi session setting của nó; mọi session
Copilot dùng chung một role nên SQL tự do có thể đọc `pg_stat_activity` hoặc `pg_cancel_backend` session
bên cạnh; PUBLIC vẫn có TEMP và EXECUTE trên `ops.set_policies` và `knowledge.immutable_unaccent`; role đọc được metadata nội bộ của
TimescaleDB (tên hypertable, khoảng chunk, không có giá trị theo home); một vài cột `device_id` /
`alert_id` có thể trỏ sang id của home khác (chỉ lộ UUID, join không ra gì). Vì vậy executor SQL của
Copilot **phải** có login riêng (không `SET ROLE` từ login của app) và một validator chạy trên parse tree
chỉ cho phép một câu SELECT, chặn `set_config`, `current_setting` của `app.*` và các hàm admin `pg_*`.

## 4. Quy tắc vận hành

- **Chunk và compression:** hypertable chunk 1 ngày, compress sau 2 ngày, `segmentby series_id`. Hai
  aggregate 1m cũng được compress (migration `f3a9c1e5b7d2`), `compress_after` 14 ngày, luôn phải lớn
  hơn `start_offset` 7 ngày của refresh policy 1m. Aggregate 1h/1d nhỏ, không compress.
- **Retention:** raw `reading`, `device_estimate` và aggregate 1m giữ 400 ngày; 1h và 1d giữ vô thời
  hạn. Retention luôn là `drop_chunks` qua policy, không bao giờ `DELETE` từng dòng.
- **Refresh policy:** 1m mỗi phút (cửa sổ 7 ngày), 1h mỗi giờ (30 ngày), 1d mỗi giờ (60 ngày).
- **`ops.set_policies(true|false)`** bật/tắt toàn bộ policy một cách idempotent. Chú ý: `alembic upgrade
  head` **bật tất cả policy** (14 job). Trước khi nạp lịch sử cũ hơn 400 ngày phải gọi
  `ops.set_policies(false)`, nếu không retention sẽ xóa chính dữ liệu vừa nạp; nạp xong, backfill rồi mới
  bật lại.
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
- **Roles:** migration chạy bằng login owner của database (`POSTGRES_USER`, spec gọi là
  `wattprint_owner` nhưng migration không tạo role tên đó); ba role do migration tạo: `wattprint_app` (API: DML trên bảng của nó, phát scope
  token), `wattprint_ingest` (INSERT readings và `ops`), `wattprint_copilot_ro` (SELECT trên whitelist).
  Grant theo từng object, không bao giờ `ALL TABLES`.
- **Migration** viết tay bằng Alembic, mỗi thay đổi một revision, DDL của TimescaleDB đặt trong
  `op.execute`, refresh trong `autocommit_block()`. Database phải dựng lại được từ volume rỗng.
- **Image** pin `timescale/timescaledb:2.31.0-pg17`; nâng cấp là một thay đổi có chủ đích.

## 5. Kết quả đo

Dữ liệu: REFIT house 1-3 nạp qua đúng ingest path, ngày được dời để kết thúc vào 2026-10-31, policy tắt
trong lúc nạp. Máy audit: PostgreSQL 17.11, TimescaleDB 2.31.0, 16 CPU, `shared_buffers` 3GB.

| Hạng mục | Kết quả | Loại |
|---|---|---|
| Khối lượng | 196,881,280 reading + 177,193,152 dòng `device_estimate`, khoảng 5.1 home-year | đo |
| Tốc độ nạp | 49,583 reading/s một luồng (house 1); hai luồng song song 81,141 reading/s tổng (khoảng 44.7k mỗi luồng); batch 30k dòng CSV, policy tắt | đo (bulk load) |
| Idempotency | nạp lại 1,000,000 reading: 0 mới, 1,000,000 trùng, count và checksum `reading_1d` không đổi, cả trên chunk đã compress | đo, PASS |
| Compression raw | 17x trên cả hai hypertable (`reading` 18.8 GB → 1.1 GB, 5.6 byte/reading); kết quả theo ngày giống hệt trước và sau | đo |
| Aggregate | chưa compress 6.5 GB (3x raw đã compress); compress 1m trên bản sao một tháng của house 1: 19.1x (`reading_1m`) và 23.1x (`device_estimate_1m`); áp lên toàn bộ dữ liệu audit dự kiến còn khoảng 0.3 GB | đo trên bản sao; con số 0.3 GB là ngoại suy |
| Dung lượng mỗi home-year | 0.88 GB (raw + aggregate chưa compress) | đo |
| Latency p95 (warm / cửa sổ thay đổi, ms) | series 1d/90 ngày 4.0 / 3.7; 6h/90 ngày 6.3 / 5.3; 1h/45 ngày 5.7 / 5.7; 5m/1 ngày 4.4 / 10.8; Week (15m/7 ngày) 11.6 / 52.3; `latest_power` 2.5 / 4.3; device breakdown 1 ngày 3.1 / 2.8, 30 ngày 3.9 / 3.4; `compute_bill` 16.3 / 17.0 | đo, PASS (mục tiêu 100 ms, `latest_power` 20 ms) |
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

- **Gate năng lượng 1% theo từng home-day: FAIL như đã đo.** Với tham chiếu ban đầu (giữ mẫu tối đa 5 ×
  cadence trung vị = 35 s, mẫu gắn cờ tính là thời gian thiếu), 507 trên 1,359 ngày có coverage ≥ 95%
  lệch hơn 1% (max 54%, p95 1.9-5.4%), view gần như luôn cao hơn. Nguyên nhân: meter REFIT thường log
  khoảng 62 s một lần, cap 35 s coi đó là thiếu trong khi `energy_wh` tính trọn phút; và mẫu gắn cờ
  `Issues` là thời gian thiếu ở tham chiếu nhưng được phủ ở view. Với tham chiếu đã sửa trong spec (giữ
  qua mẫu gắn cờ, cap 120 s): p95 0.8-1.2%, max 2.4-4.4%, vẫn còn 16-30 ngày mỗi house vượt 1% (chưa
  điều tra). **Cần chủ spec quyết định:** giữ gate 1% cho mọi ngày, hay chấp nhận cách phát biểu theo
  p95 ("p95 khoảng 1%, max 4.4%"). Đến lúc đó `test_energy_gate_one_percent` vẫn là xfail mang số đo.
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
  `ops.stale_series` dựa vào checkpoint nên series chưa bao giờ báo dữ liệu không xuất hiện; view "khoảng
  trống dài hơn N phút" của spec mục 6.8 chưa làm; `copilot.scope_token` không có job dọn, backend phải
  tự prune.
