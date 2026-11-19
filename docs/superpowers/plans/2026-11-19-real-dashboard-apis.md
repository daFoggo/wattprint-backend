# Bỏ toàn bộ mock của dashboard, thay bằng API thật

Ngày 2026-11-19. Mục tiêu: dashboard (`wattprint-web/apps/dashboard`) không còn dữ liệu mẫu, hàm giả lập hay `shortcut:`
nào chờ backend. Mọi số hiển thị đến từ DB hoặc từ nhà cung cấp thật, có test, đã audit (ponytail-audit) và tự click thử
khi đăng nhập.

Nguồn đã đọc: `docs/PROJECT_CONTEXT.md`, hai pitch deck, `docs/database-design*.md`, spec và plan trong
`docs/superpowers/`, sơ đồ `docs/architecture/06, 07`; phía web `docs/adding-a-feature.md`, `data-fetching.md`,
`advanced-patterns.md`, `authentication.md`, `internationalization.md`, skill `next-mono-base`,
`vercel-react-best-practices`, `design-system`, `hairline-ui`; backend skill `fastapi` (chính thức) và
`supabase-postgres-best-practices` (cài vào `.agents/skills/`); handbook của `wattprint-text2sql-mcp`.

## 1. Mock hiện có

| # | Mock (web) | Thay bằng |
|---|---|---|
| 1 | `features/home/demo.ts`, `saveHomeSettingsAction` trả lại giá trị không lưu | `GET/PATCH /homes/current`, `GET/PATCH /users/me/preferences`, danh mục tỉnh |
| 2 | `lib/env.ts` thời tiết cố định Hà Nội, gọi OpenWeather từ web | `GET /energy/weather` theo tỉnh của nhà (Open-Meteo, backend) |
| 3 | `features/billing/demo.ts` lịch sử hoá đơn sinh ngẫu nhiên | `GET /billing/history` từ `tb_bill` (job `compute_bill`) |
| 4 | `features/billing/forecast.ts` nội suy đường thẳng | `GET /billing/forecast` (hồ sơ theo thứ trong tuần), lưu `tb_forecast_snapshot` |
| 5 | `features/insight/demo.ts` cohort | `GET /insights/cohort` từ `tb_cohort_stat`, chỉ hộ thật, ẩn khi < 10 hộ |
| 6 | `features/insight/demo.ts` cảnh báo + ánh xạ thiết bị theo loại ở `dashboard/page.tsx` | bộ phát hiện chạy nền ghi `tb_alert`, `GET/PATCH /insights/alerts` |
| 7 | `features/copilot/demo.ts`, `playback.ts`, luồng giả, lịch sử hội thoại trong RAM | copilot thật: LLM (OpenRouter) + tool có phạm vi theo nhà + text2sql, SSE, lưu `ai.*` |
| 8 | `voice-mode.tsx` câu hỏi soạn sẵn | STT/TTS AstralX qua backend |
| 9 | `widgets.tsx` nút "bắt đầu thử" chỉ hiện toast | kế hoạch tiết kiệm thật: `tb_suggestion` + đo M&V (`tb_savings_measure`) |
| 10 | Tuỳ chọn `notify_anomaly`, `notify_tier`, `weekly_summary` không làm gì | email cảnh báo, chạm bậc, tóm tắt tuần qua SMTP (Mailpit khi dev) |

## 2. Quyết định (đã chốt với người dùng, 2026-11-19)

- Cohort: chỉ hộ thật trong hệ thống; DB giữ `CHECK n_homes >= 10`; chưa đủ thì API trả 404 `cohort_too_small`, thẻ ẩn.
- Copilot: orchestrator trong backend, tool gọi service nội bộ có phạm vi theo nhà; câu hỏi dữ liệu tự do chuyển sang
  text2sql. Sửa text2sql: xác thực giữa service + phạm vi theo nhà bằng `tb_scope_token` (đúng sơ đồ 07).
- LLM: dùng chung key OpenRouter của text2sql (`OPENROUTER_*`), model mặc định giống text2sql.
- Voice: AstralX (`https://token.astralx.com.vn/v1`), STT `whisper-large-v3-turbo`, TTS `astralx-tts` giọng `speaker_05`.
  Biến `ASTRALX_API_KEY` tạo sẵn để trống; thiếu key thì endpoint trả 503 `voice_unavailable`.

Quyết định thiết kế khác (của mình, theo docs):

- Bỏ tuỳ chọn `show_cost` của mock: PROJECT_CONTEXT yêu cầu số liệu luôn kèm tiền, không có chỗ nào đọc nó.
- Tuỳ chọn thông báo là của **người dùng**, không phải của nhà: bảng `tb_user_preference`.
- Vị trí nhà: `tb_home.province_code` → danh mục `cat_province` (34 tỉnh/thành sau sắp xếp 01/07/2025, toạ độ trung tâm
  hành chính). Nhà demo không có tỉnh (REFIT không cho, không bịa): thẻ thời tiết mời chọn tỉnh trong Cài đặt.
- Thời tiết do backend sở hữu (Open-Meteo, không cần key, cache 10 phút theo tỉnh) vì dự báo hoá đơn, cảnh báo và
  copilot đều cần; web bỏ OpenWeather.
- Loại cảnh báo theo hứa hẹn của sản phẩm (Final deck 35–36, spec 118): `longer_than_usual` (thiết bị chạy lâu hơn
  thường lệ), `standby_high` (tải nền ban đêm tăng), `tier_near` (sắp sang bậc giá mới, đúng như tuỳ chọn "trước khi sang bậc" và spec 118), `unexplained_load` (phần
  "Khác" tăng bất thường kéo dài, gợi ý thiết bị mới). Bỏ `new_device`/`repeated_cycle` của mock.
- Một tiến trình nền mới `insight` (giống `nilm`): một vòng asyncio, mỗi việc có chu kỳ riêng, khoá advisory để không
  chạy trùng: hoá đơn, dự báo, cohort, cảnh báo, thời tiết, thông báo, dọn `tb_scope_token`, đo M&V.

## 3. Backend

### 3.1 Migration (`alembic/versions/updates/`)

1. `tb_user_preference(user_id PK → tb_users CASCADE, notify_anomaly, notify_tier, weekly_summary, updated_at)`.
2. `cat_province(code PK, name, lat, lon)` + seed 34 dòng; FK `tb_home.province_code → cat_province`.
3. `tb_alert`: `dedup_key text NOT NULL`, `resolved_at`, `notified_at`; unique một phần
   `(home_id, dedup_key) WHERE status <> 'resolved'` để bộ phát hiện upsert, CHECK `kind`.
4. `ai.ai_conversation`: `pinned bool`, `updated_at`; `ai.ai_message`: `reply jsonb` (Reply có cấu trúc),
   `feedback varchar(8)` (`up`/`down`).
5. `tb_notification_log(id, user_id, kind, ref, sent_at)` unique `(user_id, kind, ref)`: không gửi trùng email.

### 3.2 Endpoint mới (tất cả dưới `/api/v1`, phạm vi theo `CurrentHome`)

| Module | Endpoint |
|---|---|
| home | `GET /homes/current`, `PATCH /homes/current` (chỉ owner), `GET /homes/provinces` |
| auth | `GET /users/me/preferences`, `PATCH /users/me/preferences` |
| energy | `GET /energy/weather` |
| billing | `GET /billing/history`, `GET /billing/forecast` |
| insight | `GET /insights/cohort`, `GET /insights/alerts?status=&limit=`, `PATCH /insights/alerts/{id}` |
| copilot | `GET/PATCH/DELETE /copilot/conversations[/{id}]`, `GET /copilot/conversations/{id}/messages`, `POST /copilot/chat` (SSE), `POST /copilot/messages/{id}/feedback`, `GET /copilot/suggestions`, `POST /copilot/plans/{id}/accept`, `POST /copilot/voice/transcribe`, `POST /copilot/voice/speech` |

### 3.3 Cách tính

- **Lịch sử hoá đơn**: job gọi `compute_bill` cho mọi chu kỳ đã có số đo (từ số đo đầu tiên tới chu kỳ hiện tại), chạy
  lại mỗi giờ cho chu kỳ đang mở và chu kỳ vừa đóng. Trả `coverage` để web ghi "thiếu dữ liệu" khi < 95 %.
- **Dự báo**: kWh đã dùng + với mỗi ngày còn lại, trung bình kWh của cùng thứ trong 28 ngày đủ dữ liệu gần nhất
  (cần ≥ 7 ngày, không đủ thì 404 `forecast_unavailable`); định giá bằng `_price` của billing (cùng bậc, VAT, tách
  phiên bản giá); ngày chạm bậc kế tiếp = ngày đầu tiên luỹ kế vượt ngưỡng bậc. Job lưu snapshot mỗi ngày.
- **Cohort**: mỗi ngày, công suất trung bình 30 ngày của mỗi nhà có độ phủ ≥ 90 %; `cohort_key` = `home_type` nếu nhóm
  đó ≥ 10 nhà, không thì `all`; chỉ ghi khi ≥ 10 nhà.
- **Cảnh báo** (mỗi 5 phút):
  - `longer_than_usual`: trung vị thời lượng các lần chạy 3 ngày gần nhất của một thiết bị > 1,5 × trung vị 28 ngày
    trước đó, mỗi bên ≥ 3 lần chạy (tái dùng `_cycles` của energy).
  - `standby_high`: tải nền (p5 công suất 00–05 giờ) 3 đêm gần nhất > 1,3 × và > +50 W so với 28 đêm trước.
  - `tier_near`: theo dự báo, luỹ kế kWh của chu kỳ sẽ vượt ngưỡng bậc kế tiếp trong ≤ 3 ngày (hoặc đã vượt);
    một cảnh báo mỗi bậc mỗi chu kỳ.
  - `unexplained_load`: chuỗi "Khác" > p95 của nó trong 28 ngày + 300 W, kéo dài ≥ 30 phút.
  - Điều kiện hết thì tự `resolved`; người dùng `acknowledged`/`resolved` qua PATCH.
- **Thông báo**: email cho từng thành viên theo tuỳ chọn (`notify_anomaly`: cảnh báo warning+, `notify_tier`:
  `tier_near`, `weekly_summary`: thứ Hai 08:00 giờ VN, kWh tuần, so tuần trước, tiền tạm tính, cảnh báo mở).

### 3.4 Copilot

- Orchestrator: OpenRouter chat completions có tool calling, stream token; timeout LLM 20 s, tối đa 4 vòng tool.
- Tool (đọc, phạm vi theo nhà trong code): `devices_breakdown`, `current_bill`, `bill_forecast`, `bill_history`,
  `weather`, `cohort`, `alerts`, `compare_periods`, `standby`, `query_data` (text2sql, với scope token 5 phút),
  `propose_plan` (ghi `tb_suggestion` trạng thái `proposed`).
- Reply: `tier` suy từ tool đã dùng (đo/ước tính/suy luận), `steps` = các lần gọi tool, `sql` từ text2sql, `sources`
  theo tool (biểu giá EVN, Open-Meteo, trang của app), `widgets` dựng **từ kết quả tool** chứ không do LLM viết,
  `followUps` do LLM đề xuất (tool `final_answer`).
- SSE tới web: `meta`, `step`, `token`, `done{reply}`, `error`. Web proxy qua route handler (token ở server).
- Lưu hội thoại vào `ai.ai_conversation/ai_message/ai_tool_call`; text2sql được gọi không kèm `user_id` (lịch sử của
  copilot là nguồn duy nhất).
- Guardrail: câu hỏi ≤ 2 000 ký tự, giới hạn 20 lượt/phút/người, tool chỉ đọc, kết quả tool cắt gọn trước khi đưa LLM,
  LLM lỗi thì trả 503 `copilot_unavailable` kèm số liệu thô từ tool nếu có.
- Kế hoạch thử: `POST /copilot/plans/{id}/accept` → `accepted` + baseline 14 ngày trước; job M&V ghi
  `tb_savings_measure` sau 14 ngày.
- text2sql: header `X-Service-Key` (bật khi đặt `TEXT2SQL_SERVICE_KEY`), trường `scope_token` → executor
  `set_config('app.copilot_token', …, true)` trong transaction chỉ đọc.

## 4. Web

Theo `docs/adding-a-feature.md`: schemas (Zod, khớp API) → `server.ts` → `queries.ts` → `actions.ts` (`updateTag`) →
component → test. Xoá `features/*/demo.ts`, `copilot/playback.ts`, `env` thời tiết, ánh xạ cảnh báo theo loại.
Copilot: route handler `app/api/copilot/chat` (POST, stream), lịch sử hội thoại từ server, voice qua route handler.
Mọi chuỗi mới vào `messages/{vi,en}`.

## 5. Thứ tự, kiểm tra, audit

| Bước | Việc | Xong khi |
|---|---|---|
| M0 | Cấu hình, `.env`, service `insight`, migration 1–5 | migration lên/xuống sạch, `pytest` pass |
| M1 | Cài đặt nhà + tuỳ chọn + tỉnh | sửa trong UI, tải lại vẫn còn; member không sửa được nhà |
| M2 | Thời tiết | thẻ thời tiết theo tỉnh; chưa chọn tỉnh thì mời chọn |
| M3 | Lịch sử hoá đơn | các chu kỳ có dữ liệu hiện đúng kWh/tiền, khớp `compute_bill` |
| M4 | Dự báo | số dự báo + ngày chạm bậc từ API; snapshot được ghi |
| M5 | Cohort | 2 nhà → thẻ ẩn; test với 10 nhà → có số |
| M6 | Cảnh báo + email | detector có test; danh sách thật, link đúng thiết bị; email vào Mailpit |
| M7 | Copilot backend + text2sql | hỏi thật qua SSE, tool đúng nhà, nhà khác không lộ |
| M8 | Voice | STT/TTS qua backend (503 rõ ràng khi chưa có key) |
| M9 | Copilot web | chat, lịch sử, ghim, đổi tên, xoá, phản hồi, kế hoạch, voice |
| M10 | Audit toàn bộ, dọn, docs | ponytail-audit cả hai repo không còn mục nghiêm trọng; `pnpm check`, `pnpm build`, `pytest` pass; tự click khi đăng nhập |

Sau mỗi bước: chạy test, `ponytail-review` phần thay đổi, sửa rồi mới sang bước sau.

## 6. Tiến độ (nhánh `feat/real-dashboard-apis`, commit cục bộ, chưa push)

- [x] M0–M2 (backend `ac63ba4`, web `adc9f76`): migration `9b4e2d7f1a63`, cài đặt/tuỳ chọn/tỉnh, thời tiết
  qua backend (OpenWeather, key ở backend `.env`; không lưu `tb_weather_hourly` vì chưa có ai đọc).
- [x] M3–M4 (backend `afbc9c4`, web `bca95ef`): lịch sử hoá đơn, dự báo theo thứ, worker `insight`
  (`app/modules/insight/worker.py`, job ở `services/jobs.py`; đang chạy: `bills` mỗi giờ, `forecasts` mỗi ngày).
- [x] M5 (backend `967199e`, web `04fe25a`): cohort từ công tơ tổng (`reading_1d`, công suất TB trên số phút có
  số, độ phủ ≥ 90 %), job `cohorts` mỗi ngày, `GET /insights/cohort` (kèm kWh của chính nhà cùng cửa sổ). Dữ liệu
  thật hiện 2 nhà → 404 `cohort_too_small`, thẻ ẩn.
- [x] M6 (backend `d513349`, web `d66593d`): `tb_device_cycle` tách lần chạy từ ước lượng NILM (tăng dần), 4
  detector mỗi 5 phút (tủ lạnh chạy lâu, điện nền đêm, tải lạ trong "Other", bậc giá), upsert theo `dedup_key`, tự
  resolve; `GET/PATCH /insights/alerts` (✕ trên Tổng quan = đã xem); mail SMTP theo tuỳ chọn (1 lần/ngày/nguyên nhân)
  và tóm tắt tuần thứ Hai 08:00.
- [x] M7 (backend `527e235`, text2sql nhánh `feat/copilot-scope-token`): module copilot, OpenRouter tool calling (11
  tool), SSE `meta/step/token/done/error`, reply dựng từ kết quả tool, hội thoại/feedback/kế hoạch + M&V 14 ngày,
  20 câu/phút. text2sql: `scope_token` → `set_config('app.copilot_token')`, `time_zone`, `X-Service-Key` tuỳ chọn,
  cổng thứ hai trên docker0 (`BACKEND_DOCKER_BIND=172.17.0.1`) để container gọi qua `host.docker.internal:11101`.
- [x] M8 (backend `141faff`): STT/TTS AstralX (`speaker_05`), body thô `audio/*` ≤ 10 MB, 30 lượt/phút.
- [x] M9 (web `b7a7e16`, backend `3fed4e7`): Wappi thật (route handler proxy SSE, Server Actions lịch sử, voice qua
  backend), avatar `@bible-strong/avatar-react` 1.2.1 (MIT) với bảng cảm xúc `features/copilot/moods.ts`.
- [x] M10 (backend `e6a6acb`, web `316de06`, text2sql `19f1269`): audit độc lập 2 repo, sửa: mail không gửi lặp khi
  một địa chỉ lỗi, kế hoạch commit ngay, không giữ kết nối DB suốt câu trả lời, `pinned: null`, giới hạn voice,
  "hôm nay" theo giờ VN trong text2sql; web: câu trả lời không kẹt "đang nghĩ", không mất lượt khi đang tải hội
  thoại, giới hạn body đếm theo byte, nhả micro, thu hồi audio, URL nguồn chỉ http(s)/đường dẫn app.
- [x] M11 giọng nói (backend `12a0cb6`, web `f464782` `49b0c23`): CSP cho phép audio `blob:`/`data:` (trước đó
  không phát được); TTS đọc từng câu thành một luồng MP3 (AstralX không stream, xử lý tuần tự), đổi số, đơn vị,
  giờ thành chữ trước khi đọc, Whisper có từ vựng ngành; bản đọc trọn vẹn lưu ở `ai.ai_speech` (30 ngày).
- [x] M12 an toàn và chi phí (backend `9725739` `8d2c349` `d200bbc` `cb0b2d8` `518c0bb` `ec36009`, web `b976ed9`
  `6427273`): token và chi phí mỗi câu trả lời ở `ai_message.usage`, giờ đặt sau lịch sử để prompt cache được;
  thông tin cá nhân (SĐT, giấy tờ, email, thẻ, STK) được cảnh báo trên web và thay bằng nhãn ở backend; câu
  injection bị từ chối, Llama Guard 4 lọc câu độc hại song song vòng đầu; nhãn "Dự đoán"/"Ước tính" kèm độ tin
  cậy và lý do, "Nội dung do AI tạo" dưới câu trả lời; test mọi endpoint (trừ health, provinces) cần token.
- Còn lại có chủ đích (`shortcut:` trong code): job hoá đơn tính lại mọi kỳ mỗi giờ; giới hạn voice đếm theo process;
  nhận diện thông tin cá nhân theo mẫu (không có NER cho tên, địa chỉ).

Lưu ý khi làm tiếp:
- Nguồn dữ liệu (người dùng chốt 2026-11-19): số theo thiết bị chỉ lấy từ ước lượng NILM (`tb_device_estimate`,
  `device_estimate_*`); tổng cả nhà lấy từ kênh `main` (như công tơ thật). Không API nào đọc kênh thiết bị gốc của
  CSV REFIT (chỉ `scripts/eval_nilm.py` dùng để chấm điểm offline). Đã kiểm: series `device` có 0 dòng `tb_reading`.
- `ruff format` của máy reformat cả file cũ: chỉ format file mình sửa.
- Chạy **toàn bộ** `docker compose exec -T api pytest -q` trước mỗi commit (migration từng làm hỏng fixture cũ ở
  `tests/db/test_domain_tables.py`, `test_roles.py` ma trận quyền: bảng mới phải thêm vào `expected_*`).
- Test chèn số đo vào quá khứ phải `backfill` aggregate (`app.modules.energy.services.aggregates`).
- Đổi `.env`/compose thì `docker compose up -d --no-deps api` rồi chạy lại replay:
  `docker exec -d wattprint-api sh -c 'cd /code && python -m scripts.replay_refit > /tmp/replay.log 2>&1'`
  (container không có `pkill`; tìm PID qua `/proc/*/cmdline`).
- Web: commit cần `PATH=$HOME/.local/node-v22/bin:$PATH` (husky), commitlint giới hạn 100 ký tự/dòng thân.
- Sau khi máy khởi động lại: `docker compose up -d` (container `db`/`api`/`keycloak` có thể mất, volume vẫn còn),
  `docker compose up -d --no-deps --force-recreate insight` nếu nó lặp "name resolution", chạy lại replay (lệnh ở
  trên), rồi bật lại hai dev server web.
- Self-test: script Playwright ở scratchpad (`selftest2.mjs`), đăng nhập `refit.house2@wattprint.local` với
  `DEMO_PASSWORD`; chụp với `caret: "initial"` (mặc định Playwright chèn style gây hydration mismatch giả).
