Business rules# Từ điển thuật ngữ và theo dõi văn phong

Sinh từ `tracking/glossary.py`. Sửa ở đó rồi chạy `python tracking/check_terms.py --md`.

## Thuật ngữ thống nhất

| Tránh | Dùng | Ghi chú | Thay tự động |
|---|---|---|---|
| `\bnhận số đo\b` | ingest dữ liệu sensor | Ingest là từ chuẩn của luồng nhận dữ liệu vào hệ thống | có |
| `\bNhận số đo\b` | Ingest dữ liệu sensor | như trên, đầu câu | có |
| `\bthu thập số đo\b` | ingest dữ liệu sensor | như trên | có |
| `\bThu thập số đo\b` | Ingest dữ liệu sensor | như trên, đầu câu | có |
| `\bsố đo\b` | dữ liệu sensor | Thống nhất theo quyết định của nhóm: dữ liệu sensor, không dùng 'số đo' | có |
| `\bSố đo\b` | Dữ liệu sensor | như trên, đầu câu | có |
| `\bcảm biến\b` | sensor | Sensor là thuật ngữ IoT quen thuộc. Riêng '10 điểm đo' ở phần pitch giữ nguyên | có |
| `\bCảm biến\b` | Sensor | như trên, đầu câu | có |
| `\bhàng đợi lỗi\b` | DLQ | DLQ (dead-letter queue) là tên chuẩn, đã định nghĩa ở danh mục viết tắt | có |
| `\bcô lập lỗi\b` | fault isolation | Thuật ngữ SOA/microservices chuẩn | có |
| `\bchịu lỗi\b` | fault tolerance | Thuật ngữ chuẩn | có |
| `\bgiới hạn giao lại\b` | giới hạn redelivery | Theo tên cấu hình delivery-limit của RabbitMQ | có |
| `\bgiao lại\b` | redeliver | Broker giao lại message gọi là redelivery | có |
| `\bthử lại\b` | retry | Dùng retry xuyên suốt | có |
| `\bgửi lại\b` | retry | Dùng retry xuyên suốt | có |
| `\bvòng phụ thuộc\b` | circular dependency | Thuật ngữ kiến trúc chuẩn | có |
| `\btác vụ nền\b` | background job | Thuật ngữ chuẩn | có |
| `\blời gọi\b` | call | call đồng bộ, call mạng, call hàm | có |
| `\btiến trình\b` | process | Dùng process cho nhất quán với 'cùng process' | có |
| `\bbản sao dữ liệu tiêu thụ\b` | read model dữ liệu tiêu thụ | CQRS gọi là read model | có |
| `\bnguồn dữ liệu gốc duy nhất \(`source of truth`\)` | `source of truth` duy nhất | Không dịch song song hai cách | có |
| `Suy luận` | Inference | Dùng inference cho NILM/model, nhất quán với báo cáo | có |
| `suy luận` | inference | như trên | có |
| `Sự kiện` | Event | Trong sơ đồ và slide dùng 'event' | có |
| `sự kiện` | event | Trong sơ đồ và slide dùng 'event'. Báo cáo văn xuôi có thể giữ 'sự kiện' khi đọc tự nhiên hơn | có |
| `một lệnh` | (viết lại) | Compose là cách chạy môi trường demo/dev. Production chạy trên orchestrator. Không nhấn 'một lệnh' như tiêu chí kiến trúc | không, viết lại tay |
| `hộ gia đình` | (giữ khi nói về người dùng; dùng `home` khi nói về thực thể dữ liệu) | Tránh lặp 'hộ gia đình' quá nhiều trong mô tả kỹ thuật | không, viết lại tay |

## Dấu hiệu văn slop cần soát

| Mẫu | Vì sao |
|---|---|
| `đóng vai trò` | câu mở sáo rỗng, nói thẳng chức năng |
| `không chỉ .{0,40} mà còn` | cấu trúc 'không chỉ... mà còn' |
| `toàn diện/mạnh mẽ/đột phá/vượt trội/tối ưu hóa/linh hoạt` | tính từ hoa mỹ không kèm số liệu |
| `(?:^/[.!?]\s)(?:Ngoài ra/Bên cạnh đó/Hơn nữa/Đặc biệt/Nhìn chung/Tóm lại),` | từ nối đầu câu lặp |
| `quan trọng nhất/cốt lõi/then chốt` | nhấn mạnh chung chung |
| `—` | dấu gạch ngang dài |
| `;` | dấu chấm phẩy liệt kê ý |
| `chúng tôi/chúng em` | chỉ xưng 'Nhóm' |
| `\bmock\b` | không dùng 'mock' trong kiến trúc |
| `có thể giúp/có thể mang lại/đảm bảo rằng` | câu giáo trình, hedge hoặc đệm |
