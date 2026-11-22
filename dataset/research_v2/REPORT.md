# Nghiên cứu tối ưu hai nhánh NILM trên hộ chưa thấy

## Kết luận thực nghiệm

Đã thử thay backbone của **cả detector ON/OFF và regressor công suất** bằng
hai residual TCN riêng, giữ công thức dự đoán `P(ON) × conditional watts`.
Thí nghiệm có bốn fold leave-one-house-out (LOHO) thực sự trên REFIT Houses
2, 3, 5, 6, hai seed 11/22 mỗi fold, validation theo hộ nguồn và cùng 128 cửa
sổ test/hộ với baseline v1. TCN v2.1 tốt hơn TCN v2.0 thử đầu, nhưng **chưa
vượt bundle GRUDetector + NILMFormerRegressor production**. Không thay
bundle production bằng checkpoint TCN trong nghiên cứu này.

Hiệu chỉnh nhẹ hai nhánh production ở v2.2 là hướng có tín hiệu: giữ nguyên
weights, chọn lại ngưỡng ON của detector và hệ số công suất của regressor bằng
hộ nguồn còn lại. Trên House 3/6 chưa thấy, sai số kWh trung bình 22 cặp
nguồn–hộ–thiết bị giảm **0.745 → 0.634 kWh** (−15.0%), còn macro F1 gần như
ngang **0.418 → 0.415**. Khoảng tin cậy bootstrap ghép cặp 95% cho chênh
lệch sai số là **[−0.243, +0.005] kWh**, vẫn chạm 0. Đây là cải thiện thăm
dò, chưa đủ chắc để khuyến nghị triển khai chung.

## Cơ sở và thiết kế

[Subtask Gated Networks](https://arxiv.org/abs/1811.06692) là cơ sở cho
hai mô hình phân loại trạng thái và hồi quy công suất kết hợp bằng soft gate.
[NILMFormer](https://arxiv.org/abs/2506.05880) chỉ ra drift bên trong cửa sổ;
TCN dùng aggregate, đạo hàm từng bước và aggregate trừ median cửa sổ để
giảm lệ thuộc mức nền. [Nghiên cứu về chuyển hộ](https://arxiv.org/abs/1912.06200)
ủng hộ đánh giá trên tòa nhà chưa thấy, thay vì suy ra tổng quát hóa từ chia
thời gian trong cùng nhà. v2.1 còn thử tái tổ hợp residual background giữ
nguyên nhãn thiết bị theo [Liu & Fan 2026](https://arxiv.org/abs/2609.18315).
Đây là động cơ thiết kế, không phải bằng chứng rằng từng thành phần đã gây ra
cải thiện trong thí nghiệm REFIT này.

Mỗi TCN có 84,966 tham số, sáu block dilation 1–32, receptive field 253/256
mẫu. Detector xuất logits `(B,6,256)`; regressor xuất công suất ON chuẩn hóa
cùng shape. Loss gồm BCE có class weight, Huber công suất, sai số soft-gated
và sai số năng lượng cửa sổ. v2.1 dùng validation đều theo thời gian nguồn,
phạt công suất OFF, hiệu chỉnh kWh bằng nguồn validation và tái tổ hợp nền
chỉ trong train. [Mã kiến trúc](architecture.py), [trainer v2.0](run.py),
[trainer v2.1](run_v21.py), [protocol chi tiết](RESEARCH.md).

Hộ test không tham gia fit, threshold, epoch, scaling hoặc hậu xử lý. Trong
ba hộ nguồn, một hộ có Fridge được giữ làm inner grouped validation; hai hộ
còn lại dùng để chọn epoch, sau đó hai seed được train lại trên cả ba hộ nguồn.
House 6 có Freezer thay vì Fridge; head Fridge bị mask trong train House 6 và
không chấm Fridge hay Freezer ở fold House 6. Không có head unknown/Other.

## TCN LOHO so với bundle nguồn đã đóng băng

F1 là macro ON/OFF, kWh là trung bình sai số năng lượng tuyệt đối theo thiết
bị. Bundle tham chiếu chỉ dùng khi hộ nguồn khác hộ test; vì bundle production
được train trên một hộ còn TCN train trên ba hộ, so sánh đo hiệu quả hệ thống,
không cô lập tác động của backbone. Các giá trị từng hộ–thiết bị, true/pred
kWh, sai số có dấu và số lần bật nằm trong [paired_metrics.csv](paired_metrics.csv)
và [v2.1 evaluation](v2_1/evaluation/).

| Hộ test | Bundle nguồn | F1 baseline → TCN v2.1 | Sai số kWh baseline → TCN v2.1 |
|---|---:|---:|---:|
| 2 | 5 | 0.395 → 0.282 | 2.173 → 2.780 |
| 3 | 2 | 0.445 → 0.320 | 0.435 → 2.097 |
| 3 | 5 | 0.319 → 0.320 | 1.564 → 2.097 |
| 5 | 2 | 0.455 → 0.365 | 0.896 → 2.102 |
| 6 | 2 | 0.477 → 0.369 | 0.620 → 0.862 |
| 6 | 5 | 0.446 → 0.369 | 0.260 → 0.862 |

Trên 34 cặp có thể so sánh, macro F1 baseline → v2.0 → v2.1 là
**0.421 → 0.218 → 0.335**; sai số kWh là **1.024 → 2.324 → 1.855**.
v2.1 cải thiện so với v2.0, nhưng còn kém baseline. Hộ 3 có khoảng tin cậy
bootstrap ghép cặp 95% cho v2.1−v2.0: F1 **[+0.060,+0.133]**, sai số kWh
**[−1.252,−0.155]**; hộ 6 F1 **[+0.176,+0.328]**. Đây là bước lặp thăm dò:
thiết kế v2.1 đã được sửa sau khi xem lỗi v2.0, chưa phải xác nhận trên tập
hộ độc lập mới. [Kết quả bootstrap v2.0→v2.1](v2_1/paired_vs_v20.json).

Theo từng thiết bị trên các cặp cross-house, F1 baseline→v2.1:
Fridge 0.580→0.615, WashMach 0.249→0.253, Dishwash 0.209→0.232,
Microwave 0.198→0.179, Toaster 0.564→0.123, Kettle 0.777→0.704.
Sai số kWh Microwave giảm 1.760→0.708, nhưng Kettle tăng 0.148→2.207.
Do đó một metric riêng không đủ để gọi v2.1 là cải thiện.

### Mức tải và thiết bị bật đồng thời

Bảng gộp các cặp cross-house được chấm ở cùng cửa sổ; một số hộ test xuất
hiện dưới hai bundle nguồn. N là số mẫu 15 giây, tính một lần theo cặp
nguồn–hộ–tầng, không cộng lặp theo thiết bị. Bảng đủ per device có ở
[paired_strata.csv](paired_strata.csv).

| Tầng | N | F1 baseline → v2.1 | Sai số kWh baseline → v2.1 |
|---|---:|---:|---:|
| Aggregate 100–500 W | 138,820 | 0.200 → 0.140 | 0.320 → 0.203 |
| Aggregate 500–1500 W | 41,890 | 0.342 → 0.242 | 0.214 → 0.203 |
| Aggregate ≥1500 W | 11,812 | 0.498 → 0.389 | 0.787 → 1.579 |
| 0 thiết bị ON | 128,612 | 0.000 → 0.000 | 0.759 → 0.418 |
| 1 thiết bị ON | 60,615 | 0.454 → 0.351 | 0.835 → 1.211 |
| 2 thiết bị ON | 7,080 | 0.516 → 0.476 | 0.433 → 0.773 |
| ≥3 thiết bị ON | 301 | 0.439 → 0.457 | 0.043 → 0.067 |

v2.1 giảm năng lượng ảo khi không thiết bị nào trong nhãn bật, nhưng kém ở
tải cao và phần lớn nhóm 1/2 thiết bị. Nhóm ≥3 có quá ít mẫu để kết luận.
[Đồ thị điển hình House 3](figures/house3_representative.png) và
[ca lỗi lớn House 3](figures/house3_high_error.png) vẽ aggregate, truth và
ba dự đoán cho từng thiết bị trên cùng thời điểm. Ở ca lỗi, v2.0 tạo công
suất giả cho Dishwash/Microwave/Toaster/Kettle; v2.1 giảm lỗi này nhưng vẫn
bỏ sót tải WashMach lớn.

## Hiệu chỉnh hai nhánh production (v2.2)

House 2 bundle chỉ dùng House 5 làm nguồn calibration; House 5 bundle chỉ dùng
House 2. Cả hai được thử trên House 3/6 chưa từng dùng để fit calibration.
Detector chọn threshold bằng F1 nguồn calibration. Regressor áp dụng hệ số
`clip(sqrt(true_kWh/pred_kWh), 0.5, 2)` từ cùng nguồn; weights gốc được sao
chép vào đường dẫn mới. [Metadata và weights](v2_2_source_calibrated/metadata.json),
[mã suy luận](calibrated_inference.py), [bảng per device](v2_2_source_calibrated/metrics.csv).
Các bảng năng lượng có dấu/phần trăm, số mẫu, số lần bật và tầng tải cho v2.2
có trong [evaluation](v2_2_source_calibrated/evaluation/).

| Bundle → test | F1 gốc → calibrated | Sai số kWh gốc → calibrated |
|---|---:|---:|
| 2 → 3 | 0.445 → 0.380 | 0.435 → 0.622 |
| 2 → 6 | 0.477 → 0.522 | 0.620 → 0.473 |
| 5 → 3 | 0.319 → 0.346 | 1.564 → 1.020 |
| 5 → 6 | 0.446 → 0.436 | 0.260 → 0.344 |

Khoảng tin cậy ghép cặp 95% cho giảm sai số kWh là [−0.214,−0.076] ở
2→6 và [−0.726,−0.130] ở 5→3. F1 tăng tại hai cặp này nhưng khoảng tin cậy
F1 vẫn chứa 0. Hai cặp kia suy giảm. Không chọn bundle theo kết quả test;
đây là đánh giá giới hạn của phương pháp, chưa có một bản calibrated chung
thắng đều các hộ.

## Seed, kiểm thử và giới hạn

[Seed metrics](v2_1/seed_metrics.csv) ghi F1 và kWh từng thiết bị cho seed
11/22. Macro F1 giữa hai seed ở House 5 là 0.295/0.370, nên biến thiên
khởi tạo còn đáng kể. [Bootstrap ghép cặp](comparison.json) resample cùng
cửa sổ 256 mẫu cho baseline và TCN, 200 lần, seed 17; đây là bất định có
điều kiện trên bốn hộ REFIT, không đại diện quần thể hộ mới.

[Kiểm tra artifact](v2_1/verification.json) xác nhận hash bốn checkpoint,
fold train không chứa hộ test, dữ liệu đánh giá khớp baseline, output hữu hạn
và inference chỉ từ `dataset/`. Trên một cửa sổ thật mỗi hộ, sai khác lớn nhất
giữa loader bàn giao và NPZ là <0.001 W. CPU 4 thread trên máy dùng chung:
~6.8 ms/cửa sổ, ~52.9 ms/32 cửa sổ; đây chỉ là phép đo tham khảo.

Mẫu test chỉ có 128 cửa sổ/hộ, nhãn hiếm có ít sự kiện, House 6 không có
Fridge và thiếu ground truth cho nhiều tải nền. Phần v2.1 thay đổi đồng thời
loss, validation, augmentation và calibration, nên không suy ra hiệu quả
nhân quả riêng của từng thay đổi. v2.2 được phát triển sau khi đã xem kết
quả thử trước đó; cần hộ ngoài REFIT hoặc holdout mới để xác nhận.

## Tái lập và giao diện backend sau này

Từ gốc repo:

```bash
uv run --group nilm python dataset/research_v2/run.py --epochs 8 --windows-per-epoch 256 --device cpu
uv run --group nilm python dataset/research_v2/run_v21.py --epochs 16 --windows-per-epoch 512 --device cpu
uv run --group nilm python dataset/research_v2/calibrate_sources.py
uv run --group nilm python dataset/research_v2/analyze.py
uv run --group nilm python dataset/research_v2/seed_variability.py
uv run --group nilm python dataset/research_v2/validate_artifacts.py
uv run --group nilm python dataset/research_v2/plots.py
```

Checkpoint v2.1 có format `wattprint-nilm-tcn/1`, không tương thích trực tiếp
`wattprint-nilm/2`. Nếu tích hợp sau này, backend cần thêm loader cho
`TCNDetector`/`TCNRegressor`, áp dụng `power_scale_w`, `energy_calibration`
và giữ thứ tự nhãn, ngưỡng, nhịp 15 giây, input `(B,9,256)`, output
`(P_ON, watts)` mỗi tensor `(B,C,256)`. [inference.py](inference.py) là ví
dụ chạy độc lập; [preprocess.py](preprocess.py) tạo input từ CSV. v2.2 dùng
weights production định dạng cũ cộng wrapper threshold/scale, được mô tả
trong [calibrated_inference.py](calibrated_inference.py). **Không file backend
nào được sửa trong nghiên cứu này.**
