import os
import random

import numpy as np
import torch

BASE_SEED = 42
MODEL_SEED_COUNT = 5
MIN_MODEL_SEED = 0
MAX_MODEL_SEED = 2**31 - 1


def generate_model_seeds(base_seed: int = BASE_SEED, count: int = MODEL_SEED_COUNT, lower: int = MIN_MODEL_SEED, upper: int = MAX_MODEL_SEED) -> list[int]:
    assert 0 <= base_seed <= 2**32 - 1, "Seed gốc phải nằm trong khoảng [0, 2³²−1]."
    assert 0 <= lower <= upper <= 2**32 - 1, "Khoảng seed phải hợp lệ và nằm trong [0, 2³²−1]."
    assert 1 <= count <= upper - lower + 1, "Số seed phải dương và không vượt quá số giá trị trong khoảng."
    # Bộ sinh cục bộ lấy mẫu không hoàn lại, không làm thay đổi trạng thái ngẫu nhiên toàn cục.
    return random.Random(base_seed).sample(range(lower, upper + 1), count)


def seed_everything(seed: int = BASE_SEED, deterministic: bool = True) -> None:
    assert 0 <= seed <= 2**32 - 1, "Seed phải nằm trong khoảng [0, 2³²−1]."
    # Thiết lập trước phép tính CUDA đầu tiên; cấu hình này phục vụ tính toán cuBLAS xác định.
    if deterministic:
        os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = deterministic
    torch.use_deterministic_algorithms(deterministic)


def seed_worker(worker_id: int) -> None:
    # PyTorch cấp seed riêng cho từng worker; đồng bộ Python và NumPy theo seed đó.
    worker_seed = torch.initial_seed() % 2**32
    random.seed(worker_seed)
    np.random.seed(worker_seed)


def make_data_generator(seed: int = BASE_SEED) -> torch.Generator:
    assert 0 <= seed <= 2**32 - 1, "Seed dữ liệu phải nằm trong khoảng [0, 2³²−1]."
    # Tách bộ sinh DataLoader khỏi bộ sinh dùng cho tham số mô hình và dropout.
    return torch.Generator().manual_seed(seed)
