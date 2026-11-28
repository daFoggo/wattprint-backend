# Bảo vệ dữ liệu nếp sinh hoạt: đề xuất thiết kế

Ngày: 2026-11-28 · Trạng thái: **bản đề xuất để phản biện**, chưa triển khai · Mốc code: commit `b0eb01b` (nhánh `main`)

Phạm vi: lưu trữ, chia sẻ, phân quyền, xóa và gọi dịch vụ bên ngoài đối với dữ liệu điện của hộ gia đình trong backend
WattPrint, áp cho cả code hiện tại (một app, một database nhiều schema) lẫn kiến trúc 4 service đã chốt
(`docs/architecture/README.md`). Ngoài phạm vi: code app mobile/web (tài liệu chỉ đặc tả màn hình và API), phần cứng
cảm biến, an ninh vật lý.

Ký hiệu dùng trong tài liệu:

- **[V]** đã kiểm bằng đọc code ở commit `b0eb01b`; chưa chạy thử trên database trừ khi ghi rõ.
- **[L]** trích từ văn bản pháp luật (nguồn ở Phụ lục B). Phần diễn giải áp dụng cho WattPrint là của người soạn,
  **chưa qua tư vấn pháp lý**.
- **[C]** lựa chọn của người soạn, mời phản biện.
- **[U]** cần nhóm quyết (tổng hợp ở mục 13).
- **[TBV]** phải kiểm chứng bằng chạy thật khi làm.

Tài liệu liên quan: `docs/database-design.md`, `docs/superpowers/specs/2026-11-01-database-design-design.md`,
`docs/architecture/README.md`, `docs/superpowers/plans/2026-11-10-microservices-split.md`, `docs/database-audit.md`.

---

## 0. Tóm tắt cho người phản biện

**Đề bài.** Dữ liệu phụ tải theo giờ có thể tiết lộ lịch sinh hoạt của gia đình. Hệ thống phải giảm mức chi tiết phải
lưu và chia sẻ, giới hạn quyền truy cập, cho phép xóa lịch sử và nêu rõ khi gọi dịch vụ bên ngoài. Minh chứng gồm sơ
đồ luồng dữ liệu, màn hình quyền riêng tư và thử phân quyền.

**Hiện trạng (mục 5).**

- Phần đọc dữ liệu của Copilot (`copilot_ro`) được cách ly rất chặt.
- Ngược lại, có **10 lỗ hổng**. Bốn lỗ hổng nặng nhất:
  - Dữ liệu theo giờ và theo ngày đang giữ vô hạn (G1).
  - Xóa nhà không xóa số đo (G2).
  - Role AI đọc được dữ liệu theo phút của mọi nhà (G4).
  - Không có cơ chế đồng ý hay nhật ký khi gửi dữ liệu ra ngoài (G7).

**Pháp lý (mục 3).** Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 và Nghị định 356/2025/NĐ-CP có hiệu lực từ
01/01/2026. Đề xuất áp dụng theo hướng thận trọng:

- Xếp dữ liệu nếp sinh hoạt (số đo chi tiết, kết quả NILM) vào **dữ liệu cá nhân nhạy cảm**, theo Nghị định 356 Điều
  4.1.c và 10.2.
- Thời hạn xử lý yêu cầu xóa là **20 ngày**; nếu phải nhờ bên xử lý hoặc bên thứ ba thì **30 ngày** (Nghị định 356
  Điều 5.4).
- Gửi dữ liệu cho LLM đặt ở nước ngoài là **chuyển dữ liệu xuyên biên giới**, phải lập hồ sơ đánh giá tác động trong
  60 ngày (Luật Điều 20).
- Sự đồng ý phải tách theo từng mục đích, kiểm chứng được và **không được mặc định đồng ý** (Luật Điều 9, Nghị định
  356 Điều 6).

**Đề xuất cốt lõi.** Nguyên tắc chung: chi tiết chỉ dành cho chính hộ đó và chỉ giữ ngắn hạn; mọi bên khác và mọi
thứ lưu dài hạn chỉ dùng dữ liệu đã gộp thô.

1. Rút hạn lưu (mục 7.1):
   - Số đo thô: từ 400 ngày xuống 14 ngày.
   - Tầng 1 phút: từ 400 ngày xuống 35 ngày.
   - Tầng 1 giờ: từ vô hạn xuống 13 tháng.
   - Giờ bật/tắt từng thiết bị: 90 ngày.
2. Đặt **sàn mức chi tiết** cho từng bên nhận (mục 7.2). Dữ liệu đưa vào LLM tối thiểu là 1 giờ và đã bỏ tên thiết
   bị, tên phòng, định danh.
3. Phân quyền theo nhà (mục 7.3):
   - API không nhận `home_id` từ client.
   - Admin không mặc nhiên được xem dữ liệu nhà; truy cập hỗ trợ phải được chủ nhà cấp và có thời hạn.
   - Role database chỉ có quyền tối thiểu cần thiết.
4. Xóa thật ở mọi bản sao, có trạng thái theo từng service, theo đúng thời hạn luật định (mục 7.4).
5. Một cửa ra (egress) duy nhất cho dịch vụ bên ngoài (mục 7.5). Cửa này kiểm sự đồng ý, tối thiểu hóa dữ liệu, ghi
   nhật ký mà người dùng xem được, và gắn công bố vào từng câu trả lời của Copilot.

**Muốn được phản biện nhiều nhất.**

- Hạn 14 ngày cho số đo thô có đủ cho NILM không (U1)?
- Có nên xếp dữ liệu phụ tải là dữ liệu nhạy cảm không (U2)?
- Nên dùng LLM trong nước hay LLM nước ngoài kèm khử nhận dạng (U3)?
- Cách xóa trực tiếp trên bảng materialization của aggregate (mục 7.4.3, [TBV]) có an toàn không?
- Thành viên trong nhà nên được xem dữ liệu tới mức nào (U6)?

---

## 1. Đề bài và tiêu chí đạt

> **1. Bảo vệ dữ liệu nếp sinh hoạt.** Vấn đề: Dữ liệu phụ tải theo giờ có thể tiết lộ lịch sinh hoạt gia đình.
> Yêu cầu: Giảm độ chi tiết phải lưu/chia sẻ, giới hạn quyền truy cập và cho phép xóa lịch sử; nêu rõ khi gọi dịch vụ
> ngoài. Minh chứng: Sơ đồ luồng dữ liệu, màn hình quyền riêng tư và thử phân quyền.

Tách đề bài thành các yêu cầu kiểm chứng được:

| Mã | Yêu cầu | Tiêu chí đạt (tóm tắt, chi tiết ở mục 10.4) |
|---|---|---|
| R1 | Giảm độ chi tiết phải **lưu** | Mọi loại dữ liệu có hạn lưu; dữ liệu càng chi tiết thì giữ càng ngắn; policy được kiểm bằng test |
| R2 | Giảm độ chi tiết phải **chia sẻ** | Mỗi bên nhận có sàn mức chi tiết và danh sách trường bị cấm; được kiểm bằng test trên payload |
| R3 | Giới hạn quyền truy cập | Chỉ thành viên của nhà xem được dữ liệu nhà; admin không mặc nhiên xem; role database chỉ có quyền tối thiểu; có ma trận test |
| R4 | Cho phép xóa lịch sử | Người dùng tự xóa được; xóa ở mọi service và mọi bản sao; có trạng thái; đúng thời hạn luật định |
| R5 | Nêu rõ khi gọi dịch vụ ngoài | Có danh mục bên xử lý; có đồng ý theo mục đích; có nhật ký từng lần gọi; công bố ngay trên giao diện |
| R6 | Minh chứng | Sơ đồ luồng dữ liệu (DFD), màn hình quyền riêng tư, bộ thử phân quyền chạy được, cho thấy rõ trước/sau |

---

## 2. Vì sao dữ liệu phụ tải nhạy cảm

### 2.1 Suy ra được gì ở từng mức chi tiết

Bảng dưới tổng hợp từ tài liệu nghiên cứu ở Phụ lục B, **chưa đo trên dữ liệu WattPrint** [TBV, xem đề xuất thí
nghiệm ở mục 10.5].

| Mức chi tiết | Có thể suy ra | Ví dụ trong WattPrint |
|---|---|---|
| Dưới 1 giây đến vài giây | Thiết bị cụ thể đang chạy. Với dữ liệu 0,5 s còn nhận ra được kênh TV đang xem (Greveler và cộng sự, 2012) | `tb_reading` (REFIT khoảng 7 s một mẫu) |
| 1 phút đến 15 phút | Giờ thức dậy, nấu ăn, tắm, đi ngủ; lúc nhà có người hay vắng (Molina-Markham và cộng sự, 2010) | `reading_1m`, `device_estimate_1m`, `tb_device_cycle` |
| 1 giờ | Lịch sinh hoạt theo ngày; khung giờ vắng nhà lặp lại đều đặn (rủi ro trộm cắp) | `reading_1h`, read model theo giờ của insight |
| 1 ngày | Vắng nhà dài ngày (đi du lịch), thay đổi số người ở | `reading_1d`, hóa đơn |
| 1 tháng | Mức tiêu thụ; gần như không lộ nếp sinh hoạt | `tb_bill` |

### 2.2 NILM làm rủi ro tăng

Số đo tổng chỉ cho thấy "nhà đang dùng điện". NILM tách ra thành "ấm đun nước bật lúc 6:10, máy giặt chạy lúc 23:40,
TV tắt lúc 0:15". `tb_device_estimate` và `tb_device_cycle` vì thế là **nhật ký sinh hoạt** theo đúng nghĩa đen.

Nghị định 356 Điều 10.2 nói rõ dữ liệu suy luận từ AI, nếu giúp xác định một con người cụ thể, thì phải được bảo vệ
như dữ liệu cá nhân [L].

### 2.3 Tiền lệ quốc tế

- **Anh (Smart Metering Data Access and Privacy Framework, 2012).** Nhà cung cấp điện được lấy dữ liệu theo tháng mà
  không cần đồng ý, theo ngày trừ khi khách từ chối, còn theo nửa giờ thì chỉ khi khách đồng ý. Đây là tiền lệ cho
  việc phân tầng mức chi tiết với mặc định thô.
- **Hà Lan (2009).** Thượng viện bác dự luật bắt buộc lắp công tơ thông minh vì lý do quyền riêng tư. Sau đó người
  dùng được quyền từ chối hoặc chọn chế độ đọc hạn chế.
- **EU (Article 29 Working Party, Opinion 12/2011 về smart metering).** Yêu cầu quyền riêng tư từ thiết kế (privacy by
  design), tối thiểu hóa dữ liệu, và giữ dữ liệu chi tiết ngắn hạn.

---

## 3. Khung pháp lý Việt Nam

Nguồn đã đọc nguyên văn:

- Luật 91/2025/QH15, bản Word đăng trên LuatVietnam.
- Nghị định 356/2025/NĐ-CP, bản Công báo số 18 ngày 18/01/2026.

Đường dẫn ở Phụ lục B. Mọi trích dẫn dưới đây là [L]. Phần "áp dụng cho WattPrint" là diễn giải của người soạn, cần
người có chuyên môn pháp lý xác nhận trước khi đưa vào báo cáo chính thức.

### 3.1 Hiệu lực và phạm vi

- Luật có hiệu lực từ 01/01/2026 (Điều 38.1). Nghị định 356 có hiệu lực cùng ngày và thay Nghị định 13/2023/NĐ-CP
  (Điều 42.1, 42.2).
- Luật áp dụng cho tổ chức, cá nhân Việt Nam và nước ngoài xử lý dữ liệu cá nhân của công dân Việt Nam (Điều 1.2).
- Phân vai (Luật Điều 2.7–2.10):
  - WattPrint (đơn vị vận hành) là **bên kiểm soát và xử lý dữ liệu cá nhân**.
  - LLM provider, Expo, APNs/FCM, Telegram, nhà cung cấp đám mây là **bên xử lý** hoặc **bên thứ ba**.
  - Ai là bên kiểm soát trong giai đoạn thí điểm (nhóm, PTIT hay đối tác) là câu hỏi U5.

### 3.2 Phân loại dữ liệu của WattPrint

Định nghĩa trong Luật (Điều 2):

- Điều 2.1: dữ liệu cá nhân là "dữ liệu số hoặc thông tin dưới dạng khác xác định hoặc giúp xác định một con người cụ
  thể… Dữ liệu cá nhân sau khi khử nhận dạng không còn là dữ liệu cá nhân."
- Điều 2.11: khử nhận dạng là "quá trình thay đổi hoặc xóa thông tin để tạo ra dữ liệu mới không thể xác định hoặc
  không thể giúp xác định được một con người cụ thể."

Áp dụng cho từng loại dữ liệu:

| Dữ liệu WattPrint | Phân loại đề xuất | Căn cứ |
|---|---|---|
| Email, họ tên (`tb_users`) | Cơ bản | NĐ 356 Điều 3.1, 3.11 |
| Mã bưu chính, mã tỉnh, loại nhà, diện tích, số người ở (`tb_home`) | Cơ bản (gắn với nơi ở) | NĐ 356 Điều 3.4, 3.11 |
| Số đo thô, aggregate 1 phút/1 giờ, ước lượng NILM, chu kỳ thiết bị, cảnh báo | **Nhạy cảm (đề xuất, thận trọng)** | NĐ 356 Điều 4.1.c ("thông tin về đời sống riêng tư, bí mật cá nhân, bí mật gia đình"); Điều 10.2 (kết quả suy luận AI) |
| Tên thiết bị, tên phòng do người dùng đặt | Cơ bản; có thể nhạy cảm (ví dụ "Phòng bé Na") | NĐ 356 Điều 3.11 |
| Hội thoại Copilot | Tùy nội dung, xử lý như nhạy cảm | NĐ 356 Điều 4.1.c |
| `tb_cohort_stat` (phân vị trên ≥ 10 hộ) | Đã khử nhận dạng, không còn là dữ liệu cá nhân | Luật Điều 2.1, 2.11 |
| Thời tiết theo tỉnh | Không phải dữ liệu cá nhân | — |

Nếu nhóm chấp nhận xếp dữ liệu nếp sinh hoạt là **nhạy cảm** (U2), kéo theo năm hệ quả:

1. Phải có quy định phân quyền giới hạn truy cập, quy trình xử lý và biện pháp bảo mật (NĐ 356 Điều 4.2).
2. Khi xin đồng ý phải báo cho chủ thể biết đây là dữ liệu nhạy cảm (NĐ 356 Điều 6.4).
3. Khi chuyển giao phải có biện pháp mã hóa hoặc ẩn danh (NĐ 356 Điều 7.2).
4. **Mất quyền miễn** lập hồ sơ đánh giá tác động trong 5 năm dành cho doanh nghiệp nhỏ và khởi nghiệp, vì quyền miễn
   này không áp dụng cho bên "trực tiếp xử lý dữ liệu cá nhân nhạy cảm" (Luật Điều 38.2, NĐ 356 Điều 41.1).
5. Có thể bị coi là "dịch vụ xử lý dữ liệu cá nhân" (NĐ 356 Điều 21.6, 21.8: dịch vụ phân tích, khai thác dữ liệu
   cá nhân, dự đoán hành vi, xử lý tự động bằng AI). Khi đó phải có Giấy chứng nhận đủ điều kiện kinh doanh (NĐ 356
   Điều 22–25). **Đây là điểm pháp lý lớn nhất cần hỏi chuyên gia trước khi thương mại hóa** [U5].

### 3.3 Sự đồng ý

Luật 91/2025/QH15 quy định:

- Thu thập phải có đồng ý **trước khi** thu thập, trừ khi luật quy định khác (Điều 11.1).
- Đồng ý chỉ có hiệu lực khi tự nguyện và chủ thể biết rõ ba điều (Điều 9.2):
  - (a) loại dữ liệu và mục đích xử lý;
  - (b) bên kiểm soát;
  - (c) quyền và nghĩa vụ của chủ thể.
- Đồng ý phải được thể hiện "rõ ràng, cụ thể, có thể in, sao chép bằng văn bản, bao gồm cả dưới dạng điện tử hoặc
  định dạng kiểm chứng được" (Điều 9.3).
- Bốn nguyên tắc (Điều 9.4): đồng ý **theo từng mục đích**; không kèm điều kiện buộc đồng ý mục đích khác; có hiệu
  lực tới khi chủ thể thay đổi; "**sự im lặng hoặc không phản hồi không được coi là sự đồng ý**".
- Rút lại đồng ý (Điều 10): bằng văn bản, kể cả dạng điện tử. Việc rút lại **không áp dụng ngược** cho phần xử lý đã
  làm trước thời điểm rút (Điều 10.4).
- Trường hợp không cần đồng ý (Điều 19.1), trong đó có điểm d: "thực hiện thỏa thuận của chủ thể dữ liệu cá nhân với
  cơ quan, tổ chức, cá nhân có liên quan theo quy định của pháp luật".

Nghị định 356/2025/NĐ-CP quy định:

- Phương thức xin đồng ý phải "bảo đảm khả năng kiểm chứng được về việc xác định chủ thể dữ liệu cá nhân đã thực hiện
  sự đồng ý, thời điểm và nội dung được đồng ý". Đồng ý qua ứng dụng có thiết lập kỹ thuật xin đồng ý là hợp lệ (Điều
  6.1.d).
- Bên kiểm soát phải **lưu trữ** sự đồng ý; khi có tranh chấp, **bên kiểm soát chịu trách nhiệm chứng minh** (Điều
  6.2).
- "**không được thiết lập phương thức mặc định đồng ý**". Thiết lập mặc định phải bảo đảm nguyên tắc bảo vệ dữ liệu
  (Điều 6.3).
- Với dữ liệu nhạy cảm, chủ thể phải được thông báo rằng dữ liệu cần xử lý là dữ liệu nhạy cảm (Điều 6.4).

**Áp dụng cho WattPrint** [C]:

- Đồng ý tách theo mục đích:
  - `core`: đo, tách thiết bị, hiển thị, hóa đơn.
  - `ai_copilot`: gửi dữ liệu tới LLM.
  - `push_detail`: thông báo có nội dung chi tiết.
  - `telegram`.
  - `cohort`: đóng góp số liệu cho so sánh nhóm.
  - `research`: giữ số đo thô lâu hơn để cải thiện mô hình.
- Mọi lựa chọn mặc định là **tắt**.
- Mỗi lần đồng ý lưu: ai, lúc nào, phiên bản nội dung và mã băm của nội dung đã hiển thị.
- Màn hình xin đồng ý hiện đủ ba thông tin bắt buộc của Điều 9.2, ghi rõ "dữ liệu nhạy cảm", và nói rõ dữ liệu có ra
  nước ngoài hay không.

### 3.4 Quyền của chủ thể và thời hạn phải đáp ứng

Luật Điều 4.1 liệt kê các quyền:

- được biết về việc xử lý;
- đồng ý, không đồng ý hoặc rút lại đồng ý;
- xem, chỉnh sửa;
- **yêu cầu cung cấp, xóa, hạn chế xử lý, phản đối**;
- khiếu nại, đòi bồi thường;
- yêu cầu áp dụng biện pháp bảo vệ.

Thời hạn theo NĐ 356 Điều 5. Mỗi loại yêu cầu được gia hạn tối đa một lần, phải thông báo lý do và chứng minh việc gia
hạn là cần thiết:

| Yêu cầu | Phản hồi | Thực hiện | Khi cần bên xử lý hoặc bên thứ ba | Gia hạn tối đa |
|---|---|---|---|---|
| Rút đồng ý, hạn chế, phản đối (Điều 5.2) | 2 ngày làm việc | 15 ngày | 20 ngày | +15 ngày |
| Xem, chỉnh sửa, cung cấp (Điều 5.3) | 2 ngày làm việc | 10 ngày | 15 ngày | +10 ngày |
| **Xóa** (Điều 5.4) | 2 ngày làm việc | **20 ngày** | **30 ngày** | +20 ngày |
| Yêu cầu biện pháp bảo vệ (Điều 5.5) | 2 ngày làm việc | 15 ngày | — | +15 ngày |

NĐ 356 Điều 5.1 còn yêu cầu bên kiểm soát phải có "quy trình, thủ tục, biểu mẫu rõ ràng" để chủ thể thực hiện quyền.

**Áp dụng cho WattPrint** [C]:

- Mọi yêu cầu đi qua API nên được xác nhận ngay lập tức, đáp ứng mốc phản hồi 2 ngày làm việc.
- Mục tiêu tự đặt cho việc xóa là **24 giờ** cho dữ liệu nội bộ, dưới mốc 20 ngày của luật.
- Nên có **xuất dữ liệu** (quyền được cung cấp, thời hạn 10 ngày). Vì vậy tài liệu xếp chức năng này vào P1, không để
  P2.

### 3.5 Xóa, hủy dữ liệu

Luật Điều 14 quy định:

- Các trường hợp phải xóa (14.1): chủ thể yêu cầu (a); **đã hoàn thành mục đích** (b); **hết thời hạn lưu trữ** (c);
  theo thỏa thuận (đ).
- Bên kiểm soát phải xóa, hoặc **yêu cầu bên xử lý và bên thứ ba xóa**, "bằng các biện pháp an toàn; ngăn chặn hoạt
  động xâm nhập và khôi phục trái phép dữ liệu cá nhân đã bị xóa, hủy" (14.3).
- "Trường hợp không thể xóa, hủy dữ liệu cá nhân vì lý do chính đáng… phải thông báo để chủ thể dữ liệu cá nhân biết"
  (14.5).
- Không xóa trong các trường hợp của Điều 19, hoặc khi việc xóa vi phạm Điều 4.3 (14.2). Điều 4.3.c: thực hiện quyền
  không được xâm phạm quyền, lợi ích hợp pháp của người khác. Điểm này liên quan đến dữ liệu chung của cả nhà.

Các quy định bổ trợ:

- Luật Điều 3.3: dữ liệu được lưu "trong khoảng thời gian phù hợp với mục đích xử lý". Đây là căn cứ cho G1 và mục
  7.1.
- NĐ 356 Điều 9.2.c (xử lý dữ liệu lớn): phải "xây dựng chính sách lưu trữ, xóa, hủy dữ liệu cá nhân phù hợp".
- NĐ 356 Điều 10.6 (hệ thống AI): chủ thể "phải có quyền chỉnh sửa, ẩn danh, xóa hồ sơ nhận dạng, kể cả khi nền tảng
  lưu trữ lịch sử hành vi".

**Áp dụng cho WattPrint** [C]:

- Hạn lưu tự động chính là cách thực hiện điểm b và c của Điều 14.1.
- Bản sao lưu (backup) nên giữ **≤ 14 ngày**. Khi đó dữ liệu đã xóa sẽ tự biến mất khỏi mọi backup trước mốc 20 ngày,
  không cần dùng tới ngoại lệ "lý do chính đáng" của Điều 14.5.
- Dữ liệu đã gửi cho LLM provider không thể thu hồi về phía mình. Hệ thống phải gửi yêu cầu xóa tới provider (nếu
  provider có API cho việc này) và thông báo cho chủ thể theo Điều 14.5.

### 3.6 Chuyển dữ liệu xuyên biên giới

Luật Điều 20.1 coi ba trường hợp sau là chuyển dữ liệu xuyên biên giới:

- (a) chuyển dữ liệu đang lưu ở Việt Nam sang hệ thống lưu trữ ở nước ngoài;
- (b) chuyển cho tổ chức, cá nhân ở nước ngoài;
- (c) "sử dụng nền tảng ở ngoài lãnh thổ… để xử lý dữ liệu cá nhân được thu thập tại Việt Nam".

NĐ 356 Điều 17.1.a nói thêm rõ trường hợp lưu "trên dịch vụ điện toán đám mây của nhà cung cấp dịch vụ ở nước ngoài".

Nghĩa vụ:

- Lập **hồ sơ đánh giá tác động chuyển dữ liệu cá nhân xuyên biên giới** và gửi bản chính cho cơ quan chuyên trách
  (thuộc Bộ Công an) **trong 60 ngày kể từ lần chuyển đầu tiên** (Luật 20.2).
- Đánh giá làm một lần, sau đó cập nhật định kỳ 6 tháng khi có mục đích mới hoặc bên xử lý mới. Một số thay đổi phải
  cập nhật trong 10 ngày (Luật 20.3, 22; NĐ 356 Điều 20).
- Hồ sơ gồm (NĐ 356 Điều 18.2, 18.3):
  - báo cáo theo Mẫu số 09;
  - bản sao hợp đồng với bên nhận;
  - chính sách và quy trình bảo vệ dữ liệu;
  - mục đích, loại dữ liệu và **sơ đồ luồng xử lý dữ liệu cá nhân** (18.3.c);
  - việc xin đồng ý và chính sách lưu trữ, xóa, hủy (18.3.d);
  - biện pháp bảo vệ (18.3.đ);
  - sơ đồ hệ thống của bên nhận (18.3.e);
  - đánh giá rủi ro và biện pháp giảm thiểu (18.3.i).
- Các trường hợp miễn (Luật 20.6, NĐ 356 Điều 17.3) **không bao gồm** trường hợp của WattPrint. Gần nhất là điểm
  20.6.c, "chủ thể dữ liệu cá nhân tự chuyển dữ liệu cá nhân của mình", nhưng ở đây hệ thống mới là bên gửi.
- Phạt: vi phạm quy định chuyển dữ liệu xuyên biên giới bị phạt tối đa **5% doanh thu năm trước**; vi phạm khác tối
  đa 3 tỷ đồng; cá nhân chịu một nửa mức của tổ chức (Luật Điều 8.4–8.6).

Áp dụng cho các luồng ra ngoài của WattPrint [C]:

| Luồng | Có phải chuyển dữ liệu cá nhân xuyên biên giới? | Ghi chú |
|---|---|---|
| Copilot gửi LLM provider ở nước ngoài | **Có** (Điều 20.1.b/c) | Câu hỏi tự do của người dùng có thể chứa dữ liệu cá nhân, nên khử nhận dạng không loại trừ hoàn toàn được |
| Copilot gửi LLM trong nước hoặc tự host | Không | Phương án A ở mục 7.5.6 |
| Thông báo đẩy qua Expo (Mỹ), rồi APNs/FCM | **Có**: push token và nội dung thông báo | Không tránh được nếu cần push trên mobile; giảm thiểu bằng nội dung chung chung |
| Telegram | **Có** | Khó ký thỏa thuận xử lý dữ liệu với Telegram, xem U4 |
| Google OIDC (đăng nhập) | Người dùng tự đăng nhập với Google; Keycloak nhận email và tên từ Google | Chiều đi ra gần như không có dữ liệu; vẫn liệt kê để minh bạch |
| Open-Meteo (Đức) | Không: chỉ gửi tọa độ tỉnh, không phải dữ liệu cá nhân | Không được gắn định danh nhà vào request |
| Máy chủ hoặc backup đặt trên đám mây ở nước ngoài | **Có** (NĐ 356 Điều 17.1.a) | Nên đặt máy chủ thí điểm tại Việt Nam |

### 3.7 Đánh giá tác động xử lý dữ liệu (DPIA)

- Bên kiểm soát lập hồ sơ DPIA và gửi bản chính trong **60 ngày kể từ lần xử lý đầu tiên** (Luật Điều 21.1).
- Nội dung hồ sơ (NĐ 356 Điều 19.3): mục đích, loại dữ liệu, **sơ đồ luồng dữ liệu cá nhân**, việc xin đồng ý,
  chính sách lưu trữ và xóa, phương án bảo đảm an toàn, **sơ đồ thiết kế hệ thống**, kết quả đánh giá tuân thủ, đánh
  giá rủi ro.
- Miễn 5 năm cho doanh nghiệp nhỏ và khởi nghiệp, **trừ khi** trực tiếp xử lý dữ liệu nhạy cảm hoặc có từ 100.000 chủ
  thể trở lên (Luật Điều 38.2; NĐ 356 Điều 41.1).

**Áp dụng cho WattPrint:** phần lớn những gì đề xuất này tạo ra (DFD, chính sách hạn lưu, quy trình xóa, ma trận
quyền, đánh giá rủi ro) chính là nội dung bắt buộc của hồ sơ DPIA và hồ sơ chuyển xuyên biên giới. Phụ lục A truy vết
từng mục.

### 3.8 AI, dữ liệu lớn, đám mây

Luật Điều 30:

- 30.1: xử lý đúng mục đích và "giới hạn trong phạm vi cần thiết". Đây là căn cứ cho sàn mức chi tiết của LLM.
- 30.3: phải tích hợp biện pháp bảo mật, xác thực, định danh và **phân quyền truy cập**.
- 30.4: xử lý bằng AI "phải thực hiện **phân loại theo mức độ rủi ro**".

Nghị định 356:

- **Điều 9, dữ liệu lớn.** Là xử lý "quy mô lớn, có tính liên tục, tích hợp từ nhiều nguồn khác nhau, có khả năng
  phân tích hành vi, dự đoán xu hướng". WattPrint có thể thuộc nhóm này khi mở rộng. Các yêu cầu:
  - 9.2.e: phải giải thích cho chủ thể;
  - 9.3.b: xác thực mạnh, "**yêu cầu tối thiểu xác thực đa yếu tố**… phù hợp với mức độ nhạy cảm";
  - 9.3.c: mã hóa hoặc ẩn danh khi chuyển giao, cung cấp; định nghĩa ẩn danh ở đây là tách dữ liệu định danh để lưu
    riêng, khớp với cách thay tên bằng bí danh ở mục 7.2;
  - 9.3.d: "giám sát liên tục… theo dõi hoạt động truy cập dữ liệu cá nhân".
- **Điều 10, hệ thống AI.**
  - 10.3: phải thông báo việc xử lý tự động, "giải thích nguyên tắc hoạt động của thuật toán", và "đưa ra các lựa
    chọn để chủ thể dữ liệu có quyền không tham gia".
  - 10.5.đ: đánh giá tuân thủ **mỗi năm một lần**.
- **Điều 12, điện toán đám mây.**
  - 12.2: hợp đồng với nhà cung cấp phải nêu rõ luồng dữ liệu, vai trò và yêu cầu xóa.
  - 12.4: dữ liệu trên đám mây "phải được **mã hoá ở trạng thái nghỉ và truyền**".

**Phân loại rủi ro AI đề xuất** (theo Luật Điều 30.4) [C]:

| Thành phần | Mức | Lý do | Biện pháp chính | Cách từ chối tham gia |
|---|---|---|---|---|
| NILM (tách thiết bị) | Trung bình | Tạo ra dữ liệu nếp sinh hoạt từ số đo tổng | Hạn lưu ngắn; xử lý trong nước; không gửi ra ngoài | Tắt NILM; chỉ xem số tổng |
| Dự báo, phát hiện bất thường | Thấp đến trung bình | Dùng dữ liệu theo giờ, kết quả ở lại trong nhà | Hạn lưu; phân quyền | Tắt cảnh báo |
| Copilot hỏi đáp (pull) | **Cao** nếu LLM ở nước ngoài, trung bình nếu trong nước | Dữ liệu ra khỏi hệ thống | Đồng ý riêng; sàn chi tiết; khử nhận dạng; nhật ký; công bố | Mặc định tắt |
| Copilot gợi ý chủ động (push) và xếp hạng theo phản hồi | Trung bình | Lập hồ sơ hành vi chấp nhận gợi ý (`p̂_u`) | Giải thích nguyên lý; cho phép tắt cá nhân hóa | Tắt gợi ý chủ động |

### 3.9 Trẻ em

Với trẻ em, người đại diện theo pháp luật thay mặt thực hiện các quyền. Việc "công bố, tiết lộ thông tin về đời sống
riêng tư" của trẻ từ đủ 7 tuổi phải có đồng ý của cả trẻ và người đại diện (Luật Điều 24.2).

**Áp dụng cho WattPrint** [C]: nhà có trẻ em thì nếp sinh hoạt của trẻ nằm trong dữ liệu nhà. Vì vậy:

- Chủ nhà xác nhận khi bắt đầu dùng rằng mình là người đại diện, hoặc đã thông báo cho các thành viên trong nhà.
- Không có tính năng nào công bố dữ liệu ra ngoài nhà.

### 3.10 Vi phạm và thông báo

- Phải thông báo cho cơ quan chuyên trách **chậm nhất 72 giờ** kể từ khi phát hiện vi phạm có thể xâm phạm tính
  mạng, danh dự, tài sản của chủ thể (Luật Điều 23.1).
- Nội dung thông báo gồm thời gian, loại dữ liệu, số lượng, hậu quả và biện pháp xử lý, theo Mẫu số 08 (NĐ 356
  Điều 28).

**Áp dụng cho WattPrint** [C]: nhật ký truy cập (mục 7.3.6) và nhật ký gọi ra ngoài (mục 7.5.4) là nguồn dữ liệu để
lập thông báo này. Cần thêm một quy trình xử lý sự cố 72 giờ (mục 11, nhánh L).

### 3.11 Từ quy định ra yêu cầu kỹ thuật

| Quy định [L] | Yêu cầu kỹ thuật | Mục |
|---|---|---|
| Luật 3.3, 14.1.b/c; NĐ 9.2.c | Hạn lưu theo mức chi tiết, có policy và test | 7.1 |
| Luật 30.1; NĐ 7.2, 9.3.c | Sàn mức chi tiết; khử nhận dạng và thay tên bằng bí danh trước khi chuyển giao | 7.2 |
| NĐ 4.2; Luật 30.3; NĐ 9.3.b | Phân quyền theo nhà; role database tối thiểu; bắt buộc MFA cho tài khoản admin và hỗ trợ | 7.3 |
| NĐ 9.3.d | Nhật ký truy cập, cảnh báo truy cập bất thường | 7.3.6 |
| Luật 4.1.d, 14; NĐ 5.4, 10.6 | Xóa tự phục vụ, lan truyền tới mọi service, có trạng thái và hạn chót | 7.4 |
| Luật 9, 10, 11.1; NĐ 6 | Đồng ý theo mục đích, mặc định tắt, có bằng chứng, rút lại được | 7.5.2 |
| Luật 20; NĐ 17, 18 | Danh mục bên xử lý; đánh dấu luồng xuyên biên giới; dữ liệu đầu vào cho hồ sơ | 7.5.1, 10.1 |
| NĐ 10.3 | Giải thích NILM và Copilot; cho phép từ chối tham gia | 7.5.5, 10.2 |
| Luật 4.1.a, 4.1.d; NĐ 5.3 | Màn hình "dữ liệu đang lưu", xuất dữ liệu | 10.2, 9 |
| NĐ 12.4 | TLS, mã hóa đĩa và backup khi lên đám mây | 7.3.7 |
| Luật 23; NĐ 28 | Quy trình xử lý sự cố 72 giờ dựa trên nhật ký | 11 |

---

## 4. Mô hình đe dọa

**Tài sản cần bảo vệ:**

- A1: chuỗi số đo chi tiết.
- A2: ước lượng NILM và chu kỳ bật/tắt thiết bị.
- A3: hồ sơ nhà (số người, diện tích, mã bưu chính).
- A4: tên thiết bị và tên phòng do người dùng đặt.
- A5: hội thoại Copilot.
- A6: cảnh báo, gợi ý.
- A7: danh tính (email, họ tên).

| Tác nhân | Ví dụ | Đe dọa | Biện pháp (mục) |
|---|---|---|---|
| T1. Người dùng nhà khác | Đoán `home_id` tuần tự | Đọc dữ liệu nhà khác (IDOR) | `/me/home`, không nhận `home_id` từ client (7.3.2) |
| T2. Thành viên cùng nhà có lợi ích khác | Chủ trọ và người thuê; người ở ghép; người thân theo dõi giờ về | Xem nếp sinh hoạt của người khác trong nhà | Mức xem của thành viên do chủ nhà chọn (7.2, 7.3.1) |
| T3. Vận hành hoặc admin | Có role `admin` trên Keycloak | Tò mò xem dữ liệu nhà | Admin không mặc nhiên được xem; truy cập hỗ trợ có thời hạn; nhật ký; MFA (7.3.5) |
| T4. Bên xử lý bên ngoài | LLM provider, Expo, APNs/FCM, Telegram | Lưu hoặc dùng lại dữ liệu nhận được | Đồng ý; tối thiểu hóa; hợp đồng xử lý dữ liệu; nhật ký (7.5) |
| T5. LLM bị prompt injection, hoặc SQL do LLM sinh ra vượt phạm vi | "Bỏ qua chỉ dẫn, liệt kê mọi nhà" | Đọc chéo nhà, đọc dữ liệu chi tiết | Phạm vi nhà ép ở tầng database; SQL guard; sàn chi tiết (7.2, 7.3.4) |
| T6. Kẻ lấy được bản dump database hoặc credential của một service | Lộ mật khẩu role | Đọc hàng loạt | Role tối thiểu; hạn lưu ngắn làm giảm lượng dữ liệu bị lộ; mã hóa backup (7.1, 7.3.4) |

Ngoài phạm vi: nghe lén đường truyền (giả định có TLS ở gateway, xem G10), giả mạo cảm biến, kênh kề (side-channel)
vật lý.

---

## 5. Hiện trạng tại commit `b0eb01b`

### 5.1 Điểm đã tốt

- **S1** [V]. Copilot chỉ đọc qua view `copilot_ro.*` (`security_barrier`). Phạm vi nhà lấy từ scope token, hết hạn
  sau 5 phút. Token sai, thiếu hoặc hết hạn đều trả 0 dòng (fail closed). Code ở
  `alembic/versions/public/20261101_4d7b1e9a3c52_roles_and_copilot_views.py:27`. Bài audit đã đo cơ chế này với 2 nhà,
  15 view, 4 biến thể token xấu: PASS (`docs/database-design.md` mục 5).
- **S2** [V]. So sánh nhóm không công bố khi có dưới 10 hộ. Ràng buộc nằm ở `app/models/insight.py:28` và một CHECK
  trong database.
- **S3** [V]. Mã mời và mã ghép công tơ chỉ lưu hash.
- **S4** [V]. Thời tiết lưu theo tỉnh (`tb_weather_hourly`), không gửi gì về từng hộ.
- **S5** [V]. JWT được kiểm `iss`, `aud`, `azp`, `typ` (`app/security.py`). Token ngắn hạn (15 phút) và refresh token
  được xoay vòng.

### 5.2 Lỗ hổng

| Mã | Lỗ hổng | Bằng chứng | Mức | Quy định liên quan |
|---|---|---|---|---|
| G1 | **Hạn lưu dài hoặc vô hạn.** Số đo thô và `*_1m` giữ 400 ngày; `*_1h`, `*_1d` vô hạn. `tb_device_cycle` (hypertable), `tb_alert`, `ai_message`, `ai_tool_call`, `tb_suggestion` không có hạn lưu | `alembic/versions/public/20261101_f3a9c1e5b7d2_compress_1m_aggregates.py:97-116`; `docs/database-design.md` mục 4 ("1h và 1d giữ vô thời hạn"); hypertable `tb_device_cycle` ở `20261110_c1d4e8a2b6f0_initial_insight_module.py:77` không có retention [V] | Cao | Luật 3.3; NĐ 9.2.c |
| G2 | **Xóa nhà không xóa số đo.** `tb_reading` và `tb_device_estimate` không có FK (theo thiết kế). Xóa `tb_home` làm `tb_series` bị xóa dây chuyền, nhưng các dòng đo và bucket aggregate vẫn còn, thành mồ côi. Code đã ghi nhận điều này: "rows of deleted series are orphans" | `app/models/energy.py:96`, `app/services/aggregates.py:65` [V] | **Cao** | Luật 14.3 |
| G3 | **Xóa mềm bảng dimension của data mart AI.** `ai.dim_home` và `ai.dim_device` chỉ đặt `is_deleted = true`, vẫn giữ `device_name`, `room`, `occupants`, diện tích | `alembic/versions/ai/20261110_a4c7e1d93b62_initial_home_device_dimensions.py:85,124` [V] | Trung bình | Luật 14.3; NĐ 10.6 |
| G4 | **Role AI đọc chéo nhà.** `wattprint_ai` có SELECT trên `ai.fact_reading_1m`, `ai.fact_estimate_1m`, `ai.fact_energy`, `ai.dim_*` mà **không lọc theo nhà** (khác với `copilot_ro`). Role này còn có DML trên hội thoại của mọi người dùng | `.../ai/20261110_f39a7b2c5d18_initial_energy_fact_views.py:41`; `.../ai/20261110_a4c7e1d93b62_...py:231`; `.../ai/20261110_e5b8c2a7d914_initial_conversation_module.py:76` [V] | **Cao** | NĐ 4.2; Luật 30.3 |
| G5 | `wattprint_app` có `ALL PRIVILEGES` kèm default privileges trên schema `public`. Tài liệu đã ghi là "cần rà soát" | `alembic/versions/public/20261110_cf93b7d8a102_public_app_user.py:43`; `docs/database-design.md` mục 4 [V] | Trung bình | NĐ 4.2 |
| G6 | **Chưa có kiểm quyền theo nhà.** Vai trò `owner`/`member` có trong database nhưng chưa được dùng ở đâu. ID nhà là số nguyên tăng dần nên đoán được. Hiện chưa có endpoint dữ liệu nhà nào, nên chưa khai thác được; sẽ thành lỗ hổng ngay khi thêm endpoint | `app/models/core.py:57-58`; `app/routers/` chỉ có `health`, `users` [V] | Cao (tiềm ẩn) | Luật 30.3 |
| G7 | **Không có cơ chế đồng ý và minh bạch.** Không có bảng đồng ý, danh mục bên xử lý, nhật ký gọi ra ngoài hay công bố trên giao diện. Nội dung thông báo đẩy và Telegram chưa bị giới hạn | Kế hoạch tách service chỉ nêu "guardrail PII" và notifier (`docs/architecture/README.md` mục 1; plan dòng 134-136) [V] | **Cao** | Luật 9, 11.1, 20; NĐ 6 |
| G8 | **Không có sàn mức chi tiết cho dữ liệu đưa vào LLM.** `copilot_ro` cung cấp `reading_1m`, `device_estimate_1m` và `device_cycle` với giờ bật/tắt chính xác, kèm `device.name`, `device.room` | `.../20261101_4d7b1e9a3c52_...py` (danh sách `VIEWS`) [V] | **Cao** | Luật 30.1; NĐ 7.2 |
| G9 | **Hai FK chặn việc xóa.** `fk_meter_home_id_home` không có `ondelete` (NO ACTION), nên xóa nhà có công tơ đã ghép sẽ lỗi. `fk_home_invite_used_by_users` cũng NO ACTION, nên xóa tài khoản từng dùng mã mời sẽ lỗi | `alembic/versions/public/20261101_7a91e4d2b6c8_initial_home_module.py:179,196` [V] [TBV chạy thử] | Trung bình | Luật 14; NĐ 5.4 |
| G10 | Dev chạy HTTP, `start-dev`, chưa mã hóa lưu trữ. README đã ghi là cần làm trước khi lên production | `README.md` "Hardening before production" [V] | Thấp hiện tại, **bắt buộc trước thí điểm** | NĐ 12.4 |

Lệnh kiểm chứng từng lỗ hổng nằm ở Phụ lục C.

---

## 6. Nguyên tắc thiết kế

1. **Chi tiết cho chủ nhà và ngắn hạn; thô cho mọi bên khác và dài hạn.** Giá trị sản phẩm (timeline giống Sense)
   cần dữ liệu chi tiết, nhưng chỉ cho chính hộ đó và chỉ trong thời gian ngắn.
2. **Mặc định riêng tư.** Mọi thứ đi ra ngoài phạm vi chức năng cốt lõi đều phải tự bật (opt-in), mặc định tắt (NĐ 6.3).
3. **Không tin `home_id` từ client hay từ LLM.** Phạm vi nhà luôn lấy từ danh tính đã xác thực, và được ép ở tầng thấp
   nhất có thể (view hoặc database).
4. **Xóa là xóa thật ở mọi bản sao.** Phần không xóa được (dữ liệu đã gửi LLM, backup chưa hết hạn) phải được nói rõ
   (Luật 14.5).
5. **Mỗi lần gọi ra ngoài để lại một dòng nhật ký mà người dùng xem được.**
6. **Chứng minh bằng test chạy thật.** Đây là văn hóa audit sẵn có của repo: test đỏ trước khi sửa, xanh sau khi sửa.

---

## 7. Đề xuất chi tiết

### 7.1 R1: Hạn lưu

#### 7.1.1 Bảng hạn lưu mặc định [C]

| Dữ liệu | Hiện tại | Đề xuất | Vì sao còn đủ cho tính năng |
|---|---|---|---|
| Số đo thô `tb_reading`, ước lượng thô `tb_device_estimate` | 400 ngày | **14 ngày**. Giữ 400 ngày chỉ khi chủ nhà bật `research` | NILM chạy ngay sau ingest (luồng `PENDING_INFERENCE`); 14 ngày đủ để chạy lại khi nilm gặp sự cố hoặc phải rollback model. **[U1]** cần nhóm NILM xác nhận lượng dữ liệu cần cho hiệu chỉnh theo hộ |
| `reading_1m`, `device_estimate_1m` | 400 ngày | **35 ngày** | `pick_step` dùng `reading_1m` cho cửa sổ ≤ 41 ngày (30 ngày cho ra bước 30m, 42 ngày cho ra 1h; đã tính lại theo `LADDER`). Màn hình Month cần 30 ngày; 35 ngày = 30 + đệm |
| `reading_1h`, `device_estimate_1h` | vô hạn | **13 tháng** | So sánh cùng kỳ năm trước, M&V (cần ≥ 14 ngày), dự báo (cần ≥ 7 ngày) |
| `reading_1d`, `device_estimate_1d`, `tb_bill`, `tb_bill_item` | vô hạn | Đến khi xóa nhà | Hóa đơn, xu hướng theo năm; mức ngày ít lộ nếp sinh hoạt |
| `tb_device_cycle` (giờ bật/tắt từng lần) | vô hạn | **90 ngày** | Timeline thiết bị gần đây. Sau 90 ngày, kWh/ngày theo thiết bị vẫn còn trong `device_estimate_1d` |
| `tb_alert` | vô hạn | 13 tháng | Lịch sử cảnh báo trong một năm |
| `tb_suggestion`, `tb_suggestion_feedback` | vô hạn | 13 tháng; `tb_savings_measure` giữ cùng gợi ý | M&V theo năm |
| `ai_message`, `ai_tool_call` | vô hạn | **90 ngày**; người dùng tự xóa được bất kỳ lúc nào | Ngữ cảnh hội thoại |
| `tb_scope_token` | không có job dọn | Dọn token hết hạn mỗi giờ | Đã là việc mở trong `docs/database-design.md` mục 6 |
| Outbox, inbox (sau khi tách service) | chưa có | Outbox: xóa sau khi gửi + 7 ngày. Inbox: chỉ lưu `message_id`, xóa sau 30 ngày | Payload sự kiện chứa kWh theo giờ của từng thiết bị |
| Log container | mặc định của Docker | `max-size`/`max-file`, khoảng 7 ngày; **không log giá trị đo, tên thiết bị hay nội dung câu hỏi** | — |
| Backup | chưa có | **≤ 14 ngày**, có mã hóa | Mục 3.5 |

#### 7.1.2 Cách làm

1. **Một revision trong `alembic/versions/updates/`** (vì sửa đối tượng đã có): đưa `public.set_policies` lên phiên
   bản 3 với các offset mới, rồi chạy `set_policies(false)` và `set_policies(true)` để gỡ và thêm lại policy. Phải
   làm vậy vì `if_not_exists` không cập nhật offset của policy đã tồn tại (ghi chú có sẵn trong migration
   `c8a4e1f7b295`). Thêm retention cho `*_1h` (395 ngày) và `tb_device_cycle` (90 ngày).
2. **Job dọn bảng thường** (không phải hypertable): `tb_alert`, `tb_suggestion*`, `ai_message`, `ai_tool_call`,
   `tb_scope_token`. Có thể dùng `add_job` của TimescaleDB hoặc background task trong lifespan của service.
3. **`app/services/meter.py`**: thêm `RETENTION_1M = timedelta(days=35)`. Khi `since < now - RETENTION_1M`, ladder bắt
   đầu từ `1h` để không đọc vào vùng 1 phút đã bị xóa.

#### 7.1.3 Bất biến phải giữ khi rút hạn lưu [C] [TBV]

Continuous aggregate xếp tầng: 1m đọc từ raw, 1h đọc từ 1m, 1d đọc từ 1h. Một refresh đi qua vùng mà tầng nguồn đã bị
xóa sẽ **xóa luôn bucket** của tầng đích. Đây đúng là rủi ro đã đo ở drill 10b (`docs/database-audit.md`). Vì vậy với
mỗi tầng:

| Tầng | `start_offset` của refresh | Hạn lưu của tầng nguồn | Bất biến |
|---|---|---|---|
| 1m | 7 ngày | raw 14 ngày | 7 < 14 ✔ |
| 1h | 30 ngày | 1m 35 ngày | 30 < 35 ✔ |
| 1d | 60 ngày | 1h 395 ngày | 60 < 395 ✔ |

Thêm hai điều kiện về nén:

- `compress_after` của 1m (14 ngày) phải lớn hơn `start_offset` 7 ngày và nhỏ hơn hạn lưu 35 ngày ✔.
- Raw nén sau 2 ngày, nhỏ hơn hạn lưu 14 ngày ✔.

Hệ quả cho `backfill_aggregates`: guard so số dòng đã materialize với **raw**. Khi raw chỉ còn 14 ngày, mọi ngày cũ
hơn 14 ngày đều bị bỏ qua ở cả ba tầng. Nghĩa là chỉ backfill được dữ liệu trễ trong 14 ngày gần nhất. Như vậy chấp
nhận được, nhưng phải ghi rõ trong tài liệu vận hành.

Kiểm chứng bằng test T-RET-01 (mục 10.3) và một drill trên bản sao giống drill 10b.

#### 7.1.4 Phương án đã cân nhắc và bị loại cho bản đầu

- **Hạn lưu riêng cho từng nhà.** `drop_chunks` áp cho cả bảng nên không làm theo nhà được. Muốn làm phải `DELETE`
  theo `series_id` trên chunk đã nén, trong khi spec cấm dùng `DELETE` từng dòng cho retention và chi phí chưa đo.
  Để lại làm chế độ "Riêng tư cao" ở P2 (mục 11).
- **Gộp dữ liệu ngay trên cảm biến.** NILMFormer cần đầu vào tần số cao, và cảm biến (ESP32, Shelly) không chạy được
  NILM.
- **Thêm nhiễu hoặc che tải (load hiding) trên dữ liệu lưu trữ.** Làm sai hóa đơn và NILM, tức phá giá trị cốt lõi
  của sản phẩm. Chỉ cân nhắc thêm nhiễu cho `tb_cohort_stat` (P2).
- **Mã hóa theo từng nhà rồi xóa khóa (crypto-shredding).** Nén và continuous aggregate của TimescaleDB cần số ở
  dạng rõ.

### 7.2 R2: Sàn mức chi tiết khi chia sẻ

#### 7.2.1 Theo từng bên nhận [C]

| Bên nhận | Hiện tại | Đề xuất |
|---|---|---|
| Chủ nhà (app) | Chưa có API | Mọi mức chi tiết còn trong hạn lưu |
| Thành viên | Chưa có kiểm quyền | Chủ nhà chọn `member_view`: `full` (mặc định cho gia đình), `device_daily` (tổng thiết bị theo ngày) hoặc `home_daily` (chỉ tổng nhà theo ngày, cho nhà trọ hay ở ghép) **[U6]** |
| Insight (nội bộ, qua sự kiện) | kWh theo giờ của từng thiết bị | Giữ nguyên. Đây là chia sẻ giữa các bộ phận trong cùng tổ chức (Luật 17.1.b), nhưng cần quy trình kiểm soát (NĐ 7.4). Read model của insight theo hạn lưu 13 tháng |
| Copilot gửi LLM | Mức 1 phút, giờ bật/tắt chính xác, tên thiết bị và phòng (G8) | **Tối thiểu 1 giờ**; câu hỏi tổng quát mặc định theo ngày; quy tắc ở mục 7.2.2 |
| Thông báo đẩy (Expo, APNs/FCM) | Nội dung tùy ý | Mặc định nội dung chung ("Có cảnh báo mới về điện nhà bạn"). Nội dung chi tiết chỉ khi người dùng bật `push_detail`, vì nó hiện trên màn hình khóa và đi qua máy chủ ở nước ngoài |
| Telegram | Nội dung tùy ý | Như thông báo đẩy, hoặc bỏ kênh này **[U4]** |
| So sánh nhóm | Tối thiểu 10 hộ | Giữ tối thiểu 10 hộ; chỉ theo ngày hoặc tháng; hộ phải bật `cohort`; P2 cân nhắc thêm nhiễu |
| Admin, vận hành | Role `admin` trên Keycloak; `wattprint_app` có ALL | Không xem dữ liệu nhà; chỉ xem khi có truy cập hỗ trợ (mục 7.3.5) |
| Open-Meteo | Theo tỉnh | Giữ nguyên |

#### 7.2.2 Quy tắc tối thiểu hóa cho Copilot [C]

1. **Tool trả về hai kênh.** `display` chứa dữ liệu chi tiết, đi thẳng tới client để vẽ thẻ hay biểu đồ. `llm_view`
   chứa bản thô đã tối thiểu hóa, là thứ duy nhất LLM nhìn thấy. Cách này khớp nguyên tắc "tools first, language
   second" của concept note: con số đến từ tool, LLM chỉ giải thích.
   Ví dụ, với câu "Máy giặt hôm qua chạy lúc mấy giờ?", thẻ trên giao diện ghi "21:47–22:31", còn LLM chỉ thấy
   "thiết bị #2 (máy giặt): 1 lần, buổi tối, 0,6 kWh".
2. **Thay tên bằng bí danh.** `device.name` và `device.room` được thay bằng `thiết bị #k (<loại>)`. Bảng ánh xạ chỉ
   tồn tại trong bộ nhớ của request ở copilot, và được thay ngược lại trong câu trả lời cuối trước khi trả cho người
   dùng. Cách này đúng với định nghĩa "ẩn danh" ở NĐ 9.3.c.
3. **Không gửi định danh.** Không gửi email, họ tên, tên nhà, mã bưu chính, `home_id`, `user_id`. Hồ sơ nhà chỉ gửi
   ở dạng khoảng, ví dụ "3–4 người", "50–80 m²".
4. **Làm tròn thời gian về giờ** hoặc dùng mô tả tương đối ("tối hôm qua").
5. **Lọc PII trong câu hỏi tự do.** Guardrail PII đã có trong kế hoạch: che số điện thoại, địa chỉ, họ tên trước khi
   gửi.
6. **Kiểm ở tầng dữ liệu.** API truy vấn an toàn của insight, hay `copilot_ro` trên code hiện tại, **không cung cấp**
   view 1 phút hay `device_cycle` dạng thô cho đường đi tới LLM. Chỉ có view 1h/1d và
   `device_cycle_hourly(device_id, hour, n_cycles, energy_wh)`.

### 7.3 R3: Phân quyền

#### 7.3.1 Vai trò và ma trận quyền [C]

| Hành động | Chủ nhà | Thành viên | Hỗ trợ (có grant) | Admin realm | Service nội bộ |
|---|---|---|---|---|---|
| Xem chuỗi số đo, thiết bị | ✔ | ✔ theo `member_view` | ✔ trong thời hạn grant, chỉ đọc | ✘ | Theo role database |
| Đổi cài đặt riêng tư, mời hoặc xóa thành viên | ✔ | ✘ | ✘ | ✘ | — |
| Xóa lịch sử của nhà (theo khoảng, theo thiết bị) | ✔ | ✘ | ✘ | ✘ | — |
| Xóa hội thoại, phản hồi của chính mình | ✔ | ✔ | ✘ | ✘ | — |
| Rời nhà | — | ✔ | — | — | — |
| Xóa nhà | ✔ | ✘ | ✘ | ✘ | — |
| Đồng ý, rút đồng ý | ✔ (của mình) | ✔ (của mình) | ✘ | ✘ | — |
| Xem nhật ký gọi ra ngoài | ✔ | ✔ (các lần do chính mình gây ra) | ✘ | ✘ | — |
| Cấp hoặc thu hồi truy cập hỗ trợ | ✔ | ✘ | — | ✘ | — |
| Liệt kê người dùng (`GET /users`) | ✘ | ✘ | ✘ | ✔, không kèm dữ liệu nhà | — |

#### 7.3.2 Tầng API

- **Không nhận `home_id` từ client.** Mỗi tài khoản chỉ thuộc một nhà (`UNIQUE (user_id)` trên `tb_home_member`), nên
  route có dạng `/me/home/...`. Nhà và vai trò được lấy từ người dùng đã xác thực. Cách này **loại bỏ cả nhóm lỗi
  IDOR** chứ không chỉ chặn từng trường hợp.
- Dependency đề xuất (phác thảo, theo phong cách của `app/dependencies.py`):

```python
async def get_membership(user: CurrentUser, db: DbSession) -> HomeMember:
    m = await db.scalar(select(HomeMember).where(HomeMember.user_id == user.id))
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No home")
    return m

def require_home_role(*roles: str):
    async def dep(m: Annotated[HomeMember, Depends(get_membership)]) -> HomeMember:
        if m.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Owner role required")
        return m
    return dep

HomeOwner = Annotated[HomeMember, Depends(require_home_role("owner"))]
HomeReader = Annotated[HomeMember, Depends(require_home_role("owner", "member"))]
```

- Quy ước mã lỗi:
  - 401: chưa đăng nhập.
  - 404: chưa có nhà.
  - 403: đúng nhà nhưng sai vai trò.
  - 403 kèm `consent_required`: chưa đồng ý mục đích cần thiết.

#### 7.3.3 Giữa các service (sau khi tách)

- Core là nguồn sự thật về thành viên.
- Insight và copilot lấy `{home_id, role, member_view}` qua `GET /internal/membership`, dựa trên header `X-User-Id`
  (do Envoy gán sau khi kiểm JWT). Kết quả được cache tối đa 60 giây và bị xóa khi nhận sự kiện `core.home.*`.
- Lời gọi đồng bộ đi chiều copilot → insight → core, nên đúng chiều phụ thuộc đã chốt.
- `home_id` không bao giờ được lấy từ body request hay từ output của LLM. SQL guard của insight ép `home_id` vào mọi
  view (đúng như `docs/database-design.md` mục 7.3).

#### 7.3.4 Tầng database

- **Sửa G4 trên code hiện tại.** Tạo `ai.current_home()` theo đúng mẫu `copilot_ro.current_home()` (dùng scope token,
  fail closed). Tạo lại `ai.fact_*` và `ai.dim_*` thành view có `WHERE ... = ai.current_home()`. Thu hồi quyền DML của
  `wattprint_ai` trên `ai.ai_conversation` và `ai.ai_message`: chỉ app được ghi, AI đọc qua view đã lọc theo người
  dùng.
- **Sau khi tách service:** `copilot_db` chỉ có service copilot truy cập. Mọi truy vấn hội thoại đều lọc theo
  `user_id` lấy từ header, có test kèm theo.
- **Sửa G5.** Thu hồi `ALL PRIVILEGES` và default privileges của `wattprint_app`. Chỉ giữ ma trận quyền trong
  `TABLE_GRANTS` của revision `4d7b1e9a3c52`.
- **View hay RLS?** Spec đã chọn view thay cho Row Level Security, nên đề xuất giữ nhất quán. RLS là phương án thay
  thế: ép ở tầng bảng nên khó bỏ sót, nhưng phức tạp hơn với continuous aggregate và hiệu năng chưa được đo [C].

#### 7.3.5 Truy cập hỗ trợ

- Bảng `tb_support_grant`: chủ nhà cấp quyền có thời hạn (mặc định 24 giờ), chỉ đọc, thu hồi được bất kỳ lúc nào.
- Endpoint hỗ trợ kiểm grant còn hiệu lực. Mỗi lần đọc ghi vào `tb_access_audit`, và chủ nhà thấy được "Hỗ trợ đã xem
  dữ liệu lúc …".
- Bắt buộc **MFA** (OTP trong Keycloak) cho người có role `admin` hoặc làm hỗ trợ (NĐ 9.3.b). Người dùng thường đăng
  nhập Google nên MFA phụ thuộc cài đặt tài khoản Google của họ; ghi điều này vào hồ sơ DPIA.

#### 7.3.6 Nhật ký truy cập

Bảng `tb_access_audit` ghi các sự kiện:

- đổi cài đặt riêng tư;
- đồng ý và rút đồng ý;
- yêu cầu xóa;
- xuất dữ liệu;
- truy cập hỗ trợ;
- thay đổi thành viên.

Hạn lưu 13 tháng. Bảng **không chứa giá trị đo**. Đây là căn cứ cho NĐ 9.3.d và cho thông báo vi phạm (NĐ 28).

#### 7.3.7 Mã hóa (G10)

Trước khi thí điểm cần:

- TLS ở gateway;
- `sslRequired=all` trên Keycloak;
- mã hóa đĩa của máy chủ database;
- mã hóa backup.

Đây là yêu cầu của NĐ 12.4 khi chạy trên đám mây, và là thực hành tốt kể cả khi không chạy trên đám mây.

### 7.4 R4: Xóa lịch sử

#### 7.4.1 Phạm vi xóa và ai được xóa [C]

| Phạm vi | Ai | Xóa gì |
|---|---|---|
| Theo khoảng ngày `[từ, đến]` (theo ngày địa phương, không chọn giờ) | Chủ nhà | Mọi dữ liệu năng lượng của nhà trong khoảng đó. Hóa đơn được giữ mặc định **[U7]** |
| Một thiết bị | Chủ nhà | Series và dữ liệu của thiết bị đó trên toàn bộ thời gian |
| Hội thoại Copilot | Mỗi người, của chính mình | Hội thoại, tin nhắn, lời gọi tool |
| Rời nhà | Thành viên | Dữ liệu cá nhân của người đó trong nhà (hội thoại, phản hồi gợi ý). Dữ liệu năng lượng chung vẫn ở lại **[U8]** |
| Xóa nhà | Chủ nhà | Toàn bộ dữ liệu của nhà; bỏ ghép công tơ |
| Xóa tài khoản | Chính người đó | `tb_users`, user trên Keycloak (gọi admin API); nếu là chủ nhà duy nhất thì kèm xóa nhà |

Vì sao thành viên không được xóa dữ liệu năng lượng chung: Luật 4.3.c và 14.2 không cho thực hiện quyền theo cách xâm
phạm quyền, lợi ích hợp pháp của người khác. Dữ liệu năng lượng của nhà cũng phản ánh các thành viên khác. Đây là
điểm mời phản biện.

#### 7.4.2 Bản đồ dữ liệu cần xóa

| Đối tượng | Nơi (sau khi tách service) | Theo khoảng | Thiết bị | Hội thoại | Rời nhà | Xóa nhà |
|---|---|---|---|---|---|---|
| `tb_reading`, `tb_device_estimate` | core | ✔ | ✔ | | | ✔ |
| Bucket của `*_1m`, `*_1h`, `*_1d` (bảng materialization) | core | ✔ | ✔ | | | ✔ |
| `tb_device_cycle`, `tb_alert`, `tb_forecast_snapshot` | insight | ✔ | ✔ | | | ✔ |
| Read model tiêu thụ theo giờ | insight | ✔ | ✔ | | | ✔ |
| `tb_suggestion`, `_feedback`, `tb_savings_measure` | copilot / insight | ✔ | ✔ | | phản hồi của người đó | ✔ |
| `ai_conversation`, `ai_message`, `ai_tool_call` | copilot | | | ✔ | ✔ | ✔ |
| `tb_external_call` | copilot | | | | | ✔ (giữ bằng chứng **[U9]**) |
| `ai.dim_home`, `ai.dim_device` (code hiện tại) | ai | | ✔ | | | ✔ (**xóa cứng**, sửa G3) |
| `tb_bill`, `tb_bill_item` | core | **[U7]** | `bill_item` của thiết bị | | | ✔ |
| `tb_inference_run`, tham số hiệu chỉnh theo hộ | nilm | | | | | ✔ |
| `tb_device`, `tb_series`, `tb_home`, `tb_home_member`, `tb_home_invite` | core | | ✔ | | thành viên | ✔ |
| `tb_meter` | core | | | | | bỏ ghép: `home_id = NULL`, `status = 'new'`, xóa `claim_code_hash` |
| `tb_ingest_batch` | core | giữ (`home_id` chuyển `SET NULL`, chỉ còn số đếm) | | | | |
| Outbox, inbox, tin nhắn đang nằm trong DLQ | mọi service | ✔ | ✔ | | | ✔ |
| Backup | máy chủ | tự hết hạn sau ≤ 14 ngày | | | | |
| Dữ liệu đã gửi LLM provider, Expo | bên ngoài | gửi yêu cầu xóa nếu provider có API; thông báo theo Luật 14.5 | | | | |

#### 7.4.3 Thuật toán xóa theo khoảng `[d1, d2)` cho nhà H [C]

Các bước:

1. Ghi `tb_erasure_request` (`status = accepted`, `due_at = requested_at + 20 ngày`) và `tb_access_audit`, rồi trả về
   202 ngay.
2. Lấy danh sách `series_id` của H (hoặc của thiết bị, nếu phạm vi là một thiết bị). Đổi `d1`, `d2` sang mốc 17:00
   UTC (nửa đêm giờ Việt Nam). Vì là nguyên ngày nên mọi bucket 1m, 1h, 1d đều nằm trọn trong khoảng, không phải xử lý
   bucket bị cắt dở.
3. **Xóa raw trước:** `DELETE FROM tb_reading WHERE series_id = ANY(:ids) AND ts >= :t1 AND ts < :t2`, làm tương tự với
   `tb_device_estimate`. TimescaleDB 2.11 trở lên cho phép DELETE trên chunk đã nén; `segmentby = series_id` giúp
   giảm chi phí **[TBV đo chi phí]**.
4. **Xóa bucket aggregate trực tiếp trên bảng materialization** theo `series_id` và khoảng `bucket`. Tên bảng lấy từ
   `timescaledb_information.continuous_aggregates`, giống cách `_materialized_row_counts` đang làm. Làm cho cả 6 view.
   - **Không dùng `refresh_continuous_aggregate` để xóa.** Refresh tính lại cho **mọi series** trong khoảng. Với khoảng
     cũ hơn hạn lưu raw, refresh sẽ xóa luôn 1h/1d của **các nhà khác** (rủi ro đã đo ở drill 10b).
   - Xóa raw trước rồi mới xóa bucket, để một lần refresh chạy chen giữa không tạo lại bucket.
   - **[TBV]** Trên bản sao, cần kiểm: xóa trực tiếp trên bảng materialization có được phép không, có làm hỏng
     watermark và real-time aggregation không, và refresh policy sau đó có tạo lại bucket không (raw đã mất nên lẽ ra
     không). Đây là điểm rủi ro kỹ thuật lớn nhất của đề xuất. Nếu không được phép: giới hạn xóa theo khoảng trong
     cửa sổ raw (≤ 14 ngày, khi đó refresh an toàn vì các nhà khác vẫn còn raw), còn với khoảng cũ hơn thì chỉ cho xóa
     cả nhà hoặc cả thiết bị.
5. Xóa các bảng còn lại trong khoảng (cảnh báo, chu kỳ, dự báo, gợi ý) theo bảng 7.4.2.
6. **Lan truyền** (sau khi tách service): core ghi sự kiện `core.home.history_erased {erasure_id, home_id, scope, from,
   to, device_ids}` vào outbox.
   - Insight, copilot và nilm xử lý idempotent nhờ inbox, ghi `tb_erasure_step` của mình, rồi phát
     `<service>.erasure.completed`.
   - Core cập nhật trạng thái. Đây là **chiều sự kiện mới** (từ insight/copilot về core), cần nhóm chấp nhận **[U10]**.
   - Phương án thay thế: client tự gọi trạng thái ở từng service.
7. **Hoàn tất:** khi mọi bước xong thì `status = done`. Quá 24 giờ chưa xong thì phát cảnh báo cho vận hành. Message
   xóa rơi vào DLQ thì đặt `status = partial` và báo cho vận hành, không để kẹt im lặng. Không xóa được vì lý do
   chính đáng thì ghi vào `note` và thông báo cho chủ thể (Luật 14.5).

#### 7.4.4 Xóa nhà (sửa G2, G3, G9)

1. Trigger `BEFORE DELETE ON public.tb_series FOR EACH ROW` đưa `series_id` vào `tb_purge_queue`.
2. Job purge xóa raw và bucket materialization theo `series_id` trên toàn bộ thời gian, theo thứ tự như bước 3–4 ở
   mục 7.4.3.
3. Bỏ ghép công tơ trước khi xóa `tb_home`. Sửa `fk_meter_home_id_home` thành `ON DELETE SET NULL` và
   `fk_home_invite_used_by_users` thành `ON DELETE SET NULL` (sửa G9).
4. Sửa nhánh `DELETE` của `ai.sync_dim_home()` và `ai.sync_dim_device()` thành **xóa cứng** (sửa G3).

#### 7.4.5 Phương án đã cân nhắc và bị loại

| Phương án | Lý do loại |
|---|---|
| Xóa mềm (`deleted_at`) | Không đáp ứng Luật 14.3 |
| Crypto-shredding | Đã nêu ở mục 7.1.4 |
| Refresh lại toàn bộ aggregate sau khi xóa | Tốn chi phí, và xóa mất dữ liệu 1h/1d của các nhà khác |

### 7.5 R5: Dịch vụ ngoài, đồng ý và minh bạch

#### 7.5.1 Danh mục bên xử lý [C]

Danh mục lưu dạng dữ liệu tĩnh trong code (`libs/common/processors.py`) và được hiển thị trên màn hình quyền riêng tư.

| Mã | Dịch vụ | Service gọi | Dữ liệu gửi | Mục đích | Vị trí | Mục đích đồng ý | Xuyên biên giới |
|---|---|---|---|---|---|---|---|
| `llm` | LLM provider **[U3]** | copilot | Câu hỏi đã lọc PII; kết quả tool đã tối thiểu hóa | `ai_copilot` | Theo provider | `ai_copilot` | Có, nếu ở nước ngoài |
| `expo_push` | Expo → APNs/FCM | copilot | Push token; nội dung thông báo | Thông báo | Mỹ | `core` (nội dung chung) / `push_detail` | Có |
| `telegram` | Telegram Bot API | copilot | `chat_id`; tin nhắn | Thông báo | Nước ngoài | `telegram` | Có |
| `google_oidc` | Google (qua Keycloak) | keycloak | Chuyển hướng đăng nhập | Đăng nhập | Nước ngoài | `core` | Người dùng tự thực hiện |
| `open_meteo` | Open-Meteo | insight | Tọa độ tỉnh | Hiệu chỉnh theo thời tiết | Đức | Không cần (không có dữ liệu cá nhân) | Không phải dữ liệu cá nhân |

Mỗi bên xử lý có dữ liệu cá nhân cần một **thỏa thuận xử lý dữ liệu** với các nội dung bắt buộc ở NĐ 7.1: mục đích,
loại dữ liệu, thời hạn, yêu cầu xóa, trách nhiệm (Luật 37.2.a). Bên nào không ký được thì đó là lý do để bỏ kênh đó
(Telegram, U4).

#### 7.5.2 Mô hình đồng ý [C]

- Bảng `tb_consent`: chỉ ghi thêm, không sửa (append-only). Mỗi mục đích tại một thời điểm chỉ có một dòng đang hiệu
  lực cho mỗi người dùng. Mỗi dòng có `notice_version` và `notice_sha256` của nội dung đã hiển thị, để chứng minh được
  theo NĐ 6.2.
- Mọi mục đích mặc định **tắt** (NĐ 6.3).
- Mục đích `core`:
  - được xin khi người dùng tạo nhà hoặc tham gia nhà;
  - màn hình xin phải nêu rõ đây là dữ liệu nhạy cảm (NĐ 6.4);
  - đây là chính dịch vụ, nên không tính là ép đồng ý kèm theo; căn cứ thêm là Luật 19.1.d (thỏa thuận dịch vụ).
- Mục đích `ai_copilot`: xin **ngay lúc người dùng mở Copilot lần đầu** (just-in-time). Màn hình liệt kê đúng những gì
  sẽ được gửi, nêu bên nhận, vị trí, có ra nước ngoài hay không, cùng quyền của người dùng (Luật 9.2).
- Rút đồng ý có hiệu lực **ngay lập tức** cho các lần gọi sau, nhanh hơn nhiều so với hạn 15 ngày của NĐ 5.2. Rút lại
  `research` sẽ kích hoạt việc xóa số đo thô cũ hơn 14 ngày.
- Với nhà nhiều người, mỗi tài khoản đồng ý cho chính mình. Chủ nhà xác nhận đã thông báo cho người ở cùng không có
  tài khoản, kể cả trẻ em (Luật 24.2) [C].

#### 7.5.3 Cửa ra duy nhất (egress) [C]

Module `libs/common/egress.py` là nơi duy nhất được phép tạo HTTP client tới host bên ngoài:

```python
async with egress.call(
    processor="llm", purpose="ai_copilot", home_id=m.home_id, user_id=user.id,
    categories=["kwh_hourly", "device_type"], granularity=timedelta(hours=1),
    payload=llm_view,
) as client:            # 1. kiểm đồng ý  2. kiểm chính sách  3. ghi nhật ký  4. gửi
    resp = await client.post(url, json=llm_view)
```

Bốn bước kiểm tra trước khi gửi:

1. **Đồng ý.** Có dòng `tb_consent` đang hiệu lực cho `(user_id, purpose)`; không có thì báo lỗi `ConsentRequired`.
2. **Chính sách.**
   - `granularity` không nhỏ hơn sàn của processor;
   - payload không chứa khóa hoặc giá trị bị cấm: email, họ tên, `device_name`, `room`, `postal_code`, `home_id`, mốc
     thời gian lẻ phút.
3. **Nhật ký.** Ghi `tb_external_call` gồm processor, mục đích, `consent_id`, loại dữ liệu, mức chi tiết, số dòng,
   kích thước, `sha256` của payload, cờ `cross_border`, `request_id`. **Không lưu payload.**
4. **Gửi.**

Kiểm soát kèm theo:

- **Cô lập mạng:**
  - `core` và `nilm` ở network `internal: true` của Docker Compose;
  - chỉ `copilot` (tới LLM, Expo, Telegram), `insight` (tới Open-Meteo) và `keycloak` (tới Google) ra được Internet.
- **Test kiến trúc:** quét mã nguồn, mọi tên host bên ngoài chỉ được xuất hiện trong `processors.py`.

#### 7.5.4 Nhật ký gọi ra ngoài người dùng xem được

`GET /api/copilot/me/external-calls` trả các dòng `tb_external_call` của chính người dùng, hoặc của cả nhà nếu là chủ
nhà. Nhật ký đặt ở copilot vì gần như mọi lời gọi có dữ liệu cá nhân đều xuất phát từ copilot; Open-Meteo không có dữ
liệu cá nhân nên chỉ xuất hiện trong danh mục.

#### 7.5.5 Công bố ngay trên câu trả lời

Mỗi câu trả lời của Copilot có gọi ra ngoài đều kèm trường:

```json
"disclosure": {
  "processor": "llm",
  "processor_name": "<tên provider>",
  "location": "<quốc gia>",
  "cross_border": true,
  "sent": ["câu hỏi (đã che thông tin cá nhân)", "kWh theo giờ của 7 ngày", "loại thiết bị"],
  "not_sent": ["tên thiết bị", "tên phòng", "email", "giờ bật/tắt chính xác"],
  "external_call_id": 12345
}
```

Giao diện hiện chip "Đã gửi tới dịch vụ AI bên ngoài ⓘ"; bấm vào thì mở chi tiết.

Ngoài ra, màn hình giải thích NILM và Copilot (NĐ 10.3) trình bày nguyên lý hoạt động, ảnh hưởng tới người dùng và
cách từ chối tham gia.

#### 7.5.6 Phương án cho LLM **[U3]**

| Phương án | Ưu | Nhược |
|---|---|---|
| A. LLM tự host hoặc nhà cung cấp có vùng dữ liệu tại Việt Nam | Không chuyển dữ liệu xuyên biên giới; không phải lập hồ sơ cho luồng này | Cần GPU hoặc chi phí; chất lượng có thể thấp hơn |
| B. LLM ở nước ngoài, có khử nhận dạng | Chất lượng tốt | Phải lập hồ sơ chuyển xuyên biên giới trong 60 ngày; cần hợp đồng xử lý dữ liệu, tùy chọn không lưu và không dùng để huấn luyện; rủi ro phạt tới 5% doanh thu |
| C. Như B, nhưng chỉ cho tài khoản đã bật `ai_copilot` và chỉ gửi `llm_view` | Giảm rủi ro so với B | Vẫn phải lập hồ sơ |

Khuyến nghị cho giai đoạn thí điểm 5–10 hộ: **A**. Nếu không khả thi thì **C**, kèm hồ sơ chuyển dữ liệu xuyên biên
giới [C].

---

## 8. Thay đổi dữ liệu (phác thảo DDL)

Trên code hiện tại, các bảng này đặt trong schema `public`. Sau khi tách service, cột cuối của mỗi khối ghi database
đích.

```sql
-- core_db
CREATE TABLE public.tb_privacy_setting (
    home_id     integer PRIMARY KEY REFERENCES public.tb_home(id) ON DELETE CASCADE,
    member_view text NOT NULL DEFAULT 'full' CHECK (member_view IN ('full','device_daily','home_daily')),
    updated_by  integer REFERENCES public.tb_users(id) ON DELETE SET NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.tb_consent (           -- append-only; NĐ 356 Điều 6.2
    id             integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    user_id        integer NOT NULL REFERENCES public.tb_users(id) ON DELETE CASCADE,  -- [U9]
    home_id        integer REFERENCES public.tb_home(id) ON DELETE CASCADE,
    purpose        text NOT NULL CHECK (purpose IN
                   ('core','ai_copilot','push_detail','telegram','cohort','research')),
    notice_version text NOT NULL,
    notice_sha256  text NOT NULL,
    channel        text NOT NULL CHECK (channel IN ('app','web')),
    granted_at     timestamptz NOT NULL DEFAULT now(),
    withdrawn_at   timestamptz
);
CREATE UNIQUE INDEX uq_consent_active ON public.tb_consent (user_id, purpose) WHERE withdrawn_at IS NULL;

CREATE TABLE public.tb_erasure_request (   -- không FK tới tb_home: phải còn sau khi nhà bị xóa
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    home_id         integer,
    requested_by    integer,                -- id nội bộ; không lưu email
    scope           text NOT NULL CHECK (scope IN ('range','device','conversations','leave','home','account')),
    device_id       integer,
    from_day        date,
    to_day          date,
    status          text NOT NULL DEFAULT 'accepted'
                    CHECK (status IN ('accepted','running','done','partial','failed')),
    requested_at    timestamptz NOT NULL DEFAULT now(),
    due_at          timestamptz NOT NULL DEFAULT now() + interval '20 days',   -- NĐ 356 Điều 5.4
    completed_at    timestamptz,
    note            text                    -- lý do không xóa được (Luật Điều 14.5)
);
CREATE TABLE public.tb_erasure_step (
    erasure_id   uuid REFERENCES public.tb_erasure_request(id) ON DELETE CASCADE,
    target       text,                      -- 'core.raw', 'core.cagg', 'insight', 'copilot', 'nilm', 'llm_provider'
    status       text NOT NULL,
    rows_deleted bigint,
    finished_at  timestamptz,
    PRIMARY KEY (erasure_id, target)
);
CREATE TABLE public.tb_purge_queue (
    id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    series_id   integer NOT NULL,
    from_ts     timestamptz,                -- NULL = toàn bộ thời gian
    to_ts       timestamptz,
    erasure_id  uuid,
    enqueued_at timestamptz NOT NULL DEFAULT now(),
    done_at     timestamptz
);
CREATE TABLE public.tb_support_grant (
    id          integer GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    home_id     integer NOT NULL REFERENCES public.tb_home(id) ON DELETE CASCADE,
    granted_by  integer NOT NULL REFERENCES public.tb_users(id) ON DELETE CASCADE,
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz
);
CREATE TABLE public.tb_access_audit (       -- hạn lưu 13 tháng; không chứa giá trị đo
    id          bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    actor_id    integer,
    actor_kind  text NOT NULL CHECK (actor_kind IN ('user','support','admin','system')),
    home_id     integer,
    action      text NOT NULL,
    target      text,
    request_id  text
);

-- copilot_db
CREATE TABLE tb_external_call (
    id              bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    at              timestamptz NOT NULL DEFAULT now(),
    home_id         integer NOT NULL,
    user_id         integer,
    processor       text NOT NULL,
    purpose         text NOT NULL,
    consent_id      integer,
    data_categories text[] NOT NULL,
    min_granularity interval,
    n_rows          integer,
    payload_bytes   integer,
    payload_sha256  text,
    cross_border    boolean NOT NULL,
    request_id      text,
    ok              boolean NOT NULL
);
```

Sửa bảng và đối tượng đã có:

- `fk_meter_home_id_home` và `fk_home_invite_used_by_users` đổi sang `ON DELETE SET NULL` (G9).
- Thêm trigger `BEFORE DELETE` trên `tb_series` (G2).
- Nhánh DELETE của `ai.sync_dim_*` đổi sang xóa cứng (G3).
- Tạo lại view `ai.fact_*` có lọc theo nhà (G4).
- Thu hồi quyền của `wattprint_app` (G5).
- `set_policies` lên phiên bản 3 (G1).

---

## 9. API

| Method, path | Service | Vai trò | Mô tả |
|---|---|---|---|
| `GET /api/core/me/home/privacy` | core | owner, member | Hạn lưu đang áp dụng, `member_view`, danh sách thành viên, danh mục bên xử lý kèm trạng thái đồng ý của người gọi |
| `PUT /api/core/me/home/privacy` | core | owner | Đổi `member_view` (và về sau là mức riêng tư của nhà) |
| `GET /api/core/me/consents` | core | user | Đồng ý của chính mình, gồm cả lịch sử |
| `PUT /api/core/me/consents/{purpose}` | core | user | `{grant: true\|false, notice_version}`; trả bản ghi vừa tạo |
| `POST /api/core/me/home/erasures` | core | owner (thành viên chỉ được `conversations` và `leave`) | `{scope, from_day, to_day, device_id}`; trả 202 kèm `{id, due_at}` |
| `GET /api/core/me/erasures/{id}` | core | người yêu cầu | Trạng thái theo từng bước và từng service |
| `POST /api/core/me/home/exports` | core | owner | Xuất dữ liệu (NĐ 5.3, hạn 10 ngày); trả 202 |
| `POST /api/core/me/home/support-grants` | core | owner | `{hours}` |
| `DELETE /api/core/me/home/support-grants/{id}` | core | owner | Thu hồi |
| `GET /api/core/me/home/access-log` | core | owner | Nhật ký truy cập hỗ trợ và thay đổi cài đặt |
| `GET /api/copilot/me/external-calls` | copilot | user / owner | Nhật ký gọi ra ngoài |
| `POST /api/copilot/chat` | copilot | user đã bật `ai_copilot` | Câu trả lời kèm `disclosure`; chưa đồng ý thì 403 `consent_required` và **không có request nào đi ra ngoài** |
| `DELETE /api/copilot/me/conversations[/{id}]` | copilot | user | Xóa hội thoại của mình |

---

## 10. Minh chứng (R6)

### 10.1 Sơ đồ luồng dữ liệu

Sơ đồ mức 1, có ranh giới tin cậy. Bản Excalidraw sẽ sinh thành `docs/architecture/07-privacy-dataflow.excalidraw`
bằng `docs/architecture/gen_excalidraw.py`, cùng phong cách C4 với các sơ đồ hiện có.

```mermaid
flowchart LR
  subgraph H["Nhà người dùng"]
    S[Cảm biến CT]
    A[App / Web]
  end
  subgraph W["Ranh giới WattPrint (máy chủ đặt tại Việt Nam)"]
    GW[Envoy gateway]
    C[("core_db")]
    N[nilm]
    I[("insight_db")]
    P[("copilot_db")]
    E{{"egress: đồng ý, tối thiểu hóa, nhật ký"}}
  end
  subgraph X["Bên ngoài"]
    L[LLM provider]
    PU[Expo → APNs/FCM]
    T[Telegram]
    O[Open-Meteo]
    G[Google OIDC]
  end
  S -->|F1| GW -->|F2| C
  C -->|F3| N -->|F4| C
  C -->|F5| I
  I -->|F6| P
  P --> E
  E -->|F7| L
  E -->|F8| PU
  E -->|F9| T
  I -->|F10| O
  A -->|F11| G
  A <-->|F12| GW
```

| Luồng | Dữ liệu | Mức chi tiết | Hạn lưu ở đích | Căn cứ | Kiểm soát | Xuyên biên giới |
|---|---|---|---|---|---|---|
| F1–F2 | Công suất tổng (W), `Idempotency-Key`, API key thiết bị | Vài giây | Raw 14 ngày | `core` | TLS, API key, công tơ phải thuộc nhà | Không |
| F3–F4 | Cửa sổ số đo thô; ước lượng theo thiết bị | Vài giây | 14 ngày | `core` | Mạng nội bộ; nilm không có Internet | Không |
| F5 | Sự kiện `energy.usage.updated`: kWh theo giờ từng thiết bị | 1 giờ | 13 tháng | `core` (chia sẻ nội bộ, Luật 17.1.b) | Outbox/inbox; payload tối thiểu | Không |
| F6 | Kết quả truy vấn an toàn | 1 giờ trở lên | Theo hội thoại, 90 ngày | `core` | `home_id` lấy từ header; SQL guard; chỉ view 1h/1d | Không |
| F7 | Câu hỏi đã lọc PII; `llm_view` | 1 giờ trở lên; dùng bí danh | Theo hợp đồng với provider | `ai_copilot` | Egress, nhật ký, `disclosure` | **Có** (phương án B/C) |
| F8 | Push token; nội dung chung hoặc chi tiết | — | Theo Expo | `core` / `push_detail` | Egress, nhật ký | **Có** |
| F9 | `chat_id`; tin nhắn | — | Theo Telegram | `telegram` | Egress, nhật ký | **Có** **[U4]** |
| F10 | Tọa độ tỉnh | — | — | Không phải dữ liệu cá nhân | Không gắn định danh | Không |
| F11 | Chuyển hướng đăng nhập; email và tên trả về Keycloak | — | `tb_users` | `core` | PKCE, kiểm JWT | Do người dùng tự thực hiện |
| F12 | Dữ liệu nhà cho thành viên | Theo `member_view` | — | `core` | JWT, `/me/home`, nhật ký | Không |

Bảng này cùng sơ đồ là đầu vào trực tiếp cho NĐ 356 Điều 18.3.c (hồ sơ chuyển dữ liệu xuyên biên giới) và Điều 19.3.c
(hồ sơ DPIA).

### 10.2 Màn hình quyền riêng tư

Màn hình chính ("Cài đặt › Quyền riêng tư"):

```
┌ Quyền riêng tư ───────────────────────────────────────────┐
│ DỮ LIỆU NHÀ BẠN ĐANG LƯU                       (Luật 4.1.a)│
│  Số đo chi tiết (vài giây)              14 ngày           │
│  Theo phút                              35 ngày           │
│  Theo giờ                               13 tháng          │
│  Theo ngày, hóa đơn                     đến khi xóa nhà   │
│  Giờ bật/tắt thiết bị                   90 ngày           │
│  [ ] Đóng góp cho nghiên cứu (giữ số đo chi tiết 400 ngày) │
├───────────────────────────────────────────────────────────┤
│ AI ĐƯỢC XEM                                                │
│  Bạn (chủ nhà) · An (thành viên)                           │
│  Thành viên xem:  (•) Đầy đủ  ( ) Theo ngày  ( ) Tổng nhà  │
│  Hỗ trợ kỹ thuật: không có quyền        [Cấp 24 giờ]       │
│  Nhật ký truy cập ›                                        │
├───────────────────────────────────────────────────────────┤
│ DỊCH VỤ BÊN NGOÀI                                          │
│  Trợ lý AI  · <provider> · <quốc gia>     [Tắt]  ⓘ         │
│  Thông báo có nội dung chi tiết            [Tắt]           │
│  Telegram                                  [Tắt]           │
│  So sánh với nhóm hộ (≥10 hộ, ẩn danh)     [Tắt]           │
│  Nhật ký gửi ra ngoài: 12 lần / 7 ngày ›                   │
├───────────────────────────────────────────────────────────┤
│ QUYỀN CỦA BẠN                                              │
│  [Tải dữ liệu]  [Xóa theo khoảng ngày]  [Xóa một thiết bị] │
│  [Xóa hội thoại trợ lý]  [Xóa nhà]                         │
│  Yêu cầu gần nhất: ✔ đo đạc ✔ phân tích ✔ trợ lý  (3 phút) │
│  Cách WattPrint tách thiết bị và trợ lý AI hoạt động ›     │
└───────────────────────────────────────────────────────────┘
```

Màn hình xin đồng ý cho Trợ lý AI, hiện khi mở Copilot lần đầu (Luật 9.2, NĐ 6.4):

```
┌ Bật Trợ lý AI? ────────────────────────────────────────────┐
│ Để trả lời, WattPrint gửi tới <provider> (<quốc gia>):     │
│  ✔ câu hỏi của bạn (đã che số điện thoại, địa chỉ, tên)    │
│  ✔ điện năng theo giờ hoặc theo ngày, loại thiết bị        │
│  ✘ không gửi: tên thiết bị, tên phòng, email, giờ bật/tắt  │
│    chính xác                                               │
│ Đây là dữ liệu cá nhân NHẠY CẢM và sẽ được chuyển ra nước  │
│ ngoài.                                                     │
│ Bên kiểm soát dữ liệu: <đơn vị vận hành WattPrint>         │
│ Bạn có thể tắt bất kỳ lúc nào; dữ liệu đã gửi trước khi    │
│ tắt không thu hồi được (Luật 10.4). Xem mọi lần gửi trong  │
│ "Nhật ký gửi ra ngoài".                                    │
│               [Không đồng ý]        [Đồng ý]               │
└────────────────────────────────────────────────────────────┘
```

Màn hình xác nhận xóa theo khoảng:

```
Xóa dữ liệu điện từ 01/10 đến 15/10?
Sẽ xóa: số đo, ước lượng thiết bị, cảnh báo, gợi ý trong khoảng này,
ở mọi bộ phận của WattPrint. Hóa đơn tháng được giữ lại.
Bản sao lưu tự hết hạn trong 14 ngày. Không thể hoàn tác.
Hoàn tất dự kiến: trong 24 giờ (hạn luật định: 20 ngày).
[Hủy]  [Xóa]
```

Sau khi bấm Xóa, màn hình hiển thị trạng thái theo từng bước:

```
⟳ đo đạc · ✔ phân tích · ⟳ trợ lý
```

### 10.3 Thử phân quyền và các bộ test khác

Chạy bằng pytest. Đồng thời thêm thư mục "privacy" vào Postman collection để Newman xuất báo cáo làm minh chứng.

Cột "Hiện tại" là kết quả dự kiến khi chạy trên code ở commit `b0eb01b`. **Đỏ** nghĩa là test đó minh chứng cho một
lỗ hổng, và phải chuyển xanh sau khi sửa.

**Ma trận API** (T-API):

| ID | Hành động | Ẩn danh | User nhà khác | Member | Owner | Admin realm | Hỗ trợ có grant | Hỗ trợ hết hạn |
|---|---|---|---|---|---|---|---|---|
| T-API-01 | `GET` chuỗi số đo | 401 | 404 | 200 theo `member_view` | 200 | 404 | 200 | 404 |
| T-API-02 | `PUT /me/home/privacy` | 401 | 404 | 403 | 200 | 404 | 403 | 403 |
| T-API-03 | `POST /me/home/erasures` scope=range | 401 | 404 | 403 | 202 | 404 | 403 | 403 |
| T-API-04 | `POST /me/home/erasures` scope=conversations | 401 | 404 | 202 (của mình) | 202 | 404 | 403 | 403 |
| T-API-05 | `POST /api/copilot/chat` khi chưa đồng ý | 401 | — | 403 `consent_required` | 403 `consent_required` | — | — | — |
| T-API-06 | `member_view = home_daily`, member gọi API chuỗi theo thiết bị | — | — | 403 | 200 | — | — | — |
| T-API-07 | Body chứa `home_id` của nhà khác | — | bị bỏ qua, vẫn trả dữ liệu nhà mình | bị bỏ qua | bị bỏ qua | — | — | — |

**Tầng database** (T-DB):

| ID | Kiểm | Hiện tại | Sau khi sửa |
|---|---|---|---|
| T-DB-01 | `wattprint_ai_user`: `SELECT count(DISTINCT home_key) FROM ai.fact_reading_1m` | **Đỏ**: thấy mọi nhà (G4) | 0 nếu không có token; 1 nếu có token |
| T-DB-02 | `wattprint_ai_user`: `SELECT` hoặc `DELETE` trên `ai.ai_message` của người khác | **Đỏ** (G4) | Bị từ chối, hoặc 0 dòng |
| T-DB-03 | `wattprint_app`: `CREATE TABLE`, `ALTER` trên bảng không thuộc ma trận quyền | **Đỏ** (G5) | `permission denied` |
| T-DB-04 | Đường đi tới LLM: role của copilot hoặc SQL guard đọc view 1 phút hay `device_cycle` dạng thô | **Đỏ** (G8) | Bị từ chối |
| T-DB-05 | Bài isolation `copilot_ro` sẵn có (2 nhà, 15 view, 4 token xấu) | Xanh | Vẫn xanh (không được hồi quy) |

**Xóa** (T-ERA):

| ID | Kịch bản | Hiện tại | Sau khi sửa |
|---|---|---|---|
| T-ERA-01 | 2 nhà A và B; xóa A trong `[d1, d2)`. Đếm raw, 1m/1h/1d, chu kỳ, cảnh báo, hội thoại của A trong khoảng: phải bằng 0. Checksum của B: không đổi | Chưa có chức năng | Xanh |
| T-ERA-02 | Xóa nhà, sau đó không còn dòng `tb_reading`/`tb_device_estimate`/bucket nào có `series_id` mồ côi | **Đỏ** (G2) | Xanh |
| T-ERA-03 | Xóa tài khoản đã từng dùng mã mời | **Đỏ**: lỗi FK (G9) | Xanh |
| T-ERA-04 | Xóa nhà có công tơ đã ghép | **Đỏ**: lỗi FK (G9) | Xanh; công tơ về `status = 'new'` |
| T-ERA-05 | Xóa nhà, sau đó `ai.dim_home` và `ai.dim_device` không còn dòng của nhà | **Đỏ** (G3) | Xanh |
| T-ERA-06 | Xóa A ở khoảng **cũ hơn hạn lưu raw**; 1h/1d của B không đổi | — | Xanh. Test này canh đúng cái bẫy refresh ở mục 7.4.3 |
| T-ERA-07 | Lan truyền: sự kiện được insight và copilot xử lý; phát lại sự kiện không gây lỗi; message trong DLQ làm `status = partial` | — | Xanh |
| T-ERA-08 | `due_at = requested_at + 20 ngày`; job quá hạn thì phát cảnh báo | — | Xanh |

**Hạn lưu** (T-RET):

| ID | Kiểm | Hiện tại | Sau khi sửa |
|---|---|---|---|
| T-RET-01 | Đọc `timescaledb_information.jobs`: hạn lưu khớp bảng 7.1.1; bất biến ở mục 7.1.3 đúng | **Đỏ** (G1) | Xanh |
| T-RET-02 | `pick_step` với cửa sổ bắt đầu trước `now - 35 ngày` không chọn bước đọc từ 1 phút | **Đỏ** | Xanh |
| T-RET-03 | Drill trên bản sao (giống drill 10b): chạy policy với offset mới, 1h/1d không mất bucket | — | Xanh [TBV] |
| T-RET-04 | Job dọn: tin nhắn hơn 90 ngày, token hết hạn, cảnh báo hơn 13 tháng đều bị xóa | **Đỏ** | Xanh |

**Egress và đồng ý** (T-EGR, T-CON):

| ID | Kiểm | Sau khi sửa |
|---|---|---|
| T-EGR-01 | Chưa đồng ý: mock transport ghi nhận **0 request** ra ngoài; API trả 403 `consent_required` | Xanh |
| T-EGR-02 | Đã đồng ý: có đúng 1 dòng `tb_external_call`; payload không chứa tên thiết bị, phòng, email, `home_id`; mốc thời gian đã làm tròn giờ | Xanh |
| T-EGR-03 | Rút đồng ý: lời gọi kế tiếp bị chặn ngay | Xanh |
| T-EGR-04 | Test kiến trúc: tên host bên ngoài chỉ xuất hiện trong `processors.py` | Xanh |
| T-EGR-05 | Từ container `core` không ra được Internet (`curl` thất bại) | Xanh |
| T-EGR-06 | Câu trả lời có `disclosure` khớp với dòng nhật ký | Xanh |
| T-CON-01 | Người dùng mới: mọi mục đích ở trạng thái tắt; mỗi lần đồng ý có `notice_version` và `notice_sha256` | Xanh |

### 10.4 Tiêu chí chấp nhận

| Yêu cầu | Đạt khi |
|---|---|
| R1 | T-RET-01…04 xanh; tài liệu vận hành ghi hạn lưu và bất biến |
| R2 | T-DB-04, T-EGR-02 xanh; quy tắc ở mục 7.2.2 có test riêng cho phần thay tên bằng bí danh và làm tròn thời gian |
| R3 | T-API-01…07, T-DB-01…05 xanh; admin không có đường đọc dữ liệu nhà khi không có grant |
| R4 | T-ERA-01…08 xanh; màn hình hiện trạng thái và hạn chót |
| R5 | T-EGR-01…06, T-CON-01 xanh; màn hình danh mục bên xử lý và nhật ký hoạt động |
| R6 | Có DFD (mục 10.1 và file Excalidraw); có ảnh chụp ba màn hình ở mục 10.2 trên app; báo cáo pytest và Newman cho thấy trạng thái trước (đỏ) và sau (xanh) |

### 10.5 Thí nghiệm tùy chọn: định lượng rủi ro theo mức chi tiết

Dùng dữ liệu REFIT House 2 (đã seed), chạy các bộ phát hiện đơn giản ở ba mức 1 phút, 1 giờ, 1 ngày:

- giờ thức dậy (công suất tăng đầu tiên sau 4 giờ sáng);
- giờ đi ngủ;
- ngày vắng nhà (tải nền liên tục).

Đo độ chính xác so với nhãn thiết bị REFIT. Kết quả là bằng chứng định lượng cho lựa chọn sàn mức chi tiết, thay vì
chỉ dựa vào tài liệu tham khảo [C] [TBV].

---

## 11. Lộ trình

Gợi ý chung: làm P0 trên code hiện tại để có minh chứng trước/sau ngay; P1 làm thẳng trong các service mới theo kế
hoạch tách service **[U11]**.

| Mức | Việc | Lỗ hổng | Minh chứng tạo ra |
|---|---|---|---|
| **P0** | Viết các test đỏ trước: T-DB-01…04, T-ERA-02…05, T-RET-01…02 | — | Báo cáo "trước" |
| P0 | Hạn lưu mới (`set_policies` phiên bản 3), job dọn, sửa `pick_step` | G1 | T-RET xanh |
| P0 | Trigger purge, sửa FK, xóa cứng dimension | G2, G3, G9 | T-ERA-02…05 xanh |
| P0 | Lọc theo nhà cho `ai.*`, thu hồi quyền app, sàn chi tiết cho đường tới LLM | G4, G5, G8 | T-DB xanh |
| P0 | `/me/home` và `require_home_role`; ma trận T-API | G6 | T-API xanh |
| **P1** | Xóa theo khoảng và theo thiết bị; lan truyền sự kiện; trạng thái; hạn chót | — | T-ERA-01, 06…08 |
| P1 | `tb_consent`, egress, `tb_external_call`, `disclosure`, cô lập mạng | G7 | T-EGR, T-CON |
| P1 | Màn hình quyền riêng tư, màn hình xin đồng ý; xuất dữ liệu | — | Ảnh chụp màn hình |
| P1 | DFD dạng Excalidraw | — | `07-privacy-dataflow.excalidraw` |
| P1 | TLS, mã hóa đĩa và backup, MFA cho admin | G10 | Cấu hình, ảnh chụp |
| **P2** | Chế độ "Riêng tư cao" theo nhà (xóa theo `series_id`, cần đo chi phí trước) | — | — |
| P2 | Truy cập hỗ trợ đầy đủ; nhiễu cho so sánh nhóm; thí nghiệm ở mục 10.5 | — | — |
| **L** (pháp lý, song song) | Xác định bên kiểm soát (U5); hỏi về điều kiện "dịch vụ xử lý dữ liệu cá nhân" (NĐ 356 Điều 21–22); lập hồ sơ DPIA (Mẫu số 10) và hồ sơ chuyển dữ liệu xuyên biên giới (Mẫu số 09) trong 60 ngày từ ngày thí điểm; ký thỏa thuận xử lý dữ liệu với provider; công bố chính sách quyền riêng tư; quy trình và biểu mẫu thực hiện quyền (NĐ 5.1); quy trình xử lý sự cố 72 giờ (Luật 23); chỉ định nhân sự bảo vệ dữ liệu (Luật 33.2) | — | Hồ sơ |

---

## 12. Rủi ro và đánh đổi

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Raw 14 ngày không đủ để chạy lại NILM trên lịch sử dài hoặc huấn luyện model mới | Mất khả năng cải thiện mô hình từ dữ liệu cũ | Opt-in `research`; REFIT vẫn dùng được cho huấn luyện; U1 |
| Không được phép, hoặc không an toàn, khi xóa trực tiếp trên bảng materialization | Không xóa theo khoảng được ở vùng cũ | Phương án dự phòng ở mục 7.4.3 bước 4; drill [TBV] |
| DELETE trên chunk đã nén tốn tài nguyên | Xóa chậm, có thể khóa bảng | Chạy nền, chia nhỏ theo ngày; đo trên bản sao |
| Màn hình Meter không còn xem được mức phút cho tháng trước nữa | Giảm chút trải nghiệm | Mức 1 giờ vẫn có; ghi rõ trên giao diện |
| Đồng ý theo từng mục đích làm ít người bật Copilot | Ít người dùng tính năng Pro | Màn hình xin đồng ý rõ ràng, đúng lúc cần; đây là đánh đổi chấp nhận được |
| Bí danh và làm tròn làm câu trả lời kém chính xác | Chất lượng Copilot giảm | Kênh `display` vẫn hiện số chính xác cho người dùng; LLM chỉ cần giải thích |
| Thêm chiều sự kiện từ service về core (`*.erasure.completed`) | Lệch khỏi kiến trúc đã chốt | U10; phương án client tự gọi trạng thái |
| Backup còn giữ dữ liệu đã xóa | Chưa xóa xong hoàn toàn | Backup ≤ 14 ngày; công bố cho người dùng |
| Dữ liệu đã gửi LLM không thu hồi được | Không đáp ứng trọn quyền xóa | Phương án A; tùy chọn không lưu của provider; thông báo theo Luật 14.5 |
| Diễn giải pháp lý sai (ví dụ phân loại nhạy cảm, điều kiện "dịch vụ xử lý dữ liệu cá nhân") | Thiếu hoặc thừa nghĩa vụ | Nhánh L: hỏi chuyên gia trước khi thương mại hóa |

---

## 13. Quyết định cần chốt

| Mã | Câu hỏi | Đề xuất của người soạn |
|---|---|---|
| U1 | Raw 14 ngày có đủ cho NILM (hiệu chỉnh theo hộ, chạy lại khi đổi model)? | 14 ngày, kèm opt-in `research` |
| U2 | Có xếp dữ liệu phụ tải và kết quả NILM vào dữ liệu cá nhân nhạy cảm (NĐ 4.1.c, 10.2)? | Có (thận trọng) |
| U3 | Dùng LLM nào: tự host hoặc trong nước (A), hay nước ngoài kèm khử nhận dạng (B/C)? | A cho thí điểm |
| U4 | Có giữ kênh Telegram không? | Bỏ ở bản thí điểm |
| U5 | Ai là bên kiểm soát trong thí điểm (nhóm, PTIT, đối tác)? Có thuộc diện "dịch vụ xử lý dữ liệu cá nhân" không? | Hỏi chuyên gia pháp lý |
| U6 | Thành viên mặc định được xem gì? | `full` cho gia đình; chủ nhà đổi được |
| U7 | Xóa theo khoảng có xóa luôn hóa đơn không? | Giữ hóa đơn; cho chọn xóa kèm |
| U8 | Thành viên rời nhà có được yêu cầu xóa dữ liệu năng lượng chung không? | Không (Luật 4.3.c); chỉ xóa dữ liệu cá nhân của người đó |
| U9 | Giữ bằng chứng đồng ý và nhật ký gọi ra ngoài bao lâu sau khi xóa tài khoản (NĐ 6.2 đặt nghĩa vụ chứng minh)? | Giữ tối thiểu (id băm, mục đích, thời điểm) 13 tháng |
| U10 | Có chấp nhận chiều sự kiện mới `*.erasure.completed` về core không? | Có, ghi rõ là ngoại lệ |
| U11 | Làm P0 trên code hiện tại hay chờ tách service? | P0 trên code hiện tại |

---

## 14. Gợi ý câu hỏi phản biện

1. Bảng hạn lưu ở mục 7.1.1 có quá chặt hoặc quá lỏng ở chỗ nào? Có tính năng nào trong pitch deck bị ảnh hưởng mà
   tài liệu bỏ sót không (dự báo, M&V, so sánh cùng kỳ)?
2. Bất biến ở mục 7.1.3 có đủ không? Còn đường nào khác làm refresh xóa mất bucket của tầng trên?
3. Dùng `/me/home` dựa trên giả định mỗi tài khoản chỉ thuộc một nhà. Nếu sau này một tài khoản thuộc nhiều nhà (chủ
   trọ có nhiều phòng) thì thiết kế đổi thế nào?
4. Bí danh có thật sự khử nhận dạng không, khi chuỗi kWh theo giờ của một hộ có thể là "dấu vân tay"? Khi nào thì
   payload gửi LLM vẫn là dữ liệu cá nhân theo Luật 2.1?
5. Dữ liệu năng lượng chung của nhà thuộc về ai? Quy tắc "chỉ chủ nhà được xóa" có mâu thuẫn với quyền xóa của thành
   viên không (Luật 4.1.d so với 4.3.c)?
6. Xóa trực tiếp trên bảng materialization so với các phương án khác: có cách nào an toàn hơn mà vẫn xóa được theo
   nhà ở vùng cũ không?
7. Đồng ý `core` lúc tạo nhà có bị coi là "kèm theo điều kiện bắt buộc" (Luật 9.4.b) không?
8. Phân loại rủi ro AI ở mục 3.8 đã hợp lý chưa? NILM có nên ở mức cao không?
9. Bộ test ở mục 10.3 còn thiếu kịch bản tấn công nào (ví dụ prompt injection để đọc nhà khác qua SQL guard)?
10. Với 5–10 hộ thí điểm, phần nào ở nhánh L là bắt buộc ngay, phần nào để sau được?

---

## Phụ lục A. Truy vết yêu cầu, đề xuất và minh chứng

| Nguồn yêu cầu | Nội dung | Mục đề xuất | Minh chứng |
|---|---|---|---|
| Đề bài R1; Luật 3.3, 14.1.b/c; NĐ 9.2.c | Giảm mức chi tiết phải lưu | 7.1 | T-RET-01…04 |
| Đề bài R2; Luật 30.1; NĐ 7.2, 9.3.c | Giảm mức chi tiết phải chia sẻ | 7.2 | T-DB-04, T-EGR-02 |
| Đề bài R3; NĐ 4.2, 9.3.b, 9.3.d; Luật 30.3 | Giới hạn quyền truy cập | 7.3 | T-API, T-DB |
| Đề bài R4; Luật 4.1.d, 14; NĐ 5.4, 10.6 | Xóa lịch sử | 7.4 | T-ERA |
| Đề bài R5; Luật 9, 10, 11.1, 20; NĐ 6, 17, 18 | Nêu rõ khi gọi dịch vụ ngoài; đồng ý | 7.5 | T-EGR, T-CON; màn hình 10.2 |
| Đề bài R6 | DFD, màn hình, thử phân quyền | 10 | 10.1–10.4 |
| NĐ 19.3.c, 18.3.c | Sơ đồ luồng dữ liệu trong hồ sơ DPIA và hồ sơ chuyển xuyên biên giới | 10.1 | Cùng DFD |
| NĐ 19.3.d, 18.3.d | Chính sách đồng ý và lưu, xóa | 7.1, 7.4, 7.5.2 | — |
| NĐ 10.3 | Giải thích AI; cho phép từ chối tham gia | 3.8, 7.5.5 | Màn hình giải thích |
| Luật 4.1.d (cung cấp); NĐ 5.3 | Xuất dữ liệu trong 10 ngày | 9 | — |
| Luật 23; NĐ 28 | Thông báo vi phạm 72 giờ | 7.3.6, 11 (L) | — |

## Phụ lục B. Nguồn

Văn bản pháp luật (đã đọc nguyên văn ngày 2026-11-28):

- Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15, Quốc hội thông qua ngày 26/06/2025, hiệu lực từ 01/01/2026. Bản Word:
  https://static3.luatvietnam.vn/uploaded/others/2025/08/21/luat-91-2025-qh15_2108094942.docx ; trang Bộ Công an:
  https://mps.gov.vn/chinh-sach-phap-luat/co-so-du-lieu-van-ban/luat-bao-ve-du-lieu-ca-nhan-1753688803
- Nghị định 356/2025/NĐ-CP ngày 31/12/2025 quy định chi tiết một số điều và biện pháp thi hành Luật Bảo vệ dữ liệu cá
  nhân, Công báo số 18 ngày 18/01/2026:
  https://congbaocdn.chinhphu.vn/180507251028987904/2026/1/17/356signed-1768638052103952849513.pdf

Nghiên cứu và tiền lệ:

- A. Molina-Markham, P. Shenoy, K. Fu, E. Cecchet, D. Irwin, "Private Memoirs of a Smart Meter", ACM BuildSys 2010.
- U. Greveler, B. Justus, D. Löhr, "Multimedia Content Identification Through Smart Meter Power Usage Profiles",
  CPDP 2012.
- Article 29 Data Protection Working Party, Opinion 12/2011 on smart metering (WP 183).
- UK Department of Energy & Climate Change, Smart Metering Data Access and Privacy: Government Response (2012).
- NIST IR 7628 Rev. 1, Guidelines for Smart Grid Cybersecurity, Vol. 2: Privacy and the Smart Grid.

Tài liệu nội bộ: `docs/database-design.md`, `docs/database-audit.md`, `docs/architecture/README.md`,
`docs/superpowers/plans/2026-11-10-microservices-split.md`, `docs/PROJECT_CONTEXT.md`.

## Phụ lục C. Lệnh kiểm chứng hiện trạng

Chạy trên database thử (scratch), **không chạy trên dữ liệu thật**. Cần quyền owner của database.

```sql
-- G1: các policy hiện có
SELECT hypertable_schema, hypertable_name, proc_name, config
FROM timescaledb_information.jobs
WHERE proc_name IN ('policy_retention','policy_compression','policy_refresh_continuous_aggregate')
ORDER BY hypertable_name, proc_name;
-- Kỳ vọng hiện tại: không có policy_retention cho *_1h, *_1d, tb_device_cycle

-- G2: xóa nhà để lại số đo mồ côi
BEGIN;
WITH h AS (INSERT INTO public.tb_home (name) VALUES ('privacy-probe') RETURNING id),
     s AS (INSERT INTO public.tb_series (home_id, kind, metric, unit)
           SELECT id, 'main', 'power_w', 'W' FROM h RETURNING series_id)
INSERT INTO public.tb_reading (ts, series_id, value) SELECT now(), series_id, 500 FROM s;
DELETE FROM public.tb_home WHERE name = 'privacy-probe';
SELECT count(*) FROM public.tb_reading r
WHERE NOT EXISTS (SELECT 1 FROM public.tb_series s WHERE s.series_id = r.series_id);
-- Hiện tại: >= 1 (mồ côi). Sau khi sửa: 0 sau khi job purge chạy
ROLLBACK;

-- G4: role AI đọc chéo nhà
SET ROLE wattprint_ai_user;
SELECT count(DISTINCT home_key) FROM ai.fact_reading_1m;   -- hiện tại: số nhà có dữ liệu
SELECT count(*) FROM ai.ai_message;                         -- hiện tại: tin nhắn của mọi người dùng
RESET ROLE;

-- G5: quyền rộng của app
SELECT has_schema_privilege('wattprint_app', 'public', 'CREATE');   -- hiện tại: true

-- G9: FK chặn xóa
SELECT conname, confdeltype FROM pg_constraint
WHERE conname IN ('fk_meter_home_id_home', 'fk_home_invite_used_by_users');
-- confdeltype 'a' = NO ACTION (hiện tại); mong đợi sau khi sửa: 'n' = SET NULL
```

## Lịch sử phản biện

| Ngày | Người phản biện | Mục | Ý kiến | Xử lý |
|---|---|---|---|---|
| | | | | |
