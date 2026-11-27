# Seed cho các thực nghiệm huấn luyện

Mã dùng chung nằm trong `training/seeds.py`. Cấu hình đã chốt nằm trong
`training/configs/seeds.json`: seed gốc mặc định **42**, sinh **5 seed khác nhau**
trong khoảng đóng **[0, 2³¹−1]**. Có thể đổi seed gốc và khoảng qua tham số
`generate_model_seeds`, rồi lưu cấu hình mới trước khi thực nghiệm.

- Seed gốc cố định dùng cho chia dữ liệu, thứ tự batch, worker và ngẫu nhiên
  trong quá trình train. Giữ cùng danh sách hộ và cửa sổ giữa các lần chạy.
- Năm seed mô hình chỉ dùng trước constructor để khởi tạo các bộ trọng số khác
  nhau. Sau khi khởi tạo, hàm train đặt lại seed chung cho quá trình huấn luyện.
- `generate_model_seeds` lấy mẫu không hoàn lại bằng bộ sinh cục bộ; không phụ
  thuộc các lệnh ngẫu nhiên đã chạy trước đó và không đổi bộ sinh toàn cục.
- `seed_everything` đồng bộ Python, NumPy và PyTorch CPU/CUDA; tắt tìm thuật toán
  cuDNN bằng benchmark và bật thuật toán xác định. Cấu hình cuBLAS cần được đặt
  trước phép tính CUDA đầu tiên; không dùng chế độ attention tối ưu chưa kiểm chứng.
- Bộ sinh NumPy tạo bằng `default_rng` phải nhận seed riêng, ví dụ
  `np.random.default_rng(BASE_SEED)`; nó không dùng trạng thái `np.random.seed`.

Ví dụ chuẩn bị từng lần chạy TwoStageNILMFormer sau khi đã có dataset:

```python
from torch.utils.data import DataLoader

from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig
from training.seeds import BASE_SEED, generate_model_seeds, make_data_generator, seed_everything, seed_worker
from training.train_twostage_nilmformer import initialize_twostage_nilmformer, train_twostage_nilmformer

seed_everything(BASE_SEED)
# Chia hộ và xây dựng train_dataset/val_dataset một lần với seed gốc cố định.
for model_seed in generate_model_seeds():
    model = initialize_twostage_nilmformer(
        GRUConfig(c_out=9), NILMFormerConfig(c_out=9), model_seed,
    )
    # Tạo lại bộ nạp và generator cho từng lần chạy để thứ tự batch giống nhau.
    train_loader = DataLoader(
        train_dataset, batch_size=32, shuffle=True,
        generator=make_data_generator(BASE_SEED), worker_init_fn=seed_worker,
        num_workers=0,
    )
    val_loader = DataLoader(
        val_dataset, batch_size=32, shuffle=False,
        generator=make_data_generator(BASE_SEED), worker_init_fn=seed_worker,
        num_workers=0,
    )
    history = train_twostage_nilmformer(
        model, train_loader, val_loader,
        training_seed=BASE_SEED,
        checkpoint_path=f"training/checkpoints/twostage_seed_{model_seed}.pt",
    )
```

Hàm khởi tạo lưu seed vào mô hình; hàm train tự ghi lại vào checkpoint cùng
`training_seed`. Tham số `model_seed` của hàm train chỉ ghi nhận/kiểm tra metadata,
không khởi tạo lại một mô hình đã có. Với mô hình được tạo trực tiếp, người gọi
phải đặt seed trước constructor; đặt seed sau constructor không đổi trọng số.
Hàm train NILMFormer gốc cũng nhận `training_seed` và `model_seed` để dùng cùng
quy trình khi đối chứng. Không tái sử dụng mô hình đã train cho seed tiếp theo.

Nếu tăng `num_workers`, giữ `worker_init_fn` và generator như ví dụ. Phần chuẩn
bị dữ liệu không được phụ thuộc thứ tự của set/hash. Nếu cần cố định hash của
Python, đặt `PYTHONHASHSEED=42` khi khởi chạy tiến trình; đặt bên trong một tiến
trình đang chạy không thay đổi hash hiện tại.

Tính tái lập được kiểm tra trong cùng môi trường; không bảo đảm kết quả khớp
tuyệt đối giữa các phiên bản thư viện, GPU hoặc hệ điều hành khác nhau.
Đây mới là thiết lập seed, chưa chia dữ liệu hoặc chạy 5 thực nghiệm thực tế.
