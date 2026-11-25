# Sense, phần 2: lấp chỗ trống, so sánh, giới hạn tần số thấp và một thí nghiệm kiểm chứng

Ngày 2026-11-25. Tiếp nối [research.md](research.md). Vẫn là nghiên cứu, không sửa code, migration hay cấu hình.
Quy ước: **[Tuyên bố]** là lời của công ty (Sense, Smappee, Bidgely...), chưa ai đo độc lập; **[Suy luận]** là
của mình; số học thuật là tác giả tự báo cáo, mình chưa chạy lại. help.sense.com và community.sense.com (nay
chuyển hướng về help.sense.com) trả 403 cho công cụ đọc tự động; mình không vượt chặn, phần đó lấy từ trích
đoạn của công cụ tìm kiếm, nên ghi "(trích đoạn)".

## 1. Lấp các chỗ trống của ghi chú 1

### 1.1 Cần lặp bao nhiêu lần, ngưỡng nào

- **Sense không công bố con số.** Bài *How Sense Learns About Your Devices* chỉ nói cần "repeated occurrences"
  và "many occurrences", không có số lần hay ngưỡng [Tuyên bố] (S1). Bài *How Your Input Improves Device
  Detection* cho mốc thô: tủ lạnh "a few days of data", thiết bị khó "months" [Tuyên bố] (S2).
- **Mốc tổng của Sense:** khoảng 12 thiết bị tháng đầu, 25–30 sau 12 tháng; Sense phải thấy cả thiết bị đó lẫn
  "competing devices" chạy trong nhà mới dám hiện [Tuyên bố, trích đoạn] (S3).
- **Mô hình mới chỉ được đẩy xuống khi đủ "confidence"**, ngưỡng không công khai, quy trình tự động (người dùng
  thuật lại lời Sense, trích đoạn) (S4). Đây là chỗ gần nhất với "ngưỡng" mà nguồn công khai có.
- **Số học thuật cụ thể nhất tìm được: eNILM (Breyer và cộng sự, RWTH, IEEE 2026, đã đọc bản PDF)** (S5):
  bỏ thiết bị có dưới **10 sự kiện**; gom cụm HDBSCAN với `min_cluster_size` **10 hoặc 44** (10 bắt được thiết
  bị ít sự kiện hơn, 44 cho cụm ít hơn); vùng chờ "sự kiện chưa ai nhận" phải đủ **500 sự kiện** mới kích hoạt
  gom cụm (thử theo bước 50, 500 tốt nhất); DBSCAN thường chỉ tạo cụm cỡ tối thiểu (12 điểm). Thiết bị dùng
  nhiều thì học được, thiết bị ít dùng thì "incapable of learning" khi khởi động không có tri thức trước.
- **Không có bài nào trên REFIT** nêu số lần tối thiểu để "đăng ký" một thiết bị ở tần số thấp (tìm theo từ khóa
  đó không ra; các bài event-based tần số thấp như Barsim, bài clustering phi tham số trên REDD đều không cho
  ngưỡng này) (S6, S7).

Kết luận [Suy luận]: không có "con số chuẩn". Tham số hợp lý để bắt đầu là cụm tối thiểu 10 lần xuất hiện, kèm
điều kiện ổn định (cụm còn sống sau K tuần). Số này phải đo trên dữ liệu của mình, đó là lý do của mục 4.

### 1.2 Mua máy mới sau khi nhà đã "học xong"

Không có bài chính thức nào của Sense mô tả riêng trường hợp này. Bằng chứng gián tiếp (trích đoạn):

- Mô hình thiết bị **được cập nhật khi có thêm dữ liệu**; thiết bị đã xóa có thể bị tạo lại vì hệ thống ở backend
  vẫn chạy trên lịch sử (S4). Trang *How Sense Updates Your Devices List*: hệ thống có thể đổi tên, đổi loại, gộp
  thiết bị nhiều chữ ký và tự gỡ thiết bị sai [Tuyên bố] (S8).
- Thay bình nóng lạnh: có nhà Sense coi máy mới là máy cũ "never missed a beat" (chữ ký giống), có nhà máy cũ
  "pop up again as a new device", lời khuyên chung là chờ vài tuần (S9). Thiết bị mới phát hiện thì "không có
  lịch sử" lúc đầu; nhân viên Sense nói sẽ gửi bù dữ liệu từ lúc phát hiện khi mô hình xong (S10).
- Phương pháp "data-driven" song song (10/2025) cần khoảng **24 giờ** dữ liệu để bắt đầu nhận loại thiết bị mới,
  chỉ cho mặt trời, bơm nhiệt biến tần, xe điện cấp 1/2; nhiều máy cùng loại gộp thành một [Tuyên bố] (S11).

Kết luận [Suy luận]: máy mới đi đúng đường như lúc mới lắp (sự kiện không giải thích được → gom cụm → đủ tin
cậy → đẩy mô hình), không có luồng riêng. Máy thay thế cùng đời có thể được "nhận vơ" là máy cũ, đó là ưu điểm
(liền mạch) và cũng là rủi ro (không biết đã thay máy). eNILM (S5) là bài duy nhất đã đọc mô tả rõ vòng này:
sự kiện không chuyên gia nào nhận → vùng chờ → đủ ngưỡng thì gom cụm → mỗi cụm thành một "chuyên gia" mới,
không huấn luyện lại các chuyên gia cũ, người dùng chỉ đặt tên.

### 1.3 Có số đo nào "nhãn cộng đồng làm tốt hơn bao nhiêu" không

- **Sense: không.** Chỉ có mô tả cơ chế: người dùng đặt tên giúp "build our growing database of device labels",
  ví dụ tách "Motor" thành "máy hút bụi"; smart plug, Hue, Ecobee cho "ground truth data for thousands of
  devices"; đánh dấu "đoán" để đội dữ liệu cân trọng số nhãn [Tuyên bố] (S2, S12). Không có phần trăm nào.
- **Học thuật, gần nhất:**
  - Nhãn người dùng nhiễu: Valovage & Gini 2016, nhãn bật/tắt thô do người dùng bấm chỉ tạo dương tính giả, sửa
    nhãn rồi mới dùng được (S13).
  - Hỏi người dùng có chọn lọc (active learning): NREL 2016; bài "user-centered" mô hình hóa việc người dùng có
    chịu trả lời không, báo cáo cải thiện tới 55,38 % (S14, S15). Rossier 2017: nhận dạng gần thời gian thực ở
    1 Hz (P, Q) với active learning (S16).
  - Nhãn yếu, ít nhãn (Tanoni 2024, đã nêu ở ghi chú 1): F1 0,69 → 0,83 với 1,7 % nhãn.
  - Liên kết nhiều nhà (federated): Fed-NILM (arXiv 2105.11085) tốt hơn huấn luyện từng nhà riêng và gần bằng
    huấn luyện tập trung, nhưng là trên vài nhà công khai, không phải nhãn cộng đồng thật (S17).
- **Không tìm thấy** nghiên cứu nào đo lợi ích của nhãn do *đám đông người dùng thật* trên *nhiều nhà*. Đây vẫn
  là chỗ trống, và đúng câu phản biện số (3) ở ghi chú 1.

## 2. Sản phẩm khác so sánh nhanh

| Sản phẩm | Tốc độ đo | Nhãn đến từ đâu | Người dùng thấy gì | Nguồn |
|---|---|---|---|---|
| Sense (Mỹ) | 1 MHz trên CT tủ điện [Tuyên bố] | học không nhãn + đặt tên, Community Names, smart plug/DCM làm chân lý | danh sách thiết bị dần lớn lên, "Other", "Always On", trạng thái phát hiện | S1–S4, S11 |
| Wiser Energy (Schneider) | phần cứng Sense; tách khỏi Sense 5/2024 | như Sense | FAQ tự nhận phát hiện "Not everything" | S18 |
| Smappee (Bỉ) | không công bố | **khảo sát thiết bị có trong nhà** + vuốt đúng/sai từng sự kiện + "Assisted Learning" (bật/tắt máy cho nó nghe) + ổ cắm Switch | danh sách sự kiện để xác nhận; NILM tắt mặc định, tự tắt sau 1 tháng nếu đo sai | S19, S20 |
| Neurio / Generac PWRview | không công bố | học máy trên mains | người dùng kể chỉ tốt với tải lớn; ứng dụng ngừng hỗ trợ 10/3/2025 | S21 |
| Emporia Vue | 1 s, CT từng mạch | không phân rã, đo thẳng từng mạch | điện theo mạch | ghi chú 1 |
| Bidgely (cho điện lực) | AMI 15 phút đến 1 giờ | phân cụm không giám sát + chân lý thu ở giai đoạn đầu; **không dùng khảo sát** | 12 loại tải/nhà, "90+ % phát hiện, 85+ % tiêu thụ" [Tuyên bố] | S22 |
| Informetis (Nhật) | dạng sóng dòng ở tủ điện; bản công tơ 30 phút | thư viện dạng sóng thu >10 năm [Tuyên bố] | tới 10 loại (có **nồi cơm**, điều hòa); bản 30 phút chỉ 5 nhóm | S23 |
| Việt Nam | VConnex: công tơ thông minh cho nhà trọ, chỉ tổng và cảnh báo | – | không phân rã theo thiết bị | S24 |

Điểm rút ra [Suy luận]: (1) ai đo thô thì đều chuyển sang **nhóm tải lớn theo lịch** (Bidgely 15 phút,
Informetis 30 phút: điều hòa, tủ lạnh, chờ, chiếu sáng); (2) Smappee lấy nhãn chủ động từ người dùng (khảo
sát + "bật máy cho tôi nghe"), rẻ và hợp với nhóm nhỏ hơn cách "đợi cộng đồng" của Sense; (3) chưa thấy đối thủ
Việt Nam làm phân rã từng thiết bị.

## 3. Ràng buộc quan trọng nhất: WattPrint đo thưa

WattPrint: công tơ ~5–10 s, ứng dụng làm việc trên lưới 15 s (`app/modules/nilm/services/windows.py`, `STEP`),
màn hình đọc tổng hợp theo phút. Sense lấy mẫu 1 MHz. Bằng chứng về độ phân giải:

- eNILM chuyển từ FIRED (2/8 kHz) sang DARCK **1 Hz**, chỉ còn đặc trưng công suất tác dụng: macro F1 **dưới
  15 %**, kNN có giám sát cũng chỉ 22,7 %; tác giả kết luận event-based "require high-frequency features to
  scale to a large number of devices" (S5).
- Phát hiện sự kiện suy giảm phi tuyến theo độ phân giải; phần lớn sự kiện đúng ở khoảng 1 kHz (Huchtkoetter &
  Reinhardt 2019, trích đoạn) (S25). Ở 30 phút vẫn phát hiện được một số thiết bị có/không (Petralia 2023) (S26).
- Bidgely, Informetis ở 15–30 phút chỉ còn vài nhóm tải lớn (S22, S23).

| Cơ chế của Sense | Ở 5–60 s còn dùng được? | Lý do |
|---|---|---|
| Đặc trưng transient, hài, EMI, ~500 đặc trưng/sự kiện | **Không** | cần kHz–MHz (ghi chú cũ, S5) |
| Tách hai máy cùng công suất (hai cửa gara, đèn) | **Không**, kể cả Sense cũng hay gộp | chỉ còn ΔP, thời lượng |
| Ghép cặp bật/tắt, ΔP bậc thang, thời lượng | **Có**, với tải ≥ vài trăm W | thấy được ở 10 s; ở 1 phút tải < 2–3 phút bị nhòe |
| Ngữ cảnh giờ giấc, chuỗi (máy sấy sau máy giặt) | **Có** | không phụ thuộc tần số |
| "Other" và "Always On" là đầu ra hạng nhất | **Có**, WattPrint đã có "Khác" (`windows.balance`) | |
| Lặp lại mới tin, ngưỡng cụm tối thiểu, đẩy mô hình khi đủ tin cậy | **Có** | là logic, không phải tín hiệu |
| Nhãn người dùng, gộp/tách, "không bật" | **Có** | |
| Smart plug làm chân lý | **Có**, nên làm | không phụ thuộc công tơ chính |
| Bộ phát hiện "data-driven" cho EV, bơm nhiệt, mặt trời (24 h) | **Có lẽ** [Suy luận] | tải lớn, kéo dài, giống thứ mô hình theo cửa sổ của mình làm |

Nói thẳng: thứ WattPrint chép được từ Sense là **quy trình** (lặp lại, ngưỡng tin cậy, hỏi đúng lúc, "Khác"),
không phải **độ phân giải**. Kỳ vọng hợp lý là phát hiện máy mới cho tải lớn, đều, khác biệt (điều hòa, bình
nóng lạnh, ấm đun, nồi cơm), không phải máy nhỏ hay máy nhiều pha.

## 4. Thí nghiệm: phát hiện máy mới từ "Khác"

**Giả thuyết (bác bỏ được):** với một thiết bị bị giấu khỏi mô hình của nhà, các sự kiện của nó trong phần "Khác"
gom được thành ít nhất một cụm có độ tinh khiết ≥ 0,8 trong ≤ 4 tuần của phần thời gian giữ lại, trong khi số cụm
"máy mới" sai ≤ 1/tuần. Nếu không đạt cho cả điều hòa (Plegma 101) lẫn ấm đun (REFIT 2), giả thuyết sai cho WattPrint.

**Dữ liệu và chia:** REFIT nhà 2, 5; Plegma 101; ENERTALK 200 (CSV phải tạo lại bằng
`scripts/enertalk_to_refit.py`, hiện không có `CLEAN_House200.csv` trong `dataset/`). Chia thời gian như
`train_house.py`: 80 % đầu huấn luyện, 20 % cuối là các tuần giữ lại.

**Hai mức "Khác":**
1. *Oracle* (cận trên, rẻ): Khác = Tổng − tổng chân lý của các thiết bị còn lại. Đo riêng khâu gom cụm.
2. *Thật*: huấn luyện lại bundle bỏ thiết bị H (`train_house.py` thêm tham số bỏ một nhãn), chạy trên tuần giữ lại,
   lấy "Khác" từ `windows.balance`. Đo cả lỗi NILM rò sang "Khác". Đắt hơn (mỗi nhà một lần huấn luyện).

Chân lý thiết bị chỉ dùng để chấm, offline, giống `scripts/eval_nilm.py`; không API nào đọc kênh thô (đúng
`.claude/rules/data.md`).

**Thuật toán ứng viên (tối giản, theo thứ tự thử):**
- A. *Đường nền + ngưỡng*: phần dư trên mức thấp nhất cuộn 1 giờ > T (300 W) → một đợt; đặc trưng: log ΔP (trung
  vị), log thời lượng, giờ (sin/cos). Gom HDBSCAN `min_cluster_size` 10 (theo eNILM).
- B. *Bước lên/xuống*: dò cạnh trên hiệu bậc một (hoặc CUSUM), ghép cặp lên/xuống theo |ΔP| gần nhau; thêm đặc
  trưng hình dạng (số bậc trong đợt, độ lệch công suất). Hợp tải nhiều pha hơn A.
- C. *Vùng chờ kiểu eNILM*: chỉ đem gom cụm các đợt không khớp cụm đã biết; kích hoạt khi vùng chờ đủ N đợt.

**Thước đo:**
- *Khớp*: cụm có ≥ 50 % sự kiện của H (gọi là cụm-H): độ tinh khiết và độ phủ (tỷ lệ sự kiện H nằm trong cụm-H).
- *Bao nhiêu lần thì nhận ra*: số lần H chạy thật (theo chân lý) trước khi cụm-H đầu tiên đủ 10 thành viên; và số ngày.
- *Báo sai*: số cụm không phải cụm-H mỗi tuần. Lưu ý: trong REFIT, phần lớn là tải thật không mô hình (TV, quạt,
  hi-fi, tải không đo), nên cần gán nhãn bằng mọi kênh chân lý để tách "tải thật chưa mô hình" khỏi "rác".
- *Ổn định*: cụm-H còn tồn tại khi chạy lại trên các tuần sau.
- Mỗi số chạy với 3 tốc độ: 10 s, 60 s (đúng cái app lưu theo phút), và 15 s (lưới của mô hình).

**Tệp cần:** một script offline `scripts/eval_new_device.py` (đọc CSV kiểu REFIT, bỏ H, tính phần dư, dò sự kiện,
gom cụm, in bảng), test nhỏ cho hàm dò sự kiện trên chuỗi tổng hợp; tùy chọn bỏ nhãn trong `train_house.py` cho
mức 2. Không đụng schema, worker hay API.

### 4.1 Chạy thử nhanh (oracle, thuật toán A, ~1 phút máy)

Script tạm `hidden_device.py` trong thư mục scratch (không nằm trong repo). 20 % thời gian cuối, mức Khác oracle
nên đây là **cận trên** của khâu gom cụm, chưa tính lỗi NILM. Cụm-H = cụm có ≥ 50 % sự kiện của H.

| Nhà, giấu | Tốc độ | Số cụm | Cụm-H | Tinh khiết cụm-H | Phủ sự kiện H | Cụm khác/tuần |
|---|---|---|---|---|---|---|
| REFIT 2, ấm đun | 10 s | 72 | 5 | 0,98 | 0,41 | 4,4 |
| REFIT 2, ấm đun | 60 s | 3 | **0** | – | 0 | 0,1 |
| REFIT 2, lò vi sóng | 10 s | 69 | 9 | 0,66 | 0,34 | 3,9 |
| REFIT 2, lò vi sóng | 60 s | 3 | **0** | – | 0 | 0,1 |
| REFIT 2, máy giặt | 10 s | 69 | 2 | 0,90 | 0,08 | 4,3 |
| REFIT 2, máy giặt | 60 s | 5 | **0** | – | 0 | 0,3 |
| REFIT 5, ấm đun | 10 s | 216 | 10 | 0,85 | 0,32 | 9,9 |
| REFIT 5, ấm đun | 60 s | 35 | 5 | 0,70 | 0,39 | 1,4 |
| Plegma 101, bình nóng lạnh | 10 s | 48 | 20 | 0,98 | 0,79 | 2,2 |
| Plegma 101, bình nóng lạnh | 60 s | 4 | 1 | 1,00 | 0,26 | 0,2 |
| Plegma 101, điều hòa | 10 s | 89 | 82 | 0,99 | 0,68 | 0,6 |
| Plegma 101, điều hòa | 60 s | 27 | 27 | 0,99 | 0,68 | 0,0 |

Thời gian đến cụm-H sạch đầu tiên đủ 10 thành viên: ấm đun REFIT 2 (10 s) ngày 16, sau ~90 lần đun thật;
bình nóng lạnh Plegma 101 (10 s) ngày 17. Đọc trung thực:
- Tải lớn, đều, khác biệt (điều hòa, bình nóng lạnh, ấm đun ở 10 s) **tạo được cụm sạch** ngay với thuật toán ngây
  thơ. Điều hòa ở Plegma giữ được cả ở 60 s. Đây là tin tốt cho bối cảnh Việt Nam (điều hòa, bình nóng lạnh).
- Ở **60 s**, ấm đun và lò vi sóng REFIT 2 **bị gộp chung** vào một cụm lớn với tải khác (tinh khiết 0,16–0,36):
  đợt 2–3 phút không còn hình dạng. Máy giặt thất bại ở cả hai tốc độ (nhiều pha, đúng như Sense nói).
- Cụm bị **vụn** (một thiết bị thành 5–82 cụm, phần lớn do đặc trưng giờ) và phần "nhiễu" của HDBSCAN 20–50 %;
  cần gộp cụm theo ΔP trước khi đưa ra thẻ "thiết bị mới", nếu không người dùng nhận nhiều thẻ trùng.
- "Cụm khác/tuần" 2–10 ở 10 s là con số **chưa phải tỷ lệ báo sai**: phần lớn là TV, quạt, tải không đo của REFIT.
  Phải gán nhãn bằng mọi kênh mới tách được. Chưa có ENERTALK, chưa có mức NILM thật, mỗi cấu hình chạy một lần.

## 5. Nên làm gì tiếp (rẻ đến đắt)

1. **Biến script thử thành `scripts/eval_new_device.py`** + test, chạy đủ 4 nhà × các thiết bị × 10/15/60 s, gán
   nhãn cụm bằng mọi kênh chân lý (vài giờ). Kết quả cho biết thẻ "máy mới" nên chỉ bật cho loại tải nào.
2. **Gộp cụm và điều kiện ổn định** (cụm-H sống qua 2 tuần, gộp cụm cùng ΔP ±15 %), đo lại tỷ lệ báo sai (1 ngày).
3. **Mức "Khác" thật**: huấn luyện lại một bundle bỏ thiết bị (REFIT 2 bỏ ấm đun, Plegma 101 bỏ điều hòa), chạy
   trên tuần giữ lại (vài giờ máy mỗi nhà).
4. **Luồng hỏi kiểu Smappee** thay vì đợi cộng đồng: khảo sát "nhà có những máy gì" lúc đăng ký + "bật máy X trong
   5 phút" để lấy nhãn; lưu nhãn trên số đã suy luận, không trên số đo thô (cần thiết kế, ngoài phạm vi ghi chú).
5. **Smart plug cho vài nhà thật ở Việt Nam** làm chân lý (đắt về hậu cần, giá trị cao nhất).
6. **Cộng đồng / federated**: chỉ khi có ≥ 10 nhà (khớp ngưỡng cohort `n_homes >= 10` của rules).

## 6. Câu hỏi phản biện và trả lời nháp

- *"Công tơ 10 s–1 phút thì làm sao nhận máy mới như Sense?"* → Không như Sense. Chỉ tải lớn, đều, khác biệt; số
  ở mục 4.1 (điều hòa giữ được ở 60 s, ấm đun mất ở 60 s); eNILM ở 1 Hz cũng chỉ F1 < 15 % cho nhiều thiết bị.
- *"Cần bao nhiêu lần lặp?"* → Không ai công bố cho Sense. Mình dùng cụm tối thiểu 10 (như eNILM) và đo: ấm
  đun ~90 lần/16 ngày ở 10 s trên oracle. Sẽ báo con số trên mức NILM thật.
- *"Đây là oracle, thực tế tệ hơn?"* → Đúng, oracle là cận trên; bước 3 đo lỗi NILM rò vào "Khác".
- *"Báo sai làm phiền người dùng?"* → Đo "cụm khác/tuần", gộp cụm, chỉ hiện thẻ khi cụm ổn định 2 tuần; người
  dùng có nút "không phải máy mới".
- *"Cộng đồng có thật sự giúp không?"* → Chưa ai công bố số đo cho nhãn đám đông thật, kể cả Sense. Bằng chứng
  gần nhất: ít nhãn chọn lọc giúp nhiều (Tanoni), federated gần bằng tập trung (Fed-NILM). WattPrint mới 4 nhà demo.
- *"Quyền riêng tư?"* → Thẻ và cụm tính trên số đã suy luận của chính nhà đó, không chia sẻ; cộng đồng cần đồng ý
  riêng và ≥ 10 nhà.
- *"Sao không mua phần cứng tần số cao?"* → Có thể sau; trước hết đo xem tần số thấp làm được tới đâu (mục 4),
  ghi chú cũ cũng nói chưa ai đo cùng nhà ở nhiều tốc độ.

## Nguồn

- S1 Sense, How Sense Learns About Your Devices: <https://sense.com/consumer-blog/training-sense/>
- S2 Sense, How Your Input Improves Device Detection: <https://sense.com/consumer-blog/how-your-input-improves-device-detection/>
- S3 Sense, Understanding Device Detection Stages (trích đoạn): <https://help.sense.com/hc/en-us/articles/35377658948627-Understanding-Device-Detection-Stages-in-Sense>; Very few new devices identified in months (trích đoạn): <https://community.sense.com/t/very-few-new-devices-identified-in-months/13761>
- S4 Sense community, Do Sense device models dynamically update? / How often do the models update? (trích đoạn): <https://community.sense.com/t/do-sense-device-models-dynamically-update/2961>, <https://community.sense.com/t/how-often-do-the-models-update/10128/5>
- S5 Breyer, Plachetka, Alizai, Wehrle, eNILM: Dynamic Device Integration in NILM (IEEE 2026): <https://www.comsys.rwth-aachen.de/publication/2026/2026_breyer_enilm/2026_breyer_enilm.pdf>
- S6 Barsim và cộng sự, UPEC 2013: <https://www.iss.uni-stuttgart.de/forschung/publikationen/barsim_upec2013.pdf>
- S7 Event-based NILM, phân cụm phi tham số tần số thấp: <https://arxiv.org/pdf/2009.02656>
- S8 Sense, How Sense Updates Your Devices List (trích đoạn): <https://help.sense.com/hc/en-us/articles/360015628013-Devices-How-Sense-Updates-Your-Devices-List>
- S9 Sense community, thay bình nóng lạnh (trích đoạn): <https://community.sense.com/t/water-heater-replacement-thinks-new-one-is-old/2757>, <https://community.sense.com/t/advice-on-deleting-a-water-heater-or-not/4547>
- S10 Sense community, New devices but no data (trích đoạn): <https://community.sense.com/t/new-devices-but-no-data/1751>
- S11 Sense, What's New In Device Detection October 2025 (trích đoạn): <https://help.sense.com/hc/en-us/articles/45841367022483-What-s-New-In-Device-Detection-October-2025>
- S12 Sense, Renaming Devices / Community Names (trích đoạn): <https://help.sense.com/hc/en-us/articles/115005522568-Renaming-Devices>
- S13 Valovage & Gini, AAAI workshop 2016: <https://www-users.cs.umn.edu/~gini/papers/Valovage2016aaaiw.pdf>
- S14 NREL, Active Learning Framework for NILM: <https://nrel.gov/docs/fy16osti/66273.pdf>
- S15 User-centered active learning for appliance recognition: <https://par.nsf.gov/servlets/purl/10165984>
- S16 Rossier, Lang, Hennebert, CISBAT 2017: <https://arodes.hes-so.ch/record/8300/files/published%20version.pdf>
- S17 Fed-NILM: <https://arxiv.org/abs/2105.11085>; FedNILM: <https://arxiv.org/pdf/2106.07751>; FederatedNILM: <https://arxiv.org/pdf/2108.03591>
- S18 Schneider FAQ: <https://www.se.com/us/en/faqs/FA370377/>; Wiser–Sense tách: <https://community.se.com/t5/Schneider-Electric-Wiser-Forum/Wiser-Energy-Sense-Rebrand/td-p/497871>
- S19 Smappee appliance recognition: <https://www.smappee.com/blog/smappee-appliance-recognition>
- S20 Smappee support: <https://support.smappee.com/hc/en-gb/articles/4404733727380-Why-isn-t-Smappee-showing-any-appliances>
- S21 Generac PWRview FAQ: <https://generac.com/service-support/clean-energy-homeowner-resources/pwrview-faq>; ACEEE 2026: <https://www.aceee.org/wp-content/uploads/2026/10/at-long-last-realizing-the-promise.pdf>; SmartThings thread: <https://community.smartthings.com/t/depecrated-neurio-smartthings-integration/12905?page=4>
- S22 Bidgely: <https://www.bidgely.com/disaggregation>, whitepaper <https://go.bidgely.com/rs/492-VKN-623/images/Behind-the-Meter-Disaggregation.pdf?version=1>
- S23 Informetis: <https://www.informetis.com/en/engine/>, <https://www.informetis.com/en/service/forbusiness/smart_meter>
- S24 Bộ Công Thương, công tơ VConnex: <https://moit.gov.vn/tin-tuc/tiet-kiem-nang-luong/cong-to-thong-minh-giup-kiem-soat-luong-dien-tieu-thu-cho-ph.html>
- S25 Huchtkoetter & Reinhardt, Energy Informatics 2019 (trích đoạn): <https://energyinformatics.springeropen.com/articles/10.1186/s42162-019-0096-9>
- S26 Petralia và cộng sự, e-Energy 2023: <https://arxiv.org/abs/2305.10352>
- Tanoni, Appliance-Incremental Learning for NILM (SmartGridComm 2023, bản toàn văn hạn chế): <https://iris.univpm.it/handle/11566/325452>

**Vẫn chưa có nguồn:** ngưỡng/số lần lặp thật của Sense; luồng riêng cho máy mua sau; bất kỳ số đo nào về lợi ích của
nhãn cộng đồng thật (Sense hay học thuật); tốc độ lấy mẫu của Smappee và PWRview; số liệu tăng dần (incremental)
của Tanoni 2023 trên REFIT.
