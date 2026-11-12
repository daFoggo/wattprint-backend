# Pipeline dữ liệu và dashboard live

Ngày chốt: 2026-11-12. Phạm vi: backend monolith hiện tại + `wattprint-web/apps/dashboard`. Khi tách microservice
(`2026-11-10-microservices-split.md`) contract ở đây giữ nguyên, chỉ đổi chỗ chạy.

## Quyết định

| Câu hỏi | Chốt | Lý do |
|---|---|---|
| Redis | Không | Cache phía server đã là continuous aggregate; bài toán "mở lại web thấy số cũ" nằm ở trình duyệt |
| Thư viện fetch phía client (TanStack Query, SWR) | Không | Server-first theo `wattprint-web/docs/data-fetching.md`; live đi qua một luồng SSE |
| Cập nhật live | **Phương án A**: một SSE mỗi trang báo "cái gì vừa đổi" | Dữ liệu đổi theo sự kiện backend, không theo đồng hồ |
| NILM lỗi | Không rollback số đo | `tb_reading` là nguồn sự thật; NILM là bước dẫn xuất chạy lại được |

## Luồng dữ liệu

```
REFIT replayer (scripts/replay_refit.py)        ← thay cảm biến thật; sau này gọi qua API ingest
  │ dời giờ theo bội số tuần, lấp khoảng trống tới "now" rồi tail mỗi 5 s
  ▼
ops.ingest_readings  (validate, dedupe, COPY, tb_ingest_batch, checkpoint 'replay')
  ▼
tb_reading (hypertable) → reading_1m/1h/1d (policy refresh, real-time aggregation cho bucket mở)
  │
  ├─ GET  /api/v1/energy/overview   live + hôm nay so với cùng thứ các tuần trước (không còn hoá đơn: GET không ghi DB)
  ├─ GET  /api/v1/energy/series     meter_series (biểu đồ)
  └─ GET  /api/v1/energy/stream     SSE: event `reading` khi có số đo mới của công tơ tổng
  │
  ▼ (bước sau) NILM worker theo checkpoint
     pending = checkpoint('replay') > checkpoint('nilm'); chạy model → ingest_estimates(run_id)
     → nâng checkpoint 'nilm' cùng transaction → SSE event `nilm.updated`
```

### Xử lý lỗi

- Dòng hỏng: đếm `rows_bad`, không làm hỏng batch. Gửi lại batch: `ON CONFLICT DO NOTHING`, không trùng.
- Lỗi DB khi ghi: batch `failed` + note, dữ liệu rollback qua savepoint, nguồn gửi lại.
- NILM lỗi: checkpoint `nilm` đứng yên, `inference_run.status='failed'`, lần sau chạy lại (upsert, run mới thắng).
  Đây là `PENDING_INFERENCE` của kế hoạch tách service. UI hiện "đã phân tích đến HH:MM".
- Giới hạn: số đo đến muộn trước checkpoint `nilm` không được NILM tự chạy lại; chạy lại khoảng đó bằng tay.

## Frontend (`apps/dashboard`)

| Tầng độ tươi | Dữ liệu | Cách cập nhật |
|---|---|---|
| Giây | Công suất hiện tại, trạng thái cảm biến, đuôi biểu đồ live | Client island nhận SSE `reading` |
| Ngày | So sánh tuần/tháng, 30 ngày | Render khi vào trang; trang Overview không còn tile đổi trong ngày nên `reading` không refresh route |
| NILM (~5 phút) | Bong bóng thiết bị, dòng sự kiện, always-on | `router.refresh()` khi có `nilm.updated` (chưa có: dùng dữ liệu mẫu, gắn nhãn rõ) |

- Lần đầu vào: App Shell + mỗi widget một `<Suspense>` có skeleton đúng kích thước.
- Trong phiên: `"use cache: private"` + `cacheLife` ngắn; refresh chạy trong `useTransition`, UI cũ giữ nguyên.
- Đổi số: `NumberRoll`; biểu đồ live: `LiveLineChart`, cửa sổ 5 phút.
- SSE đi qua Route Handler `app/api/energy/stream/route.ts` (token giữ phía server, `connection()`).
  Backend gửi 5 phút mẫu gần nhất khi mở rồi từng mẫu mới, đóng sau 10 phút để kiểm lại auth;
  client bỏ mẫu trùng khi kết nối lại, lỗi thì thử lại 10 s → 20 s → … tối đa 5 phút.
- Trang Overview (bento 12 cột): Thiết bị (`DonutChart`, Now W / Today kWh, mẫu) | Live (`LiveLineChart`, 5 phút)
  · Thời tiết (OpenWeather, cache 10 phút) | So sánh (`CompareBars`, bật sẵn, Week = 7 ngày, Month = 4 tuần, cột
  trượt khi đổi) | Hoạt động (`LogStream`, mẫu, cao 2 hàng) · 30 ngày (`ComboChart`). Đơn vị đứng sau số (prop
  `unit` vá vào qua `packages/ui/hairline/patch.mjs`, Intl không có kWh/W).
  Ngày không có số đo được tính 0 kWh (khoảng trống REFIT hiện thành cột 0).
  Đã bỏ: hoá đơn tạm tính, theo giờ, BalanceMeter hôm nay. Không dùng `TickTape` và `Pace` (sai nghĩa).

### Đã gặp

- Seed REFIT nạp raw nhưng không refresh aggregate: policy chỉ quét 7/30/60 ngày và watermark đã vượt
  qua lịch sử, nên `reading_*` trống. Revision `5d0c9a3e7f21` (updates) refresh theo cửa sổ nửa đêm-nửa
  đêm, dừng trước bucket còn mở của hôm nay; DB đã migrate trước đó cũng nhận được qua revision mới này.

## Thứ tự làm

1. Backend: `CurrentHome`, `/energy/overview`, `/energy/series`, `/energy/stream` + test.
2. Replayer REFIT lấp khoảng trống và tail.
3. Web: feature `energy` (schemas, server, queries), Route Handler SSE, trang Overview dạng bento.
4. Sau: NILM worker theo checkpoint, `nilm.updated`, thay dữ liệu mẫu bằng API thật.
5. Chỉ khi có số đo chứng minh cần: ETag, Redis, thư viện fetch phía client.
