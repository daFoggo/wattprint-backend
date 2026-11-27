# Các chỉ số đánh giá NILM

File triển khai: `training/metrics.py`. Bộ chỉ số phục vụ ba mục tiêu: dự đoán
công suất, ước tính điện năng và phát hiện trạng thái bật/tắt. Không nên kết luận
chất lượng mô hình từ một chỉ số duy nhất.

## Công suất

Ký hiệu `y` là công suất thực tế, `p` là công suất dự đoán, `N` là số điểm hợp lệ.
Các tổng dưới đây chỉ lấy trên cùng các điểm hợp lệ. Công suất phải được đổi về W
trước khi đánh giá. Các công thức được đối chiếu với
[mã metrics NILMFormer](https://github.com/EDF-Lab/NILMFormer/blob/main/src/helpers/metrics.py)
và [tài liệu NILMTK](https://nilmtk.github.io/nilmtk/master/nilmtk.html#module-nilmtk.metrics).

| Khóa | Công thức | Diễn giải |
| --- | --- | --- |
| `mae_w` | `sum(abs(p-y))/N` | Sai số tuyệt đối trung bình, W; càng thấp càng tốt |
| `mse_w2` | `sum((p-y)^2)/N` | Sai số bình phương trung bình, W² |
| `rmse_w` | `sqrt(MSE)` | Nhạy với lỗi công suất lớn, W |
| `nde` | `sum((p-y)^2)/sum(y^2)` | Sai số phân rã chuẩn hóa; không lấy căn |
| `sae` | `abs(sum(p)-sum(y))/sum(y)` | Sai số tổng tín hiệu; tương đương sai số điện năng tương đối khi thời lượng mẫu bằng nhau |
| `nep` | `sum(abs(p-y))/sum(y)` | Sai số tuyệt đối chuẩn hóa theo tổng công suất thực tế |
| `teca` | `1-sum(abs(p-y))/(2*sum(y))` | Điểm gán đúng điện năng theo công thức trong mã NILMFormer; có thể âm |
| `mr` | `sum(min(p,y))/sum(max(p,y))` | Matching Rate; càng lớn càng tốt, dùng với công suất không âm |

SAE có thể bằng 0 khi dự đoán thừa và thiếu triệt tiêu nhau, dù MAE vẫn lớn.
Do đó báo cáo chính nên dùng MAE/RMSE cùng sai số điện năng và F1. NDE, NEP,
TECA, MR là các chỉ số bổ sung, hữu ích khi đối chiếu các nghiên cứu.
Không dùng MAPE làm chỉ số chính vì thiết bị thường có công suất thực tế bằng 0.

`power_metrics` không tự chặn dự đoán âm. MR trả NaN nếu có dự đoán âm trên
các điểm hợp lệ; các chỉ số sai số khác vẫn đánh giá đầu ra nguyên bản.
Nếu muốn so sánh hậu xử lý chặn âm, cần áp dụng và ghi rõ cùng một quy tắc cho các mô hình.

## Điện năng

`energy_metrics` nhận `sample_duration_s` là số giây cố định hoặc tensor cùng
shape với công suất. Mỗi giá trị công suất đại diện cho khoảng thời gian tương ứng:
`E = sum(P * duration) / 3.600.000`, với P tính bằng W và E tính bằng kWh.

| Khóa | Ý nghĩa |
| --- | --- |
| `predicted_energy_kwh`, `target_energy_kwh` | Điện năng dự đoán và thực tế trên các khoảng được đánh giá |
| `energy_bias_kwh` | Điện năng dự đoán trừ thực tế; giữ dấu thừa/thiếu |
| `energy_error_kwh` | Giá trị tuyệt đối của sai lệch điện năng |
| `relative_energy_error` | Sai số điện năng tuyệt đối chia điện năng thực tế; giá trị tỷ lệ, không nhân 100 |

Không mặc định lấy mẫu REFIT luôn đều 8 giây hoặc PLEGMA luôn đủ 10 giây.
Với chuỗi không đều, pipeline phải xác định thời lượng đại diện của từng mẫu,
loại các khoảng mất dữ liệu và xử lý ranh giới đoạn. Thời lượng 0 loại một mẫu
khỏi tích phân; không tự kéo dài công suất qua khoảng mất dữ liệu.
Các hàm không tự suy thời lượng từ timestamp. Điện năng báo cáo chỉ đại diện
phần thời gian có nhãn hợp lệ, không tự suy rộng sang cả kỳ theo dõi.

## Bật/tắt

`state_metrics` nhận trạng thái nhị phân, không nhận trực tiếp logits hoặc xác suất.
TP là bật đúng, FP là bật nhầm, FN là tắt nhầm, TN là tắt đúng.

| Khóa | Công thức |
| --- | --- |
| `precision` | `TP/(TP+FP)` |
| `recall` | `TP/(TP+FN)` |
| `f1` | `2*TP/(2*TP+FP+FN)` |
| `accuracy` | `(TP+TN)/(TP+FP+FN+TN)` |
| `false_negative_rate` | `FN/(TP+FN)` |

Các chỉ số này tính theo từng mẫu thời gian, không ghép sự kiện bật/tắt theo chu kỳ.
Accuracy dễ cao khi thiết bị hầu hết thời gian tắt; ưu tiên F1, precision và recall.
FNR giúp phân tích vấn đề detector tắt nhầm. Các số đếm TP/FP/FN/TN và số mẫu bật
được trả kèm để thấy mức mất cân bằng nhãn.

Khi có dữ liệu nhưng mẫu số precision/recall/F1 bằng 0, quy ước trả 0.
FNR không có mẫu thực sự bật trả NaN. Khi không có điểm hợp lệ, các điểm số trả NaN.
Không coi một kênh toàn tắt là F1 bằng 1.

Để so công bằng hai mô hình, đánh giá trạng thái suy ra từ **công suất cuối cùng**
theo cùng ngưỡng thiết bị và quy tắc thời lượng bật/tắt tối thiểu. Đánh giá riêng
mask detector bằng `state_metrics` là một phân tích bổ sung. Nhãn có sẵn trong
dataset được ưu tiên; không mặc định mọi thiết bị dùng chung ngưỡng 0 W.
Hàm metrics không tự thực hiện lọc thời lượng tối thiểu hoặc chọn ngưỡng.

## Dữ liệu thiếu, tổng hợp và phân nhóm

- Dùng `valid` boolean cùng shape với nhãn để loại mẫu lỗi và chọn nhóm tải,
  số thiết bị bật đồng thời hoặc các trường hợp cần phân tích.
- NaN/Inf trong nhãn được loại; dự đoán không hữu hạn tại nhãn hợp lệ gây lỗi,
  không bị thay bằng 0 hoặc loại âm thầm. Mẫu số chuẩn hóa bằng 0 trả NaN.
- `valid_count`, `total_count`, `coverage` phản ánh độ phủ nhãn công suất;
  `energy_valid_count` và `state_valid_count` phản ánh số điểm dùng cho từng nhóm chỉ số.
- Các hàm gom mọi trục của đầu vào. Cắt theo hộ và thiết bị trước khi gọi để lập
  bảng tương ứng. Trục B trong `(B, C, L)` là batch/cửa sổ, không mặc định là hộ.
- `compute_nilm_metrics` gộp ba nhóm; chỉ tính điện năng khi truyền thời lượng,
  chỉ tính bật/tắt khi truyền đủ hai tensor trạng thái. Bật/tắt kết hợp dùng giao
  giữa các nhãn công suất và trạng thái hợp lệ; hàm riêng có thể đánh giá độc lập.
- Không lấy trung bình F1 hoặc SAE theo batch. Ghép các dự đoán và nhãn của cùng
  phạm vi đánh giá rồi tính một lần; có thể cộng TP/FP/FN/TN trước khi tính F1.
- Với cửa sổ chồng lấn, phải gộp các dự đoán về mỗi timestamp trước khi đánh giá
  để không đếm lặp điện năng. Các hàm này không quản lý timestamp hoặc window overlap.
- Khi báo trung bình theo hộ/thiết bị, nêu rõ macro (mỗi nhóm một trọng số)
  hay gộp điểm dữ liệu. Nêu riêng số nhóm không xác định, không âm thầm đổi NaN thành 0.

```python
from training.metrics import compute_nilm_metrics

# Sau khi đổi về W và gộp cửa sổ; chỉ chọn một hộ và một thiết bị.
# predicted_w, target_w, valid có shape (L,) trong ví dụ này.
result = compute_nilm_metrics(
    predicted_w, target_w, valid,
    sample_duration_s=duration_s,
    predicted_on=predicted_state,
    target_on=target_state,
)
```

Đây là công cụ đánh giá, không phải loss khả vi: tensor được detach và chuyển
sang float64 trên CPU. `NILMMetricAccumulator` đã được tích hợp vào runner
TwoStage để ghi metrics từng epoch bằng các tổng và số đếm theo thiết bị, không
giữ toàn bộ dự đoán trong RAM. Runner dùng chung công thức với các hàm đánh giá
riêng; chỉ số trên hình là macro theo thiết bị có nhãn hợp lệ. Chưa có kết quả
benchmark đầy đủ trên REFIT/PLEGMA. AUROC/PR-AUC và chỉ số theo sự kiện có thể bổ sung
khi có quy trình đánh giá xác suất và nhãn sự kiện rõ ràng.
