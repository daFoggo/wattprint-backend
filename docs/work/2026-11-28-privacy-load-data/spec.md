# Spec: bảo vệ dữ liệu nếp sinh hoạt

Intent: [intent.md](intent.md). Status: approved (chủ dự án, 2026-11-28: "1. xóa cùng 2. cho phép config 3. có làm",
trả lời ba câu hỏi còn mở của bản đề xuất chốt). Record: none. Hiện trạng: [audit.md](audit.md).
Lane L (auth, copilot, migration, ba repo). Đã đối chiếu với [proposal1.md](proposal1.md) (viết trên commit `b0eb01b`,
cũ hơn 91 commit), [proposal2.md](proposal2.md) và [legal.md](legal.md); phần lấy từ đó ghi ở "Approaches considered".

Thứ tự làm, rà lại sau mỗi bước: Phần 0 → bảng thử quyền của Phần 4 (chạy trên mã hiện tại để có kết quả "trước") →
Phần 3 → Phần 2 → Phần 4 còn lại → Phần 5 → Phần 1 (cuối cùng, vì không đảo ngược được) → Phần 6.

## Requirements

### Phần 0. Vá ngay (A1, A2, audit mục H)

R0.1 text2sql bắt buộc `X-Service-Key` trên mọi router (trừ own-knowledge, đã có khóa riêng): thiếu hoặc sai trả 401,
     dịch vụ chưa đặt khóa trả 503 ở mọi route (đóng khi thiếu, theo mẫu own-knowledge; `/openapi.json` vẫn mở cho
     healthcheck). Giao diện quản trị của text2sql đang gọi API thẳng từ trình duyệt, nên chuyển sang gọi qua một
     route cùng nguồn gắn khóa ở phía server.
R0.2 Xác định kết nối text2sql đã lưu đăng nhập bằng vai DB nào; phải là `wattprint_copilot_ro`.
R0.3 Vai `wattprint_ai` còn `SELECT` trên `ai.fact_*`, `ai.dim_*` không lọc theo nhà (migration `f39a7b2c5d18`,
     `a4c7e1d93b62`) và không mã nào dùng vai này: thu quyền.

### Phần 1. Giảm chi tiết lưu (B1, B2, B3)

R1.1 Thời hạn giữ mặc định, áp cho mọi nhà:

| Dữ liệu | Hiện nay | Mới |
|---|---|---|
| Số đo thô (khoảng 10 giây) | 400 ngày | 30 ngày |
| Tổng theo phút (công tơ, thiết bị), lượt bật/tắt thiết bị | 400 ngày / mãi | 90 ngày |
| Tổng theo giờ, dự đoán theo giờ, cảnh báo | mãi | 13 tháng (400 ngày) |
| Tổng theo ngày | mãi | 800 ngày (25 kỳ hóa đơn cộng đệm) |
| Hóa đơn | 25 kỳ gần nhất, dựng lại từ số theo ngày ở mỗi lượt chạy | không đổi |
| Kết quả công cụ và SQL kèm tin nhắn Wappi | mãi | 30 ngày (lời hỏi và trả lời vẫn giữ) |
| Nhật ký lượt chạy NILM và lô công tơ gửi (`tb_inference_run`, `tb_ingest_batch`) | mãi | 90 ngày |

R1.2 Không làm thời hạn riêng từng nhà ("Giữ ngắn") trong bản này (lý do ở Areas of concern). Chủ nhà muốn giữ ít
     hơn thì dùng "xóa trước ngày" ở Phần 2. Bảng thường (`tb_expect_hourly`, `tb_alert`, `ai_tool_call`,
     `tb_inference_run`, `tb_ingest_batch`) do một việc hằng đêm của insight worker dọn theo R1.1.
R1.3 Biểu đồ xin độ phân giải mịn hơn mức còn giữ thì nhận mức thô kế tiếp, kèm cờ `coarsened` để giao diện ghi
     "Chi tiết theo phút chỉ giữ 90 ngày". Không trả biểu đồ rỗng.
R1.4 Việc dựng lại lượt bật/tắt và bộ phát hiện bất thường không đọc lùi quá mức còn giữ của nhà.
R1.5 NILM của một nhà chậm hơn 20 ngày so với số đo mới nhất thì báo người bảo trì (số đo thô chỉ còn 30 ngày;
     quá hạn là mất phần ước tính của quãng đó).
R1.6 Bất biến của bản tổng hợp xếp tầng: cửa sổ refresh của mỗi tầng ngắn hơn thời hạn của tầng nguồn (phút 7 < thô
     30; giờ 30 < phút 90; ngày 60 < giờ 400), nếu không refresh sẽ xóa bucket của tầng trên. Số theo ngày phải phủ
     đủ 25 kỳ hóa đơn, nếu không `refresh_bills` ghi đè hóa đơn cũ về 0 (`billing/services/history.py:20-53`). Một test đọc
     `timescaledb_information.jobs` kiểm cả thời hạn lẫn bất biến này; trước khi áp lên DB thật, chạy thử trên bản sao.

### Phần 2. Xóa lịch sử (C1…C4)

R2.1 `DELETE /api/v1/homes/current/history?before=YYYY-MM-DD` (chỉ chủ nhà, 204). Xóa số đo, ước tính thiết bị,
     mọi bản tổng hợp, lượt bật/tắt, cảnh báo, dự đoán và dự báo trước ngày đó; bỏ `before` là xóa tất cả. Giữ tài
     khoản, nhà, thiết bị, mô hình. Kế hoạch tiết kiệm của từng người giữ lại, bỏ số của các ngày đã xóa. Hóa đơn đi theo số theo ngày: kỳ nằm trọn trước mốc mất, kỳ bị cắt ngang hiện
     "chưa đủ dữ liệu". Nhà demo từ chối thao tác này. Hộp xác nhận nói rõ hóa đơn nào mất, và rằng bản đã gửi cho
     dịch vụ ngoài không xóa được từ đây (kèm link chính sách lưu của họ).
R2.2 Nhà ghi lại mốc đã xóa; công tơ gửi lại lô cũ hơn mốc thì bị từ chối (C4).
R2.3 `DELETE /api/v1/copilot/conversations` xóa mọi cuộc trò chuyện của người gọi trong nhà, kèm âm thanh đã lưu.
R2.4 Xóa tài khoản dọn nốt: dòng `ai.dim_home` (xóa thật), `tb_ingest_batch`, `last_seen_at` của công tơ, file mô
     hình NILM riêng của nhà (C2, C3).

### Phần 3. Giảm chi tiết gửi ra ngoài và nêu rõ (D1…D5)

R3.1 Vai `wattprint_copilot_ro` mất quyền đọc các view theo phút, giờ bật/tắt thiết bị, tên nhà, mã bưu chính, số
     người. Còn lại: theo giờ, theo ngày, thiết bị, hóa đơn.
R3.2 Chủ nhà đặt "Wappi xem tới mức": `theo ngày` hoặc `theo giờ`. Nhà chưa chọn thì theo thiết lập hệ thống
     `copilot_ai_detail_default` (giá trị ban đầu `daily`); nhà demo đặt sẵn `theo giờ` vì là dữ
     liệu công khai. Biểu đồ theo giờ vẫn vẽ cho người dùng vì không đi qua mô hình. Ở `theo ngày`:
     `query_data` chỉ đọc được view theo ngày; `standby` (mức điện 0–5 giờ từng đêm) không chạy và nói vì sao;
     `alerts` chỉ đưa ngày, bỏ giờ và bỏ `start_hour`/`at` trong số liệu kèm; các công cụ còn lại vốn đã theo ngày.
R3.3 Đồng ý theo từng mục đích, mặc định tắt: `wappi` (AI bên ngoài), `voice` (giọng nói), `email` (cảnh báo và tóm
     tắt tuần qua email; `notify_anomaly`, `notify_tier` đổi mặc định sang tắt cho tài khoản mới). Lần đầu dùng phải
     bấm đồng ý, lời mời ghi: gửi gì, cho ai, ở nước nào, ai chịu trách nhiệm, tắt ở đâu. Mỗi lần bật hoặc tắt ghi
     thêm một dòng vào `tb_consent` (ai, mục đích, bật/tắt, phiên bản lời mời, lúc nào), không sửa dòng cũ. Chưa
     đồng ý hoặc đã rút thì backend trả 403 `consent_required` và không có lời gọi nào ra ngoài.
R3.4 Khung chat luôn có một dòng: "Câu hỏi và số liệu cần để trả lời được gửi tới OpenRouter (ngoài Việt Nam)."
     Mỗi câu trả lời có mục "Đã gửi ra ngoài" liệt kê loại dữ liệu và mức chi tiết của lượt đó.
R3.5 Nhật ký gửi ra ngoài: mỗi lần gọi OpenRouter, AstralX, OpenWeather, Telegram ghi một dòng (lúc nào, bên nào,
     để làm gì, loại dữ liệu, mức chi tiết; không ghi nội dung). Người dùng xem 30 ngày gần nhất; giữ 90 ngày.
     Mọi lời gọi ra ngoài đi qua một hàm chung (kiểm đồng ý → ghi nhật ký → gửi); một test quét mã nguồn bảo đảm tên
     máy chủ bên ngoài chỉ xuất hiện ở đó.
R3.6 Bấm 👎 mặc định chỉ gửi đánh giá. Nội dung câu hỏi và câu trả lời chỉ đi Telegram khi người dùng tích
     "Gửi kèm nội dung cho người bảo trì" (D1).
R3.7 Che thông tin cá nhân chạy ở một chỗ duy nhất ngay trước khi gửi, phủ cả bước kiểm duyệt (hiện nhận câu hỏi
     chưa che, `guard.py:43-50`), bước tìm tài liệu, câu trả lời cũ và kết quả công cụ gửi lại, cả bản chữ của giọng
     nói (D4). Âm thanh gốc không che được: lời đồng ý ở R3.3 nói rõ điều này.
R3.8 Mọi lời gọi OpenRouter, ở backend và ở text2sql, kèm `provider: {zdr: true, data_collection: "deny"}` (D3).

### Phần 4. Giới hạn quyền (A1…A4, F3)

R4.1 Chủ nhà mời người thân bằng mã (dùng bảng `tb_home_invite` đã có), xem danh sách, đổi mức xem, gỡ; thành viên
     tự rời nhà. Người đang là chủ nhà hoặc thành viên của nhà khác không nhận được lời mời; người chỉ đang xem
     nhà demo thì nhận được (dòng xem demo bị thay). Người rời nhà thấy màn "Chưa có nhà" kèm ô nhập mã mời.
R4.2 Mỗi thành viên có mức xem `đầy đủ` hoặc `chỉ theo ngày` (mặc định khi mời: chỉ theo ngày). Khách demo: đầy đủ.
R4.3 Thành viên "chỉ theo ngày" không nhận số mịn hơn một ngày hay giờ chạy của thiết bị: route chỉ trả số mịn
     (`/energy/activity`, `/energy/stream`, `/expected`) trả 403 `detail_restricted`; `/energy/series` trả theo ngày;
     route trộn (tổng quan, thiết bị, cảnh báo) bỏ trường mịn. Wappi của họ chạy như R3.2 `theo ngày`. Giao diện ẩn
     các khối đó và nói vì sao.
R4.4 Chỉ chủ nhà: xóa lịch sử, đổi thời hạn giữ, đổi mức của Wappi, mời và gỡ thành viên. Thành viên vẫn tạo kế
     hoạch, đặt nhắc và trò chuyện của riêng mình như hiện nay.
R4.5 Admin không có route nào đọc dữ liệu của một nhà (hiện đã vậy); bảng thử quyền giữ điều này.
R4.6 Bảng thử quyền `tests/test_permissions.py`: mỗi route × bảy chủ thể (chưa đăng nhập, chủ nhà khác, khách
     demo, thành viên theo ngày, thành viên đầy đủ, chủ nhà, admin) có mã trả về mong đợi. Thêm ở mức DB: vai
     copilot không đọc được bảng gốc, scope token hết hạn không trả dòng nào. Một lệnh in bảng kết quả ra Markdown.

### Phần 5. Trang Quyền riêng tư

R5.1 `/dashboard/settings/privacy`, vào từ Cài đặt và từ menu tài khoản. Bốn khối:

```
Quyền riêng tư
├─ Đang giữ gì     10 giây·30 ngày → phút·90 ngày → giờ·13 tháng → ngày·25 tháng
│                  kèm ngày cũ nhất thật của nhà ở từng mức
├─ Ai xem được     chủ nhà, người thân (mức xem), [Mời người thân]
├─ Gửi ra ngoài    từng dịch vụ: gửi gì, mức nào, ở đâu · công tắc Wappi, Giọng nói
│                  Wappi xem tới [theo giờ | theo ngày] · nhật ký 30 ngày
├─ Xóa             lịch sử điện [trước ngày… | tất cả] · trò chuyện · tài khoản
└─ AI dùng dữ liệu của bạn thế nào   hai câu về tách thiết bị và Wappi, link trang chính sách
```

R5.2 Người không phải chủ nhà thấy trang ở dạng chỉ xem, trừ công tắc và nút xóa của riêng họ.
R5.3 Mỗi thao tác xóa có hộp xác nhận nói rõ cái gì mất và không lấy lại được.

### Phần 6. Minh chứng và tài liệu

R6.1 Sơ đồ luồng dữ liệu riêng tư `docs/diagrams/privacy-data-flow.svg`: nguồn → các tầng lưu kèm thời hạn → ai đọc
     được → ranh giới ra ngoài (cái gì qua, mức chi tiết nào).
R6.2 Ảnh chụp trang Quyền riêng tư (chủ nhà, thành viên theo ngày), lời báo trong chat, hộp đồng ý giọng nói.
R6.3 Bảng thử quyền in từ lần chạy thật (R4.6), hai bản: trước khi sửa (các ô sai để nguyên) và sau khi sửa.
R6.4 `docs/evidence/privacy.md` cho giám khảo: mỗi ý của đề → đã làm gì → minh chứng nào.
R6.5 Trang chính sách (`apps/web/messages/{vi,en}/legal.json`) sửa hết E1…E9 theo mã sau thay đổi.
R6.6 README và `submission/` cập nhật; eval Wappi chạy lại một nhà, một lượt, ghi kết quả trước/sau.

## Design

- **Thời hạn**: một migration mới đổi `add_retention_policy` của hai hypertable thô và các view `_1m`, thêm cho
  `_1h`, `_1d`, `tb_device_cycle`. `energy/services/erase.py` nhận thêm tham số `before`, dùng chung cho R2.1 và xóa
  tài khoản.
- **Độ phân giải**: `energy/services/meter.py` chọn view theo cả độ dài cửa sổ lẫn tuổi dữ liệu.
- **Mức xem**: cột `detail` (`full|daily`) trên `tb_home_member`; cột `ai_detail` (`hourly|daily`) và
  `history_erased_before` trên `tb_home`. `home/dependencies.py` thêm `DetailedMembership` và `OwnerMembership`
  cạnh `WritableMembership`. Mức hiệu lực của một lượt hỏi là mức thấp hơn giữa nhà và người hỏi; `Ctx` của công
  cụ Wappi mang nó, và `ScopeToken` thêm cột `detail` để view `copilot_ro.*_1h` chỉ trả dòng khi token là `hourly`.
- **Xóa trong bản tổng hợp**: continuous aggregate không nhận `DELETE`; xóa ở các hypertable vật chất hóa như
  `erase.py` đang làm. `tb_expect_hourly` là bảng thường, việc hằng đêm xóa trực tiếp.
- **Đồng ý**: bảng `tb_consent` trong mô-đun `auth`, chỉ ghi thêm; dòng mới nhất của mỗi mục đích là trạng thái hiện
  tại. Route `GET/PUT /users/me/consents/{purpose}`.
- **Nhật ký**: bảng `tb_outbound_log` trong mô-đun `ops`, ghi tại các điểm gọi ra ngoài (`copilot/services/llm.py`,
  `voice.py`, thời tiết, `common/notify.py`, `query_data`). Route `GET /users/me/outbound`.
- **Che dữ liệu**: gọi `redact` trong `llm.py` ngay trước khi gửi, thay cho các chỗ gọi rải rác.
- **Thành viên**: route trong `home/routes`, theo `docs/keycloak-auth.md` và rule card của `routes/`, `schemas/`.
- **Web**: `features/privacy/` mới theo `docs/adding-a-feature.md`; thành phần Hairline; chữ vào
  `messages/{vi,en}/privacy.json` trước rồi mới viết TSX; dựng bố cục bằng Hallmark trước khi viết JSX. Mục xóa tài
  khoản hiện có chuyển vào trang này.
- **Sơ đồ**: theo cách các sơ đồ trong `docs/diagrams` đang được tạo (HTML → SVG).

## Approaches considered

| Cách | Đánh đổi |
|---|---|
| A. Vá tối thiểu: ba minh chứng, xóa lịch sử, dòng báo trong chat | Nhanh; ý "giảm độ chi tiết" chưa làm |
| B. Quy tắc cứng toàn hệ thống, trang chỉ để xem và xóa | Dễ chứng minh; người dùng không tự quyết |
| **C. Mặc định như B, chủ nhà tự chọn thêm, có nhật ký gửi ra ngoài** | Phủ đủ bốn ý; khối lượng lớn nhất |
| D. Tách thiết bị tại nhà, máy chủ chỉ nhận tổng theo ngày | Mạnh nhất; không có phần cứng để chứng minh |

Chọn C: chủ dự án muốn điểm cao nhất và không giới hạn thời gian, giao phần cách làm cho người xây (lựa chọn của
người xây, chưa phải điều chủ dự án đã xác nhận từng mục).

Lấy từ hai bản đề xuất: bảng đồng ý chỉ ghi thêm, email mặc định tắt, hàm gọi ra ngoài chung kèm test quét mã nguồn,
bất biến refresh, làm thời hạn sau cùng, kết quả test trước/sau, khối giải thích AI, lời báo phần không xóa được.

Không lấy từ proposal1, vì mã hiện tại không có hoặc đã làm xong: lan truyền xóa giữa bốn service và bảng trạng thái
yêu cầu xóa (hệ thống đang là một app, xóa xong trong một giao dịch); thông báo đẩy Expo và Telegram cho người dùng
(không có trong mã); quyền hỗ trợ có thời hạn và MFA cho admin (admin không có đường đọc dữ liệu nhà); xóa nhà để lại
số đo mồ côi và hai khóa ngoại chặn xóa (đã sửa ở `2026-11-25-delete-account`); thay tên thiết bị bằng bí danh (không
có chức năng đặt tên thiết bị); xuất dữ liệu; số theo phút 35 ngày (dựng lại lượt bật/tắt cần 65 ngày).

## Areas of concern

- **Xóa không lấy lại được.** Migration thời hạn xóa chi tiết cũ ngay khi chạy. Chỉ chạy trên dev; nhà demo nạp lại
  được từ `dataset/`. Prod chờ chủ dự án.
- **Số đo thô 30 ngày, đã kiểm**: NILM lượt đầu bắt đầu từ số đo cũ nhất trong 90 ngày (`nilm/services/runner.py:74-90`),
  nên nhà mới chạy trên khoảng 30 ngày thay vì 90; các lượt sau chỉ cần vài ngày. Rủi ro còn lại là worker dừng quá
  30 ngày (R1.5).
- **Lượt bật/tắt 90 ngày, đã kiểm**: bộ phát hiện đọc 60 ngày (`insight/services/detectors.py:352`), lời khuyên đọc 4
  tuần (`billing/services/device_forecast.py:20`), dựng lại đọc 65 ngày (`insight/services/cycles.py:12-25`). Mức
  mặc định không ảnh hưởng; "Giữ ngắn" thì tắt ba tính năng ở R1.2.
- **Bỏ "Giữ ngắn"**: xóa số theo phút của riêng một nhà ở ngày thứ 14 nằm trong cửa sổ refresh 30 ngày của tầng giờ,
  nên tầng giờ của nhà đó có thể bị tính lại thành rỗng (bẫy refresh mà proposal1 mục 7.1.3 nêu, `docs/database-audit.md`
  drill 10b); `docs/database-design-guide.md` cũng không cho dùng `DELETE` từng dòng làm retention. Xóa theo yêu cầu
  ở Phần 2 thì xóa mọi tầng cùng lúc nên không dính bẫy này, nhưng vẫn phải có test "xóa nhà A, số của nhà B không đổi"
  cho cả quãng cũ hơn thời hạn số đo thô.
- **Căn cứ pháp lý chưa chắc**: legal.md đọc từ bản chép, proposal1 ghi đọc từ Công báo, chưa đối chiếu hai bản. Trên
  trang chính sách và hồ sơ minh chứng chỉ trích điều khoản sau khi đối chiếu bản Công báo; không phải tư vấn pháp lý.
- **Hóa đơn sau khi xóa lịch sử, đã kiểm**: `refresh_bills` dựng lại 25 kỳ ở mỗi lượt và ghi đè; kỳ mất số theo ngày
  bị ghi về 0, kỳ cũ hơn bucket ngày đầu tiên bị xóa hẳn. Vì vậy R2.1 để hóa đơn đi theo dữ liệu; muốn giữ hóa đơn
  phải đóng băng kỳ đã chốt, là thay đổi ở phần tính tiền và chờ chủ dự án quyết.
- **Nguồn phát lại của nhà demo, đã kiểm**: đọc từ file CSV trong `dataset/` (`scripts/replay_refit.py:107`), thời hạn
  mới không chạm tới.
- **Bảng chưa kiểm nội dung theo giờ**: `tb_forecast_snapshot`, `tb_alert_feedback`, `tb_savings_measure`, `tb_watch`,
  và ba công cụ `create_watch`, `list_watches`, `propose_plan`. Kiểm khi lập kế hoạch phần 1 và phần 3.
- **R3.8** có thể làm hẹp số nhà cung cấp phục vụ được model đang dùng; kiểm bằng một lời gọi thật, nếu không định
  tuyến được thì ghi rõ giới hạn thay vì bật im lặng.
- **Khách demo phải bấm đồng ý một lần** trước khi dùng Wappi. Thêm một bước cho giám khảo, đổi lại họ thấy ngay
  tính năng được yêu cầu.
- **Trang chính sách** vẫn chưa có luật sư đọc (nợ cũ, không đổi).

## Open questions carried forward

Chủ dự án quyết (lựa chọn tạm của người xây ghi trong ngoặc):

1. Có làm mời người thân không (có, làm sau phần lõi; bỏ thì Phần 4 chỉ còn bảng thử quyền và danh sách chỉ xem).
2. Mô hình AI: giữ nhà cung cấp nước ngoài kèm đồng ý và giảm chi tiết, hay chuyển sang mô hình đặt trong nước (giữ;
   cần hỏi AstralX đặt máy chủ ở đâu).
3. Coi dữ liệu điện là dữ liệu nhạy cảm trong lời mời đồng ý và trang chính sách (có, theo hướng thận trọng).
4. Tài khoản cũ và khách demo có phải bấm đồng ý lại không (có).
5. Khi nào áp thời hạn mới lên prod (chờ yêu cầu).
6. Ai lập hồ sơ chuyển dữ liệu ra nước ngoài (việc giấy tờ của người chịu trách nhiệm dữ liệu, ngoài mã).

Đầy đủ mười quyết định và mặc định đang dùng: [final-proposal.md](final-proposal.md) mục 7. Việc theo đợt:
[checklist.md](checklist.md).

Người xây kiểm khi làm: tham số không lưu dữ liệu có làm OpenRouter không định tuyến được model đang dùng không;
AstralX đặt máy chủ ở đâu.
