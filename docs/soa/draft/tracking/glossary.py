"""Từ điển thuật ngữ và danh sách dấu hiệu văn "slop" của báo cáo và slide SOA WattPrint.
Nguồn duy nhất cho: check_terms.py (đếm vi phạm), apply_glossary.py (thay tự động), TU-DIEN-THUAT-NGU.md (sinh ra).
TERMS: (mẫu regex cần tránh, thay bằng, ghi chú, auto) - auto=True thì apply_glossary.py được thay thẳng, thứ tự trên xuống dưới.
"""
TERMS = [
    # dữ liệu sensor
    (r"\bnhận số đo\b", "ingest dữ liệu sensor", "Ingest là từ chuẩn của luồng nhận dữ liệu vào hệ thống", True),
    (r"\bNhận số đo\b", "Ingest dữ liệu sensor", "như trên, đầu câu", True),
    (r"\bthu thập số đo\b", "ingest dữ liệu sensor", "như trên", True),
    (r"\bThu thập số đo\b", "Ingest dữ liệu sensor", "như trên, đầu câu", True),
    (r"\bsố đo\b", "dữ liệu sensor", "Thống nhất theo quyết định của nhóm: dữ liệu sensor, không dùng 'số đo'", True),
    (r"\bSố đo\b", "Dữ liệu sensor", "như trên, đầu câu", True),
    (r"\bcảm biến\b", "sensor", "Sensor là thuật ngữ IoT quen thuộc. Riêng '10 điểm đo' ở phần pitch giữ nguyên", True),
    (r"\bCảm biến\b", "Sensor", "như trên, đầu câu", True),
    # độ tin cậy, messaging
    (r"\bhàng đợi lỗi\b", "DLQ", "DLQ (dead-letter queue) là tên chuẩn, đã định nghĩa ở danh mục viết tắt", True),
    (r"\bcô lập lỗi\b", "fault isolation", "Thuật ngữ SOA/microservices chuẩn", True),
    (r"\bchịu lỗi\b", "fault tolerance", "Thuật ngữ chuẩn", True),
    (r"\bgiới hạn giao lại\b", "giới hạn redelivery", "Theo tên cấu hình delivery-limit của RabbitMQ", True),
    (r"\bgiao lại\b", "redeliver", "Broker giao lại message gọi là redelivery", True),
    (r"\bthử lại\b", "retry", "Dùng retry xuyên suốt", True),
    (r"\bgửi lại\b", "retry", "Dùng retry xuyên suốt", True),
    (r"\bvòng phụ thuộc\b", "circular dependency", "Thuật ngữ kiến trúc chuẩn", True),
    (r"\btác vụ nền\b", "background job", "Thuật ngữ chuẩn", True),
    (r"\blời gọi\b", "call", "call đồng bộ, call mạng, call hàm", True),
    (r"\btiến trình\b", "process", "Dùng process cho nhất quán với 'cùng process'", True),
    (r"\bbản sao dữ liệu tiêu thụ\b", "read model dữ liệu tiêu thụ", "CQRS gọi là read model", True),
    (r"\bnguồn dữ liệu gốc duy nhất \(`source of truth`\)", "`source of truth` duy nhất", "Không dịch song song hai cách", True),
    (r"Suy luận", "Inference", "Dùng inference cho NILM/model, nhất quán với báo cáo", True),
    (r"suy luận", "inference", "như trên", True),
    (r"Sự kiện", "Event", "Trong sơ đồ và slide dùng 'event'", True),
    (r"sự kiện", "event", "Trong sơ đồ và slide dùng 'event'. Báo cáo văn xuôi có thể giữ 'sự kiện' khi đọc tự nhiên hơn", True),
    # chưa tự động, cần viết lại theo ngữ cảnh
    (r"một lệnh", "(viết lại)", "Compose là cách chạy môi trường demo/dev. Production chạy trên orchestrator. Không nhấn 'một lệnh' như tiêu chí kiến trúc", False),
    (r"hộ gia đình", "(giữ khi nói về người dùng; dùng `home` khi nói về thực thể dữ liệu)", "Tránh lặp 'hộ gia đình' quá nhiều trong mô tả kỹ thuật", False),
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
    (r"chúng tôi|chúng em", "chỉ xưng 'Nhóm'"),
    (r"\bmock\b", "không dùng 'mock' trong kiến trúc"),
    (r"có thể giúp|có thể mang lại|đảm bảo rằng", "câu giáo trình, hedge hoặc đệm"),
]
