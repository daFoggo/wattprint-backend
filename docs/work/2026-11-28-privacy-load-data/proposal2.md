# Đề xuất: Bảo vệ dữ liệu nếp sinh hoạt

Ngày: 2026-11-28 · Lane: L (chạm migration dữ liệu, auth, backend copilot, web dashboard) · Trạng thái: chờ phản biện

Tài liệu này để phản biện trước khi làm. Mỗi đề xuất ghi rõ: làm gì, căn cứ điều luật nào, sửa ở đâu, minh chứng gì.
Những chỗ chưa chắc được đánh dấu **[cần quyết]** hoặc **[chưa kiểm]**. Phần đọc luật là cách hiểu của nhóm kỹ thuật,
chưa phải ý kiến luật sư.

## 1. Yêu cầu gốc

> **Bảo vệ dữ liệu nếp sinh hoạt.** Dữ liệu phụ tải theo giờ có thể tiết lộ lịch sinh hoạt gia đình.
> Yêu cầu: giảm độ chi tiết phải lưu/chia sẻ, giới hạn quyền truy cập và cho phép xóa lịch sử; nêu rõ khi gọi dịch vụ ngoài.
> Minh chứng: sơ đồ luồng dữ liệu, màn hình quyền riêng tư và thử phân quyền.

Vấn đề cốt lõi: chỉ cần nhìn đường tiêu thụ điện cũng đoán được mấy giờ cả nhà ngủ dậy, lúc nào nhà vắng người,
lúc nào nấu ăn. Dữ liệu càng chi tiết (theo phút, theo giây) và giữ càng lâu thì càng lộ nhiều.

## 2. Căn cứ pháp lý (đã đọc nguyên văn)

Nguồn: Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 (bản Word của LuatVietnam), và Nghị định 356/2025/NĐ-CP
(bản đăng lại trên luatnguyen.vn, chưa đối chiếu với Công báo). Cả hai có hiệu lực từ 01/01/2026. Nghị định 356
thay Nghị định 13/2023.

### 2.1 Quyền xóa dữ liệu

| Điều | Nội dung chính | Áp dụng cho WattPrint |
|---|---|---|
| Luật Điều 4 khoản 1 điểm d | Chủ thể có quyền yêu cầu cung cấp, xóa, hạn chế xử lý dữ liệu; phản đối xử lý | Người dùng phải tự xóa được, không chỉ có cách "xóa cả tài khoản" |
| Luật Điều 14 khoản 1 | Xóa khi: chủ thể yêu cầu; **đã xong mục đích xử lý**; hết hạn lưu trữ; theo thỏa thuận | Dữ liệu chi tiết đã dùng xong (đã tổng hợp thành số theo giờ, theo ngày) thì nên xóa |
| Luật Điều 14 khoản 3 | Bên kiểm soát phải xóa bằng biện pháp an toàn, chặn khôi phục trái phép, và **yêu cầu bên xử lý, bên thứ ba cùng xóa** | Phải tính tới bản sao đã gửi cho OpenRouter, AstralX |
| Luật Điều 14 khoản 5 | Không xóa được vì lý do chính đáng thì phải báo cho chủ thể biết | Ví dụ: hóa đơn đã chốt nếu cần giữ. Màn hình phải nói rõ phần nào không xóa |
| Luật Điều 3 khoản 3 | Lưu trữ trong khoảng thời gian **phù hợp với mục đích** | Giữ dữ liệu theo phút 400 ngày cần lý do. Hiện chưa có lý do nào được viết ra |
| NĐ 356 Điều 5 khoản 4 | Yêu cầu xóa: phản hồi trong 02 ngày làm việc, xong trong 20 ngày; nếu cần bên xử lý hoặc bên thứ ba cùng làm thì 30 ngày; gia hạn tối đa một lần, thêm 20 ngày | Xóa tự phục vụ ngay trong app thì đáp ứng ngay. Phần ở bên thứ ba cần quy trình riêng |
| NĐ 356 Điều 5 khoản 1 | Phải có quy trình, thủ tục, biểu mẫu rõ ràng để thực hiện quyền, và cho chủ thể biết thủ tục đó | Màn hình Quyền riêng tư chính là "thủ tục" này |
| NĐ 356 Điều 10 khoản 6 | Chủ thể có quyền chỉnh sửa, ẩn danh, xóa hồ sơ nhận dạng, **kể cả khi nền tảng lưu lịch sử hành vi** | Lịch sử điện năng và lịch sử trò chuyện với Wappi đều là lịch sử hành vi |

### 2.2 Đồng ý

| Điều | Nội dung chính | Áp dụng cho WattPrint |
|---|---|---|
| Luật Điều 9 khoản 2 | Đồng ý chỉ có hiệu lực khi tự nguyện và người dùng biết rõ: loại dữ liệu, mục đích, ai là bên kiểm soát, quyền của mình | Lời mời đồng ý phải nêu đủ bốn ý này |
| Luật Điều 9 khoản 4 | Đồng ý **riêng cho từng mục đích**; không được buộc đồng ý mục đích khác; im lặng không phải là đồng ý | Câu ở màn đăng ký "Khi tiếp tục, bạn đồng ý với Điều khoản và Chính sách" gộp mọi mục đích vào một lần |
| Luật Điều 10 | Được rút lại đồng ý và yêu cầu hạn chế xử lý. Việc rút lại không có hiệu lực ngược với phần đã xử lý trước đó | Cần nút rút lại, và rút xong thì dừng ngay |
| Luật Điều 19 khoản 1 điểm d | Không cần xin đồng ý khi xử lý để **thực hiện thỏa thuận** với chủ thể | Phần lõi (đo điện, tính hóa đơn, tách thiết bị) dựa vào thỏa thuận dịch vụ. Wappi, giọng nói, email là các mục đích tùy chọn |
| NĐ 356 Điều 6 khoản 1–2 | Phương thức đồng ý phải **kiểm chứng được** (ai, lúc nào, đồng ý nội dung gì); bên kiểm soát phải lưu bằng chứng và chịu trách nhiệm chứng minh | Hiện không có bảng nào lưu sự đồng ý |
| NĐ 356 Điều 6 khoản 3 | Không được đặt **mặc định là đồng ý**; thiết lập mặc định phải theo hướng bảo vệ dữ liệu | `notify_anomaly`, `notify_tier` mặc định `true`, trong khi trang Chính sách lại nói "bạn tự bật thông báo qua email" |
| NĐ 356 Điều 6 khoản 4 | Xin đồng ý cho dữ liệu nhạy cảm thì phải nói rõ đó là dữ liệu nhạy cảm | Xem câu hỏi ở mục 8.1 |
| NĐ 356 Điều 10 khoản 3 | Xử lý tự động (AI) thì phải báo cho chủ thể, giải thích nguyên tắc thuật toán và ảnh hưởng, và **cho chọn không tham gia** | Áp dụng cho Wappi và cho NILM (tách điện từng thiết bị bằng mô hình) |

### 2.3 Chuyển dữ liệu ra nước ngoài

| Điều | Nội dung chính | Áp dụng cho WattPrint |
|---|---|---|
| Luật Điều 20 khoản 1 | Ba trường hợp được tính là chuyển xuyên biên giới, trong đó có: chuyển cho tổ chức ở nước ngoài; dùng nền tảng ngoài Việt Nam để xử lý dữ liệu thu ở Việt Nam | Gửi câu hỏi kèm số liệu của nhà cho OpenRouter (Mỹ) là chuyển xuyên biên giới. AstralX: **[chưa kiểm]** đặt máy chủ ở đâu |
| Luật Điều 20 khoản 2 | Phải lập **hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên giới** và nộp bản chính cho cơ quan chuyên trách trong 60 ngày kể từ lần chuyển đầu tiên | Việc giấy tờ, không phải code. Xem mục 6 |
| Luật Điều 38 khoản 2–3 và NĐ 356 Điều 41 | Doanh nghiệp nhỏ, khởi nghiệp, hộ kinh doanh, siêu nhỏ được miễn **Điều 21, 22 và khoản 2 Điều 33**. Hết miễn nếu xử lý dữ liệu nhạy cảm hoặc từ 100 nghìn chủ thể trở lên | Miễn trừ **không có Điều 20**. Hồ sơ chuyển xuyên biên giới vẫn phải làm dù quy mô nhỏ |
| NĐ 356 Điều 18 khoản 3 | Báo cáo theo Mẫu số 09, gồm cả **sơ đồ luồng xử lý dữ liệu**, loại dữ liệu, cách xin đồng ý, chính sách lưu và xóa, đánh giá rủi ro | Sơ đồ luồng dữ liệu của yêu cầu này dùng lại được cho hồ sơ |
| NĐ 356 Điều 7 khoản 1 | Chuyển giao phải có thỏa thuận ghi rõ: mục đích, loại dữ liệu, thời hạn xử lý, yêu cầu xóa sau khi xong, trách nhiệm các bên | Cần dẫn điều khoản xử lý dữ liệu của OpenRouter và AstralX, hoặc cấu hình "không lưu" nếu nhà cung cấp có |
| Luật Điều 30 khoản 1 và 3 | Dữ liệu trong hệ thống AI và đám mây chỉ xử lý trong **phạm vi cần thiết**; phải phân quyền truy cập | Không cần gửi số theo phút cho mô hình ngôn ngữ |
| NĐ 356 Điều 12 khoản 4 | Dữ liệu cá nhân trên điện toán đám mây phải mã hóa khi lưu và khi truyền | **[chưa kiểm]** máy chủ prod có mã hóa ổ đĩa hay không |

## 3. Hiện trạng (đã kiểm trong code ngày 2026-11-28)

| Mặt | Đã có | Chỗ trong code |
|---|---|---|
| Thời gian lưu | Số đo gốc (`tb_reading`), ước tính thiết bị (`tb_device_estimate`) và bảng tổng hợp theo phút (`*_1m`) đều giữ **400 ngày**. Chưa thấy chính sách giữ riêng cho bảng theo giờ và theo ngày | `wattprint-backend/alembic/versions/public/20261101_f3a9c1e5b7d2_compress_1m_aggregates.py` |
| Wappi đọc dữ liệu | Wappi chỉ đọc được một nhà, qua mã phạm vi sống 5 phút và các view `copilot_ro` có `security_barrier`. Các view này có **cả mức phút** (`reading_1m`, `device_estimate_1m`) bên cạnh mức giờ và mức ngày | `wattprint-backend/alembic/versions/public/20261101_4d7b1e9a3c52_roles_and_copilot_views.py` |
| Gửi cho mô hình ngôn ngữ | Câu hỏi đã che thông tin cá nhân (regex và Luhn), kèm kết quả công cụ. Thứ tự gọi: OpenRouter trước, AstralX dự phòng | `copilot/services/privacy.py`, `app/config.py` (`copilot_llm_order`) |
| Phân quyền | Ba vai trò `owner`, `member`, `viewer`. Nhà lấy theo tài khoản đăng nhập, không có `home_id` trên URL. `viewer` chỉ đọc. Chỉ `owner` sửa được hồ sơ nhà. Mỗi tài khoản thuộc một nhà | `home/dependencies.py`, `home/services/home.py` |
| Thành viên | Có bảng lời mời (`tb_home_invite`) nhưng **không có API** mời, xem danh sách hay gỡ thành viên | `home/models/`, `home/routes/home.py` |
| Xóa | Xóa tài khoản (`DELETE /users/me`): xóa nhà và số đo khi chủ nhà ở một mình, trả 409 nếu còn thành viên. Xóa từng cuộc trò chuyện. **Không có** cách xóa lịch sử điện mà vẫn giữ tài khoản, cũng không xóa được hết Wappi trong một lần | `auth/services/account.py`, `copilot/routes/copilot.py` |
| Đồng ý | Một câu ở màn đăng ký gộp mọi mục đích. **Không lưu** bằng chứng đồng ý. Thông báo email bật sẵn | `dashboard/messages/vi/auth.json` (`terms`), `auth/models/model_user_preference.py` |
| Công khai | Trang Chính sách quyền riêng tư nêu tên OpenRouter, AstralX, OpenWeather, Google và mốc giữ 400 ngày. Trong dashboard **không có** màn hình quyền riêng tư; trang Cài đặt chỉ có form thông tin nhà | `web/messages/vi/legal.json`, `dashboard/app/[locale]/(dashboard)/(pages)/dashboard/settings/page.tsx` |
| So sánh với các nhà khác | Chỉ dùng phân vị, chỉ tính khi có ít nhất 10 nhà | `insight/services/cohort.py` (`MIN_COHORT_HOMES`) |
| Sơ đồ | Đã có `data-flow.svg`, `data-lifecycle.svg`, `system.svg`. **[chưa kiểm]** chúng có thể hiện các bên ngoài và chỗ vượt biên giới hay không | `wattprint-backend/docs/diagrams/` |

## 4. Khoảng trống

| # | Khoảng trống | Gắn với yêu cầu | Gắn với điều luật |
|---|---|---|---|
| G1 | Dữ liệu theo phút và dữ liệu gốc giữ 400 ngày, dài hơn mức các tính năng cần | Giảm độ chi tiết phải lưu | Luật Đ3 k3, Đ14 k1 b |
| G2 | Wappi truy vấn được dữ liệu theo phút, và kết quả đi sang OpenRouter ở nước ngoài | Giảm độ chi tiết phải chia sẻ | Luật Đ30 k1, Đ20 |
| G3 | Không xóa được lịch sử điện mà vẫn giữ tài khoản; không xóa hết Wappi trong một lần; chưa có quy trình yêu cầu bên ngoài cùng xóa | Cho phép xóa lịch sử | Luật Đ4 k1 d, Đ14 k3; NĐ Đ10 k6 |
| G4 | Đồng ý gộp mọi mục đích, không lưu bằng chứng, thông báo email bật sẵn | (luật) | Luật Đ9 k4; NĐ Đ6 k1–3 |
| G5 | Chỉ báo về dịch vụ ngoài trong trang Chính sách; lúc dùng Wappi hay giọng nói không có dòng báo nào | Nêu rõ khi gọi dịch vụ ngoài | Luật Đ9 k2; NĐ Đ10 k3 |
| G6 | Không có màn hình nào cho người dùng thấy ai đang xem được dữ liệu nhà mình | Giới hạn quyền truy cập, màn hình quyền riêng tư | NĐ Đ5 k1 |
| G7 | Test phân quyền rải ở nhiều file, chưa có một ma trận vai trò × API để làm minh chứng | Thử phân quyền | Luật Đ30 k3 |
| G8 | Chưa có hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên giới | (luật) | Luật Đ20 k2; NĐ Đ18 |

## 5. Đề xuất

### P1. Giữ dữ liệu theo bậc (G1)

**Làm gì.** Dữ liệu chi tiết chỉ giữ ngắn hạn. Sau đó chỉ còn số theo giờ và theo ngày.

| Bảng | Hiện tại | Đề xuất |
|---|---|---|
| `tb_reading`, `tb_device_estimate` (số gốc) | 400 ngày | N ngày **[cần quyết]** |
| `*_1m` (theo phút) | 400 ngày | N ngày, bằng số gốc |
| `*_1h` (theo giờ) | chưa thấy chính sách | 400 ngày (đủ so cùng kỳ năm trước) |
| `*_1d` (theo ngày) | chưa thấy chính sách | Giữ tới khi người dùng xóa |
| Hóa đơn đã chốt | giữ | Giữ (là thứ người dùng cần xem lại) |

**Trước khi chọn N phải kiểm** (chưa làm): những phần nào đang đọc dữ liệu gốc hoặc dữ liệu phút cũ hơn N ngày. Đã biết có:
NILM (cửa sổ đầu vào và chạy lại lịch sử), mô hình dự báo dùng mức 7 ngày, công cụ `standby` (đọc 14 đêm), các
mô hình thiết bị được huấn luyện lại. Cách làm: grep các truy vấn tới `tb_reading` và `*_1m`, ghi lại mỗi chỗ cần lùi
về bao xa. N là số lớn nhất trong đó, làm tròn lên.

**Sửa ở đâu.** Một migration Alembic mới: `remove_retention_policy` rồi `add_retention_policy` với N, có `downgrade`
trả về 400 ngày. Ghi mốc giữ dữ liệu mới vào `legal.json` (mục giữ dữ liệu).

**Rủi ro.** Dữ liệu cũ hơn N ngày bị xóa ngay khi job chạy, **không lấy lại được**. Phải chạy thử trên bản sao DB
trước. Các nhà demo (REFIT, Plegma, ENERTALK) phát lại bản ghi theo vòng lặp, nên cần kiểm tra chính sách mới không
xóa mất phần nguồn của vòng phát lại.

**Minh chứng.** Truy vấn `timescaledb_information.jobs` trước và sau. Test migration lên rồi xuống.

### P2. Wappi chỉ thấy số theo giờ trở lên (G2)

**Làm gì.** Thu quyền `SELECT` của role copilot trên `copilot_ro.reading_1m` và `copilot_ro.device_estimate_1m`
(hoặc bỏ hẳn hai view này). Các công cụ cần dữ liệu phút (như `standby`) vẫn chạy trong backend và chỉ gửi kết quả
tóm tắt (một con số, một mức) cho mô hình, không gửi chuỗi số theo phút.

**Sửa ở đâu.** Migration cho quyền trên view; schema mô tả bảng mà text2sql dùng (bỏ hai view khỏi danh sách để mô
hình không sinh SQL tới chúng); phần mô tả trong `wattprint-text2sql-mcp`.

**Kiểm thêm [chưa kiểm]:** kết quả `query_data` có giới hạn số dòng trước khi gửi cho mô hình hay không. Nếu chưa có,
đặt một trần (ví dụ 48 dòng theo giờ, đủ cho hai ngày) để một câu hỏi không kéo cả tháng theo giờ đi ra nước ngoài.

**Minh chứng.** Test: role copilot `SELECT` vào view phút thì bị từ chối. Đo lại `scripts/eval_wappi.py` trên một nhà:
câu trả lời không được kém đi. Nếu kém đi thì ghi số đo thật, không ghi ước đoán.

### P3. Đồng ý theo từng mục đích, có lưu bằng chứng (G4, G5)

**Làm gì.** Tách các mục đích:

| Mục đích | Căn cứ | Mặc định |
|---|---|---|
| Đo điện, tính hóa đơn, tách thiết bị (NILM), cảnh báo trong app | Thỏa thuận dịch vụ (Luật Đ19 k1 d) | Luôn bật, nói rõ ở màn đăng ký |
| Wappi: gửi câu hỏi và số liệu nhà cho OpenRouter hoặc AstralX ở nước ngoài | Đồng ý | **Tắt.** Hỏi lần đầu mở Wappi |
| Giọng nói: gửi âm thanh cho AstralX | Đồng ý | **Tắt.** Hỏi lần đầu bấm mic |
| Email cảnh báo và tóm tắt tuần | Đồng ý | **Tắt** (đổi default `notify_anomaly`, `notify_tier` sang `false` cho tài khoản mới) |

Bảng mới `tb_consent` (`user_id`, `purpose`, `granted`, `policy_version`, `at`), chỉ ghi thêm, không sửa dòng cũ.
Dòng cuối của mỗi mục đích là trạng thái hiện tại. Bảng này là bằng chứng "ai, lúc nào, đồng ý nội dung gì" mà
NĐ Đ6 k2 yêu cầu.

Rút lại đồng ý Wappi thì chặn ngay ở backend: route chat trả lỗi `consent_required`, không chỉ ẩn nút ở giao diện.

**Câu hỏi khi xin đồng ý Wappi (bản nháp, viết bằng lời thường):**
> Wappi trả lời bằng mô hình AI của OpenRouter (Mỹ), dự phòng bằng AstralX. Khi bạn hỏi, câu hỏi (đã che số điện
> thoại, căn cước, email, số thẻ) và các con số điện năng theo giờ hoặc theo ngày của nhà bạn sẽ được gửi tới đó.
> WattPrint không gửi tên hay địa chỉ của bạn. Bạn có thể tắt bất cứ lúc nào trong Cài đặt › Quyền riêng tư.
> [Đồng ý và dùng Wappi] [Không, cảm ơn]

**Tài khoản cũ:** Luật Đ39 chỉ giữ hiệu lực cho đồng ý đã xin theo NĐ 13/2023. Câu gộp chung hiện nay khó coi là
đồng ý theo từng mục đích, nên đề xuất hỏi lại tài khoản cũ khi họ mở Wappi lần tới. Khách xem demo cũng được hỏi
như vậy. **[cần quyết]**

**Minh chứng.** Test: chưa đồng ý thì gọi chat nhận 403 `consent_required`; đồng ý rồi rút lại thì bị chặn lại ngay;
mỗi lần bật hoặc tắt ghi thêm một dòng.

### P4. Màn hình Cài đặt › Quyền riêng tư (G5, G6, minh chứng)

Một tab mới trong Cài đặt. Theo quy ước giao diện: dùng component Hairline, chữ thường ngày, chi tiết đặt trong tooltip.

1. **Chúng tôi giữ gì, bao lâu.** Bảng ngắn theo bậc ở P1, viết bằng lời thường: "Số đo từng phút: N ngày",
   "Số theo giờ: 400 ngày", "Số theo ngày và hóa đơn: tới khi bạn xóa".
2. **Ai xem được nhà này.** Danh sách thành viên, gồm tên, vai trò và ngày tham gia. Chỉ xem, không có thao tác. Cần
   một API đọc mới: `GET /home/current/members`.
3. **Gửi ra ngoài.** Mỗi dịch vụ một dòng: tên, nước đặt máy chủ, dữ liệu gửi đi, công tắc đồng ý (Wappi, giọng nói,
   email). OpenWeather (chỉ tọa độ cấp tỉnh) và Google (chỉ khi đăng nhập bằng Google) được ghi ra để biết, không có
   công tắc.
4. **Xóa.** Ba nút, mỗi nút có bước xác nhận ngay trong trang:
   - Xóa toàn bộ trò chuyện với Wappi (kèm âm thanh đã lưu).
   - Xóa lịch sử điện năng (P5).
   - Xóa tài khoản (dùng lại luồng đã có).
5. **Cách AI dùng dữ liệu của bạn.** Hai câu giải thích NILM và Wappi (NĐ Đ10 k3). Link tới trang Chính sách.

Khách xem demo (`viewer`) thấy cả màn hình nhưng các nút xóa và công tắc bị khóa, kèm một dòng giải thích.

### P5. Xóa lịch sử điện năng, vẫn giữ tài khoản (G3)

**Làm gì.** `DELETE /home/current/history`, **chỉ chủ nhà** (`owner`) được gọi **[cần quyết: thành viên có được không]**.
Xóa số đo gốc, ước tính thiết bị, các bảng tổng hợp, chu kỳ thiết bị, ảnh chụp dự báo, cảnh báo và gợi ý của nhà.
Giữ hồ sơ nhà, thiết bị, công tơ và hóa đơn đã chốt **[cần quyết]**. Sau khi xóa, nhà bắt đầu lại từ số đo mới.

**Dùng lại** cách xóa của `delete_account`, vì nó đã xử lý được giới hạn giải nén 100.000 dòng của Timescale. Tách phần
"xóa dữ liệu điện của một nhà" thành một hàm, cho cả hai luồng cùng gọi. Không viết lại lần thứ hai.

**Xóa hết Wappi:** `DELETE /copilot/conversations` xóa mọi cuộc trò chuyện của tài khoản và âm thanh đã lưu.

**Bên ngoài (Luật Đ14 k3, NĐ Đ5 k4):** WattPrint không gọi được API xóa ở OpenRouter hoặc AstralX. Đề xuất:
(a) kiểm xem OpenRouter có chế độ không lưu dữ liệu (zero data retention) cho tài khoản API hay không, nếu có thì bật
**[chưa kiểm]**; (b) ghi trên màn hình Xóa rằng bản đã gửi ra ngoài phụ thuộc chính sách lưu của bên đó, kèm link
(Luật Đ14 k5: không xóa được thì phải báo).

**Minh chứng.** Test: chủ nhà xóa thì các bảng về 0 dòng cho nhà đó và nhà khác không bị đụng; thành viên hoặc khách
xem gọi thì nhận 403; nhà demo thì bị từ chối.

### P6. Báo ngay lúc gọi dịch vụ ngoài (G5)

- Ô chat Wappi: một dòng nhỏ cố định dưới ô nhập: "Câu hỏi được gửi tới OpenRouter (Mỹ). Thông tin cá nhân đã được che."
- Nút mic: tooltip "Âm thanh được gửi tới AstralX để chuyển thành chữ".
- Mỗi câu trả lời ghi tên nhà cung cấp đã trả lời (OpenRouter hoặc AstralX dự phòng). Backend đã biết bên nào trả lời
  vì có thứ tự `copilot_llm_order`. **[chưa kiểm]** giá trị này đã được lưu theo từng câu trả lời chưa.

Sửa copy trong `copilot.json` trước, rồi mới sửa TSX.

### P7. Ma trận thử phân quyền (G7, minh chứng)

Một file test mới `tests/test_access_matrix.py`, có tham số theo bốn vai trò: chủ nhà, thành viên, khách xem, người
ngoài (tài khoản có nhà khác). Chạy qua mọi route đọc và ghi dữ liệu nhà: năng lượng, thiết bị, hóa đơn, cảnh báo, kế
hoạch, Wappi, xóa lịch sử, danh sách thành viên. Thêm hai ca riêng: mã phạm vi của Wappi hết hạn sau 5 phút thì view trả
0 dòng; mã của nhà A không đọc được nhà B.

Kết quả xuất thành một bảng (vai trò × route → mã trạng thái) và đưa vào minh chứng. Bảng sinh từ test, không gõ tay.

### P8. Sơ đồ luồng dữ liệu (minh chứng, G8)

Cập nhật `wattprint-backend/docs/diagrams/data-flow.svg` (hoặc vẽ mới): công tơ → ingest → Timescale (ghi rõ mỗi bậc
giữ bao lâu) → NILM, dự báo → dashboard; nhánh Wappi → text2sql (chỉ mức giờ trở lên) → OpenRouter hoặc AstralX, đánh
dấu **ranh giới Việt Nam / nước ngoài**; giọng nói → AstralX; thời tiết → OpenWeather (tọa độ tỉnh); email → SMTP.
Mỗi mũi tên ghi loại dữ liệu đi qua. Sơ đồ này cũng là phần "sơ đồ luồng xử lý dữ liệu" của Mẫu số 09.

## 6. Việc ngoài code (không thuộc PR này, nhưng cần người chịu trách nhiệm)

- **Hồ sơ đánh giá tác động chuyển dữ liệu xuyên biên giới** (Mẫu số 09, nộp trong 60 ngày kể từ lần chuyển đầu).
  Không có miễn trừ cho quy mô nhỏ. Đầu vào: sơ đồ P8, bảng mục đích ở P3, chính sách giữ ở P1. Người làm: bên kiểm
  soát dữ liệu ghi trên trang Chính sách.
- **Thỏa thuận với bên nhận** (NĐ Đ7 k1): lưu lại bản điều khoản xử lý dữ liệu của OpenRouter và AstralX đang áp dụng.
- **Hồ sơ đánh giá tác động xử lý** (Mẫu số 10): có thể được miễn theo NĐ Đ41, **nếu** dữ liệu không bị coi là nhạy cảm
  (mục 8.1) và WattPrint thuộc diện doanh nghiệp nhỏ hoặc hộ kinh doanh. Hiện bên kiểm soát là **một cá nhân**, nên
  không rõ có thuộc diện đó hay không.
- Luật sư đọc lại trang Chính sách (đã ghi trong backlog).

## 7. Không làm (đề xuất bỏ, mời phản biện)

- **Quản lý thành viên** (mời, gỡ, đổi vai trò): yêu cầu chỉ đòi "giới hạn quyền". Phần đó đã có trong backend, chỉ
  thiếu minh chứng (P7) và chỗ hiển thị (P4 mục 2).
- **Xuất dữ liệu** (quyền được cung cấp dữ liệu, Luật Đ4 k1 d): luật có quyền này, nhưng yêu cầu lần này không nhắc
  tới. Nếu làm thì riêng một thay đổi khác. NĐ Đ5 k3 cho 10 ngày, nên trước mắt có thể xử lý qua email.
- **Làm nhiễu hoặc gộp dữ liệu trước khi lưu** (differential privacy, gộp 15 phút ngay khi ghi): NILM cần dữ liệu chi
  tiết lúc tính. Bậc giữ ở P1 đã giảm phần lưu lâu dài với ít rủi ro hơn.
- **NER để nhận ra tên, địa chỉ** (backlog #14): giữ ở backlog. Câu hỏi về điện ít khi chứa địa chỉ, và P2 đã cắt phần
  dữ liệu lộ nếp sinh hoạt nhất.
- **Cho tắt NILM**: NĐ Đ10 k3 đòi có lựa chọn không tham gia xử lý tự động, nhưng tắt NILM thì mất tính năng lõi. Xem
  mục 8.3.

## 8. Câu hỏi để phản biện

1. **Đường phụ tải có phải dữ liệu cá nhân nhạy cảm không?** NĐ 356 Điều 4 khoản 1 có điểm c ("thông tin về đời sống
   riêng tư, bí mật gia đình") và điểm l ("dữ liệu theo dõi hành vi, hoạt động sử dụng... các dịch vụ khác trên không
   gian mạng"). Đường tiêu thụ theo phút gắn với một hộ có thể bị coi là thuộc một trong hai điểm. Nếu đúng vậy: phải
   nói rõ đó là dữ liệu nhạy cảm khi xin đồng ý (NĐ Đ6 k4), phải mã hóa khi chuyển giao (NĐ Đ7 k2), và **mất miễn trừ**
   theo Đ41 (phải lập cả Mẫu 10). Nhóm kỹ thuật nghiêng về phương án làm như thể đó là dữ liệu nhạy cảm (P1, P2 đi
   theo hướng này), nhưng đây là chỗ cần người hiểu luật xác nhận.
2. **N ngày cho dữ liệu chi tiết** là bao nhiêu? Đề xuất: chọn theo kết quả kiểm ở P1, không chọn trước.
3. **NILM có phải cho chọn không tham gia không** (NĐ Đ10 k3)? Phương án: coi NILM là một phần thỏa thuận dịch vụ (Đ19
   k1 d), giải thích cách hoạt động ở P4 mục 5, và lối thoát là xóa lịch sử hoặc xóa tài khoản. Phương án này có đủ không?
4. **Thành viên có được xóa lịch sử điện của cả nhà không?** Đề xuất: chỉ chủ nhà.
5. **Hóa đơn đã chốt** có nằm trong phần "xóa lịch sử điện" không?
6. **Tài khoản cũ** có phải hỏi lại đồng ý không (P3)?
7. **AstralX** đặt máy chủ ở đâu? Nếu ở Việt Nam thì đường dự phòng và giọng nói không phải chuyển xuyên biên giới, và
   lời báo ở P6 viết khác đi.

## 9. Thứ tự làm và độ khó

Độ khó theo quy ước của backlog. Chưa ước lượng giờ.

| Bước | Việc | Khó | Phụ thuộc |
|---|---|---|---|
| 1 | P2: Wappi bỏ mức phút, đặt trần số dòng | Dễ | Không |
| 2 | P7: ma trận phân quyền (viết trước để giữ an toàn cho các bước sau) | Vừa | Không |
| 3 | P3: `tb_consent`, chặn ở backend, đổi default email | Vừa | Câu hỏi 6 |
| 4 | P5: xóa lịch sử điện, xóa hết Wappi | Vừa | Câu hỏi 4, 5 |
| 5 | P4 và P6: màn hình Quyền riêng tư, dòng báo trong Wappi | Vừa | Bước 3, 4 |
| 6 | P1: bậc giữ dữ liệu (cuối cùng, vì không đảo ngược được) | Vừa | Câu hỏi 2, chạy thử trên bản sao |
| 7 | P8: sơ đồ, ảnh chụp màn hình, bảng ma trận (gom minh chứng) | Dễ | Bước 1–6 |

Mỗi bước có test viết trước, và đi qua vòng review của sdlc (R1 đầy đủ, R2 và R3 có phạm vi).

## 10. Nguồn

- Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15, bản Word:
  https://static3.luatvietnam.vn/uploaded/others/2025/08/21/luat-91-2025-qh15_2108094942.docx
  (bản chính thức: https://mps.gov.vn/chinh-sach-phap-luat/co-so-du-lieu-van-ban/luat-bao-ve-du-lieu-ca-nhan-1753688803)
- Nghị định 356/2025/NĐ-CP:
  https://luatnguyen.vn/van-ban-phap-luat/nghi-dinh-356-2025-nd-cp-huong-dan-luat-bao-ve-du-lieu-ca-nhan-2574.html
  (đối chiếu: https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Nghi-dinh-356-2025-ND-CP-huong-dan-Luat-Bao-ve-du-lieu-ca-nhan-687428.aspx)
- Hiện trạng trong code: các đường dẫn ở mục 3.
