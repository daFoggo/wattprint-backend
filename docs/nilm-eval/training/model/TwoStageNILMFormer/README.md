# Huấn luyện đồng thời TwoStageNILMFormer

```text
Điện tổng ── GRU Detector ── sigmoid ── mask bật/tắt cứng ───┐
                                                           × ── Công suất dự đoán
Điện tổng + đặc trưng thời gian ── NILMFormer ── softplus ────┘
```

Khi huấn luyện, mask dùng bộ ước lượng straight-through:
`mask = hard_mask + (probability - probability.detach())`.
Forward nhận giá trị đúng 0/1; backward dùng đạo hàm sigmoid. Nếu chỉ dùng
`(probability >= threshold).float()`, gradient từ loss công suất về detector sẽ
bị cắt. Khi đánh giá, mô hình dùng mask cứng và không cần gradient thay thế.

Lớp ghép áp dụng softplus lên đầu ra regressor để công suất không âm. Đây là
phép biến đổi bổ sung cho huấn luyện đồng thời, không thay đổi regressor độc lập.
Với target công suất dương và mask tắt nhầm, MSE sau mask đẩy logits của detector
về phía bật, trừ trường hợp sigmoid bão hòa về mặt số học. BCE giám sát trực tiếp
nhãn bật/tắt của detector.

Loss mặc định:

`loss = MSE(mask * power, target) + BCEWithLogits(logits, on) + 0.1 * MSE(power[true_on], target[true_on])`

Loss phụ tại các điểm thực sự bật giúp regressor học ngay cả khi mask tắt nhầm
chặn gradient hồi quy chính. Có thể cấu hình trọng số các loss;
`positive_weight > 1` tăng mức phạt BCE khi bỏ sót trạng thái bật.
Gradient straight-through là gradient thay thế, không phải đạo hàm chính xác của
phép so ngưỡng cứng. Mô hình vẫn tính regressor cho toàn bộ kênh rồi nhân mask;
cơ chế này không tiết kiệm phép tính của regressor.

Mỗi batch từ bộ nạp dữ liệu là một dictionary:

| Khóa | Shape | Ý nghĩa |
| --- | --- | --- |
| `x` | `(B, 1 + e, L)` | Điện tổng và đặc trưng thời gian hữu hạn; mặc định `e=8` |
| `power` | `(B, C, L)` | Công suất thiết bị thực tế, không âm |
| `on` | `(B, C, L)` | Nhãn bật/tắt thực tế, giá trị 0 hoặc 1 |
| `valid` (tùy chọn) | `(B, C, L)` | Mask boolean xác định nhãn hợp lệ |

Trong đó `B` là số mẫu, `C` là số thiết bị và `L` là độ dài chuỗi.
Nhãn NaN/Inf và các điểm `valid=False` được loại khỏi loss. Batch không có điểm
hợp lệ gây báo lỗi. Dữ liệu đầu vào bị thiếu phải được xử lý trước khi huấn luyện.
Tạo nhãn bật/tắt từ ngưỡng công suất vật lý và thời lượng bật/tắt tối thiểu trước
khi đổi thang đo; không suy nhãn bằng điều kiện công suất đã chuẩn hóa lớn hơn 0.

Dùng hệ số công suất cố định, dương, được chọn từ tập huấn luyện (ví dụ W/1000),
áp dụng nhất quán cho điện tổng và target. Không trừ trung bình target: tắt phải
vẫn bằng 0. Đổi lại đơn vị vật lý khi tính chỉ số điện năng. Trọng số loss cần được
hiệu chỉnh theo thang đo; cấu hình mặc định chưa được chứng minh tối ưu với W thô.

```python
from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig
from training.model.TwoStageNILMFormer.TwoStageNILMFormer import TwoStageNILMFormer
from training.train_twostage_nilmformer import (
    TwoStageLossConfig,
    train_twostage_nilmformer,
)

model = TwoStageNILMFormer(GRUConfig(c_out=9), NILMFormerConfig(c_out=9))
# Hai bộ nạp dữ liệu phải lặp lại được qua nhiều epoch, ví dụ PyTorch DataLoader.
history = train_twostage_nilmformer(
    model,
    train_loader,
    val_loader,
    epochs=30,
    lr=1e-4,
    device="cpu",  # Đổi thành "cuda" khi GPU khả dụng.
    loss_config=TwoStageLossConfig(positive_weight=2.0),
    checkpoint_path="training/checkpoints/twostage_best.pt",
)
```

Một optimizer AdamW cập nhật cả hai nhánh trong một lần backward, có cắt ngưỡng
chuẩn gradient. Không đưa nhãn thực tế vào mask forward. Validation dùng mask
cứng như lúc suy luận. Checkpoint tùy chọn lưu loss validation tốt nhất, hoặc loss
huấn luyện tốt nhất nếu không truyền bộ validation. Mô hình trong bộ nhớ được khôi phục về trọng số tốt nhất rồi chuyển sang chế độ đánh giá.
Khi bật early stopping, checkpoint tốt nhất được chọn theo validation, không theo test.
Đây là huấn luyện đồng thời, không phải tiền huấn luyện tuần tự. Pipeline dữ liệu
vẫn cần đảm nhiệm chia hộ, tạo đặc trưng và thực nghiệm trên dữ liệu thật.

Thanh tiến trình `tqdm` theo dõi số epoch. Sau mỗi epoch, postfix cập nhật loss
huấn luyện, loss hồi quy, loss detector, loss phụ, loss tốt nhất và loss validation
nếu có bộ nạp validation. Thanh tự đóng khi hoàn tất hoặc có ngoại lệ.
