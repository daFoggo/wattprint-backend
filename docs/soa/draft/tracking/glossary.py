"""Từ điển thuật ngữ và danh sách dấu hiệu văn "slop" của báo cáo và slide SOA WattPrint.
Nguồn duy nhất cho: check_terms.py (đếm vi phạm), apply_glossary.py (thay tự động), TU-DIEN-THUAT-NGU.md (sinh ra).
TERMS: (mẫu regex cần tránh, thay bằng, ghi chú, auto) - auto=True thì apply_glossary.py được thay thẳng, thứ tự trên xuống dưới.
"""
TERMS = [
    # luồng ingest & sensor
    (r"\bnhận số đo\b", "ingest dữ liệu sensor", "Ingest là thuật ngữ chuẩn của luồng nhận dữ liệu vào hệ thống", True),
    (r"\bNhận số đo\b", "Ingest dữ liệu sensor", "như trên, đầu câu", True),
    (r"\bthu thập số đo\b", "ingest dữ liệu sensor", "như trên", True),
    (r"\bThu thập số đo\b", "Ingest dữ liệu sensor", "như trên, đầu câu", True),
    # độ tin cậy, messaging, kiến trúc SOA
    (r"\bhàng đợi lỗi\b", "DLQ", "DLQ (dead-letter queue) là tên chuẩn, đã định nghĩa ở danh mục viết tắt", True),
    (r"\bgiới hạn giao lại\b", "giới hạn redelivery", "Theo tên cấu hình delivery-limit của RabbitMQ", True),
    (r"\bvòng phụ thuộc\b", "circular dependency", "Thuật ngữ kiến trúc chuẩn", True),
    (r"\bbản sao dữ liệu tiêu thụ\b", "read model dữ liệu tiêu thụ", "CQRS gọi là read model", True),
    (r"\bnguồn dữ liệu gốc duy nhất \(`source of truth`\)", "`source of truth` duy nhất", "Không dịch song song hai cách", True),
    (r"\bcall hàm\b", "gọi hàm", "Không ghép 'call hàm' trong văn bản kỹ thuật tiếng Việt", True),
    (r"\bchữ của tri thức\b", "văn bản gốc của tri thức", "Tránh dịch word-by-word từ 'text'", True),
    (r"\bChữ gốc\b", "Văn bản gốc", "Tránh dịch word-by-word từ 'raw text / source text'", True),
    (r"\bchữ gốc\b", "văn bản gốc", "Tránh dịch word-by-word từ 'raw text / source text'", True),
    # chưa tự động, cần viết lại theo ngữ cảnh
    (r"một lệnh", "(viết lại)", "Compose là cách chạy môi trường demo/dev. Production chạy trên orchestrator. Không nhấn 'một lệnh' như tiêu chí kiến trúc", False),
]

# dấu hiệu văn AI slop (tiếng Việt), chỉ để đếm và soát tay
SLOP = [
    (r"đóng vai trò", "câu mở sáo rỗng, nói thẳng chức năng"),
    (r"không chỉ .{0,40} mà còn", "cấu trúc 'không chỉ... mà còn'"),
    (r"toàn diện|mạnh mẽ|đột phá|vượt trội|tối ưu hóa|linh hoạt", "tính từ hoa mỹ không kèm số liệu"),
    (r"(?:^|[.!?]\s)(?:Ngoài ra|Bên cạnh đó|Hơn nữa|Đặc biệt|Nhìn chung|Tóm lại),", "từ nối đầu câu lặp"),
    (r"quan trọng nhất|cốt lõi|then chốt", "nhấn mạnh chung chung"),
    (r"—", "dấu gạch ngang dài"),
    (r";", "dấu chấm phẩy liệt kê ý"),
    (r"chúng tôi|chúng em", "chỉ xưng 'Nhóm' trong báo cáo"),
    (r"\bmock\b", "không dùng 'mock' trong kiến trúc"),
    (r"có thể giúp|có thể mang lại|đảm bảo rằng", "câu giáo trình, hedge hoặc đệm"),
    (r"Thứ nhất,.*Thứ hai,.*Thứ ba,", "liệt kê đếm số máy móc trong đoạn văn"),
]
