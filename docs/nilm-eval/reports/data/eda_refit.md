# EDA REFIT

## 1. Các trường dữ liệu trong dataset

Bản cleaned gồm 20 file CSV, mỗi house một file. Cả 20 house đều có cùng 13 trường dưới đây. Danh sách được kiểm tra trực tiếp từ header của các file trong `data/cleaned/REFIT/`; ý nghĩa và đơn vị được đối chiếu với `data/raw/REFIT/CLEAN_READ_ME_081116.txt`. [Notebook khảo sát](../../data/scripts/EDA_REFIT.ipynb).

| Trường gốc | Ý nghĩa | Đơn vị / kiểu |
| --- | --- | --- |
| `Time` | Thời điểm đo dạng ngày giờ, đã hiệu chỉnh giờ mùa hè của UK | datetime |
| `Unix` | Thời điểm đo dạng Unix timestamp | giây UTC |
| `Aggregate` | Công suất tác dụng toàn nhà | W |
| `Appliance1`–`Appliance9` | Công suất tác dụng ở chín cổng giám sát thiết bị (IAM) | W |
| `Issues` | Cờ cho biết tổng công suất các IAM lớn hơn `Aggregate` | 0/1 |

**Quy ước diễn giải:** `Appliance1`–`Appliance9` là vị trí cảm biến. Loại thiết bị tương ứng khác nhau theo house và có thể thay đổi theo thời gian; phải tra ánh xạ trong README nguồn trước khi đặt tên thiết bị. `Issues` là cờ chất lượng dữ liệu, không phải một thiết bị. REFIT chỉ cung cấp công suất tác dụng trong các cột đo điện này; nhịp lấy mẫu danh định là 8 giây.
