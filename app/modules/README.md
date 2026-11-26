# Mô-đun của backend

Mỗi mô-đun có `models/`, `schemas/`, `services/`, `routes/` và `api.py`. **Mô-đun khác chỉ import qua `api.py`**; `scripts/check_boundaries.py` báo lỗi khi vi phạm. Router của từng mô-đun được gắn ở `app/main.py` dưới `/api/v1`.
Danh sách xuất khẩu và phụ thuộc dưới đây đọc từ `api.py` và các dòng `from app.modules.<tên>.api import`; cột vai trò suy ra từ tên xuất khẩu, mô hình dữ liệu và route.

| Mô-đun | Tiền tố route | Vai trò | Import qua api.py của |
|---|---|---|---|
| `auth` | `/users`, `/demo` | Người dùng, tùy chọn cá nhân, kiểm tra token Keycloak (JWKS), tài khoản khách demo | `home`, `energy` |
| `home` | `/homes` | Nhà, thành viên, thiết bị, công tơ, tỉnh thành | `auth`, `billing` |
| `energy` | `/energy` | Chuỗi công suất, tổng hợp theo thiết bị, thời tiết, tổng quan, luồng SSE `/energy/stream` | `home`, `nilm`, `ops` |
| `billing` | `/billing` | Biểu giá bậc thang, hóa đơn kỳ này và lịch sử, dự báo cuối kỳ, dự báo theo thiết bị | `energy`, `expect`, `home`, `ops` |
| `expect` | `/expected` | Mô hình mức dùng kỳ vọng theo giờ (LightGBM), khoảng P10–P90 | `energy`, `ops` |
| `insight` | `/insights` | Cảnh báo, so sánh nhóm nhà (chỉ khi có ít nhất `MIN_COHORT_HOMES` nhà), lệnh theo dõi (`watch`), kế hoạch tiết kiệm; có worker nền | `billing`, `copilot`, `energy`, `expect`, `home`, `ops` |
| `copilot` | `/copilot` | Wappi: chat, hội thoại, phản hồi, giọng nói, công cụ | `billing`, `energy`, `expect`, `home`, `insight` |
| `nilm` | không có | Mô hình tách tải từng thiết bị, điểm số từng loại thiết bị; có worker nền (PyTorch) | `energy`, `ops` |
| `ops` | `/ops` (chưa có endpoint) | Nạp số đo và ước tính (`ingest_readings`, `ingest_estimates`), kịch bản demo | không import mô-đun nào |

Các mô-đun `energy`↔`nilm`, `auth`↔`home`, `home`↔`billing` và `copilot`↔`insight` import lẫn nhau qua `api.py`.

## Worker nền

- `insight/worker.py`: vòng lặp ngủ `insight_poll_s` (mặc định 60 giây) giữa các lượt kiểm tra; mỗi việc có khóa advisory `insight:<tên>`. Nhịp (giây): `bills` 3600, `expect_train` 86400, `expect` 3600, `forecasts` 86400, `cohorts` 86400, `alerts` 300, `watches` 60, `mail` 60, `upkeep` 3600.
- `nilm/worker.py`: mỗi `nilm_poll_s` (mặc định 60 giây) đưa từng nhà có công tơ chính và mô hình theo kịp số đo mới nhất; nhà lỗi bị lùi 60, 120 giây... tối đa 600 giây và có khóa advisory theo nhà.
- `scripts/replay_refit.py` (service `replay`): lấp khoảng trống từ số đo mới nhất tới hiện tại rồi ghi thêm mỗi 5 giây.

## Thêm một mô-đun

1. Tạo `app/modules/x/` giống các mô-đun khác; `routes/__init__.py` xuất `router = APIRouter(prefix="/x", tags=["x"])`.
2. Thêm router vào danh sách trong `app/main.py`.
3. Mô-đun khác chỉ import từ `app.modules.x.api`.
