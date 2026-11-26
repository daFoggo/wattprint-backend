# scripts/

Chạy từ gốc repo, trong container `api` (`docker compose exec -T api python -m scripts.<tên>`) hoặc trên máy bằng `uv run python -m scripts.<tên>` khi script cần `.env`.

| Script | Việc làm |
|---|---|
| `seed_demo_homes.py` | Tạo nhà demo trong `demo_homes.toml`: tài khoản Keycloak, công tơ, mô hình NILM, lịch sử số đo, thời tiết |
| `demo_homes.toml` | Cấu hình các nhà demo (số ngày lịch sử, mô hình dùng chung, tên thiết bị) |
| `replay_refit.py` | Phát lại CSV thành số đo "thật": lấp khoảng trống rồi ghi thêm mỗi 5 giây (`--once` chỉ lấp khoảng trống) |
| `refit.py` | Thư viện chung: ánh xạ thời gian REFIT sang giờ Việt Nam |
| `import_refit_weather.py` | Lưu thời tiết theo giờ (ERA5 qua Open-Meteo, không cần khóa) cho nhà demo |
| `backfill_nilm.py` | Sinh ước tính thiết bị cho các ngày còn thiếu của nhà demo (cần PyTorch) |
| `scenario.py`, `scenarios.py` | Bật, tắt, liệt kê và định nghĩa kịch bản tải mô phỏng (`heater`, `forgotten_load`, `base_up`, `away`, `echo_run`, `cold_spell`) |
| `seed_demo_plans.py` | Tạo kế hoạch tiết kiệm quá khứ cho chủ nhà demo |
| `plegma_to_refit.py`, `enertalk_to_refit.py` | Đổi dữ liệu Plegma và ENERTALK sang CSV kiểu REFIT |
| `unpack_dataset.py` | Giải nén dữ liệu và mô hình NILM đã đóng gói |
| `preprocess_dataset.py`, `prepare_training_data.py` | Tiền xử lý REFIT và tạo cửa sổ huấn luyện NILM |
| `eval_nilm.py` | Chấm điểm đầu ra NILM với các ổ cắm đo riêng của REFIT; ghi `docs/nilm-eval.md` |
| `ingest_documents.py` | Nạp `docs/sources/*.md` vào `tb_document` và `tb_chunk`; thư mục là cả kho, tài liệu không còn trong thư mục bị xóa |
| `eval_wappi.py`, `wappi_eval.py`, `wappi_judges.py`, `wappi_scenarios.py`, `wappi_speak.py` | Đánh giá Wappi: kiểm tra không cần mô hình, ba judge, kịch bản, lint câu đọc to (xem `docs/chatbot-eval.md`) |
| `backtest_expect.py` | So mô hình kỳ vọng với hồ sơ theo thứ trong tuần |
| `check_boundaries.py` | Báo lỗi khi mô-đun import nội bộ mô-đun khác thay vì `api.py` |
