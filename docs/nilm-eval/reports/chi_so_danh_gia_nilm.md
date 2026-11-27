# Các chỉ số đánh giá NILM: công thức, nguồn gốc và ý nghĩa

Tài liệu này giải thích các chỉ số dùng trong `training/metrics.py` và trong các
báo cáo kết quả của dự án. Mỗi chỉ số gồm: công thức đúng như mã đang tính, nguồn
gốc trong tài liệu NILM, ý nghĩa với bài toán và các lưu ý khi diễn giải. Những
chỗ mã của dự án khác với định nghĩa gốc được ghi rõ.

## 1. Bài toán và ký hiệu

NILM (Non-Intrusive Load Monitoring) ước lượng công suất của từng thiết bị từ một
tín hiệu điện tổng duy nhất của hộ. Với một hộ và một thiết bị trong kỳ test:

- $y_t$: công suất thật của thiết bị tại phút $t$ (W), đo bằng ổ cắm phụ của REFIT.
- $\hat y_t$: công suất mô hình dự đoán tại phút $t$ (W), đã chặn về 0 nếu âm.
- $T$: số phút hợp lệ (có nhãn) trong kỳ test; $\Delta t = 60$ s.
- $s_t, \hat s_t \in \{0, 1\}$: trạng thái bật thật và dự đoán.
  - $s_t$ lấy từ nhãn bật/tắt của dữ liệu tiền xử lý.
  - $\hat s_t = 1$ khi $\hat y_t \ge \theta$. Ngưỡng $\theta$ lấy từ `manifest.json`:
    WashingMachine 300 W, Dishwasher 300 W, Kettle 500 W, Microwave 200 W.
- TP, FP, FN, TN: số phút dự đoán bật đúng, bật nhầm, bỏ sót và tắt đúng.

Đầu ra của mô hình là chuỗi công suất. Vì vậy có thể đánh giá theo ba câu hỏi khác nhau:

1. **Công suất từng phút có đúng không?** Nhóm sai số theo thời điểm: MAE, RMSE, NDE.
2. **Năng lượng gán cho thiết bị có đúng không?** Nhóm năng lượng: SAE, sai số
   năng lượng, NEP, TECA, MR. Đây là thông tin người dùng nhận trên hóa đơn hoặc
   ứng dụng: "máy giặt dùng bao nhiêu kWh tuần này".
3. **Thiết bị có được phát hiện đúng lúc bật không?** Nhóm trạng thái: Precision,
   Recall, F1, Accuracy. Phục vụ các ứng dụng như cảnh báo thiết bị quên tắt hoặc
   thống kê số lần sử dụng.

Makonin và Popowich (2015) chỉ ra rằng chưa có cách báo cáo độ chính xác thống
nhất trong NILM. Họ đề xuất báo cáo cả hiệu năng phân loại (trạng thái) lẫn hiệu
năng ước lượng (công suất/năng lượng), không chỉ một trong hai. Bài tổng quan của
Pereira và Nunes (2018) cũng kết luận cộng đồng chưa có đồng thuận về bộ chỉ số
cần báo cáo. Vì thế dự án báo cáo cả ba nhóm.

## 2. Nhóm sai số công suất theo thời điểm

### 2.1. MAE: sai số tuyệt đối trung bình

$$\mathrm{MAE} = \frac{1}{T}\sum_{t=1}^{T} \lvert \hat y_t - y_t \rvert \quad (\text{W})$$

- **Nguồn:** chỉ số chuẩn trong NILM học sâu, dùng trong Kelly và Knottenbelt
  (2015), Zhang và cộng sự (2018, seq2point), và là một trong hai chỉ số chính
  của NILMFormer (Petralia và cộng sự, 2025).
- **Ý nghĩa:** trung bình mỗi phút, công suất dự đoán lệch bao nhiêu watt.
  Đơn vị W nên dễ hiểu với người không chuyên.
- **Lưu ý:**
  - Phụ thuộc thang công suất và tần suất bật của thiết bị. Thiết bị tắt phần
    lớn thời gian có MAE nhỏ ngay cả khi mô hình luôn dự đoán 0. Ví dụ, nếu
    Microwave bật 0,5% thời gian với 1.200 W, dự đoán 0 vẫn chỉ có MAE 6 W.
  - Vì vậy không so MAE giữa các thiết bị hoặc giữa các hộ có mức dùng khác nhau.
    Khi cần so, dùng NDE, NEP hoặc MR.

### 2.2. RMSE: căn bậc hai sai số bình phương trung bình

$$\mathrm{RMSE} = \sqrt{\frac{1}{T}\sum_{t=1}^{T} (\hat y_t - y_t)^2} \quad (\text{W})$$

- **Nguồn:** "RMS error in assigned power" trong NILMTK (Batra và cộng sự, 2014);
  cũng được dùng trong Klemenjak và cộng sự (2020).
- **Ý nghĩa:** giống MAE nhưng phạt nặng các phút sai lớn. Với NILM, sai lớn
  thường là bỏ sót hoặc báo nhầm cả một lần bật của thiết bị công suất cao
  (ấm đun 2–3 kW).
- **Lưu ý:** RMSE lớn hơn MAE nhiều lần (ví dụ 70 W so với 8 W trong kết quả
  baseline) cho thấy sai số tập trung vào ít phút có sai lớn, không rải đều.

### 2.3. NDE: sai số phân tách chuẩn hóa

$$\mathrm{NDE} = \frac{\sum_{t} (\hat y_t - y_t)^2}{\sum_{t} y_t^2}$$

- **Nguồn:** Kolter và Jaakkola (2012) định nghĩa "normalized disaggregation
  error" là $\sqrt{\sum_{t,i}\lVert y_t^{(i)} - \hat y_t^{(i)}\rVert_2^2 \,/\, \sum_{t,i}\lVert y_t^{(i)}\rVert_2^2}$,
  với $i$ chạy qua mọi thiết bị.
- **Khác biệt với bản gốc:** mã dự án tính **không lấy căn** và tính **riêng cho
  từng thiết bị**, giống cách nhiều bài về sau dùng. Do đó NDE của dự án bằng
  bình phương NDE gốc. Khi so với số liệu trong các bài báo, cần kiểm tra bài đó
  dùng dạng nào.
- **Ý nghĩa:** tỷ lệ năng lượng của sai số so với năng lượng của tín hiệu thật,
  không phụ thuộc đơn vị nên so được giữa các thiết bị.
- **Mốc tham chiếu:** dự đoán luôn bằng 0 cho NDE = 1. **NDE ≥ 1 nghĩa là mô
  hình không tốt hơn dự đoán 0** theo sai số bình phương.
- **Lưu ý:** nhạy với các phút sai lớn giống RMSE. Không xác định khi thiết bị
  không bật lần nào ($\sum y_t^2 = 0$).

## 3. Nhóm năng lượng

### 3.1. SAE: sai số tổng năng lượng chuẩn hóa

$$\mathrm{SAE} = \frac{\left\lvert \sum_t \hat y_t - \sum_t y_t \right\rvert}{\sum_t y_t}$$

- **Nguồn:** "signal aggregate error" của Zhang và cộng sự (2018), dạng
  $\lvert \hat r - r \rvert / r$, với $r$ là tổng năng lượng của thiết bị trong
  một khoảng thời gian.
- **Phạm vi trong dự án:** tính trên toàn bộ kỳ test của từng hộ, không theo từng
  ngày. Cột `relative_energy_error` cho giá trị giống hệt SAE.
- **Các biến thể khác:**
  - Kelly và Knottenbelt (2015) dùng mẫu số $\max(E, \hat E)$ thay cho $E$.
  - Shin và cộng sự (2019) tính SAE theo từng giờ để giảm hiệu ứng bù trừ.
- **Ý nghĩa:** sai số tương đối của tổng điện năng gán cho thiết bị. Đây là con
  số người dùng thấy trực tiếp ("máy rửa bát dùng 12 kWh tháng này").
- **Lưu ý quan trọng:** SAE chỉ so tổng, nên phút dự đoán thừa và phút dự đoán
  thiếu bù trừ nhau.
  - Một mô hình dự đoán đúng tổng năng lượng nhưng sai hoàn toàn thời điểm vẫn
    có SAE bằng 0.
  - Trong kết quả baseline, Dishwasher hộ 2 có SAE 0,005 nhưng MAE 34,7 W.
  - Vì vậy không dùng SAE một mình để kết luận mô hình tốt.

### 3.2. Sai số năng lượng tuyệt đối (kWh)

$$E_{\text{err}} = \left\lvert \sum_t \hat y_t - \sum_t y_t \right\rvert \cdot \frac{\Delta t}{3\,600\,000} \quad (\text{kWh})$$

- **Nguồn:** "error in total energy assigned" trong NILMTK (Batra và cộng sự, 2014).
- **Ý nghĩa:** là SAE nhưng tính bằng kWh, không chia cho năng lượng thật. Cho
  biết sai lệch tuyệt đối trên hóa đơn.
- **Lưu ý:**
  - Phụ thuộc độ dài kỳ test và mức dùng của hộ, nên không so trực tiếp giữa các hộ.
  - Cột `energy_bias_kwh` giữ dấu: dương là dự đoán thừa, âm là dự đoán thiếu.
    Nên đọc kèm để biết mô hình thiên về phía nào.

### 3.3. NEP: sai số công suất gán chuẩn hóa

$$\mathrm{NEP} = \frac{\sum_t \lvert \hat y_t - y_t \rvert}{\sum_t y_t}$$

- **Nguồn:** "normalised error in assigned power" trong NILMTK (Batra và cộng sự,
  2014); được Bonfigli và cộng sự (2018) dùng làm chỉ số chính.
- **Cùng công thức, khác tên:** Mayhorn và cộng sự (2016, PNNL) gọi đây là
  "Energy Error" (EE 6). Không nhầm với SAE.
- **Ý nghĩa:** tổng sai số tuyệt đối từng phút so với tổng năng lượng thật. Khác
  SAE ở chỗ sai thừa và sai thiếu **không** bù trừ nhau.
- **Mốc tham chiếu:** dự đoán luôn bằng 0 cho NEP = 1. **NEP > 1 nghĩa là tổng
  sai số tuyệt đối còn lớn hơn khi dự đoán 0.**
- **Lưu ý:** không có cận trên. Mayhorn và cộng sự (2016) đánh giá EE 6 cao,
  nhưng chỉ ra rằng khi sai số lớn thì giá trị vượt 1 và khó diễn giải.

### 3.4. TECA: tỷ lệ năng lượng được gán đúng

Định nghĩa gốc gộp mọi thiết bị:

$$\mathrm{Acc} = 1 - \frac{\sum_t \sum_i \lvert \hat y_t^{(i)} - y_t^{(i)} \rvert}{2 \sum_t \bar y_t}$$

với $\bar y_t$ là công suất **điện tổng** của hộ.

- **Nguồn:** Kolter và Johnson (2011, bộ dữ liệu REDD). Kelly và Knottenbelt
  (2015) gọi là "proportion of total energy correctly assigned".
- **Lý do có hệ số 2:** năng lượng gán sai cho thiết bị A bị đếm hai lần: dự đoán
  thừa ở A và dự đoán thiếu ở thiết bị thật B.
- **Cách dự án tính:** tính riêng cho từng thiết bị, mẫu số là năng lượng thật
  của thiết bị đó, không phải điện tổng:

  $$\mathrm{TECA}_{\text{dự án}} = 1 - \frac{\sum_t \lvert \hat y_t - y_t \rvert}{2\sum_t y_t} = 1 - \frac{\mathrm{NEP}}{2}$$

- **Hệ quả của cách tính này:**
  - TECA của dự án chỉ là phép biến đổi tuyến tính của NEP, không mang thêm
    thông tin. Có thể chỉ báo cáo một trong hai.
  - Giá trị này cũng không so được với TECA trong các bài báo, vì các bài đó chia
    cho điện tổng, gồm cả tải không được giám sát. Với cách tính gốc, giá trị
    thường cao hơn nhiều.
- **Mốc tham chiếu trong dự án:** dự đoán luôn bằng 0 cho TECA = 0,5.
  - TECA < 0,5 tương đương NEP > 1.
  - TECA có thể âm. NILMTK (Batra và cộng sự, 2014) đã chỉ ra điểm này và gọi
    TECA là chỉ số đặt vấn đề chưa tốt (ill-posed).

### 3.5. MR: tỷ lệ trùng khớp

$$\mathrm{MR} = \frac{\sum_t \min(\hat y_t, y_t)}{\sum_t \max(\hat y_t, y_t)}$$

- **Nguồn:** "Match Rate" (EE 8) trong Mayhorn và cộng sự (2016, PNNL). Bài này
  thử 10 chỉ số năng lượng trên 12 kịch bản lỗi mô phỏng: lệch thời gian, dự đoán
  thiếu/thừa 5–50%, bỏ sót và báo nhầm sự kiện. MR đạt 35/36 điểm, cao nhất, và
  được nhóm tư vấn giao thức NILM khuyến nghị dùng.
- **Ứng dụng gần đây:** NILMFormer (Petralia và cộng sự, 2025) chọn MAE và MR làm
  hai chỉ số chính, gọi MR là chỉ số tổng thể tốt nhất.
- **Ý nghĩa:** phần diện tích trùng nhau giữa đường dự đoán và đường thật, chia
  cho phần diện tích hợp của hai đường.
  - Luôn nằm trong [0, 1] khi $\hat y_t \ge 0$.
  - Dự đoán 0 cho MR = 0; khớp hoàn toàn cho MR = 1.
  - Phạt cả dự đoán thừa lẫn thiếu, cả lệch thời gian, nên một con số phản ánh
    đồng thời công suất và thời điểm.
- **Lưu ý:**
  - Mã trả NaN nếu có dự đoán âm. Khi đánh giá, dự đoán đã được chặn về 0 nên
    không xảy ra.
  - Mayhorn và cộng sự lưu ý chỉ số tính trên thiết bị ít dùng hoặc ít sự kiện có
    thể không đại diện. Đây là lý do dự án loại các cặp dưới 60 phút bật (`low_support`).

## 4. Nhóm trạng thái bật/tắt

Trạng thái dự đoán suy ra từ công suất dự đoán bằng ngưỡng $\theta$ ở mục 1,
tính trên từng phút. Với TwoStage, cột `detector_*` tính thêm các chỉ số này
trực tiếp từ mask của bộ phát hiện GRU thay vì từ ngưỡng công suất.

$$\mathrm{Precision} = \frac{TP}{TP + FP}, \qquad \mathrm{Recall} = \frac{TP}{TP + FN}$$

$$F_1 = \frac{2\,TP}{2\,TP + FP + FN}, \qquad \mathrm{Accuracy} = \frac{TP + TN}{TP + FP + FN + TN}$$

- **Nguồn:** chỉ số phân loại chuẩn, được NILMTK (Batra và cộng sự, 2014) và
  Kelly và Knottenbelt (2015) đưa vào cho NILM. Makonin và Popowich (2015) dùng
  F-score cho phần phân loại.
- **Ý nghĩa với bài toán:**
  - **Precision:** khi mô hình báo thiết bị đang bật, bao nhiêu phần đúng. Precision
    thấp gây cảnh báo giả và làm tăng năng lượng dự đoán thừa.
  - **Recall:** trong các phút thiết bị thật sự bật, mô hình phát hiện được bao
    nhiêu. Recall thấp nghĩa là bỏ sót lần sử dụng, dẫn tới dự đoán thiếu năng lượng.
  - **F1:** trung bình điều hòa của Precision và Recall, là chỉ số đơn lẻ chính
    cho khả năng phát hiện.
  - **Tỷ lệ bỏ sót** (`false_negative_rate`) bằng 1 − Recall nên không báo riêng.
- **Lưu ý:**
  - **Accuracy gần như vô nghĩa với NILM.** Thiết bị đích tắt phần lớn thời gian
    nên TN chiếm ưu thế. Mô hình luôn dự đoán tắt vẫn có Accuracy khoảng 0,99
    (trong kết quả baseline, mọi cặp hộ × thiết bị đều từ 0,97 trở lên). Chỉ nên báo để đầy đủ, không dùng
    để so sánh.
  - F1 phụ thuộc ngưỡng $\theta$. Một phút bật bị dự đoán thiếu công suất xuống
    dưới ngưỡng vẫn bị tính là FN dù sai số công suất nhỏ.
  - Chỉ số tính theo từng phút, nên lệch thời điểm 1 phút ở đầu và cuối mỗi lần
    bật cũng làm giảm F1. Các chỉ số theo sự kiện (Pereira và Nunes, 2017) không
    được dùng trong dự án.
  - Mẫu số bằng 0 (ví dụ không có phút bật nào) được quy ước trả 0. Các cặp như
    vậy đã bị loại bằng cờ `low_support`.

## 5. Ví dụ minh họa

Ấm đun 2.000 W bật 3 phút; mô hình dự đoán đúng công suất nhưng **trễ 1 phút**:

| Phút | 1 | 2 | 3 | 4 |
| --- | ---: | ---: | ---: | ---: |
| Thật $y_t$ (W) | 2.000 | 2.000 | 2.000 | 0 |
| Dự đoán $\hat y_t$ (W) | 0 | 2.000 | 2.000 | 2.000 |

| Chỉ số | Mô hình trễ 1 phút | Luôn dự đoán 0 |
| --- | ---: | ---: |
| MAE (W) | 1.000 | 1.500 |
| NDE | 0,667 | 1 |
| SAE | **0** | 1 |
| NEP | 0,667 | 1 |
| TECA (dự án) | 0,667 | 0,5 |
| MR | 0,5 | 0 |
| Precision / Recall / F1 | 0,667 / 0,667 / 0,667 | 0 / 0 / 0 |
| Accuracy | 0,5 | 0,25 |

- SAE bằng 0 dù mô hình sai thời điểm, vì tổng năng lượng vẫn đúng.
- NEP, NDE và MR đều phạt lỗi lệch thời gian.
- Trong thực tế thiết bị tắt phần lớn thời gian. Ví dụ ở trên chỉ có 1 phút tắt
  nên Accuracy của "luôn dự đoán 0" thấp. Với dữ liệu thật, nó sẽ gần 1.

## 6. Tổng hợp nhiều hộ, thiết bị và seed

- **Đơn vị tính:** mọi chỉ số được tính trên từng cặp (mô hình, hộ test, thiết
  bị), cộng qua toàn bộ kỳ test, không tính theo từng cửa sổ rồi lấy trung bình.
- **Ensemble seed:** dự đoán của 5 seed được lấy trung bình theo từng phút trước,
  rồi mới tính chỉ số một lần. Không lấy trung bình chỉ số của từng seed.
- **Tổng hợp:** bảng tổng hợp lấy trung bình macro theo cặp, để hộ có nhiều dữ
  liệu không chi phối. Kèm trung vị, vì các tỷ số NDE, SAE, NEP bị kéo lên mạnh
  bởi cặp có năng lượng thật nhỏ (đặc biệt Microwave).
- **Cặp ít dữ liệu:** cặp có dưới 60 phút bật trong test bị đánh dấu `low_support`
  và loại khỏi bảng tổng hợp, vì các tỷ số và F1 trên vài phút bật không ổn định.

## 7. Bảng tóm tắt và khuyến nghị

| Chỉ số | Trả lời câu hỏi | Tốt khi | Dự đoán 0 cho | Nguồn chính |
| --- | --- | --- | ---: | --- |
| MAE | Lệch bao nhiêu W mỗi phút | thấp | MAE = trung bình $y_t$ | Kelly 2015; Zhang 2018; Petralia 2025 |
| RMSE | Có các phút sai lớn không | thấp | – | Batra 2014 |
| NDE | Sai số so với tín hiệu, không phụ thuộc đơn vị | thấp | 1 | Kolter và Jaakkola 2012 (bản gốc có căn) |
| SAE | Tổng kWh lệch bao nhiêu % | thấp | 1 | Zhang 2018 |
| Sai số NL (kWh) | Tổng kWh lệch bao nhiêu | thấp | tổng năng lượng thật | Batra 2014 |
| NEP | Tổng sai số tuyệt đối so với năng lượng thật | thấp | 1 | Batra 2014; Mayhorn 2016 (EE 6) |
| TECA (dự án) | = 1 − NEP/2 | cao | 0,5 | Kolter và Johnson 2011 (bản gốc chia điện tổng) |
| MR | Đường dự đoán trùng đường thật bao nhiêu | cao | 0 | Mayhorn 2016 (EE 8); Petralia 2025 |
| Precision | Báo bật có đúng không | cao | 0 | Batra 2014; Kelly 2015 |
| Recall | Có bỏ sót lần bật không | cao | 0 | Batra 2014; Kelly 2015 |
| F1 | Phát hiện bật/tắt tổng thể | cao | 0 | Kelly 2015; Makonin 2015 |
| Accuracy | – (bị TN chi phối) | cao | gần 1 | Kelly 2015 |

**Khuyến nghị cho báo cáo của dự án:**

1. **Chỉ số chính:** MAE, MR và F1.
   - MAE và MR khớp với bài NILMFormer, giúp so sánh với baseline gốc.
   - MR được Mayhorn và cộng sự đánh giá bền vững nhất.
   - F1 đo khả năng phát hiện, là điểm khác biệt của mô hình hai giai đoạn.
2. **Chỉ số phụ cho ứng dụng hóa đơn:** SAE và sai số năng lượng (kWh), luôn kèm
   `energy_bias_kwh` để biết dự đoán thừa hay thiếu.
3. **Kiểm tra "tốt hơn dự đoán 0":** dùng NDE < 1 hoặc NEP < 1.
4. **Không dùng Accuracy để so sánh.** Báo TECA của dự án như một dạng khác của
   NEP, hoặc bỏ đi. Khi so với các bài báo, cần nói rõ dự án tính TECA và NDE
   theo từng thiết bị và không lấy căn.
5. **Luôn báo kèm** số phút hợp lệ, số phút bật và các cặp bị loại, vì mọi tỷ số
   đều không ổn định khi thiết bị ít dùng.

## Tài liệu tham khảo

- Batra, N., Kelly, J., Parson, O., Dutta, H., Knottenbelt, W., Rogers, A., Singh, A.,
  Srivastava, M. (2014). NILMTK: An open source toolkit for non-intrusive load
  monitoring. *Proc. 5th ACM e-Energy*, 265–276. [arXiv:1404.3878](https://arxiv.org/abs/1404.3878)
- Bonfigli, R., Felicetti, A., Principi, E., Fagiani, M., Squartini, S., Piazza, F. (2018).
  Denoising autoencoders for non-intrusive load monitoring: Improvements and
  comparative evaluation. *Energy and Buildings*, 158, 1461–1474.
- Kelly, J., Knottenbelt, W. (2015). Neural NILM: Deep neural networks applied to
  energy disaggregation. *Proc. 2nd ACM BuildSys*. [arXiv:1507.06594](https://arxiv.org/abs/1507.06594)
- Klemenjak, C., Makonin, S., Elmenreich, W. (2020). Towards comparability in
  non-intrusive load monitoring: On data and performance evaluation.
  *IEEE ISGT*. [arXiv:2001.07708](https://arxiv.org/abs/2001.07708)
- Kolter, J. Z., Jaakkola, T. (2012). Approximate inference in additive factorial
  HMMs with application to energy disaggregation. *AISTATS*, PMLR 22, 1472–1482.
  [PDF](https://zicokolter.com/publications/kolter2012approximate.pdf)
- Kolter, J. Z., Johnson, M. J. (2011). REDD: A public data set for energy
  disaggregation research. *SustKDD Workshop*. [PDF](https://zicokolter.com/publications/kolter2011redd.pdf)
- Makonin, S., Popowich, F. (2015). Nonintrusive load monitoring (NILM) performance
  evaluation: A unified approach for accuracy reporting. *Energy Efficiency*, 8,
  809–814. [DOI:10.1007/s12053-014-9306-2](https://doi.org/10.1007/s12053-014-9306-2)
- Mayhorn, E. T., Sullivan, G. P., Petersen, J. M., Butner, R. S., Johnson, E. M. (2016).
  Load disaggregation technologies: Real world and laboratory performance.
  *ACEEE Summer Study on Energy Efficiency in Buildings*, 1-1–1-13.
  [PDF](https://www.aceee.org/wp-content/uploads/proceedings-1980-2020/2016/1_675.pdf)
- Pereira, L., Nunes, N. (2017). A comparison of performance metrics for event
  classification in non-intrusive load monitoring. *IEEE SmartGridComm*, 171–176.
- Pereira, L., Nunes, N. (2018). Performance evaluation in non-intrusive load
  monitoring: Datasets, metrics, and tools — A review. *WIREs Data Mining and
  Knowledge Discovery*, 8(6), e1265. [DOI:10.1002/widm.1265](https://doi.org/10.1002/widm.1265)
- Petralia, A., Charpentier, P., Kadhi, Y., Palpanas, T. (2025). NILMFormer:
  Non-intrusive load monitoring that accounts for non-stationarity. *KDD 2025*.
  [arXiv:2506.05880](https://arxiv.org/abs/2506.05880)
- Shin, C., Joo, S., Yim, J., Lee, H., Moon, T., Rhee, W. (2019). Subtask gated
  networks for non-intrusive load monitoring. *AAAI*. [arXiv:1811.06692](https://arxiv.org/abs/1811.06692)
- Zhang, C., Zhong, M., Wang, Z., Goddard, N., Sutton, C. (2018). Sequence-to-point
  learning with neural networks for non-intrusive load monitoring. *AAAI*.
  [PDF](https://homepages.inf.ed.ac.uk/csutton/publications/aaai18nilm.pdf)
