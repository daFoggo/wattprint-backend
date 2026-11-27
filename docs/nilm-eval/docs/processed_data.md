# Dữ liệu CSV đã tiền xử lý

Notebook `data/scripts/Preprocess_REFIT_NILMFormer.ipynb` xuất dữ liệu trong
`data/processed/REFIT/temporal_<mã cấu hình>/`, gồm 40 CSV train/test của 20 hộ,
manifest, mốc chia thời gian, kế hoạch thực nghiệm và các bảng kiểm tra chất lượng.

Mỗi dòng là một phút của cửa sổ được giữ lại. Công suất lưu đơn vị **W chưa
normalize**, gồm điện tổng và bốn thiết bị theo thứ tự đã chốt. Các cột:

| Cột | Ý nghĩa |
| --- | --- |
| `house_id` | Hộ đang xét |
| `window_id`, `step` | Cửa sổ và vị trí trong cửa sổ; ID cửa sổ tính riêng mỗi file |
| `timestamp` | Thời điểm theo trường Time của bản cleaned |
| `aggregate_w` | Công suất tổng, W |
| `<thiết bị>_w` | Công suất thiết bị, W |
| `<thiết bị>_on` | Trạng thái 0/1 đã tạo trước giảm nhịp |
| `<thiết bị>_valid` | Mask 0/1 cho nhãn hợp lệ |
| `active_target_devices` | Số thiết bị đích đang bật có nhãn |

Ô thiếu nhãn để trống với valid=0, không phải công suất thực tế bằng 0. Không
dropna trên toàn bộ bảng và không nối lại cửa sổ bằng vị trí dòng sau khi lọc;
luôn giữ window_id, step và timestamp. Không resample, chia lại train/test hoặc
tính lại nhãn trong train. CSV dùng UTF-8, lưu số thực với 9 chữ số có nghĩa,
đủ cho dữ liệu float32 trong pipeline.

`training/data.py` cung cấp `REFITCSVDataset`: đọc file theo manifest, kiểm tra
ranh giới cửa sổ, chia điện tổng và thiết bị cho 10000, tạo 8 đặc trưng TimeRPE
từ timestamp. Không fit thống kê từ test. Kênh thiếu được thay 0 trong tensor
sau khi đọc mask; mask vẫn giữ False để loss/metrics bỏ qua.

```python
from torch.utils.data import DataLoader

from training.data import REFITCSVDataset
from training.seeds import BASE_SEED, make_data_generator, seed_worker

# Điền đường dẫn thư mục manifest CSV mà notebook in ra sau khi chạy.
processed_dir = "data/processed/REFIT/temporal_<mã cấu hình>"
train_dataset = REFITCSVDataset(processed_dir, "train")
test_dataset = REFITCSVDataset(processed_dir, "test")
# Với mô hình riêng, thêm house_id=1 cho cả hai bộ dữ liệu.
train_loader = DataLoader(
    train_dataset, batch_size=64, shuffle=True,
    generator=make_data_generator(BASE_SEED), worker_init_fn=seed_worker,
    num_workers=0,
)
```

Batch trả `x: (B, 9, 128)`, `power/on/valid: (B, 4, 128)`, house_id và timestamp
đầu cửa sổ. Cả hai hàm train hiện có dùng trực tiếp được các khóa tensor này.
Dùng `normalize=False` để đọc công suất W; tám kênh thời gian vẫn là sin/cos.
Khi tính metrics trên batch đã normalize, nhân lại 10000 và luôn truyền valid.
Test_loader không được truyền như validation của hàm train.

Loader đọc và cache mỗi CSV một lần cho mỗi đối tượng dataset, tránh đọc lại
cả file khi shuffle giữa các hộ. RAM tăng theo số hộ đã được truy cập; bắt đầu
với num_workers=0 để tránh tạo nhiều bản cache trong các worker.
Dữ liệu NPZ của các phiên bản trước được giữ trong thư mục cấu hình cũ; không
dùng lẫn với manifest CSV mới.
