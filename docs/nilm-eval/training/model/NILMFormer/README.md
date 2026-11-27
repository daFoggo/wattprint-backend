# Mô hình đối chứng NILMFormer

Mã được chuyển từ [kho chính thức EDF-Lab/NILMFormer](https://github.com/EDF-Lab/NILMFormer),
commit `e73a975a42fbebed6f9d7e90d75f7f48ae02fed9`.
Copyright © 2025 EDF; Apache-2.0 (xem LICENSE).

Mô hình giữ kiến trúc hồi quy gốc: chuẩn hóa từng cửa sổ, token thống kê,
phép chiếu đặc trưng thời gian, tích chập giãn và attention có mask đường chéo.
Không có GRU Detector hoặc mask bật/tắt thiết bị. Mask đường chéo bên trong
attention chặn token tự chú ý chính nó, khác với mask bật/tắt công suất đầu ra.

Code tuân theo quy ước `TwoStageNILMFormer`: config nằm cùng file model,
`self.config`, `TokenStats`, `TimeRPE`, `ResidualBlock`, `DilatedResidualBlock`,
`Transformer.py`; các biến trung gian và comment diễn giải chiều tensor.
Giữ thứ tự khởi tạo của tác giả để không đổi trọng số ban đầu khi dùng cùng seed.
LayerNorm cuối giữ epsilon mặc định `1e-5`, kể cả khi `norm_eps` trong các lớp
encoder được cấu hình khác. Bản đối chứng hỗ trợ dilation tùy chỉnh và lặp lại;
khối tích chập của bản hai giai đoạn cố định `[1, 2, 4, 8]`.

Tên khóa trọng số đã đổi: `ProjStats1` → `TokenStats`, `ProjEmbedding` → `TimeRPE`,
`EmbedBlock.network.<index>.layers` → `EmbedBlock.dilated_<dilation>.block`
với danh sách dilation mặc định. Checkpoint từ kho gốc cần ánh xạ lại tên khóa.
Import trực tiếp model và config từ `NILMFormer.py`; các lớp phụ nằm trong
`DilatedResidualBlock.py` và `Transformer.py`. Không hỗ trợ chuyển đổi đối tượng
model được lưu toàn bộ bằng pickle.

xFormers chỉ được import khi dùng attention tối ưu. Nhánh PyTorch mặc định
không cần xFormers. Nhánh attention tối ưu được giữ từ mã nguồn nhưng chưa được
kiểm chứng tại đây; dùng `use_efficient_attention=False` cho mô hình đối chứng.

```python
import torch
from training.model.NILMFormer.NILMFormer import NILMFormer, NILMFormerConfig

# Mặc định gốc: một mô hình dự đoán một thiết bị.
model = NILMFormer(NILMFormerConfig())
x = torch.randn(2, 9, 128)  # (B=2, 1 kênh điện tổng + 8 đặc trưng thời gian, L=128)
y = model(x)  # (2, 9, 128) → (2, 1, 128)

# Cấu hình nhiều đầu ra để đối chứng với regressor hai giai đoạn.
model = NILMFormer(NILMFormerConfig(c_out=9))
y = model(x)  # (2, 9, 128) → (2, 9, 128)
```

Đầu vào có shape `(B, 1 + c_embedding, L)`: kênh đầu chứa công suất tổng,
các kênh còn lại chứa đặc trưng thời gian do pipeline dữ liệu chuẩn bị (mặc định 8).
Ví dụ ngẫu nhiên chỉ minh họa shape. Đầu ra là công suất hồi quy chưa áp ngưỡng,
chưa chặn giá trị và chưa tự đưa về 0. Giữ `c_in=1` vì forward chỉ chọn một kênh điện tổng.

Khi đối chứng, dùng cùng tập hộ, cửa sổ, đặc trưng thời gian, kênh đích, thang đo,
ngân sách huấn luyện và mask đánh giá. `c_out>1` là cấu hình nhiều đầu ra của kiến trúc
gốc, không tái lập thiết lập thực nghiệm dự đoán từng thiết bị trong bài báo.
Module này không bao gồm huấn luyện hoặc chuẩn bị dữ liệu.

## Huấn luyện mô hình đối chứng

Hàm huấn luyện nằm tại `training/train_nilmformer.py`, gồm `nilmformer_loss`,
`run_nilmformer_epoch` và `train_nilmformer`. Loss là MSE công suất hồi quy trực tiếp;
không áp dụng softplus, mask bật/tắt hoặc loss detector lên đầu ra gốc.

Mỗi batch gồm `x` có shape `(B, 1 + c_embedding, L)`, `power` có shape `(B, C, L)`
và `valid` boolean cùng shape với `power` nếu cần lọc chất lượng nhãn.
Nhãn NaN/Inf và các điểm `valid=False` được loại khỏi loss; dữ liệu đầu vào phải
hữu hạn. Khóa `on` nếu có trong batch không được sử dụng. Để đối chứng công bằng,
chuẩn bị cùng mask `valid` cho hai mô hình, kể cả các điểm thiếu nhãn bật/tắt.
Dùng cùng thang công suất không âm với bản hai giai đoạn và giữ trạng thái tắt bằng 0.

```python
from training.model.NILMFormer.NILMFormer import NILMFormer, NILMFormerConfig
from training.train_nilmformer import train_nilmformer

model = NILMFormer(NILMFormerConfig(c_out=9))
# Bộ nạp phải lặp lại được qua các epoch; x: (B, 9, L), power: (B, 9, L).
history = train_nilmformer(
    model, train_loader, val_loader,
    epochs=30, lr=1e-4, device="cpu",
    checkpoint_path="training/checkpoints/nilmformer_best.pt",
)
```

Hàm dùng AdamW, cắt ngưỡng chuẩn gradient, validation không tính gradient và
thanh tiến trình `tqdm` cập nhật postfix sau mỗi epoch. Checkpoint tùy chọn lưu
trọng số có loss validation tốt nhất, hoặc loss train tốt nhất nếu không có validation.
Mô hình trong bộ nhớ giữ trọng số epoch cuối và chuyển sang chế độ đánh giá.

Tham khảo: Petralia và cộng sự, *NILMFormer: Non-Intrusive Load Monitoring that
Accounts for Non-Stationarity*, KDD 2025, DOI: 10.1145/3711896.3737251.
