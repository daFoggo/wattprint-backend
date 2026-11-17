# Từ điển thuật ngữ và theo dõi văn phong

Sinh từ `tracking/glossary.py`. Sửa ở đó rồi chạy `python tracking/check_terms.py --md`.

## Thuật ngữ thống nhất

| Tránh | Dùng | Ghi chú | Thay tự động |
|---|---|---|---|
| `\bnhận số đo\b` | ingest dữ liệu sensor | Ingest là thuật ngữ chuẩn của luồng nhận dữ liệu vào hệ thống | có |
| `\bNhận số đo\b` | Ingest dữ liệu sensor | như trên, đầu câu | có |
| `\bthu thập số đo\b` | ingest dữ liệu sensor | như trên | có |
| `\bThu thập số đo\b` | Ingest dữ liệu sensor | như trên, đầu câu | có |
| `\bhàng đợi lỗi\b` | DLQ | DLQ (dead-letter queue) là tên chuẩn, đã định nghĩa ở danh mục viết tắt | có |
| `\bgiới hạn giao lại\b` | giới hạn redelivery | Theo tên cấu hình delivery-limit của RabbitMQ | có |
| `\bvòng phụ thuộc\b` | circular dependency | Thuật ngữ kiến trúc chuẩn | có |
| `\bbản sao dữ liệu tiêu thụ\b` | read model dữ liệu tiêu thụ | CQRS gọi là read model | có |
| `\bnguồn dữ liệu gốc duy nhất \(`source of truth`\)` | `source of truth` duy nhất | Không dịch song song hai cách | có |
| `\bcall hàm\b` | gọi hàm | Không ghép 'call hàm' trong văn bản kỹ thuật tiếng Việt | có |
| `\bchữ của tri thức\b` | văn bản gốc của tri thức | Tránh dịch word-by-word từ 'text' | có |
| `\bChữ gốc\b` | Văn bản gốc | Tránh dịch word-by-word từ 'raw text / source text' | có |
| `\bchữ gốc\b` | văn bản gốc | Tránh dịch word-by-word từ 'raw text / source text' | có |
| `một lệnh` | (viết lại) | Compose là cách chạy môi trường demo/dev. Production chạy trên orchestrator. Không nhấn 'một lệnh' như tiêu chí kiến trúc | không, viết lại tay |

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
| `chúng tôi/chúng em` | chỉ xưng 'Nhóm' trong báo cáo |
| `\bmock\b` | không dùng 'mock' trong kiến trúc |
| `có thể giúp/có thể mang lại/đảm bảo rằng` | câu giáo trình, hedge hoặc đệm |
| `Thứ nhất,.*Thứ hai,.*Thứ ba,` | liệt kê đếm số máy móc trong đoạn văn |
