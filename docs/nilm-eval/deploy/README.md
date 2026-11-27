# Demo suy luận NILM chạy gọn bằng Docker

Đóng gói phần suy luận của 2Stage chung (ensemble 5 seed) thành image chỉ dùng CPU.

```bash
# 1. Trên máy đã train: gộp trọng số, tạo dữ liệu mẫu và dự đoán tham chiếu.
uv run python deploy/xuat_trong_so.py
# 2. Build image từ thư mục gốc repo.
docker build -f deploy/Dockerfile -t wattprint-nilm:cpu .
# 3. Chạy với 1 lõi CPU và 512 MB RAM trên dữ liệu mẫu.
docker run --rm --cpus 1 --memory 512m wattprint-nilm:cpu
# Dữ liệu riêng: CSV có cột timestamp và aggregate_w, nhịp 1 phút liên tục.
docker run --rm --cpus 1 --memory 512m -v "$PWD/du_lieu":/data wattprint-nilm:cpu --input /data/dien_tong.csv --output /data/ket_qua.csv
```

Số đo khi viết (26/11/2026): image 1,21 GB, gói trọng số 10,4 MB, bộ nhớ đỉnh 354 MB,
suy luận 1.536 phút trong khoảng 0,33–0,36 s, kết quả khớp tuyệt đối với `vi_du/ho_03_tham_chieu.csv`.
Đoạn mẫu của hộ 3 được chọn vì có đủ bốn thiết bị hoạt động; không dùng để đánh giá độ chính xác.
