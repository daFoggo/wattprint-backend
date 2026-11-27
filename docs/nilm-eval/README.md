# NILM

Mã huấn luyện và đánh giá bài toán NILM (tách điện từng thiết bị từ công tơ tổng) cho WattPrint: baseline NILMFormer và mô hình hai giai đoạn TwoStageNILMFormer (bộ phát hiện GRU rồi bộ hồi quy NILMFormer) trên REFIT, 7 hộ, 4 thiết bị (máy giặt, máy rửa bát, ấm đun nước, lò vi sóng), 5 seed, hai giao thức `pooled` và `cross_house`.
Mô hình dùng trong ứng dụng nằm ở `wattprint-backend`.

## Cài đặt và chạy

### Yêu cầu

- Python 3.14 và [uv](https://docs.astral.sh/uv/) (`.python-version` = 3.14; `uv sync` cài PyTorch, xformers, pandas...).
- 7-Zip (`7z` hoặc `7zz`) để giải nén dữ liệu: `sudo apt install p7zip-full`.
- GPU CUDA để huấn luyện đầy đủ (mặc định `--device cuda`, lỗi nếu không có CUDA); chạy kiểm tra trên CPU bằng `--device cpu`.
- Khoảng 10 GB đĩa cho dữ liệu sau giải nén.

### Các bước

```bash
uv sync
python data/scripts/download_datasets.py        # REFIT và PLEGMA đã làm sạch, kiểm SHA-256, giải nén vào data/cleaned/
```

Dữ liệu đã chia train/test (`data/processed/REFIT/temporal_7aea0ef86866`) được tạo lại bằng notebook `data/scripts/Preprocess_REFIT_NILMFormer.ipynb` (`uv run jupyter lab`); script tải không tạo nó.

```bash
uv run python -m training.train_twostage_nilmformer --smoke-test      # chạy thử nhanh
uv run python -m training.train_twostage_nilmformer                   # TwoStageNILMFormer, 40 lượt train
uv run python -m training.train_twostage_nilmformer --model nilmformer   # baseline, cùng quy trình
```

Kết quả vào `training/runs/<mô hình>_<thời điểm>/` (`study.json`, `macro_summary.csv`, `test_metrics.csv`, thư mục từng hộ và `pooled/` có `best.pt`, `last.pt`). Cờ chính: `--epochs` (150), `--patience` (10), `--batch-size` (64), `--lr` (1e-4), `--num-seeds` (5), `--houses`, `--protocols`, `--device`, `--cpu-threads` (1). Chi tiết: [docs/train_twostage.md](docs/train_twostage.md), thiết kế thí nghiệm: [docs/study_design.md](docs/study_design.md).

### Kiểm thử

```bash
uv run python -m unittest discover -s training/tests
```

30 test (`unittest`, không dùng pytest), chạy từ gốc repo; đã chạy qua trong 34 giây trên một môi trường có đủ thư viện. Quy ước code: [docs/quy_uoc_code.md](docs/quy_uoc_code.md) (`.venv/bin/python -m compileall -q training`).

### Demo suy luận bằng Docker (CPU)

```bash
uv run python deploy/xuat_trong_so.py                          # gộp trọng số 5 seed, tạo dữ liệu mẫu
docker build -f deploy/Dockerfile -t wattprint-nilm:cpu .
docker run --rm --cpus 1 --memory 512m wattprint-nilm:cpu      # chạy trên dữ liệu mẫu
```

Dữ liệu riêng: CSV có cột `timestamp` và `aggregate_w`, nhịp 1 phút liên tục (`--input`, `--output`). Số đo và chi tiết: [deploy/README.md](deploy/README.md).

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `data/` | Script tải dữ liệu (`scripts/`) và notebook tiền xử lý; dữ liệu tải về `raw/`, `cleaned/`, `processed/` không nằm trong git |
| `training/` | `train_twostage_nilmformer.py` (runner), `train_nilmformer.py`, `data.py`, `metrics.py`, `seeds.py`, `model/NILMFormer` và `model/TwoStageNILMFormer`, `configs/seeds.json`, `tests/`, `runs/` |
| `deploy/` | Xuất trọng số và đóng gói suy luận CPU bằng Docker |
| `docs/` | Thiết kế thí nghiệm, quy trình huấn luyện, chỉ số, dữ liệu đã xử lý, seed, quy ước code |
| `reports/` | Báo cáo thực nghiệm, bài báo, hình và script sinh báo cáo |

## Chuẩn bị dữ liệu sau khi clone

Cần Python 3.14 và 7-Zip (`7z` hoặc `7zz`). Trên Ubuntu/Debian:

```bash
sudo apt install p7zip-full
python data/scripts/download_datasets.py
```

Script chỉ dùng thư viện chuẩn Python, không cần cài các thư viện huấn luyện để tải dữ liệu.
Mặc định tải cả REFIT và PLEGMA bản cleaned cùng README/metadata, kiểm tra SHA-256
và giải nén vào `data/cleaned/REFIT/` và `data/cleaned/PLEGMA/` để các notebook hiện có đọc trực tiếp.
Archive được lưu trong `data/raw/<bộ dữ liệu>/`.

Các tùy chọn:

```bash
# Chỉ chuẩn bị một bộ dữ liệu
python data/scripts/download_datasets.py --dataset refit
python data/scripts/download_datasets.py --dataset plegma

# Tải thêm cả hai archive raw gốc, giữ nguyên dạng nén
python data/scripts/download_datasets.py --include-raw

# Chỉ tải, không giải nén; không cần 7-Zip
python data/scripts/download_datasets.py --download-only
```

Có thể chạy script từ bất kỳ thư mục nào; đường dẫn mặc định được xác định theo vị trí script.
Dùng `--data-dir /đường/dẫn/data` nếu muốn lưu ở nơi khác; các notebook hiện tại vẫn dùng `data/` của repository.
Chạy lại sẽ bỏ qua tệp tải về có SHA-256 hợp lệ và thư mục cleaned đã có đủ tệp đúng kích thước.
Tệp tải dở có đuôi `.part`, được tải lại từ đầu ở lần chạy sau; script tự thử tối đa ba lần khi tải lỗi.
Nếu máy chủ trả HTTP 403, có thể tải bằng trình duyệt theo URL trong `data/scripts/datasets.json`,
đặt tệp vào `data/raw/<bộ dữ liệu>/` rồi chạy lại script để kiểm tra và giải nén.

Lần chuẩn bị đầu cần tải khoảng 0,8 GB archive cleaned và khoảng 8,3 GB dữ liệu sau giải nén.
Tùy chọn `--include-raw` tải thêm khoảng 1,4 GB archive raw gốc.
Git bỏ qua archive, tệp tải dở, toàn bộ `data/cleaned/` và `data/processed/`;
script, notebook và README/metadata nguồn nhỏ vẫn được giữ lại khi clone.
`data/processed/` được tạo lại bằng notebook `data/scripts/Preprocess_REFIT_NILMFormer.ipynb`, không được tải bởi script.

Nguồn công bố và giấy phép: [REFIT cleaned](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements-cleaned/),
[REFIT raw](https://pureportal.strath.ac.uk/en/datasets/refit-electrical-load-measurements/) và
[PLEGMA](https://pureportal.strath.ac.uk/en/datasets/plegma-dataset/) (CC BY 4.0).
URL từng tệp và SHA-256 của bản dữ liệu đang dùng được lưu trong `data/scripts/datasets.json`.
