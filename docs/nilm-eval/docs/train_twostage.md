# Chạy thực nghiệm TwoStageNILMFormer và baseline NILMFormer

Từ thư mục gốc project:

```bash
# TwoStageNILMFormer
uv run python -m training.train_twostage_nilmformer
# Baseline NILMFormer gốc, cùng hộ, cùng cách chia và cùng hàm đánh giá
uv run python -m training.train_twostage_nilmformer --model nilmformer
```

Hai lệnh dùng chung toàn bộ quy trình; chỉ kiến trúc và loss khác nhau. Baseline
chỉ có loss MSE hồi quy, không có detector nên không có cột `detector_*`; các tham
số `--max-positive-weight` và `--auxiliary-on-weight` chỉ dùng cho twostage.
Khi test, dự đoán của mọi mô hình được chặn âm về 0 trước khi tính metrics; với
TwoStage phép này không đổi gì vì đầu ra luôn không âm.

Runner mặc định đọc CSV từ `data/processed/REFIT/temporal_7aea0ef86866`, dùng
7 hộ đủ bốn thiết bị (2, 3, 6, 9, 11, 13, 20), 5 seed và hai nhánh
pooled/cross_house, tổng cộng **40 lượt train**. Nhánh cross_house train riêng
từng hộ rồi test trên cả 7 hộ; nhánh pooled train trên 4 hộ 6, 9, 11, 20 và
test trên cả 7 hộ, trong đó 2, 3, 13 là hộ chưa thấy; xem `docs/study_design.md`.
Mặc định dùng CUDA và báo lỗi nếu CUDA không khả dụng; không tự chuyển sang CPU.
Có thể đặt rõ `--device cpu` để chạy kiểm tra trên CPU.
PyTorch mặc định chỉ dùng 1 luồng CPU (`--cpu-threads 1`). Phần CPU chỉ đọc batch
và cộng metrics trên tensor nhỏ; để mặc định nhiều luồng trên máy đang tải nặng
làm mỗi batch chậm hàng trăm lần (đo được 1020 ms so với 6 ms cho bước metrics).
Đầu ra mặc định là thư mục `training/runs/<model>_<thời điểm>/`.

Mỗi mô hình × seed dùng đúng một đối tượng tqdm. Thanh được reset và tái sử dụng
theo từng epoch, tăng sau mỗi batch train/validation; postfix hiển thị epoch,
pha, batch và loss đang chạy. Phần trăm và ETA trên thanh áp dụng cho epoch hiện
tại. Cuối epoch hiển thị loss/metrics tổng hợp và trạng thái early stopping.

```bash
uv run python -m training.train_twostage_nilmformer \
    --data-dir data/processed/REFIT/temporal_7aea0ef86866 \
    --output-dir training/runs/twostage_full \
    --epochs 150 --patience 10 --num-seeds 5 --batch-size 64
```

Có thể chọn một nhóm hộ bằng `--houses 2 3 6` hoặc chỉ một nhánh bằng
`--protocols pooled` / `--protocols cross_house`. Mọi hộ được chọn phải có nhãn
train hợp lệ cho đủ bốn thiết bị. Thư mục kết quả phải là thư mục
chưa có study.json, tránh ghi đè kết quả đã chạy.

## Validation và mất cân bằng nhãn

Giữ nguyên 20% cuối làm test. Lấy 20% thời gian cuối bên trong phần train gốc
làm validation, xấp xỉ tỷ lệ toàn kỳ 64/16/20. Cấu hình bằng
`--validation-fraction 0.2`; mốc được chọn trước khi biết nhãn test. Cửa sổ cắt
ngang train/validation bị loại. Lưu mốc và số cửa sổ trong validation_split.csv.

Early stopping theo validation loss với tối đa 150 epoch, patience 10, min_delta 0
mặc định. Mức 150 được nâng từ 50 vì lần chạy đầu của TwoStage pooled vẫn đang
cải thiện validation ở epoch 50 và chưa lần nào dừng sớm.
best.pt ghi mọi cải thiện validation tuyệt đối; last.pt ghi trạng thái epoch
cuối. Nạp lại best.pt trước test. Tập test không được dùng cho early stopping.

Trọng số BCE lớp bật tính riêng từng thiết bị từ các nhãn train hợp lệ:
`(off_count + 1)/(on_count + 1)`, chặn `[0.01, 5]` mặc định. Đổi giới hạn trên
bằng `--max-positive-weight`. Với tỷ lệ bật dưới 1%, công thức cho giá trị khoảng
94–236 nên trên thực tế mọi thiết bị đều dùng đúng giới hạn 5. Kênh không có mẫu bật dùng trọng số 1 và lưu cờ
has_positive_train_labels=False; kênh thiếu nhãn không đóng góp vào thống kê.
Không dùng một tỷ lệ bật/tắt chung cho mọi thiết bị hoặc mọi mô hình riêng.
Giới hạn và trọng số các loss có thể cần hiệu chỉnh trên validation.

Với tỷ lệ bật khoảng 0,4–1%, mức chặn 100 làm detector thiên về đoán bật: lần
chạy đầu có recall detector 0,83–0,99 nhưng precision chỉ 0,02–0,47 và điện năng
bị ước tính dư ở mọi cặp hộ × thiết bị. Chọn `--max-positive-weight` trên
validation trước khi chạy đủ 40 lượt, chỉ dùng nhánh pooled và một seed:

```bash
for w in 5 10 30 100; do
  uv run python -m training.train_twostage_nilmformer --model twostage \
      --protocols pooled --num-seeds 1 --max-positive-weight $w \
      --output-dir training/runs/sweep_pw_$w
done
# So sánh metrics validation tại epoch được chọn; không nhìn các cột test.
uv run python -c "import pandas as pd; [print(w, pd.read_csv(f'training/runs/sweep_pw_{w}/seed_test_metrics.csv').filter(like='_at_best').iloc[0].round(3).to_dict()) for w in (5, 10, 30, 100)]"
```

Không so validation loss giữa các mức trọng số vì BCE có trọng số khác nhau thì
thang loss khác nhau; so F1, precision, recall và MAE validation.

Kết quả đã chạy (TwoStage, nhánh pooled, seed 478163327, metrics validation macro
theo thiết bị tại epoch được chọn). **Chốt mức 5 làm mặc định.**

| Giới hạn w | Epoch chọn/dừng | F1 | Precision | Recall | MAE (W) | SAE |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 111/121 | 0,666 | 0,627 | 0,717 | 6,9 | 0,07 |
| 10 | 111/121 | 0,658 | 0,593 | 0,759 | 7,7 | 0,19 |
| 30 | 128/138 | 0,617 | 0,531 | 0,770 | 9,1 | 0,34 |

Thứ tự 5 > 10 > 30 giữ ở cả bốn thiết bị. Trọng số lớn hơn tăng recall nhưng giảm
precision và làm điện năng bị ước tính dư nhiều hơn. Mức dưới 5 chưa được thử.

## Đầu ra

- study.json: dữ liệu nguồn, hash manifest, danh sách hộ, seed và tham số chạy.
- validation_split.csv: ranh giới train/validation và số cửa sổ từng hộ.
- `pooled/seed_<seed>/` và `house_<id>/seed_<seed>/`: best.pt, last.pt (chỉ
  twostage), class_balance.csv, history.json, epoch_metrics.csv,
  training_curves.png, training_curves.svg và test_metrics.csv của riêng seed đó.

**Kết quả báo cáo là ensemble 5 seed.** Mỗi mô hình (kiến trúc × nhánh × hộ
train) được train lại với 5 seed khởi tạo. Trên mỗi hộ test, công suất dự đoán
của 5 seed được lấy trung bình cộng theo từng phút và từng thiết bị thành **một**
dự đoán; mọi metrics, phân tầng, bảng lỗi và đồ thị tính một lần trên dự đoán
này. F1 dùng trạng thái suy ra từ công suất ensemble với ngưỡng thiết bị, không
lấy trung bình F1 của các seed. Mask detector của TwoStage là 0/1 nên ensemble
bằng bỏ phiếu: bật khi ít nhất một nửa số seed bật; detector_f1 tính trên mask đó.

- test_metrics.csv: **kết quả ensemble** theo mô hình × protocol × hộ train × hộ
  test × thiết bị (ma trận chuyển giao với cross_house). Cột `train_houses` ghi các
  hộ dùng để train; `unseen_house=True` là hộ test chưa có trong train;
  `best_epochs`, `epochs_trained` liệt kê theo seed; `train_seconds_total` cộng
  thời gian train của mọi seed.
- seed_test_metrics.csv: metrics của từng seed riêng lẻ, có cột `model_seed`; chỉ
  dùng để truy vết và xem độ phân tán giữa các seed, không phải kết quả báo cáo.
  Các cột `val_*_at_best` là metrics validation macro theo thiết bị tại epoch được
  chọn, dùng để chọn siêu tham số.
- macro_summary.csv: **bảng chính**. Macro kết quả ensemble theo các cặp hộ, tách
  hộ đã thấy và hộ chưa thấy; `_median` là trung vị, `_std` là độ lệch giữa các
  cặp hộ, `_count` là số cặp hộ có giá trị.
- low_support_pairs.csv: các cặp hộ × thiết bị có dưới 60 phút bật trong test
  (cột `low_support=True` trong test_metrics.csv). Với số phút bật quá ít, F1 và
  sai số điện năng tương đối không ổn định (ví dụ máy rửa bát hộ 11 chỉ bật 4 phút
  trong test), nên các cặp này bị loại khỏi macro, phân tầng và bảng lỗi tổng hợp
  nhưng vẫn giữ trong các bảng chi tiết.
- stratified_metrics.csv và stratified_summary.csv: metrics ensemble theo số thiết
  bị bật đồng thời (`stratum_type=concurrent_on`) và mức tải điện tổng
  (`stratum_type=load_w`), rồi macro theo cặp hộ. Tầng rỗng có valid_count=0 và
  NaN, không được tính vào trung bình.
- error_analysis.csv và error_summary.csv: số điểm FP/FN của dự đoán ensemble theo
  thiết bị đích khác đang bật; bảng tổng cộng số điểm trên các cặp hộ rồi mới chia.
- `<nhóm>/predictions/house_<id>.png`: điện tổng và từng thiết bị, thực tế so với
  dự đoán ensemble, kèm dải min–max giữa các seed, trên cửa sổ sai số lớn nhất và
  cửa sổ có nhiều thiết bị bật nhất.

Định nghĩa các tầng và bảng lỗi nằm trong `docs/study_design.md`.

Metrics công suất/điện năng dùng đơn vị W/kWh sau hoàn nguyên normalize.
F1 chính so công suất cuối với ngưỡng thiết bị; detector_f1 đánh giá riêng mask.
Nhãn bật/tắt thực tế giữ nguyên quy tắc tạo trước resample của pipeline; đây
là F1 theo mẫu phút, không phải F1 ghép sự kiện. Kênh không có nhãn được ghi
evaluated=False và score NaN. Không đổi NaN thành 0 khi tổng hợp.

Checkpoint TwoStage lưu cấu hình hai nhánh, trọng số BCE, seed, optimizer và lịch sử;
checkpoint baseline lưu cấu hình NILMFormer, seed, optimizer, best_epoch và metrics epoch.
last.pt là bản lưu trạng thái, chưa có chức năng resume hoàn chỉnh qua CLI.

## Đồ thị và metrics trong quá trình train

Sau mỗi lượt model × seed, runner lưu line plot gồm sáu ô: loss tổng, MAE,
RMSE, F1, precision và recall. Mỗi ô có đường train/validation và vạch đánh dấu
epoch validation tốt nhất. Đồ thị lưu PNG và SVG để xem hoặc đưa vào báo cáo.

Mỗi epoch lưu cả metrics từng thiết bị và macro theo các thiết bị có nhãn hợp
lệ vào history.json và epoch_metrics.csv, gồm thêm NDE, SAE, MR và sai số điện
năng. Metrics dùng công suất đã hoàn nguyên W và nhãn bật/tắt cuối pipeline.
Không dùng test để vẽ đường theo epoch hoặc chọn mô hình.

Các tổng sai số và TP/FP/FN/TN được cộng trên toàn epoch trước khi chia; không
lấy trung bình F1/SAE từng batch. Chỉ số macro trên hình lấy trung bình các
thiết bị hợp lệ, không phải macro theo hộ; bảng test cuối vẫn báo riêng từng hộ.
Train metrics là thống kê dự đoán trong quá trình cập nhật trọng số, với dropout
và mask straight-through bật. Validation metrics dùng eval và mask cứng. Vì vậy
hai đường không phải hai phép đánh giá cùng một trạng thái trọng số cuối epoch.

## Chạy thử kết nối

```bash
uv run python -m training.train_twostage_nilmformer --smoke-test --device cpu
uv run python -m training.train_twostage_nilmformer --model nilmformer --smoke-test --device cpu
```

Chế độ này chỉ dùng tối đa hai hộ, một seed, một epoch, hai cửa sổ/tập và mô hình
nhỏ. Kết quả có smoke_test=True, không dùng làm benchmark và không được trộn
với kết quả 40 lượt train đầy đủ. Xem `--help` để biết các tham số còn lại.
