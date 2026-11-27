# EDA PLEGMA

## 1. Các trường dữ liệu trong dataset

Bản cleaned có 13 house. Mỗi house có dữ liệu điện theo tháng, dữ liệu môi trường, metadata thiết bị và một workbook khảo sát hộ. Danh sách cột được kiểm tra từ header các CSV trong `data/cleaned/PLEGMA/`; ý nghĩa và đơn vị được đối chiếu với `data/raw/PLEGMA/PlegmaDataset_README_20240326.txt`. [Notebook khảo sát](../../data/scripts/EDA_PLEGMA.ipynb).

### Dữ liệu điện (`Electric_data`)

| Trường gốc | Ý nghĩa | Đơn vị / kiểu | House có trường |
| --- | --- | --- | ---: |
| `timestamp` | Thời điểm đo | datetime | 13 |
| `P_agg` | Công suất tác dụng toàn nhà | W | 13 |
| `V` | Điện áp toàn nhà | V | 9 |
| `A` | Dòng điện toàn nhà | A | 9 |
| `ac_1`, `ac_2`, `ac_3` | Công suất máy điều hòa được giám sát | W | 11, 6, 1 tương ứng |
| `boiler` | Công suất bình nước nóng | W | 12 |
| `dishwasher` | Công suất máy rửa bát | W | 4 |
| `fridge`, `fridge_1`, `fridge_2` | Công suất tủ lạnh được giám sát | W | 12, 1, 1 tương ứng |
| `kettle` | Công suất ấm đun nước | W | 1 |
| `washing_machine` | Công suất máy giặt | W | 13 |
| `issues` | Cờ tổng công suất thiết bị được giám sát lớn hơn `P_agg` | 0/1 | 13 |

### Dữ liệu môi trường (`Environmental_data`)

| Trường gốc | Ý nghĩa | Đơn vị / kiểu | House có trường |
| --- | --- | --- | ---: |
| `timestamp` | Thời điểm đo | datetime | 13 |
| `internal_temperature` | Nhiệt độ trong nhà | °C | 13 |
| `internal_humidity` | Độ ẩm trong nhà | % | 13 |
| `external_temperature` | Nhiệt độ ngoài trời | °C | 13 |
| `external_temparature` | Cùng ý nghĩa với `external_temperature`, tên cột viết sai trong file gốc | °C | 1 |
| `external_humidity` | Độ ẩm ngoài trời | % | 13 |

Hai cách viết `external_temperature` và `external_temparature` có thể xuất hiện ở các file tháng khác nhau của cùng một house. Bảng trên đếm **house có trường**, không cộng hai cột thành 14 house.

### Metadata thiết bị (`appliances_metadata.csv`)

Mỗi house có một CSV metadata với năm trường: `appliance` (tên thiết bị), `wattage [W]` (công suất, W), `threshold [W]` (ngưỡng xác định trạng thái bật, W), `min_on (sec)` (thời gian bật tối thiểu, giây) và `min_off (sec)` (thời gian tắt tối thiểu, giây).

### Workbook khảo sát hộ

Mỗi house có một XLSX dạng biểu mẫu, gồm ba nhóm nội dung chính: `SOCIODEMOGRAPHIC` (thông tin dân cư), `BUILDING CHARACTERISTICS` (đặc điểm nhà) và `TIME OF USE OF APPLIANCES` (thói quen sử dụng thiết bị). Workbook không có schema bảng phẳng như CSV; các câu hỏi và lựa chọn trả lời cần được định nghĩa riêng nếu dùng trong phân tích tiếp theo.

**Quy ước diễn giải:** tên cột thiết bị chỉ thiết bị/cảm biến được giám sát tại house đó; không suy ra rằng các house đều có cùng bộ thiết bị. `issues` là cờ chất lượng. Nhịp lấy mẫu danh định là 10 giây cho điện và 15 phút cho môi trường.
