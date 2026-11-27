# Kết quả thực nghiệm: TwoStageNILMFormer (đề xuất) và NILMFormer (baseline)

<!-- có nhận xét viết tay -->

TwoStageNILMFormer (2Stage) là phương pháp đề xuất, cải tiến từ NILMFormer bằng bộ phát hiện bật/tắt GRU
và mask đầu ra; NILMFormer gốc là baseline. Hai mô hình dùng chung dữ liệu, cách chia hộ, 5 seed,
early stopping và hàm đánh giá.

Kết quả lấy từ:

- 2Stage: `training/runs/twostage_20261126_042442`; mô hình chung đã có; mô hình một hộ 7/7 hộ.
- Baseline: `training/runs/nilmformer_20261126_042452`; mô hình chung đã có; mô hình một hộ 7/7 hộ.

## Tóm tắt

- **Hộ mới (câu hỏi 1).** Cả hai mô hình suy giảm rõ khi dùng cho hộ chưa có trong dữ liệu train:
  F1 giảm khoảng 25% với 2Stage và 32% với baseline. Ở hộ mới, 2Stage tốt hơn baseline: F1 0,415
  so với 0,374; MAE 17,4 so với 23,7 W; NEP 1,28 so với 1,94; MR 0,274 so với 0,180. Chênh lệch
  F1, MAE, NEP và MR có ý nghĩa trong kiểm định ghép cặp (p < 0,001). Ở chính hộ được train, F1 của
  hai mô hình ngang nhau, nhưng 2Stage vẫn có MAE và NEP thấp hơn rõ.
- **Theo thiết bị.** Lợi thế của 2Stage nằm ở Dishwasher và Kettle. WashingMachine hơi kém
  baseline về F1. Microwave thất bại ở cả hai mô hình (F1 tối đa 0,35).
- **Cá nhân hóa (câu hỏi 2).** Mô hình riêng cho từng hộ không tốt hơn mô hình chung. Với 2Stage,
  mô hình chung có F1 cao hơn mô hình riêng ở cả hai nhóm hộ (0,664 so với 0,623 và 0,535 so với
  0,479) và ở 6/7 hộ, trong khi không cần đo riêng từng thiết bị tại hộ dùng. Cấu hình tốt nhất là
  **2Stage chung**.
- **Chi phí.** 2Stage train lâu hơn baseline khoảng 4–5 lần, nhưng suy luận rất nhẹ: dưới 50 ms cho
  một ngày dữ liệu trên một luồng CPU mỗi seed, nên chạy được không cần GPU.
- **Lưu ý.** Baseline dừng sớm (epoch 19–54) còn phần lớn mô hình một hộ của 2Stage chạy đủ 150
  epoch mà chưa hội tụ. Độ lớn chênh lệch cần kiểm tra lại với cùng ngân sách epoch (mục Giới hạn).

## Thiết lập chung

- REFIT, bảy hộ nghiên cứu 2, 3, 6, 9, 11, 13, 20; bốn thiết bị WashingMachine, Dishwasher, Kettle,
  Microwave; cửa sổ 128 phút, mẫu 1 phút. Mỗi hộ chia theo thời gian: 80% đầu train, 20% cuối test.
- Mỗi mô hình là ensemble 5 seed: trung bình công suất dự đoán rồi tính chỉ số một lần. Early
  stopping theo validation loss (20% cuối phần train), patience 10, tối đa 150 epoch.
- 2Stage gồm bộ phát hiện GRU (BCE, trọng số lớp bật chặn tối đa 5) và bộ hồi quy NILMFormer, đầu ra
  công suất nhân với mask bật/tắt. Baseline là NILMFormer cấu hình 4 đầu ra (`c_out=4`), loss MSE.
  Bài NILMFormer gốc train mỗi thiết bị một mô hình, nên số liệu ở đây không so trực tiếp với bài.
- Mỗi ô là trung bình macro theo cặp (hộ train, hộ test, thiết bị). Loại các cặp có dưới 60 phút
  bật trong test: Dishwasher hộ 11, WashingMachine hộ 11.
- ↑: càng cao càng tốt; ↓: càng thấp càng tốt; in đậm là giá trị tốt nhất trong cột lớn.
  Công thức và ý nghĩa chỉ số: `reports/chi_so_danh_gia_nilm.md`.

## Câu hỏi 1. Hiệu năng NILM ở hộ mới

Ứng với yêu cầu 1: đo sai số điện năng và F1 theo thiết bị, hộ mới, mức tải và số thiết bị bật
đồng thời, với tập test tách theo hộ.

**Thiết kế (`cross_house`).** Train 7 mô hình, mỗi mô hình chỉ dùng phần train của một hộ, rồi
test trên 20% thời gian cuối của cả bảy hộ. "Hộ được train" là ô mô hình test trên chính hộ đã
train (7 ô mỗi thiết bị); "Hộ mới" là 6 hộ còn lại (42 ô mỗi thiết bị). Phạm vi thiết bị cố định
bốn loại, nên câu hỏi này đo hộ mới chứ không đo loại thiết bị chưa thấy.

### 1.1. Kết quả tổng thể

**Dự đoán bật/tắt**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>Precision ↑</td><td align="right">0,522</td><td align="right"><b>0,542</b></td><td align="right"><b>0,406</b></td><td align="right">0,396</td></tr>
    <tr><td>Recall ↑</td><td align="right"><b>0,657</b></td><td align="right">0,573</td><td align="right"><b>0,506</b></td><td align="right">0,409</td></tr>
    <tr><td>F1 ↑</td><td align="right"><b>0,557</b></td><td align="right">0,547</td><td align="right"><b>0,415</b></td><td align="right">0,374</td></tr>
    <tr><td>Accuracy ↑</td><td align="right">0,9912</td><td align="right"><b>0,9927</b></td><td align="right">0,9879</td><td align="right"><b>0,9882</b></td></tr>
  </tbody>
</table>


**Dự đoán công suất**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>MAE (W) ↓</td><td align="right"><b>11,5</b></td><td align="right">15,6</td><td align="right"><b>17,4</b></td><td align="right">23,7</td></tr>
    <tr><td>RMSE (W) ↓</td><td align="right"><b>93,5</b></td><td align="right">95,0</td><td align="right"><b>127,7</b></td><td align="right">141,6</td></tr>
    <tr><td>NDE ↓</td><td align="right">0,486</td><td align="right"><b>0,475</b></td><td align="right"><b>0,875</b></td><td align="right">0,912</td></tr>
  </tbody>
</table>


**Dự đoán năng lượng**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>SAE ↓</td><td align="right">0,324</td><td align="right"><b>0,264</b></td><td align="right"><b>0,618</b></td><td align="right">0,821</td></tr>
    <tr><td>Sai số năng lượng (kWh) ↓</td><td align="right">7,80</td><td align="right"><b>7,17</b></td><td align="right"><b>11,37</b></td><td align="right">16,08</td></tr>
    <tr><td>NEP ↓</td><td align="right"><b>0,808</b></td><td align="right">1,221</td><td align="right"><b>1,281</b></td><td align="right">1,939</td></tr>
    <tr><td>TECA ↑</td><td align="right"><b>0,596</b></td><td align="right">0,389</td><td align="right"><b>0,360</b></td><td align="right">0,030</td></tr>
    <tr><td>MR ↑</td><td align="right"><b>0,437</b></td><td align="right">0,337</td><td align="right"><b>0,274</b></td><td align="right">0,180</td></tr>
  </tbody>
</table>


**Nhận xét.**

- Khi sang hộ mới, F1 của 2Stage giảm từ 0,557 xuống 0,415 và của baseline từ 0,547 xuống 0,374;
  MAE tăng khoảng 1,5 lần ở cả hai.
- Ở hộ mới, 2Stage tốt hơn baseline ở 97/156 cặp về F1, 139/156 cặp về MAE và NEP, 119/156 cặp về
  MR. Kiểm định đảo dấu ngẫu nhiên trên chênh lệch trung bình theo 42 cặp (hộ train, hộ test):
  p < 0,001 cho F1, Recall, MAE, NEP và MR; p = 0,002 cho sai số năng lượng; p = 0,012 cho SAE; không khác biệt
  về Precision (p = 0,39) và NDE (p = 0,90). Các cặp cùng hộ train vẫn tương quan nên p chỉ để
  tham khảo.
- Lợi thế đến từ Recall (0,506 so với 0,409), không từ Precision (0,406 so với 0,396): bộ phát
  hiện giúp bắt thêm lần bật. Mask đưa công suất về đúng 0 khi tắt, nên MAE và NEP giảm mạnh.
  Ở hộ mới, 42% cặp của 2Stage có NEP < 1 (tốt hơn luôn dự đoán 0), so với 21% của baseline.
- Ở chính hộ được train, F1 ngang nhau (p = 0,51), Recall cao hơn (0,657 so với 0,573) nhưng
  Precision thấp hơn (0,522 so với 0,542). MAE (11,5 so với 15,6 W) và NEP (0,81 so với 1,22) tốt
  hơn với p ≈ 0,015; SAE và sai số năng lượng hơi kém hơn baseline.

### 1.2. Theo thiết bị

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>Dishwasher – F1 ↑</td><td align="right">0,756</td><td align="right"><b>0,796</b></td><td align="right"><b>0,674</b></td><td align="right">0,564</td></tr>
    <tr><td>Dishwasher – MAE (W) ↓</td><td align="right"><b>18,2</b></td><td align="right">22,7</td><td align="right"><b>28,3</b></td><td align="right">40,3</td></tr>
    <tr><td>Dishwasher – SAE ↓</td><td align="right">0,269</td><td align="right"><b>0,117</b></td><td align="right"><b>0,275</b></td><td align="right">0,580</td></tr>
    <tr><td>Dishwasher – Sai số năng lượng (kWh) ↓</td><td align="right">14,30</td><td align="right"><b>11,16</b></td><td align="right"><b>15,71</b></td><td align="right">32,06</td></tr>
    <tr><td>Kettle – F1 ↑</td><td align="right">0,723</td><td align="right"><b>0,728</b></td><td align="right"><b>0,618</b></td><td align="right">0,597</td></tr>
    <tr><td>Kettle – MAE (W) ↓</td><td align="right"><b>10,0</b></td><td align="right">14,3</td><td align="right"><b>15,2</b></td><td align="right">20,0</td></tr>
    <tr><td>Kettle – SAE ↓</td><td align="right"><b>0,111</b></td><td align="right">0,202</td><td align="right"><b>0,308</b></td><td align="right">0,391</td></tr>
    <tr><td>Kettle – Sai số năng lượng (kWh) ↓</td><td align="right"><b>4,00</b></td><td align="right">6,82</td><td align="right"><b>8,93</b></td><td align="right">12,07</td></tr>
    <tr><td>WashingMachine – F1 ↑</td><td align="right">0,520</td><td align="right"><b>0,558</b></td><td align="right">0,313</td><td align="right"><b>0,324</b></td></tr>
    <tr><td>WashingMachine – MAE (W) ↓</td><td align="right"><b>15,3</b></td><td align="right">19,8</td><td align="right"><b>22,6</b></td><td align="right">28,6</td></tr>
    <tr><td>WashingMachine – SAE ↓</td><td align="right">0,283</td><td align="right"><b>0,204</b></td><td align="right"><b>0,415</b></td><td align="right">0,436</td></tr>
    <tr><td>WashingMachine – Sai số năng lượng (kWh) ↓</td><td align="right">9,56</td><td align="right"><b>8,73</b></td><td align="right"><b>14,08</b></td><td align="right">14,20</td></tr>
    <tr><td>Microwave – F1 ↑</td><td align="right"><b>0,251</b></td><td align="right">0,142</td><td align="right"><b>0,079</b></td><td align="right">0,030</td></tr>
    <tr><td>Microwave – MAE (W) ↓</td><td align="right"><b>4,1</b></td><td align="right">7,2</td><td align="right"><b>5,9</b></td><td align="right">9,2</td></tr>
    <tr><td>Microwave – SAE ↓</td><td align="right">0,620</td><td align="right"><b>0,504</b></td><td align="right"><b>1,396</b></td><td align="right">1,789</td></tr>
    <tr><td>Microwave – Sai số năng lượng (kWh) ↓</td><td align="right">4,52</td><td align="right"><b>2,77</b></td><td align="right"><b>7,76</b></td><td align="right">7,99</td></tr>
  </tbody>
</table>


**Nhận xét.**

- **Dishwasher** được cải thiện nhiều nhất ở hộ mới: F1 0,674 so với 0,564, MAE 28 so với 40 W,
  sai số năng lượng 15,7 so với 32,1 kWh. Baseline dự đoán thiếu năng lượng Dishwasher ở hộ mới
  (trung bình −10,8 kWh mỗi cặp), 2Stage dự đoán thừa nhẹ (+3,8 kWh). Ở chính hộ được train, baseline
  có F1 và SAE tốt hơn.
- **Kettle**: 2Stage tốt hơn ở hộ mới về F1 (0,618 so với 0,597) và mọi chỉ số năng lượng; ở hộ
  được train F1 ngang nhau.
- **WashingMachine**: 2Stage có MAE thấp hơn nhưng F1 kém hơn (0,520 so với 0,558 ở hộ được
  train, 0,313 so với 0,324 ở hộ mới). Đây là thiết bị lớn khó nhất, vì chu trình có nhiều pha
  công suất thấp và dễ nhầm với Dishwasher.
- **Microwave**: cả hai mô hình gần như không nhận ra; 2Stage tốt hơn tương đối (0,251 so với
  0,142 ở hộ được train, 0,079 so với 0,030 ở hộ mới) nhưng SAE ở hộ mới vẫn trên 1.

### 1.3. Theo hộ test

Hộ được train: mô hình của chính hộ đó. Hộ mới: trung bình 6 mô hình train trên hộ khác. Trung bình 4 thiết bị.

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>Hộ 2 – F1 ↑</td><td align="right">0,476</td><td align="right"><b>0,480</b></td><td align="right"><b>0,396</b></td><td align="right">0,376</td></tr>
    <tr><td>Hộ 2 – MAE (W) ↓</td><td align="right"><b>17,7</b></td><td align="right">26,3</td><td align="right"><b>23,4</b></td><td align="right">32,7</td></tr>
    <tr><td>Hộ 2 – SAE ↓</td><td align="right"><b>0,378</b></td><td align="right">0,398</td><td align="right"><b>0,408</b></td><td align="right">0,543</td></tr>
    <tr><td>Hộ 3 – F1 ↑</td><td align="right"><b>0,482</b></td><td align="right">0,421</td><td align="right"><b>0,414</b></td><td align="right">0,351</td></tr>
    <tr><td>Hộ 3 – MAE (W) ↓</td><td align="right"><b>17,8</b></td><td align="right">25,7</td><td align="right"><b>28,0</b></td><td align="right">34,6</td></tr>
    <tr><td>Hộ 3 – SAE ↓</td><td align="right">0,403</td><td align="right"><b>0,211</b></td><td align="right"><b>0,521</b></td><td align="right">0,629</td></tr>
    <tr><td>Hộ 6 – F1 ↑</td><td align="right">0,622</td><td align="right"><b>0,687</b></td><td align="right"><b>0,511</b></td><td align="right">0,433</td></tr>
    <tr><td>Hộ 6 – MAE (W) ↓</td><td align="right"><b>7,1</b></td><td align="right">7,5</td><td align="right"><b>7,6</b></td><td align="right">14,6</td></tr>
    <tr><td>Hộ 6 – SAE ↓</td><td align="right">0,344</td><td align="right"><b>0,141</b></td><td align="right"><b>0,356</b></td><td align="right">0,600</td></tr>
    <tr><td>Hộ 9 – F1 ↑</td><td align="right"><b>0,579</b></td><td align="right">0,546</td><td align="right"><b>0,425</b></td><td align="right">0,376</td></tr>
    <tr><td>Hộ 9 – MAE (W) ↓</td><td align="right"><b>9,7</b></td><td align="right">15,9</td><td align="right"><b>22,0</b></td><td align="right">30,9</td></tr>
    <tr><td>Hộ 9 – SAE ↓</td><td align="right">0,281</td><td align="right"><b>0,111</b></td><td align="right"><b>0,850</b></td><td align="right">1,501</td></tr>
    <tr><td>Hộ 11 – F1 ↑</td><td align="right"><b>0,530</b></td><td align="right">0,409</td><td align="right"><b>0,369</b></td><td align="right">0,260</td></tr>
    <tr><td>Hộ 11 – MAE (W) ↓</td><td align="right"><b>3,7</b></td><td align="right">6,0</td><td align="right"><b>7,1</b></td><td align="right">12,6</td></tr>
    <tr><td>Hộ 11 – SAE ↓</td><td align="right"><b>0,147</b></td><td align="right">0,561</td><td align="right"><b>1,200</b></td><td align="right">1,808</td></tr>
    <tr><td>Hộ 13 – F1 ↑</td><td align="right">0,480</td><td align="right"><b>0,540</b></td><td align="right">0,355</td><td align="right"><b>0,376</b></td></tr>
    <tr><td>Hộ 13 – MAE (W) ↓</td><td align="right"><b>15,9</b></td><td align="right">16,1</td><td align="right"><b>20,2</b></td><td align="right">20,8</td></tr>
    <tr><td>Hộ 13 – SAE ↓</td><td align="right"><b>0,486</b></td><td align="right">0,533</td><td align="right">0,782</td><td align="right"><b>0,653</b></td></tr>
    <tr><td>Hộ 20 – F1 ↑</td><td align="right"><b>0,715</b></td><td align="right">0,678</td><td align="right"><b>0,414</b></td><td align="right">0,387</td></tr>
    <tr><td>Hộ 20 – MAE (W) ↓</td><td align="right"><b>4,9</b></td><td align="right">6,7</td><td align="right"><b>8,6</b></td><td align="right">14,5</td></tr>
    <tr><td>Hộ 20 – SAE ↓</td><td align="right">0,142</td><td align="right"><b>0,041</b></td><td align="right"><b>0,500</b></td><td align="right">0,509</td></tr>
  </tbody>
</table>


**Nhận xét.**

- Ở hộ mới, 2Stage có F1 cao hơn baseline ở 6/7 hộ test (trừ hộ 13: 0,355 so với 0,376) và MAE
  thấp hơn ở cả 7 hộ.
- Hộ mới khó nhất là 13 và 11 (F1 của 2Stage 0,355 và 0,369); dễ nhất là hộ 6 (0,511). Hộ 11 chỉ
  được đánh giá trên Kettle và Microwave.
- Mức giảm khi sang hộ mới khác nhau nhiều giữa các hộ: hộ 20 giảm từ 0,715 xuống 0,414, hộ 2 chỉ
  từ 0,476 xuống 0,396. Một hộ có mô hình riêng tốt chưa chắc dễ với mô hình của hộ khác.
- Theo hộ train, mô hình 2Stage của hộ 9 và hộ 3 chuyển giao tốt nhất: NEP trên hộ mới 0,84 và
  0,92, là hai mô hình duy nhất có NEP trung bình dưới 1.

### 1.4. Theo số thiết bị đích bật đồng thời

Tầng 0 không có phút bật nên chỉ báo MAE và tổng số phút báo bật nhầm.

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>0 – MAE (W) ↓</td><td align="right"><b>4,9</b></td><td align="right">6,9</td><td align="right"><b>5,9</b></td><td align="right">10,5</td></tr>
    <tr><td>0 – Phút báo bật nhầm ↓</td><td align="right">12 700</td><td align="right"><b>8 281</b></td><td align="right">91 092</td><td align="right"><b>76 123</b></td></tr>
    <tr><td>1 – F1 ↑</td><td align="right"><b>0,652</b></td><td align="right">0,589</td><td align="right"><b>0,487</b></td><td align="right">0,434</td></tr>
    <tr><td>1 – MAE (W) ↓</td><td align="right"><b>164,8</b></td><td align="right">217,3</td><td align="right"><b>294,7</b></td><td align="right">339,6</td></tr>
    <tr><td>1 – SAE ↓</td><td align="right"><b>0,245</b></td><td align="right">0,293</td><td align="right"><b>0,462</b></td><td align="right">0,510</td></tr>
    <tr><td>2 – F1 ↑</td><td align="right"><b>0,670</b></td><td align="right">0,652</td><td align="right"><b>0,530</b></td><td align="right">0,499</td></tr>
    <tr><td>2 – MAE (W) ↓</td><td align="right"><b>359,2</b></td><td align="right">428,9</td><td align="right"><b>524,0</b></td><td align="right">586,1</td></tr>
    <tr><td>2 – SAE ↓</td><td align="right"><b>0,348</b></td><td align="right">0,407</td><td align="right"><b>0,526</b></td><td align="right">0,557</td></tr>
    <tr><td>3+ – F1 ↑</td><td align="right"><b>0,649</b></td><td align="right">0,584</td><td align="right"><b>0,528</b></td><td align="right">0,448</td></tr>
    <tr><td>3+ – MAE (W) ↓</td><td align="right"><b>606,9</b></td><td align="right">690,1</td><td align="right"><b>761,2</b></td><td align="right">900,5</td></tr>
    <tr><td>3+ – SAE ↓</td><td align="right"><b>0,418</b></td><td align="right">1,025</td><td align="right">2,273</td><td align="right"><b>1,824</b></td></tr>
  </tbody>
</table>


**Nhận xét.**

- F1 không giảm khi nhiều thiết bị bật đồng thời. Ở hộ mới, F1 của 2Stage là 0,487, 0,530, 0,528
  với 1, 2, 3+ thiết bị bật; của baseline là 0,434, 0,499, 0,448. Tầng 3+ chỉ có 168 phút (hộ được
  train) và 1.008 phút (hộ mới) nên chưa đủ để kết luận.
- SAE tăng theo số thiết bị bật. Ở tầng 3+ của hộ mới, SAE của 2Stage (2,27) kém baseline (1,82).
- Điểm yếu của 2Stage nằm ở tầng 0: báo bật nhầm nhiều hơn, 12.700 so với 8.281 phút ở hộ được
  train và 91.092 so với 76.123 phút ở hộ mới, trên khoảng 3,0 và 18,0 triệu phút. Tuy vậy MAE ở
  tầng 0 vẫn thấp hơn (4,9 so với 6,9 W; 5,9 so với 10,5 W), vì baseline rò công suất nhỏ liên tục
  khi thiết bị tắt.

### 1.5. Theo mức tải điện tổng

Ngưỡng cố định cho mọi hộ. Ở [0, 500) W rất ít phút bật nên SAE không ổn định.

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>[0, 500) – F1 ↑</td><td align="right">0,022</td><td align="right"><b>0,023</b></td><td align="right"><b>0,019</b></td><td align="right">0,013</td></tr>
    <tr><td>[0, 500) – MAE (W) ↓</td><td align="right"><b>0,5</b></td><td align="right">2,9</td><td align="right"><b>0,6</b></td><td align="right">4,7</td></tr>
    <tr><td>[0, 500) – SAE ↓</td><td align="right"><b>3,136</b></td><td align="right">86,500</td><td align="right"><b>4,525</b></td><td align="right">115,832</td></tr>
    <tr><td>[500, 1500) – F1 ↑</td><td align="right"><b>0,370</b></td><td align="right">0,275</td><td align="right"><b>0,228</b></td><td align="right">0,161</td></tr>
    <tr><td>[500, 1500) – MAE (W) ↓</td><td align="right"><b>8,7</b></td><td align="right">15,6</td><td align="right"><b>10,0</b></td><td align="right">17,1</td></tr>
    <tr><td>[500, 1500) – SAE ↓</td><td align="right"><b>0,637</b></td><td align="right">1,101</td><td align="right"><b>0,883</b></td><td align="right">2,102</td></tr>
    <tr><td>[1500, 3000) – F1 ↑</td><td align="right"><b>0,625</b></td><td align="right">0,585</td><td align="right"><b>0,446</b></td><td align="right">0,408</td></tr>
    <tr><td>[1500, 3000) – MAE (W) ↓</td><td align="right"><b>96,0</b></td><td align="right">123,2</td><td align="right"><b>170,3</b></td><td align="right">197,0</td></tr>
    <tr><td>[1500, 3000) – SAE ↓</td><td align="right">0,349</td><td align="right"><b>0,327</b></td><td align="right"><b>0,885</b></td><td align="right">1,083</td></tr>
    <tr><td>[3000, inf) – F1 ↑</td><td align="right">0,530</td><td align="right"><b>0,572</b></td><td align="right"><b>0,417</b></td><td align="right">0,412</td></tr>
    <tr><td>[3000, inf) – MAE (W) ↓</td><td align="right"><b>217,7</b></td><td align="right">231,3</td><td align="right"><b>320,3</b></td><td align="right">367,3</td></tr>
    <tr><td>[3000, inf) – SAE ↓</td><td align="right">0,716</td><td align="right"><b>0,310</b></td><td align="right">1,049</td><td align="right"><b>0,853</b></td></tr>
  </tbody>
</table>


**Nhận xét.**

- 2Stage tốt hơn rõ ở [500, 1500) W (F1 0,370 so với 0,275 ở hộ được train; 0,228 so với 0,161 ở
  hộ mới) và [1500, 3000) W, nơi diễn ra phần lớn các lần bật.
- Khi điện tổng từ 3.000 W trở lên, ở hộ được train baseline có F1 cao hơn (0,572 so với 0,530) và
  SAE thấp hơn (0,310 so với 0,716): 2Stage hay gán thừa công suất khi tải tổng rất cao. Ở hộ mới
  hai mô hình ngang nhau (0,417 so với 0,412).
- Ở [0, 500) W hầu như không có phút bật, nên F1 khoảng 0,02 và SAE rất lớn do mẫu số nhỏ. MAE của
  2Stage ở tầng này chỉ 0,5–0,6 W so với 2,9–4,7 W của baseline, cho thấy mask loại bỏ rò công suất.

### 1.6. Phân tích lỗi

Tỷ lệ phút bỏ sót (FN) xảy ra khi không có thiết bị đích nào khác bật, và tỷ lệ phút báo nhầm (FP)
xảy ra khi có ít nhất một thiết bị đích khác đang bật. Bảng chi tiết theo từng bối cảnh: `error_analysis.csv`.

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="2">Hộ được train</th><th colspan="2">Hộ mới</th></tr>
    <tr><th>2Stage</th><th>Baseline</th><th>2Stage</th><th>Baseline</th></tr>
  </thead>
  <tbody>
    <tr><td>Dishwasher – FN khi không thiết bị khác bật (%)</td><td align="right">88,5</td><td align="right">89,1</td><td align="right">95,0</td><td align="right">93,4</td></tr>
    <tr><td>Dishwasher – FP khi thiết bị khác đang bật (%)</td><td align="right">31,6</td><td align="right">28,1</td><td align="right">36,6</td><td align="right">23,8</td></tr>
    <tr><td>Kettle – FN khi không thiết bị khác bật (%)</td><td align="right">88,2</td><td align="right">90,2</td><td align="right">91,2</td><td align="right">92,1</td></tr>
    <tr><td>Kettle – FP khi thiết bị khác đang bật (%)</td><td align="right">34,8</td><td align="right">42,1</td><td align="right">41,4</td><td align="right">32,6</td></tr>
    <tr><td>WashingMachine – FN khi không thiết bị khác bật (%)</td><td align="right">95,6</td><td align="right">95,9</td><td align="right">95,6</td><td align="right">94,7</td></tr>
    <tr><td>WashingMachine – FP khi thiết bị khác đang bật (%)</td><td align="right">51,6</td><td align="right">52,5</td><td align="right">56,3</td><td align="right">54,4</td></tr>
    <tr><td>Microwave – FN khi không thiết bị khác bật (%)</td><td align="right">88,2</td><td align="right">89,8</td><td align="right">86,1</td><td align="right">87,2</td></tr>
    <tr><td>Microwave – FP khi thiết bị khác đang bật (%)</td><td align="right">34,0</td><td align="right">58,1</td><td align="right">40,1</td><td align="right">55,5</td></tr>
  </tbody>
</table>


**Nhận xét.**

- 86–96% số phút bỏ sót xảy ra khi không có thiết bị đích nào khác bật, ở cả hai mô hình. Bỏ sót
  chủ yếu không do chồng tải mà do tín hiệu thiết bị yếu hoặc khác giữa các hộ.
- Hơn một nửa số phút báo nhầm WashingMachine (52–56%) trùng với lúc thiết bị đích khác đang bật:
  hai mô hình đều nhầm chu trình gia nhiệt giữa WashingMachine và Dishwasher.
- 2Stage giảm báo nhầm Microwave do chồng tải (34% so với 58% ở hộ được train; 40% so với 56% ở hộ
  mới), nhưng tăng với Dishwasher ở hộ mới (36,6% so với 23,8%).

### 1.7. Đồ thị dự đoán

Mỗi lượt chạy lưu đồ thị tại `<nhóm>/predictions/house_XX.png`: điện tổng, công suất thật từng
thiết bị, dự đoán ensemble và dải min–max giữa các seed, ở cửa sổ sai số lớn nhất và cửa sổ có
nhiều thiết bị bật nhất. Ví dụ mô hình train trên hộ 2, test trên hộ 3:

![2Stage: train hộ 2, test hộ 3](../training/runs/twostage_20261126_042442/house_02/predictions/house_03.png)

![Baseline: train hộ 2, test hộ 3](../training/runs/nilmformer_20261126_042452/house_02/predictions/house_03.png)

Hai đồ thị chọn cửa sổ theo sai số của từng mô hình nên không trùng thời điểm. Có thể thấy:

- **Baseline**: công suất dự đoán không về 0 khi thiết bị tắt (Microwave luôn khoảng 20–40 W, dải
  giữa các seed tới 160 W). Đây là nguồn của NEP > 1 và TECA âm. Dishwasher bị dự đoán thiếu nặng
  (khoảng 500 W so với 2.100 W thật).
- **2Stage**: dự đoán bằng 0 khi bộ phát hiện báo tắt và bám hình dạng Dishwasher tốt hơn, nhưng
  có đoạn gán chu trình Dishwasher sang WashingMachine (cửa sổ trái, phút 35–125), đúng lỗi nhầm
  lẫn ở mục 1.6. Dải min–max giữa các seed rộng, cho thấy ensemble cần thiết.

## Câu hỏi 2. Lợi ích và chi phí của cá nhân hóa

Ứng với yêu cầu 3: so NILM baseline, bản đề xuất và bản không cá nhân hóa trên cùng đầu vào.

**Thiết kế.** Với mỗi hộ test h, so hai cách triển khai trên cùng 20% thời gian cuối của hộ h:

- **Riêng (cá nhân hóa):** mô hình chỉ train trên dữ liệu đo riêng từng thiết bị của chính hộ h.
- **Chung (không cá nhân hóa):** một mô hình train trên các hộ 6, 9, 11, 20, dùng cho mọi hộ.

Hai nhóm hộ trả lời hai câu hỏi khác nhau. Với hộ đã có trong mô hình chung, câu hỏi là mô hình
riêng có tốt hơn mô hình chung đã học cả hộ đó không. Với hộ mới, câu hỏi là có đáng đo riêng từng
thiết bị tại hộ mới để train mô hình riêng, thay vì dùng ngay mô hình chung.

### 2.1. Độ chính xác

**Dự đoán bật/tắt**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="4">Hộ đã có trong mô hình chung (6, 9, 11, 20)</th><th colspan="4">Hộ mới với mô hình chung (2, 3, 13)</th></tr>
    <tr><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th></tr>
  </thead>
  <tbody>
    <tr><td>Precision ↑</td><td align="right">0,581</td><td align="right">0,627</td><td align="right">0,604</td><td align="right"><b>0,637</b></td><td align="right">0,453</td><td align="right"><b>0,471</b></td><td align="right"><b>0,471</b></td><td align="right">0,455</td></tr>
    <tr><td>Recall ↑</td><td align="right">0,701</td><td align="right"><b>0,732</b></td><td align="right">0,613</td><td align="right">0,587</td><td align="right">0,605</td><td align="right"><b>0,659</b></td><td align="right">0,526</td><td align="right">0,512</td></tr>
    <tr><td>F1 ↑</td><td align="right">0,623</td><td align="right"><b>0,664</b></td><td align="right">0,604</td><td align="right">0,588</td><td align="right">0,479</td><td align="right"><b>0,535</b></td><td align="right">0,480</td><td align="right">0,473</td></tr>
    <tr><td>Accuracy ↑</td><td align="right">0,9947</td><td align="right">0,9951</td><td align="right">0,9953</td><td align="right"><b>0,9954</b></td><td align="right">0,9870</td><td align="right">0,9881</td><td align="right"><b>0,9897</b></td><td align="right">0,9891</td></tr>
  </tbody>
</table>


**Dự đoán công suất**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="4">Hộ đã có trong mô hình chung (6, 9, 11, 20)</th><th colspan="4">Hộ mới với mô hình chung (2, 3, 13)</th></tr>
    <tr><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th></tr>
  </thead>
  <tbody>
    <tr><td>MAE (W) ↓</td><td align="right">6,7</td><td align="right"><b>6,3</b></td><td align="right">9,5</td><td align="right">8,4</td><td align="right">17,1</td><td align="right"><b>16,4</b></td><td align="right">22,7</td><td align="right">19,7</td></tr>
    <tr><td>RMSE (W) ↓</td><td align="right">69,5</td><td align="right"><b>68,8</b></td><td align="right">73,7</td><td align="right">70,6</td><td align="right">121,6</td><td align="right">125,3</td><td align="right"><b>119,8</b></td><td align="right">126,8</td></tr>
    <tr><td>NDE ↓</td><td align="right"><b>0,397</b></td><td align="right">0,439</td><td align="right">0,399</td><td align="right">0,406</td><td align="right">0,591</td><td align="right">0,691</td><td align="right"><b>0,565</b></td><td align="right">0,603</td></tr>
  </tbody>
</table>


**Dự đoán năng lượng**

<table>
  <thead>
    <tr><th rowspan="2">Chỉ số</th><th colspan="4">Hộ đã có trong mô hình chung (6, 9, 11, 20)</th><th colspan="4">Hộ mới với mô hình chung (2, 3, 13)</th></tr>
    <tr><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th><th>2Stage riêng</th><th>2Stage chung</th><th>Baseline riêng</th><th>Baseline chung</th></tr>
  </thead>
  <tbody>
    <tr><td>SAE ↓</td><td align="right">0,240</td><td align="right">0,250</td><td align="right"><b>0,164</b></td><td align="right">0,337</td><td align="right">0,422</td><td align="right">0,351</td><td align="right">0,381</td><td align="right"><b>0,198</b></td></tr>
    <tr><td>Sai số năng lượng (kWh) ↓</td><td align="right">2,91</td><td align="right">1,99</td><td align="right"><b>1,61</b></td><td align="right">2,97</td><td align="right">13,50</td><td align="right">8,01</td><td align="right">13,66</td><td align="right"><b>6,67</b></td></tr>
    <tr><td>NEP ↓</td><td align="right"><b>0,707</b></td><td align="right">0,795</td><td align="right">1,032</td><td align="right">1,038</td><td align="right"><b>0,927</b></td><td align="right">1,092</td><td align="right">1,443</td><td align="right">1,192</td></tr>
    <tr><td>TECA ↑</td><td align="right"><b>0,647</b></td><td align="right">0,603</td><td align="right">0,484</td><td align="right">0,481</td><td align="right"><b>0,537</b></td><td align="right">0,454</td><td align="right">0,279</td><td align="right">0,404</td></tr>
    <tr><td>MR ↑</td><td align="right">0,506</td><td align="right"><b>0,533</b></td><td align="right">0,405</td><td align="right">0,418</td><td align="right">0,356</td><td align="right"><b>0,391</b></td><td align="right">0,258</td><td align="right">0,308</td></tr>
  </tbody>
</table>


F1 theo từng hộ test của 2Stage:

| Hộ | 2 | 3 | 6 | 9 | 11 | 13 | 20 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Riêng | 0,476 | 0,482 | 0,622 | 0,579 | 0,530 | 0,480 | **0,715** |
| Chung | **0,578** | **0,514** | **0,722** | **0,609** | **0,573** | **0,513** | 0,708 |

**Nhận xét.**

- Với 2Stage, mô hình chung tốt hơn mô hình riêng về F1, Precision, Recall, MR, MAE và sai số
  năng lượng ở cả hai nhóm hộ, và có F1 cao hơn ở 6/7 hộ (17/26 cặp hộ × thiết bị). Mô hình riêng
  chỉ tốt hơn về NDE và NEP (cùng TECA), nhỉnh hơn về SAE ở hộ đã có và RMSE ở hộ mới. Theo thiết bị, mô hình chung hơn ở Dishwasher (0,827 so với 0,756),
  Microwave (0,346 so với 0,251) và Kettle (0,745 so với 0,723); WashingMachine bằng nhau (0,520).
- Ở hộ mới với mô hình chung (2, 3, 13), 2Stage chung chưa từng thấy hộ vẫn đạt F1 0,535, cao hơn
  mô hình riêng train trên chính hộ đó (0,479). Dữ liệu nhiều hộ quan trọng hơn dữ liệu của chính hộ.
- Với baseline, mô hình riêng nhỉnh hơn về F1 ở hộ đã có (0,604 so với 0,588), gần bằng ở hộ mới
  (0,480 so với 0,473), nhưng MAE kém hơn.
- 2Stage chung là cấu hình tốt nhất về F1, Recall và MR ở cả hai nhóm hộ. Điểm yếu: ở hộ mới, SAE
  (0,351 so với 0,198) và NDE (0,691 so với 0,603) kém baseline chung vì dự đoán thừa năng lượng.

### 2.2. Chi phí huấn luyện và dữ liệu

| Cấu hình | Số mô hình cần train | Dữ liệu đo riêng từng thiết bị tại hộ dùng | Epoch đã chạy (trung vị) | Thời gian train 5 seed (s) |
| --- | ---: | --- | ---: | ---: |
| 2Stage riêng | 1 mỗi hộ | khoảng 333 ngày (trung bình) | 150 | 1 190 |
| 2Stage chung | 1 cho mọi hộ | không cần | 118 | 3 974 |
| Baseline riêng | 1 mỗi hộ | khoảng 333 ngày (trung bình) | 34 | 238 |
| Baseline chung | 1 cho mọi hộ | không cần | 44 | 1 039 |

- Thời gian đo trên GPU NVIDIA L40S dùng chung, 1 luồng CPU, chưa tính bước đánh giá.
- Cấu hình riêng: thời gian là trung bình mỗi hộ. Ngoài đồng hồ tổng, cần thêm thiết bị đo cho
  từng thiết bị đích (4 ổ cắm đo) trong thời gian thu dữ liệu train ở mỗi hộ. Số ngày tính từ số
  cửa sổ train và validation hợp lệ, chưa tính các đoạn mất dữ liệu.
- Cấu hình chung: tại hộ mới chỉ cần đồng hồ tổng; chi phí train trả một lần cho mọi hộ.
- 2Stage chung tốn khoảng 66 phút GPU một lần cho mọi hộ. Cá nhân hóa 2Stage cho 7 hộ tốn tổng
  khoảng 8.300 s (khoảng 2,3 giờ), cộng chi phí đo riêng 4 thiết bị khoảng 333 ngày ở mỗi hộ.
  Baseline riêng train nhanh vì dừng sớm.
- Chưa ước tính chi phí theo đơn giá GPU và chưa có cấu hình Docker.

### 2.3. Độ trễ suy luận

Đo một checkpoint (một seed) của mô hình chung, trung bình 50 lần chạy sau khi khởi động.
Một ngày dữ liệu là 12 cửa sổ 128 phút đưa vào cùng một batch.

| Mô hình | Số tham số | CPU 1 luồng, 1 cửa sổ | CPU 1 luồng, 1 ngày | GPU L40S, 1 ngày |
| --- | ---: | ---: | ---: | ---: |
| 2Stage | 509 466 | 13,3 ms | 48,1 ms | 3,0 ms |
| Baseline | 384 150 | 3,8 ms | 39,6 ms | 2,3 ms |

- Ensemble 5 seed nhân thời gian lên 5 lần: khoảng 0,24 s cho một ngày dữ liệu của 2Stage trên
  một luồng CPU. Mô hình nhỏ (khoảng 2 MB trọng số float32), nên triển khai không cần GPU.
- GPU dùng chung với tiến trình khác khi đo, nên số liệu GPU chỉ là xấp xỉ.
- 2Stage chậm hơn baseline với một cửa sổ (13,3 so với 3,8 ms), nhiều khả năng do GRU chạy tuần tự,
  nhưng chênh lệch nhỏ khi xử lý theo batch.

**Kết luận câu hỏi 2.** Không cần cá nhân hóa: mô hình chung của phương pháp đề xuất cho F1 cao
hơn mô hình riêng, chỉ cần đồng hồ tổng tại hộ dùng và chạy được trên CPU. Chi phí chính là
một lần train trên GPU.

## Giới hạn

- **Ngân sách epoch khác nhau.** Baseline dừng sớm (epoch 19–54). Ở 6/7 mô hình một hộ, phần lớn
  seed của 2Stage chạy đủ 150 epoch với epoch tốt nhất 145–150, tức chưa hội tụ. Cần chạy lại cả
  hai với cùng cấu hình, ví dụ tối đa 300 epoch và patience 20, để xác nhận độ lớn chênh lệch.
- **F1 bị chặn trên.** F1 so trạng thái dự đoán (công suất trung bình phút ≥ ngưỡng) với nhãn tạo ở
  nhịp 10 giây. Kể cả dự đoán đúng hoàn toàn công suất, F1 tối đa chỉ khoảng 0,92 (WashingMachine,
  Kettle) đến 0,95 (Microwave). Cách tính này có thể có lợi cho mô hình báo bật nhiều như 2Stage.
- **Baseline khác bài gốc.** NILMFormer ở đây là một mô hình 4 đầu ra; bài gốc train mỗi thiết bị
  một mô hình, chia ngẫu nhiên 2 hộ test và 1 hộ validation, tối đa 50 epoch.
- Mô hình chung chỉ có một cách chia hộ; kết quả hộ mới của nó dựa trên 3 hộ.
- Kiểm định thống kê coi các cặp (hộ train, hộ test) là độc lập, trong khi chúng có chung hộ.
- Chưa đánh giá loại thiết bị chưa thấy và bản không trợ lý; chưa có demo Docker.

## Kết luận

1. Phương pháp đề xuất 2Stage cải thiện hiệu năng ở hộ mới so với NILMFormer: F1 tăng 0,04, MAE
   giảm 27%, NEP giảm từ 1,94 xuống 1,28, nhờ bộ phát hiện bật/tắt và mask đưa công suất về 0 khi
   thiết bị tắt. Cải thiện tập trung ở Dishwasher và Kettle.
2. Hiệu năng vẫn suy giảm mạnh khi sang hộ mới, và Microwave chưa giải quyết được ở cả hai mô hình.
3. Cá nhân hóa không mang lại lợi ích: mô hình chung 2Stage tốt hơn mô hình riêng của từng hộ, rẻ
   hơn khi triển khai và chạy được trên CPU.
