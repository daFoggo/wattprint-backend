# Audit: bảo vệ dữ liệu nếp sinh hoạt (2026-11-28)

Yêu cầu: giảm độ chi tiết phải lưu/chia sẻ, giới hạn quyền truy cập, cho phép xóa lịch sử, nêu rõ khi
gọi dịch vụ ngoài. Minh chứng: sơ đồ luồng dữ liệu, màn hình quyền riêng tư, thử phân quyền.

Phạm vi: đọc code `wattprint-backend`, `wattprint-web`, `wattprint-text2sql-mcp`; xem cấu hình container
đang chạy và truy vấn chỉ đọc trên DB dev. Không sửa code, không chạy test, không gọi dịch vụ ngoài.
Cột "Kiểm": **✓** đã đối chiếu code/container lần hai, **○** chỉ một lượt audit báo.

## A. Bảo mật và quyền truy cập

| ID | Mức | Vấn đề | Bằng chứng | Kiểm |
|---|---|---|---|---|
| A1 | Cao | text2sql đang chạy với `TEXT2SQL_SERVICE_KEY` trống nên API không xác thực. Nghe ở `127.0.0.1:11101` và `172.17.0.1:11101`, container khác trên máy gọi được và dùng LLM trả phí | `compose.yaml:17`, `routes/router_chat.py`, `docker inspect` | ✓ |
| A2 | Cao | Các router khác của text2sql không có xác thực; `PATCH /api/v1/database-connections/{id}` đổi được `uri`, tức trỏ kết nối WattPrint sang DB khác để lấy scope token, câu hỏi và trả số giả | `backend/main.py`, `schema_database_connection.py:29` | ○ |
| A3 | Trung bình | Viewer xem được dữ liệu phút, giờ, theo thiết bị và chat với Wappi như chủ nhà; API đọc chỉ kiểm tra là thành viên. Hiện viewer chỉ có ở demo hoặc tạo bằng script | `home/dependencies.py:13-28`, các route energy/billing/copilot | ✓ |
| A4 | Trung bình | Không có mời, đổi vai, gỡ thành viên hay rời nhà. Chủ nhà còn người khác thì không xóa được tài khoản | `home/routes/home.py` (3 route), `account.py` | ✓ |
| A5 | Thấp | Giới hạn tạo tài khoản khách theo `X-Demo-Visitor` do client chuyển tiếp, đếm trong bộ nhớ (trần chung 500 vẫn có) | `auth/services/demo.py:55-70` | ○ |

## B. Độ chi tiết và thời hạn lưu

| ID | Mức | Vấn đề | Bằng chứng | Kiểm |
|---|---|---|---|---|
| B1 | Cao | Bản tổng hợp **theo giờ** (công tơ và từng thiết bị) không có hạn xóa | migration `c8a4e1f7b295` | ✓ |
| B2 | Trung bình | Số đo thô khoảng 10 giây giữ 400 ngày, trong khi NILM và dashboard cần ít hơn nhiều (thô 7–14 ngày, trừ lượt đầu của nhà mới đọc 90 ngày) | `nilm` `config.py:34`, `runner.py:86` | ○ |
| B3 | Trung bình | Lượt chạy thiết bị (giờ bật/tắt tới phút), cảnh báo, hóa đơn, dự báo, nội dung chat kèm số liệu và SQL đều giữ mãi | `tb_device_cycle`, `tb_alert`, `ai_message`, `ai_tool_call` | ○ |

Ràng buộc đọc lịch sử (dùng khi chốt thời hạn): phút khoảng 65 ngày; giờ 365 ngày (huấn luyện expect);
ngày khoảng 25 tháng (dựng lại hóa đơn). Biểu đồ chọn độ phân giải theo độ dài cửa sổ, không theo tuổi
dữ liệu (`meter.py:21-31`).

## C. Xóa lịch sử

| ID | Mức | Vấn đề | Bằng chứng | Kiểm |
|---|---|---|---|---|
| C1 | Cao | Không xóa riêng được lịch sử điện; chỉ có xóa cả tài khoản | route list, `energy/services/erase.py` | ✓ |
| C2 | Trung bình | Xóa tài khoản để lại `ai.dim_home` (tỉnh, loại nhà, diện tích, số người, năm xây), chỉ đánh dấu `is_deleted` | migration `a4c7e1d93b62` | ✓ |
| C3 | Thấp | Còn lại công tơ (`last_seen_at`), `tb_ingest_batch`, file mô hình NILM riêng từng nhà | `account.py:43` | ○ |
| C4 | Ghi chú | Công tơ gửi lại lô cũ sẽ đưa dữ liệu đã xóa quay lại (ảnh hưởng nếu có xóa theo mốc) | `ingest.py:70` | ○ |

## D. Dịch vụ ngoài

| ID | Mức | Vấn đề | Bằng chứng | Kiểm |
|---|---|---|---|---|
| D1 | Cao | Bấm 👎 gửi câu hỏi (600 ký tự) và câu trả lời (1500 ký tự, có số liệu nhà) tới Telegram; người dùng không được báo | `copilot/routes/copilot.py:99-112`, biến Telegram đang đặt | ✓ |
| D2 | Cao | `query_data` đọc được số đo theo phút, giờ bật/tắt thiết bị, tên nhà, mã bưu chính, số người; tới 30 dòng gửi cho LLM bên ngoài | migration `4d7b1e9a3c52`, `tools.py:61,774-822` | ✓ |
| D3 | Trung bình | Không lời gọi OpenRouter nào đặt `data_collection`/`zdr`. Cài đặt cấp tài khoản chưa kiểm | grep `app`, text2sql | ✓ |
| D4 | Trung bình | Giọng nói gửi nguyên âm thanh sang AstralX trước khi che; câu trả lời cũ và kết quả công cụ gửi lại không che | `voice.py:51`, `chat.py:24` | ○ |
| D5 | Trung bình | Khung chat và nút ghi âm không nói dữ liệu được gửi ra ngoài, gửi cho ai | `apps/dashboard/messages/*/copilot.json` | ○ |

Bên nhận dữ liệu tìm thấy: OpenRouter (chat, guard, embeddings, reranker), AstralX (chat dự phòng,
embeddings, STT, TTS), OpenWeather (chỉ tọa độ tỉnh), Telegram, Google (đăng nhập), SMTP (hiện là
mailpit cục bộ). Không thấy Langfuse, LangSmith, Sentry hay web analytics.

## E. Trang quyền riêng tư nói khác code (`apps/web/messages/*/legal.json`)

| ID | Vấn đề |
|---|---|
| E1 | Không nhắc Telegram, không nói người bảo trì đọc câu trả lời bị 👎 (D1) |
| E2 | Nói chỉ gửi "các con số"; thực tế có số theo phút, giờ bật/tắt, thông tin nhà, tên thiết bị (D2) |
| E3 | "Thay bằng nhãn trước khi lưu hoặc gửi đi" không đúng với giọng nói (D4) |
| E4 | "Số đo theo phút… 400 ngày": số đo thô thật ra khoảng 10 giây |
| E5 | Mục thời hạn thiếu lượt chạy thiết bị, hóa đơn, dự báo, SQL của chat; sai với watch (90 ngày) và âm thanh đọc (30 ngày) |
| E6 | "Xóa cả ngôi nhà" không đúng hoàn toàn (C2, C3) |
| E7 | Bảo "để họ rời nhà trước" nhưng không có chức năng rời nhà (A4) |
| E8 | Không nói mô hình dự đoán mức dùng được huấn luyện trên dữ liệu của chính người dùng |
| E9 | Không nêu guard, embeddings, reranker, SMTP |

## F. Minh chứng còn thiếu

| ID | Minh chứng | Hiện trạng |
|---|---|---|
| F1 | Sơ đồ luồng dữ liệu | `wattprint-web/docs/diagrams` chỉ có sơ đồ kiến trúc và đăng nhập |
| F2 | Màn hình quyền riêng tư trong ứng dụng | Chỉ có trang chính sách (chữ) và mục xóa tài khoản |
| F3 | Thử phân quyền | Chưa rà xem test hiện có phủ tới đâu theo từng vai trò |

## G. Đã kiểm, không thấy lỗi

- Không thấy IDOR hay lộ chéo giữa các nhà; mọi route lấy nhà từ tư cách thành viên.
- Viewer không ghi được trạng thái chung của nhà.
- View `copilot_ro` lọc theo scope token; vai `wattprint_copilot_ro` không đọc được bảng gốc.
- Khách demo không thấy chat, kế hoạch, cảnh báo đã đặt của nhau.
- WattPrint không gửi `user_id` nên text2sql không lưu lượt hỏi (chỉ có bản chụp tạm, có hạn, khi hỏi lại).
- Không thấy câu hỏi của người dùng bị ghi vào log; còn vài log lỗi có thể chứa email hoặc phản hồi dịch vụ.

## H. Chưa kiểm

- Kết nối text2sql đã lưu đăng nhập bằng vai DB nào (URI mã hóa). Nếu không phải `wattprint_copilot_ro`
  thì cách ly ở mục G không còn đúng.
- Cài đặt tài khoản OpenRouter/AstralX; nhà cung cấp phía sau model `byok`.
- Backup và log trên máy prod; SMTP của Keycloak.
- Chưa chạy test hay thử xâm nhập thật.
