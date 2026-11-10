# -*- coding: utf-8 -*-
# Nội dung báo cáo. Markup: **đậm**, //nghiêng//, `mã`, [@khóa] = trích dẫn tự đánh số theo thứ tự xuất hiện.

REFS = {
 "ta": 'C. Ta, "Usage information to save electricity in Vietnam," International Growth Centre (IGC), 2025. https://www.theigc.org/blogs/usage-information-vietnam-save-electricity',
 "attari": 'S. Z. Attari, M. L. DeKay, C. I. Davidson, W. Bruine de Bruin, "Public perceptions of energy consumption and savings," PNAS, vol. 107, no. 37, 2010. https://pmc.ncbi.nlm.nih.gov/articles/PMC2941272/',
 "sggp": 'Báo Sài Gòn Giải Phóng, "Tra cứu tiền điện hằng ngày trên app dùng chung của EVN," 22/06/2026. https://www.sggp.org.vn/tra-cuu-tien-dien-hang-ngay-tren-app-dung-chung-cua-evn-post858550.html',
 "tuya": 'Tuya.vn, "Ổ cắm WiFi đo điện TC1," giá niêm yết 235.000 đồng. https://tuya.vn/o-cam-c-smart-series-wifi-cong-suat-lon-16a-tuya-tc1-p40701967.html',
 "ha": 'Home Assistant, "Home Assistant Green," giá niêm yết 199 USD. https://www.home-assistant.io/green/',
 "buckley": 'P. Buckley, "Prices, information and nudges for residential electricity conservation: A meta-analysis," Ecological Economics, vol. 172, 2020.',
 "nguyen": 'N. N. Nguyen, D. Goto, D. Tran, H. T. Vu, "Nudging households to save electricity with feedback: Experimental evidence from Vietnam," Energy Policy, vol. 195, 2024.',
 "hart": 'G. W. Hart, "Nonintrusive appliance load monitoring," Proceedings of the IEEE, vol. 80, no. 12, pp. 1870-1891, 1992.',
 "nilmformer": 'A. Petralia, P. Charpentier, Y. Kadhi, T. Palpanas, "NILMFormer: Non-Intrusive Load Monitoring that Accounts for Non-Stationarity," ACM SIGKDD, 2025. arXiv:2506.05880.',
 "refit": 'D. Murray, L. Stankovic, V. Stankovic, "An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study," Scientific Data, vol. 4, 160122, 2017.',
 "c4": 'S. Brown, "The C4 model for visualising software architecture." https://c4model.com',
 "newman": 'S. Newman, Building Microservices, 2nd ed., O\'Reilly Media, 2021.',
 "richardson": 'C. Richardson, Microservices Patterns, Manning Publications, 2018.',
 "envoy": 'Envoy Project, "JWT Authentication" (http_filters/jwt_authn_filter), tài liệu Envoy. https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/jwt_authn_filter',
 "rabbit": 'Broadcom, "Quorum Queues," tài liệu RabbitMQ. https://www.rabbitmq.com/docs/quorum-queues',
 "nygard": 'M. T. Nygard, Release It!, 2nd ed., Pragmatic Bookshelf, 2018.',
}

ABBR = [
 ("API", "Giao diện lập trình ứng dụng (Application Programming Interface)"),
 ("AMQP", "Giao thức truyền message mà RabbitMQ sử dụng (Advanced Message Queuing Protocol)"),
 ("BR", "Quy tắc nghiệp vụ (Business Rule), đánh mã BR1 đến BR9 ở mục 2.3"),
 ("C4", "Mô hình mô tả kiến trúc phần mềm theo bốn cấp: Context, Container, Component, Code"),
 ("CQRS", "Pattern tách luồng ghi và luồng đọc dữ liệu (Command Query Responsibility Segregation)"),
 ("CT", "Sensor dòng điện kẹp ngoài dây dẫn (Current Transformer)"),
 ("DLQ", "Hàng đợi lưu các message xử lý lỗi quá số lần retry (Dead Letter Queue)"),
 ("EVN", "Tập đoàn Điện lực Việt Nam"),
 ("Gateway", "API Gateway, cổng giao tiếp duy nhất đón request từ bên ngoài vào hệ thống"),
 ("JWT", "Token xác thực có chữ ký số do Keycloak cấp (JSON Web Token)"),
 ("JWKS", "Tập khóa công khai dùng để xác thực chữ ký JWT (JSON Web Key Set)"),
 ("LLM", "Mô hình ngôn ngữ lớn (Large Language Model)"),
 ("M&V", "Đo lường và kiểm chứng mức tiết kiệm điện (Measurement and Verification)"),
 ("NILM", "Kỹ thuật tách điện năng từng thiết bị từ công suất tổng (Non-Intrusive Load Monitoring)"),
 ("OIDC", "Giao thức xác thực OpenID Connect"),
 ("Outbox, Inbox", "Hai bảng trong database giúp gửi event không mất (outbox) và nhận event không trùng (inbox), xem mục 3.5"),
 ("PII", "Thông tin định danh cá nhân (Personally Identifiable Information)"),
 ("RAG", "Kỹ thuật truy xuất tri thức trước khi sinh câu trả lời (Retrieval-Augmented Generation)"),
 ("REFIT", "Bộ dữ liệu công khai đo điện năng hộ gia đình tại Vương quốc Anh"),
 ("REST", "Kiến trúc thiết kế API qua HTTP (Representational State Transfer)"),
 ("SOA", "Kiến trúc hướng dịch vụ (Service-Oriented Architecture)"),
]

SUMMARY = [
 "Báo cáo trình bày quá trình phân tích nghiệp vụ và thiết kế kiến trúc microservices cho WattPrint, hệ thống giúp hộ gia đình theo dõi điện năng của từng thiết bị chỉ từ một điểm đo ở aptomat tổng và nhận gợi ý tiết kiệm điện từ trợ lý Energy Copilot. Xuất phát từ bài toán thực tế và nhu cầu người dùng, nhóm xác định chín quy tắc nghiệp vụ, rồi dựa trên ranh giới sở hữu dữ liệu, đặc thù tải và khả năng fault isolation để tách hệ thống thành bốn service nghiệp vụ là core, nilm, insight và copilot.",
 "Các service đứng sau một API Gateway, mỗi service có database riêng, gọi đồng bộ theo một chiều duy nhất và truyền event bất đồng bộ qua RabbitMQ kết hợp pattern Transactional Outbox/Inbox. Báo cáo ghi lại các phương án đã cân nhắc, lý do lựa chọn và những đánh đổi mà nhóm chấp nhận. Phần thiết kế API, kiểm thử độ tin cậy có số liệu, triển khai và đánh giá sẽ được trình bày ở các chương tiếp theo.",
]
KEYWORDS = "microservices, SOA, API Gateway, NILM, RabbitMQ, transactional outbox, Energy Copilot."

# ---- Thân báo cáo ----
# ("h1",t) ("h2",t) ("h3",t) ("p",t) ("ul",[..]) ("ol",[..]) ("table",cap,headers,rows,widths) ("fig",key,cap,w_cm,h_cm)
BODY = []
A = BODY.append

A(("h1", "CHƯƠNG 1. GIỚI THIỆU"))
A(("h2", "1.1. Bối cảnh"))
A(("p", "Tiền điện là khoản chi cố định hằng tháng của mỗi hộ gia đình, nhưng người dùng thường chỉ biết tổng số tiền cuối tháng mà không rõ thiết bị nào tiêu thụ bao nhiêu. Một thử nghiệm trên 45.000 hộ tại Việt Nam cho thấy chỉ cần cung cấp ước tính tiền điện theo ngày, các hộ nhận thông tin đã giảm tiêu thụ điện so với nhóm đối chứng [@ta]. Phản hồi kịp thời đủ để thúc đẩy thay đổi thói quen, nhưng muốn biết cần tiết kiệm ở đâu thì người dùng phải nắm được mức tiêu thụ của từng thiết bị. Một nghiên cứu tại Mỹ chỉ ra rằng người tiêu dùng thường ước tính thấp điện năng của thiết bị khoảng 2,8 lần, và sai lệch lớn nhất lại rơi vào những thiết bị ngốn nhiều điện nhất [@attari]."))
A(("p", "Các công cụ hiện có chưa giải quyết được khoảng trống này. Ứng dụng của EVN mới chỉ hiển thị tổng điện năng theo ngày của cả hộ [@sggp]. Nếu lắp ổ cắm thông minh để đo riêng từng thiết bị, mỗi ổ có giá khoảng 235.000 đồng [@tuya]. Để theo dõi khoảng 10 điểm đo kèm bộ điều khiển trung tâm [@ha], hộ gia đình phải chi từ 4 đến 10 triệu đồng, tự lắp đặt và cấu hình mạng, trong khi ổ cắm rời cũng không đo được thiết bị đấu trực tiếp vào đường dây âm tường như điều hòa hay đèn trần."))
A(("p", "Bài toán đặt ra cho dự án là làm sao ước tính điện năng từng thiết bị với chi phí phần cứng thấp hơn nhiều. Nhóm lựa chọn hướng tiếp cận Non-Intrusive Load Monitoring (NILM) do Hart đề xuất năm 1992 [@hart]: chỉ đo tổng công suất tại aptomat chính, sau đó dùng mô hình học máy để tách ra công suất của từng thiết bị."))

A(("h2", "1.2. Giải pháp WattPrint"))
A(("p", "WattPrint gồm bốn khối chức năng liên kết nhau, đi từ dữ liệu sensor thô đến khuyến nghị hành động cụ thể:"))
A(("ol", [
 "Khối tách điện năng từng thiết bị (NILM) sử dụng NILMFormer [@nilmformer], mô hình dựa trên Transformer tách tải tốt ngay cả khi tổng công suất biến động mạnh, kết hợp bước hiệu chỉnh (calibration) theo từng hộ.",
 "Khối dashboard và tính hóa đơn hiển thị điện năng từng thiết bị theo giờ, ngày, tuần, tháng và quy đổi mọi số liệu kWh ra tiền điện theo biểu giá sinh hoạt 5 bậc.",
 "Khối phân tích và dự báo cảnh báo thiết bị chạy lâu bất thường, phát hiện điện tiêu thụ ngầm (standby), so sánh với tháng trước và với các hộ tương đồng, kết hợp dự báo hóa đơn cuối tháng và thời điểm chạm bậc giá kế tiếp.",
 "Khối Energy Copilot là trợ lý AI hai chiều, vừa trả lời câu hỏi của người dùng (pull), vừa chủ động gửi gợi ý tiết kiệm (push). Mọi con số đều do các tool tính từ dữ liệu thực của hộ, còn LLM chỉ diễn giải. Copilot cũng hỗ trợ lập kế hoạch tiết kiệm và đối chiếu kết quả trước và sau khi áp dụng.",
]))
A(("p", "Về tác động kỳ vọng, các nghiên cứu trước đây cho thấy phản hồi thông tin điện năng giúp hộ gia đình giảm khoảng 2-4% mức tiêu thụ [@buckley], riêng thử nghiệm trên khoảng 1.000 hộ tại Đà Nẵng ghi nhận mức giảm 4-7% [@nguyen]. Đây là kết quả từ các nghiên cứu đi trước để nhóm làm mốc tham chiếu, chưa phải số liệu đo thực tế của WattPrint."))

A(("h2", "1.3. Phạm vi của bài tập lớn"))
A(("p", "Trước bài tập lớn này, nhóm đã xây dựng WattPrint dưới dạng monolith (một ứng dụng FastAPI duy nhất) chạy đủ các chức năng trên. Bài tập lớn thực hiện tách bản monolith này thành các microservice độc lập, nên phần phân tích tập trung vào việc xác định ranh giới tách service và cơ chế phối hợp giữa chúng. Phạm vi thực hiện gồm:"))
A(("ul", [
 "Bốn service nghiệp vụ đứng sau API Gateway, tích hợp xác thực, database riêng cho từng service và message broker truyền event. Mỗi service có Dockerfile riêng, môi trường demo được dựng bằng Docker Compose.",
 "Service `nilm` chỉ chạy inference với trọng số NILMFormer đã nạp sẵn. Việc huấn luyện và đánh giá độ chính xác của mô hình nằm ngoài phạm vi bài tập này.",
 "Do không có sensor phần cứng thật, nhóm dùng bộ dữ liệu công khai REFIT [@refit] và phát lại (replay) luồng dữ liệu sensor qua gateway (mục 2.5).",
 "Giữ nguyên hai ứng dụng client sẵn có (mobile app Expo và web Next.js), chỉ cấu hình lại địa chỉ API trỏ về gateway.",
]))

A(("h2", "1.4. Yêu cầu của đề bài"))
A(("p", "Đề bài yêu cầu xây dựng hệ thống microservices có API Gateway và đóng gói bằng container. Với nhóm ba người, hệ thống cần tối thiểu ba service nghiệp vụ không tính gateway, mỗi service có mã nguồn và dữ liệu riêng. Mỗi service phải có ít nhất bốn REST endpoint kèm đặc tả OpenAPI, call giữa các service phải cấu hình timeout và retry, và ít nhất một luồng nghiệp vụ đi qua hai service phải xử lý được lỗi xảy ra giữa chừng. Phần kiểm thử yêu cầu Postman collection và thực nghiệm ít nhất hai tình huống lỗi có số liệu đo trước và sau khi áp dụng cơ chế fault tolerance."))
A(("p", "Ngoài phần bắt buộc, nhóm triển khai cả bốn mục điểm cộng: truyền event qua RabbitMQ với consumer đảm bảo idempotent và có DLQ, xác thực JWT tại gateway, cài đặt circuit breaker và bulkhead, cùng pipeline CI chạy test tự động. Chương 3 và Chương 4 làm rõ cách từng yêu cầu này định hình kiến trúc hệ thống."))

A(("h2", "1.5. Cấu trúc báo cáo"))
A(("p", "Chương 2 phân tích miền nghiệp vụ gồm các tác nhân tương tác, sáu nhóm chức năng, chín quy tắc nghiệp vụ, các yêu cầu phi chức năng và cơ chế phát lại nguồn dữ liệu sensor. Chương 3 trình bày thiết kế kiến trúc theo mô hình C4: tiêu chí tách service, cấu trúc container triển khai, giao tiếp đồng bộ và bất đồng bộ, xử lý luồng đa bước, phân tách dữ liệu, bảo mật tại gateway, lựa chọn công nghệ và các module bên trong từng service. Chương 4 tổng hợp những đánh đổi kiến trúc và rủi ro cần kiểm soát. Phần thiết kế chi tiết API, độ tin cậy có số liệu thực nghiệm, triển khai, kiểm thử và đánh giá sẽ được bổ sung ở các chương tiếp theo khi hoàn tất phần hiện thực."))

# ---------------- Chương 2 ----------------
A(("h1", "CHƯƠNG 2. PHÂN TÍCH NGHIỆP VỤ"))
A(("h2", "2.1. Người dùng và các bên liên quan"))
A(("p", "Hệ thống tương tác với hai nhóm người dùng, một nguồn cấp dữ liệu sensor tự động và năm hệ thống bên ngoài. Bảng 2.1 tóm tắt vai trò của từng tác nhân và luồng tương tác chính với WattPrint."))
A(("table", "Bảng 2.1. Người dùng, nguồn dữ liệu và hệ thống bên ngoài",
   ["Đối tượng", "Vai trò", "Tương tác chính"],
   [["Thành viên hộ gia đình", "Người dùng cuối. Chủ hộ tạo hồ sơ hộ gia đình và mời thành viên", "Xem điện năng từng thiết bị, hóa đơn, cảnh báo. Hỏi đáp với Energy Copilot và nhận gợi ý qua push notification"],
    ["Nhóm vận hành", "Quản trị hệ thống WattPrint", "Quản lý hộ gia đình, công tơ, phiên bản model. Theo dõi log, xử lý message trong DLQ và nhận cảnh báo sự cố qua Telegram"],
    ["Sensor ở aptomat (REFIT replayer trong đồ án)", "Nguồn cấp dữ liệu sensor", "Định kỳ gửi từng batch công suất tổng lên hệ thống, xác thực bằng API key riêng của thiết bị"],
    ["Nhà cung cấp LLM", "Hệ thống ngoài", "Sinh câu trả lời, xử lý tool calling và tạo embedding cho Copilot. Chỉ nhận prompt đã ẩn PII"],
    ["Open-Meteo", "Hệ thống ngoài", "Cung cấp dữ liệu nhiệt độ và độ ẩm theo giờ phục vụ phân tích phụ tải và gợi ý theo thời tiết"],
    ["Expo Push, Telegram", "Hệ thống ngoài", "Gửi push notification tới điện thoại người dùng và gửi cảnh báo cho nhóm vận hành"],
    ["Google Identity", "Hệ thống ngoài", "Xác thực đăng nhập bằng tài khoản Google (OIDC), liên kết qua Keycloak"]],
   [2400, 2600, 4071]))

A(("h2", "2.2. Các nhóm nghiệp vụ"))
A(("p", "Nghiệp vụ của WattPrint chia thành sáu nhóm, sắp xếp theo đường đi của dữ liệu từ khâu thiết lập hộ gia đình đến khi sinh khuyến nghị tiết kiệm cho người dùng (Bảng 2.2). Luồng dữ liệu này là cơ sở để nhóm xác định ranh giới tách service ở Chương 3."))
A(("table", "Bảng 2.2. Sáu nhóm nghiệp vụ của WattPrint",
   ["Nhóm", "Nội dung", "Dữ liệu tạo ra"],
   [["1. Quản lý hộ gia đình và thiết bị", "Tạo hồ sơ hộ gia đình, mời thành viên bằng mã, ghép nối công tơ, khai báo danh mục thiết bị theo phòng", "Hồ sơ hộ, thành viên, công tơ, thiết bị"],
    ["2. Ingest dữ liệu sensor", "Nhận batch công suất tổng từ sensor, kiểm tra tính liên tục, lưu chuỗi thời gian", "Chuỗi dữ liệu sensor theo thời gian"],
    ["3. Tách điện năng (NILM)", "Chạy inference ước tính công suất từng thiết bị từ dữ liệu sensor tổng, hiệu chỉnh theo hộ, quản lý phiên bản model", "Công suất ước tính theo thiết bị, lịch sử chạy inference"],
    ["4. Tính hóa đơn", "Tổng hợp kWh theo giờ, ngày, tháng và tính tiền điện theo biểu giá 5 bậc", "Hóa đơn, phiên bản biểu giá"],
    ["5. Phân tích và dự báo", "Cảnh báo bất thường, phát hiện tiêu thụ ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh hộ tương đồng, what-if, M&V", "Cảnh báo, bản ghi dự báo, baseline M&V"],
    ["6. Trợ lý Copilot", "Hỏi đáp tự nhiên, gợi ý chủ động, kế hoạch tiết kiệm, thông báo, ghi nhận phản hồi", "Hội thoại, gợi ý, kho tri thức RAG"]],
   [2300, 4571, 2200]))
A(("p", "Luồng xử lý chính chảy tuần tự từ trên xuống dưới Bảng 2.2. Sensor gửi batch công suất tổng, hệ thống lưu trữ rồi tách thành điện năng từng thiết bị và tính tiền (nhóm 2 đến nhóm 4). Dữ liệu sau khi tách làm đầu vào để phát hiện bất thường và dự báo chi phí (nhóm 5). Ở tầng cuối, Copilot dùng kết quả phân tích để giải đáp câu hỏi và chủ động gửi gợi ý cho người dùng (nhóm 6). Trong chuỗi này, bước chuyển từ ingest dữ liệu sensor sang chạy inference NILM (nhóm 2 gọi nhóm 3) và bước kích hoạt kế hoạch tiết kiệm (nhóm 6 gọi nhóm 5) đi qua nhiều service nên có thể gặp lỗi cục bộ giữa chừng. Nhóm thiết kế cơ chế xử lý riêng cho hai luồng đa bước này ở mục 3.6."))

A(("h2", "2.3. Quy tắc nghiệp vụ"))
A(("p", "Nhóm xác định chín quy tắc nghiệp vụ (Bảng 2.3). Một quy tắc chỉ được đưa vào bảng khi kiểm chứng được trực tiếp bằng code: nếu request vi phạm điều kiện, service phải từ chối thực thi (thường trả mã lỗi 4xx kèm lý do) hoặc chuyển nhánh xử lý."))
A(("table", "Bảng 2.3. Quy tắc nghiệp vụ",
   ["Mã", "Quy tắc", "Lý do"],
   [["BR1", "Mỗi tài khoản chỉ thuộc đúng một hộ (`home`). Thành viên mới tham gia bằng mã mời chỉ dùng một lần và có thời hạn", "Ngăn một tài khoản xem dữ liệu của nhiều hộ. Mã mời bị lộ chỉ có hiệu lực trong thời gian ngắn"],
    ["BR2", "Mỗi công tơ chỉ ghép nối với một hộ bằng mã pairing. Hệ thống chỉ ingest dữ liệu sensor từ công tơ đã ghép nối kèm API key của thiết bị", "Đảm bảo luồng dữ liệu sensor luôn gắn đúng hộ gia đình"],
    ["BR3", "Batch dữ liệu sensor phải idempotent và liên tục: gửi lặp cùng `Idempotency-Key` không ghi hai lần, khoảng thời gian của batch không được hở hoặc chồng lấp với batch liền trước", "Mạng lỗi hoặc sensor retry không làm sai lệch sản lượng điện"],
    ["BR4", "Tiền điện tính theo biểu giá sinh hoạt 5 bậc, áp dụng đúng phiên bản biểu giá có hiệu lực trong kỳ lập hóa đơn", "Đảm bảo hóa đơn đã chốt không đổi khi cập nhật biểu giá mới"],
    ["BR5", "Dự báo hóa đơn cần ít nhất 7 ngày dữ liệu, so sánh hộ tương đồng cần ít nhất 10 hộ, M&V cần ít nhất 14 ngày. Không đủ điều kiện thì trả lỗi 4xx kèm lý do", "Không đưa ra con số dự báo thiếu cơ sở thống kê. Giữ ẩn danh khi so sánh giữa các hộ"],
    ["BR6", "Energy Copilot chỉ mở cho thuê bao gói Pro. Gói thường vẫn dùng đầy đủ dashboard và các tính năng phân tích", "Phản ánh mô hình kinh doanh hai gói thuê bao của dự án"],
    ["BR7", "Thông báo chủ động giới hạn tối đa N thông báo mỗi ngày (N cấu hình được) và không gửi vào khung giờ nghỉ (`quiet hours`). Gợi ý bị từ chối sẽ bị hạ thứ hạng ở lần sau", "Tránh gửi thông báo dồn dập gây phiền người dùng"],
    ["BR8", "Mọi con số trong câu trả lời của Copilot đều do các tool tính từ dữ liệu của hộ, LLM chỉ diễn giải. Câu trả lời sai số liệu, đơn vị hoặc thiếu nguồn trích dẫn sẽ bị loại trước khi gửi", "Đảm bảo mọi con số tư vấn đều chính xác và kiểm chứng được"],
    ["BR9", "PII phải được ẩn trước khi gửi prompt cho nhà cung cấp LLM. Copilot chỉ được truy xuất dữ liệu thuộc hộ của người đang hỏi", "Bảo vệ quyền riêng tư và cô lập dữ liệu giữa các hộ"]],
   [800, 5071, 3200]))
A(("p", "Chín quy tắc trên cũng chỉ ra ranh giới sở hữu dữ liệu. BR1 đến BR4 gắn với dữ liệu vận hành gốc (hộ gia đình, công tơ, dữ liệu sensor, hóa đơn) nên cần quản lý tập trung tại một `source of truth` duy nhất. BR5 kiểm soát điều kiện của các thuật toán phân tích, còn BR6 đến BR9 điều chỉnh quyền truy cập và kiểm duyệt của trợ lý AI. Chương 3 dùng chính ranh giới này để tách service."))

A(("h2", "2.4. Yêu cầu phi chức năng"))
A(("p", "Năm yêu cầu phi chức năng dưới đây trực tiếp định hình kiến trúc microservices của hệ thống (Bảng 2.4)."))
A(("table", "Bảng 2.4. Yêu cầu phi chức năng và ảnh hưởng đến kiến trúc",
   ["Yêu cầu", "Diễn giải", "Ảnh hưởng đến kiến trúc"],
   [["Không mất, không trùng dữ liệu sensor", "Sensor thường retry batch khi mất mạng. Sai lệch ở dữ liệu sensor thô làm sai mọi kết quả tính tiền và phân tích phía sau", "Kiểm tra `Idempotency-Key`, kiểm tra batch liên tục, ghi dữ liệu và event trong cùng transaction (Transactional Outbox)"],
    ["Cô lập lỗi giữa các thành phần", "LLM phản hồi chậm hoặc model NILM quá tải không được làm gián đoạn luồng ingest dữ liệu sensor và dashboard", "Tách service theo đặc thù lỗi. Áp dụng timeout, retry, circuit breaker và trạng thái chờ (`PENDING`)"],
    ["Bảo mật và quyền riêng tư", "Chuỗi công suất tiêu thụ phản ánh chi tiết giờ giấc sinh hoạt của gia đình", "Xác thực JWT tại gateway. Ẩn PII trước khi gọi LLM. Mỗi service một database và một DB role riêng"],
    ["Dựng được toàn bộ hệ thống trên một máy để demo", "Đề bài yêu cầu chạy demo trực tiếp toàn hệ thống", "Mỗi service có Dockerfile và endpoint `/health`, `/ready` riêng. Môi trường demo gom bằng `docker-compose.yml` và giới hạn tổng số container"],
    ["Vừa sức vận hành của nhóm ba người", "Mỗi công nghệ thêm vào đều làm tăng chi phí học, cấu hình và gỡ lỗi", "Thống nhất một ngôn ngữ cho backend (Python), dùng thư viện chung, ưu tiên phần mềm có sẵn thay vì tự viết"]],
   [2300, 3200, 3571]))

A(("h2", "2.5. Nguồn dữ liệu sensor và dữ liệu thử"))
A(("p", "Trong thực tế, mỗi hộ lắp một sensor dòng điện (CT) tại aptomat tổng, chẳng hạn Shelly EM hoặc ESP32 chạy ESPHome. Sensor đo công suất tổng và định kỳ đẩy từng batch dữ liệu sensor qua HTTPS tới API Gateway. Do nhóm không có phần cứng đo thực tế, hệ thống sử dụng công cụ phát lại dữ liệu mang tên REFIT replayer."))
A(("p", "REFIT [@refit] là bộ dữ liệu công khai đo điện năng của các hộ gia đình tại Vương quốc Anh liên tục trong khoảng hai năm với chu kỳ 8 giây, gồm cả công suất tổng và công suất từng thiết bị. REFIT replayer là một script Python đọc các tệp CSV của REFIT rồi gửi từng batch qua gateway, sử dụng đúng REST endpoint, API key thiết bị và `Idempotency-Key` như sensor thật, kèm tùy chọn tua nhanh thời gian khi demo. Nhờ vậy các service phía sau gateway xử lý hai nguồn dữ liệu hoàn toàn giống nhau. Trên các sơ đồ kiến trúc, replayer được vẽ như nguồn cấp dữ liệu sensor bên ngoài kèm ghi chú đây là công cụ phát lại từ bộ dữ liệu công khai (public dataset)."))

# ---------------- Chương 3 ----------------
A(("h1", "CHƯƠNG 3. PHÂN TÍCH VÀ THIẾT KẾ KIẾN TRÚC"))
A(("h2", "3.1. Tổng quan kiến trúc"))
A(("p", "Nhóm mô tả kiến trúc theo mô hình C4 [@c4] ở ba cấp độ: Context thể hiện ranh giới hệ thống và các tác nhân bên ngoài, Container thể hiện các process hoặc container chạy độc lập, và Component đi sâu vào các module bên trong từng container. Nhóm lược bỏ cấp Code vì chi tiết lớp và hàm đã nằm trong mã nguồn và đặc tả OpenAPI. Hình 3.1 tóm tắt toàn bộ kiến trúc trên một trang."))
A(("p", "Ứng dụng người dùng và REFIT replayer gửi request vào cổng duy nhất là API Gateway (Envoy). Sau khi xác thực JWT, gateway định tuyến request tới bốn service nghiệp vụ. Các service gọi đồng bộ theo một chiều `copilot → insight → core → nilm`, và truyền thông tin ngược lại bằng event qua RabbitMQ. Mỗi service sở hữu một database riêng trên cùng một PostgreSQL server dùng chung hạ tầng."))
A(("fig", "00-overview", "Hình 3.1. Kiến trúc tổng quan của WattPrint. Mũi tên liền là call đồng bộ, mũi tên đứt là sự kiện bất đồng bộ qua RabbitMQ", 25.0, 12.0))

A(("h2", "3.2. Bối cảnh hệ thống"))
A(("p", "Ở sơ đồ System Context (Hình 3.2), WattPrint được nhìn nhận như một khối duy nhất đặt giữa hai nhóm người dùng, nguồn cấp dữ liệu sensor và các hệ thống ngoài đã nêu ở mục 2.1. Sơ đồ làm rõ hai nguyên tắc bảo mật ở ranh giới hệ thống. Thứ nhất, WattPrint không tự lưu mật khẩu: toàn bộ luồng đăng nhập đi qua Keycloak và liên kết với Google Identity khi người dùng chọn đăng nhập bằng tài khoản Google. Thứ hai, nhà cung cấp LLM nằm ngoài ranh giới tin cậy (`trust boundary`), nên mọi dữ liệu gửi đi đều phải ẩn PII trước theo quy tắc BR9."))
A(("fig", "01-system-context", "Hình 3.2. Sơ đồ System Context của WattPrint", 22.0, 13.9))

A(("h2", "3.3. Tách hệ thống thành các service"))
A(("h3", "3.3.1. Tiêu chí tách service"))
A(("p", "Nhóm tách ứng dụng monolith ban đầu thành các service dựa trên ba tiêu chí theo thứ tự ưu tiên:"))
A(("ol", [
 "Tiêu chí đầu tiên là ranh giới dữ liệu và nghiệp vụ. Bốn mảng gồm dữ liệu vận hành gốc (hộ gia đình, dữ liệu sensor, hóa đơn), chạy inference học máy, phân tích thống kê và tương tác trợ lý AI đều làm việc trên các tập bảng riêng. Mảng này chỉ cần đọc kết quả của mảng kia chứ không sửa dữ liệu chéo, bám sát nguyên tắc mỗi microservice tự chủ dữ liệu của mình [@newman].",
 "Tiêu chí thứ hai là đặc thù tiêu thụ tài nguyên. Inference NILMFormer chạy trên PyTorch tiêu tốn nhiều CPU và RAM, trong khi luồng ingest dữ liệu sensor cần phản hồi nhanh và ổn định. Các thuật toán phân tích chạy theo batch và theo lịch định kỳ, còn Copilot dành phần lớn thời gian chờ phản hồi mạng từ LLM bên ngoài.",
 "Tiêu chí thứ ba là khả năng fault isolation. API của LLM bên ngoài có độ trễ cao và dễ gặp lỗi mạng, nên cần tách riêng để không làm nghẽn luồng ingest dữ liệu sensor hay tra cứu dashboard. Tương tự, khi model NILM quá tải thì luồng ingest dữ liệu sensor vẫn phải lưu được dữ liệu mới và đánh dấu batch chờ xử lý sau.",
]))
A(("h3", "3.3.2. Các phương án đã cân nhắc"))
A(("p", "Bảng 3.1 so sánh ba phương án với mức độ chia nhỏ khác nhau. Nhóm chọn phương án B."))
A(("table", "Bảng 3.1. Các phương án tách service",
   ["Phương án", "Cách chia", "Nhận xét"],
   [["A. Hai service", "Gộp core với insight. Gộp nilm với copilot", "Không đạt tối thiểu ba service nghiệp vụ của đề bài. Chưa kể phương án này còn gộp hai khối có kiểu tải trái ngược: nilm tốn CPU/RAM, còn copilot chủ yếu chờ I/O mạng từ LLM"],
    ["B. Bốn service (chọn)", "core, nilm, insight, copilot", "Mỗi service quản lý một miền dữ liệu, một kiểu tải và một đặc thù lỗi riêng. Quy mô bốn service vừa sức triển khai và vận hành của nhóm ba người"],
    ["C. Bảy service trở lên", "Tách thêm billing, device, alert, notification", "Mỗi service chỉ có vài bảng nhưng làm tăng số database, call mạng và chi phí vận hành. Nghiệp vụ billing cần đọc trực tiếp chuỗi dữ liệu sensor của core nên phụ thuộc dữ liệu rất chặt, tách riêng chỉ thêm bước gọi mạng mà không tăng tính độc lập"]],
   [2000, 2800, 4271]))
A(("h3", "3.3.3. Bốn service sau khi tách"))
A(("p", "Bảng 3.2 tổng hợp bốn service nghiệp vụ sau khi tách, mỗi service sở hữu một database riêng với trách nhiệm và chiều gọi đồng bộ rõ ràng."))
A(("table", "Bảng 3.2. Service, trách nhiệm, dữ liệu riêng và đối tượng gọi tới",
   ["Service", "Trách nhiệm", "Dữ liệu riêng", "Gọi tới"],
   [["core", "Quản lý hộ gia đình, thành viên, mã mời, ghép công tơ, thiết bị, nhận batch dữ liệu sensor, biểu giá 5 bậc và tính hóa đơn chính thức. Giữ vai trò `source of truth`", "core_db (TimescaleDB)", "nilm"],
    ["nilm", "Chạy inference NILMFormer, hiệu chỉnh tham số theo hộ, quản lý phiên bản model", "nilm_db và volume chứa model", "Không gọi service nào"],
    ["insight", "Duy trì read model tiêu thụ, phát hiện bất thường và tiêu thụ ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh hộ tương đồng, what-if, M&V, API truy vấn SQL an toàn", "insight_db (TimescaleDB)", "core, Open-Meteo"],
    ["copilot", "Hỏi đáp tự nhiên, gợi ý chủ động, guardrail ẩn PII và chống prompt injection, verifier, RAG, xếp hạng theo phản hồi, thông báo, thống kê token, điều phối kế hoạch tiết kiệm", "copilot_db (pgvector)", "insight, LLM, Expo Push, Telegram"]],
   [1100, 4300, 2100, 1571]))
A(("p", "Từ Bảng 3.2, có ba quyết định phân bổ chức năng cần làm rõ. Thứ nhất, tính hóa đơn chính thức nằm ở `core` vì hóa đơn phải tính trực tiếp từ chuỗi dữ liệu sensor gốc và phiên bản biểu giá để đảm bảo nhất quán với `source of truth`, trong khi dự báo hóa đơn chỉ là ước tính thống kê nên nằm ở `insight`. Thứ hai, `nilm` không gọi sang service nào khác mà chỉ nhận mảng công suất tổng và trả về kết quả tách tải, nên là điểm cuối của chuỗi gọi. Thứ ba, `copilot` không đọc trực tiếp dữ liệu tiêu thụ từ `core` mà đi qua `insight` (lý do trình bày ở mục 3.7)."))
A(("p", "Mọi call đồng bộ chỉ đi theo một chiều duy nhất: `copilot → insight → core → nilm`. Thiết kế một chiều giúp loại bỏ phụ thuộc vòng (`circular dependency`) và khoanh vùng sự cố: một service ngừng đáp ứng chỉ ảnh hưởng tới các luồng gọi trực tiếp từ tầng ngay phía trên nó."))

A(("h2", "3.4. Các khối triển khai"))
A(("p", "Sơ đồ Container ở Hình 3.3 thể hiện các khối triển khai của hệ thống. Ngoài bốn service do nhóm phát triển, hệ thống dùng bốn phần mềm hạ tầng có sẵn: Envoy làm API Gateway, Keycloak quản lý định danh, RabbitMQ làm message broker và PostgreSQL làm hệ quản trị cơ sở dữ liệu. Tổng cộng có tám container chạy trong Docker Compose, chưa kể hai ứng dụng client chạy độc lập bên ngoài. Compose là môi trường demo của bài tập. Vì mỗi service đã có Dockerfile, nhận cấu hình và địa chỉ service phía sau qua biến môi trường, và có sẵn `/health`, `/ready` làm probe, việc đưa từng service lên một orchestrator như Kubernetes và triển khai độc lập không đòi hỏi đổi mã nguồn. Mỗi service nghiệp vụ được đóng gói trong một container duy nhất: các HTTP router, consumer xử lý event, outbox relay và các job định kỳ đều chạy chung trong một process dưới dạng background task. Cách đóng gói này giữ số lượng container vừa đủ để chạy mượt trên máy cá nhân của nhóm, thay vì tách thêm container worker riêng cho từng background job."))
A(("p", "Theo quy ước của mô hình C4, mỗi message queue được biểu diễn như một container lưu trữ message, còn RabbitMQ (broker) được xem là chi tiết hạ tầng bên dưới [@c4]. Vì vậy trên Hình 3.3 có bốn khối queue màu vàng gồm `insight.usage`, `copilot.alerts` và hai DLQ `.dlq` đi kèm."))
A(("fig", "02-container", "Hình 3.3. Sơ đồ Container của WattPrint. Nét đứt là message AMQP: mũi tên đi tới queue là bên gửi, đi ra khỏi queue là bên nhận", 25.0, 16.5))

A(("h2", "3.5. Giao tiếp giữa các service"))
A(("h3", "3.5.1. Gọi đồng bộ qua REST"))
A(("p", "Các tác vụ cần nhận kết quả ngay trong luồng xử lý request (`core` gọi `nilm` chạy inference, `insight` gọi `core` lấy biểu giá và thiết bị, `copilot` gọi `insight` lấy số liệu phân tích) sử dụng giao tiếp đồng bộ qua HTTP/REST, kết nối trực tiếp trong mạng nội bộ của Docker Compose mà không vòng qua gateway. Service gọi chuyển tiếp các header định danh người dùng (`X-User-Id`, `X-User-Roles`) cùng mã truy vết `X-Request-ID`, còn địa chỉ của service đích được lấy từ biến môi trường. Phía gọi luôn đặt timeout, retry có giới hạn và phân biệt rõ mã lỗi nghiệp vụ (4xx, giữ nguyên) với lỗi hạ tầng (timeout trả 504, mất kết nối hoặc circuit breaker mở trả 503). Chi tiết các thông số fault tolerance thuộc chương về độ tin cậy."))
A(("h3", "3.5.2. Sự kiện bất đồng bộ qua RabbitMQ"))
A(("p", "Ngược lại, có những thông tin cập nhật không nên bắt service gửi phải chờ. Khi `core` lưu xong kết quả tách tải mới, `core` không cần đợi `insight` cập nhật xong read model. Khi `insight` phát hiện cảnh báo bất thường, `insight` cũng không cần chờ `copilot` gọi LLM soạn xong gợi ý. Hai luồng này chuyển sang giao tiếp bất đồng bộ bằng event qua RabbitMQ (Bảng 3.3). Mỗi consumer lắng nghe trên một quorum queue [@rabbit] với giới hạn redelivery `delivery-limit = 3` và một DLQ đi kèm."))
A(("table", "Bảng 3.3. Các sự kiện trên exchange `wattprint.events` (kiểu topic)",
   ["Routing key", "Bên phát", "Bên nhận", "Mục đích"],
   [["`energy.usage.updated`", "core", "insight", "Thông báo có kết quả ước tính mới, kèm tổng điện năng theo giờ của từng thiết bị"],
    ["`core.device.changed`", "core", "insight", "Đồng bộ thay đổi danh mục thiết bị sang read model của insight"],
    ["`insight.alert.created`", "insight", "copilot", "Thông báo có cảnh báo mới để kích hoạt luồng gợi ý chủ động"]],
   [2500, 1100, 1200, 4271]))
A(("p", "Một sự kiện đi qua chín bước, minh họa ở Hình 3.4 bằng sự kiện `energy.usage.updated` từ `core` tới `insight`:"))
A(("ol", [
 "Service `core` lưu kết quả NILM và ghi một dòng vào bảng `outbox` trong cùng một transaction.",
 "Tiến trình nền `OutboxRelay` trong `core` quét các dòng chưa gửi bằng `SELECT ... FOR UPDATE SKIP LOCKED`, đảm bảo chạy nhiều instance cũng không gửi trùng.",
 "Relay publish message lên exchange `wattprint.events` kèm routing key, đợi broker xác nhận (confirm) rồi mới đánh dấu đã gửi.",
 "Exchange định tuyến message vào mọi queue có binding khớp. Hàng đợi `insight.usage` bind với `energy.usage.*` và `core.device.*`.",
 "RabbitMQ phân phối message tới consumer của `insight`. Nếu xử lý gặp lỗi, consumer trả `nack` để RabbitMQ redeliver.",
 "Consumer tra `message_id` trong bảng `inbox`. Nếu đã có thì bỏ qua ngay, nếu chưa có thì cập nhật read model và ghi `inbox` trong cùng một transaction trước khi trả `ack`.",
 "Message bị redeliver quá ba lần vẫn lỗi sẽ được quorum queue chuyển sang dead-letter exchange `wattprint.dlx`.",
 "Exchange `wattprint.dlx` đẩy message vào `insight.usage.dlq`, lưu giữ message tại đó thay vì làm mất.",
 "Nhóm vận hành kiểm tra DLQ trên giao diện quản trị RabbitMQ, khắc phục nguyên nhân lỗi rồi đẩy message về lại `insight.usage` để chạy lại.",
]))
A(("p", "Hai bảng `outbox` và `inbox` khắc phục hai nguy cơ mất nhất quán khác nhau. Ở đầu gửi, nếu lưu database xong rồi mới publish riêng qua mạng, process bị sập giữa hai bước sẽ làm `insight` thiếu dữ liệu. Thao tác ghi event vào bảng `outbox` trong cùng transaction với dữ liệu nghiệp vụ giúp loại bỏ rủi ro đó theo đúng pattern Transactional Outbox [@richardson]. Ở đầu nhận, RabbitMQ vận hành theo cơ chế giao ít nhất một lần (at-least-once), nên một message có thể đến lặp lại. Bảng `inbox` lưu các `message_id` đã xử lý để consumer tự động bỏ qua bản trùng, đảm bảo tính idempotent cho consumer."))
A(("fig", "x6-dynamic-messaging-rabbitmq", "Hình 3.4. Một sự kiện đi qua RabbitMQ: outbox, exchange, queue, consumer, DLQ", 25.0, 10.5))

A(("h2", "3.6. Luồng nghiệp vụ nhiều bước và xử lý lỗi giữa chừng"))
A(("p", "Đề bài yêu cầu ít nhất một luồng nghiệp vụ đi qua hai service và có cơ chế xử lý khi gặp lỗi giữa chừng. WattPrint có hai luồng đa bước như vậy, mỗi luồng áp dụng một hướng xử lý khác nhau tùy thuộc vào việc dữ liệu ở bước đầu có cần rollback hay không."))
A(("h3", "3.6.1. Ingest dữ liệu sensor và chạy inference NILM"))
A(("p", "Khi nhận một batch dữ liệu sensor, `core` xác thực API key thiết bị, kiểm tra công tơ thuộc hộ và kiểm tra tính liên tục của batch (BR2, BR3), lưu dữ liệu sensor thô rồi gọi đồng bộ sang `nilm`. Nếu `nilm` phản hồi kịp, `core` lưu công suất ước tính từng thiết bị, ghi event vào `outbox` và trả mã 201 với trạng thái `DONE`. Nếu request gọi `nilm` bị timeout, trả lỗi 5xx hoặc gặp lúc circuit breaker đang mở, `core` chưa có ngay kết quả inference. Lúc này `core` không rollback dữ liệu sensor đã lưu, vì dữ liệu sensor từ sensor là dữ liệu thực tế không được phép mất. Thay vào đó, `core` đánh dấu batch là `PENDING_INFERENCE`, trả mã 202, và giao cho một background task retry yêu cầu theo chu kỳ backoff 1, 2, 4 phút. Quá năm lần retry vẫn lỗi thì batch chuyển sang `FAILED` và phát cảnh báo cho nhóm vận hành (Hình 3.5)."))
A(("fig", "x2-dynamic-ingest-nilm", "Hình 3.5. Luồng ingest dữ liệu sensor và chạy inference NILM, có trạng thái PENDING_INFERENCE khi nilm không phản hồi", 25.0, 14.0))
A(("h3", "3.6.2. Kích hoạt kế hoạch tiết kiệm"))
A(("p", "Khi người dùng chấp nhận một gợi ý tiết kiệm, `copilot` điều phối một saga qua `insight` gồm hai bước. Bước một tạo `baseline` M&V tại `insight` (cần tối thiểu 14 ngày dữ liệu theo BR5, thiếu thì `insight` trả lỗi 422). Bước hai cập nhật ngân sách tháng theo kế hoạch. Tùy kết quả ở bước hai mà saga rẽ theo ba nhánh (Hình 3.6). Nếu bước hai thành công, kế hoạch chuyển sang `ACTIVE`. Nếu bước hai bị `insight` từ chối bằng lỗi nghiệp vụ 4xx, `copilot` thực hiện bước bù trừ theo thứ tự ngược bằng cách gọi API xóa `baseline` vừa tạo ở bước một, rồi đánh dấu kế hoạch là `CANCELLED` kèm lý do. Nếu bước hai bị timeout (lỗi hạ tầng 504), `copilot` chưa biết `insight` đã lưu ngân sách hay chưa nên giữ kế hoạch ở trạng thái `PENDING`, để background job `reconciler` truy vấn lại `insight` rồi hoàn tất hoặc chạy bù trừ sau."))
A(("p", "Luồng saga này dựa trên việc phân biệt rõ hai loại lỗi: lỗi nghiệp vụ 4xx khẳng định chắc chắn bước hai chưa làm thay đổi dữ liệu nên `copilot` gọi bước bù trừ ngay, còn lỗi hạ tầng mang tính bất định nên phải giữ trạng thái chờ và đối soát lại."))
A(("fig", "x5-dynamic-saving-plan-saga", "Hình 3.6. Luồng kích hoạt kế hoạch tiết kiệm (saga): thành công, hoàn tác theo thứ tự ngược và PENDING", 24.0, 14.0))

A(("h2", "3.7. Dữ liệu"))
A(("p", "Hệ thống sử dụng một PostgreSQL server chứa năm database riêng biệt: `core_db`, `insight_db`, `copilot_db`, `nilm_db` và `keycloak_db`. Mỗi database gắn với một database role riêng và không service nào có quyền truy cập vào database của service khác. Cách bố trí này giữ tổng số container ở mức tám trong khi vẫn đảm bảo cô lập dữ liệu đúng theo pattern Database per Service [@newman]. Khi cần mở rộng, mỗi database tách sang server riêng chỉ bằng cách đổi chuỗi kết nối trong biến môi trường."))
A(("p", "Server chạy PostgreSQL 18 với hai extension chuyên dụng. TimescaleDB xử lý chuỗi thời gian trên `core_db` (lưu dữ liệu sensor, tự động tổng hợp theo giờ và ngày, nén dữ liệu cũ, xóa chunk hết hạn lưu trữ) và trên `insight_db` (vận hành read model tiêu thụ). Extension `pgvector` đảm nhận tìm kiếm tương đồng vector cho tính năng RAG trên `copilot_db`."))
A(("p", "Vì các service không đọc trực tiếp database của nhau, mọi nhu cầu tra cứu dữ liệu chéo đều đi theo một trong hai cách:"))
A(("ul", [
 "Cách thứ nhất là đồng bộ qua sự kiện theo pattern CQRS [@richardson]. Service `insight` duy trì một read model dữ liệu tiêu thụ đã tổng hợp theo giờ, cập nhật bất đồng bộ từ event của `core`. Trong mô hình này, `core` phụ trách luồng ghi và giữ vai trò `source of truth`, còn `insight` tổ chức dữ liệu theo cấu trúc phù hợp cho truy vấn phân tích.",
 "Cách thứ hai là gọi trực tiếp REST API khi cần dữ liệu mới nhất hoặc dữ liệu cấu hình nhỏ, chẳng hạn `insight` lấy biểu giá và danh mục thiết bị từ `core`.",
]))
A(("p", "Thiết kế phân tách này giải quyết trực tiếp bài toán an toàn cho tính năng Text-to-SQL của Copilot. Để trả lời các câu hỏi tự do về điện năng, LLM trong `copilot` tự sinh câu lệnh SQL. Nếu câu SQL đó chạy trực tiếp trên database vận hành gốc của `core`, một câu truy vấn lỗi hoặc bị tấn công prompt injection có thể chạm vào dữ liệu nguồn. Vì vậy, `copilot` gửi câu SQL tới endpoint truy vấn an toàn của `insight`. Endpoint này dùng `SQL guard` kiểm tra cây cú pháp để chỉ cho phép câu lệnh `SELECT` trên các view được cấp quyền, tự động ép điều kiện lọc theo `home_id` của người đang hỏi, đặt timeout 2 giây và chỉ thực thi trên database phân tích `insight_db`. Khi tách service, các bảng trong bản monolith cũ cũng được chuyển về đúng database theo Bảng 3.2: nhóm bảng phân tích và M&V chuyển về `insight_db`, bảng lịch sử chạy inference (`inference_run`) chuyển về `nilm_db`, còn bảng hội thoại và tri thức RAG thuộc về `copilot_db`."))

A(("h2", "3.8. Gateway và bảo mật"))
A(("p", "API Gateway của hệ thống là Envoy, cấu hình trong tệp `envoy.yaml`. Theo đúng yêu cầu đề bài, gateway chỉ định tuyến và áp dụng chính sách kỹ thuật ở tầng biên, không chứa logic nghiệp vụ. Toàn bộ chính sách đều dùng các filter dựng sẵn của Envoy:"))
A(("ul", [
 "Định tuyến theo tiền tố `/api/core/`, `/api/insight/`, `/api/copilot/` và `/api/nilm/` (chỉ mở cho admin), mỗi route có cấu hình timeout và retry riêng. Envoy chỉ retry các request `GET` khi gặp lỗi kết nối, không retry `POST` để tránh ghi trùng dữ liệu.",
 "Filter `jwt_authn` xác thực chữ ký RS256, `issuer` và `audience` của JWT bằng tập khóa công khai (JWKS) lấy từ Keycloak [@envoy]. Sau khi xác thực, Envoy gán `sub` và role của token vào header `X-User-Id` và `X-User-Roles`, và xóa các header trùng tên do client tự gửi lên để các service phía sau tin cậy được hai header này.",
 "Áp dụng giới hạn tần suất gọi (rate limit), giới hạn kích thước request body và tự động sinh mã truy vết `x-request-id` để theo dõi log xuyên suốt.",
 "Riêng route ingest dữ liệu sensor từ sensor không yêu cầu JWT vì thiết bị không thực hiện đăng nhập người dùng. Service `core` tự xác thực API key thiết bị và kiểm tra trạng thái ghép nối công tơ (BR2).",
]))
A(("p", "Các bước kiểm tra phân quyền theo hộ gia đình, theo gói Pro và theo role admin đều do từng service tự thực hiện vì đó là quy tắc nghiệp vụ. Các container service không mở cổng ra ngoài máy host nên chỉ có gateway và các service trong mạng nội bộ mới gọi tới được."))

A(("h2", "3.9. Công nghệ sử dụng"))
A(("p", "Vì nhóm chỉ có ba thành viên, nguyên tắc chọn công nghệ là giữ số lượng công cụ nhỏ và ưu tiên tận dụng cấu hình có sẵn hơn là tự viết code (Bảng 3.4). Toàn bộ backend thống nhất dùng Python, còn hai ứng dụng client dùng TypeScript."))
A(("table", "Bảng 3.4. Công nghệ sử dụng và lý do chọn",
   ["Lớp", "Chọn", "Lý do"],
   [["Gateway", "Envoy 1.40", "Xác thực JWT, rate limit, request ID, timeout và retry đều là các filter có sẵn, không phải viết code. Là proxy chuẩn công nghiệp và là nhân của nhiều service mesh"],
    ["Identity", "Keycloak 26", "Cấp JWT theo chuẩn OIDC, liên kết đăng nhập Google. Dùng chung `keycloak_db` trên PostgreSQL server thay vì cần container database riêng"],
    ["Database", "PostgreSQL 18, TimescaleDB 2.31, pgvector", "Một server duy nhất đáp ứng cả dữ liệu quan hệ, chuỗi thời gian và tìm kiếm vector, không cần vận hành ba hệ cơ sở dữ liệu khác nhau"],
    ["Message broker", "RabbitMQ 4, quorum queue", "Hỗ trợ sẵn giới hạn redelivery (`delivery-limit`) và dead-letter exchange, không cần tự viết cơ chế đếm retry"],
    ["Service", "Python 3.12, FastAPI, SQLAlchemy async, Alembic", "Kế thừa trực tiếp mã nguồn sẵn có. FastAPI hỗ trợ bất đồng bộ và tự động sinh đặc tả OpenAPI"],
    ["Messaging trong service", "FastStream", "Viết consumer tương tự như route của FastAPI, tự sinh tài liệu AsyncAPI và có sẵn broker trong bộ nhớ để chạy test"],
    ["Gọi HTTP và fault tolerance", "httpx, tenacity. Circuit breaker và bulkhead tự viết trong thư viện chung", "Thư viện circuit breaker phổ biến chỉ hỗ trợ async qua Tornado, nên nhóm tự viết khoảng 30 dòng code và dùng `asyncio.Semaphore` làm bulkhead [@nygard]"],
    ["Mã nguồn", "Monorepo uv workspace: `services/` và `libs/common`", "Quản lý phụ thuộc bằng một lockfile. Phần fault tolerance, log, outbox và inbox chỉ cần viết một lần cho cả bốn service"],
    ["Kiểm tra", "ruff, pytest, Postman với Newman, GitHub Actions", "Tự động chạy test, build image, bật cụm compose và chạy Postman collection trên pipeline CI"]],
   [1700, 2800, 4571]))
A(("p", "Nhóm chủ động không dùng Prometheus, Grafana, Loki, Jaeger, cũng như không tách container worker riêng hay container database riêng cho Keycloak. Mỗi container xuất log JSON trực tiếp ra `stdout` kèm `request_id`, tra cứu bằng `docker compose logs` là đủ để truy vết một request đi qua các service."))

A(("h2", "3.10. Thành phần bên trong từng service"))
A(("p", "Các sơ đồ Component dưới đây thể hiện những module bên trong từng container và điểm giao tiếp ra bên ngoài. Các mũi tên không ghi nhãn là call hàm trong cùng process. Màu sắc tuân theo quy ước chung của các sơ đồ: xanh lá là phần do nhóm viết, tím là phần mềm hạ tầng có sẵn, vàng là queue, xanh ngọc là kho dữ liệu, cam là hệ thống bên ngoài, còn nét đứt là sự kiện bất đồng bộ."))
A(("p", "Service **core** (Hình 3.7) gồm ba cụm API là quản lý hộ gia đình và thiết bị, ingest dữ liệu sensor và tính hóa đơn. `IngestService` ghi chuỗi dữ liệu sensor và sự kiện qua `Repositories` trong cùng một transaction. `OutboxRelay` và `PendingRetrier` là hai background task chạy nền: một đẩy sự kiện lên RabbitMQ, một retry các batch đang chờ inference. `NilmClient` là điểm duy nhất trong `core` gọi sang service khác, nên cấu hình timeout, retry và circuit breaker đều tập trung tại đó."))
A(("p", "Service **nilm** (Hình 3.8) tách thành API chạy inference và API quản lý phiên bản model (chỉ mở cho admin). `InferenceEngine` thực thi mô hình NILMFormer, `Calibrator` hiệu chỉnh tham số theo từng hộ và `ModelLoader` nạp trọng số một lần rồi giữ cố định trong RAM. Endpoint inference áp dụng cơ chế bulkhead để giới hạn số request xử lý đồng thời, ngăn một đợt tải cao làm tràn bộ nhớ."))
A(("p", "Service **insight** (Hình 3.9) nhận sự kiện qua `Usage consumer` để cập nhật read model, sau đó kích hoạt các module `Detectors` kiểm tra phụ tải bất thường, chạm bậc giá và vượt ngân sách rồi phát sự kiện `insight.alert.created` qua `OutboxRelay`. Phía API cung cấp các endpoint phân tích và dự báo, cùng module `SQL guard` bảo vệ endpoint truy vấn SQL an toàn (mục 3.7)."))
A(("p", "Service **copilot** (Hình 3.10) có hai đường vào. Đường hỏi đáp trực tiếp đi từ `Chat API` qua `Guardrail` (ẩn PII, chặn prompt injection, kiểm tra gói Pro) tới `Orchestrator`, nơi LLM gọi các tool để lấy số liệu từ `insight`, rồi qua bước hậu kiểm của `Verifier` (kiểm tra số liệu, đơn vị và nguồn trích dẫn) trước khi trả lời. Đường gợi ý chủ động đi từ `Alert consumer` qua `Ranker` (xếp hạng theo lịch sử phản hồi, lọc khung giờ nghỉ, chống gửi trùng) tới `Notifier`. Module `Saga orchestrator` điều phối luồng kích hoạt kế hoạch tiết kiệm (mục 3.6.2)."))
A(("fig", "03-component-core", "Hình 3.7. Sơ đồ Component của service core", 22.0, 15.5))
A(("fig", "04-component-nilm", "Hình 3.8. Sơ đồ Component của service nilm", 18.5, 15.5))
A(("fig", "05-component-insight", "Hình 3.9. Sơ đồ Component của service insight", 22.0, 15.5))
A(("fig", "06-component-copilot", "Hình 3.10. Sơ đồ Component của service copilot", 25.0, 14.8))

# ---------------- Chương 4 ----------------
A(("h1", "CHƯƠNG 4. ĐÁNH ĐỔI VÀ RỦI RO CỦA KIẾN TRÚC"))
A(("h2", "4.1. Các quyết định chính và đánh đổi"))
A(("p", "Mỗi quyết định thiết kế ở Chương 3 đều đi kèm sự đánh đổi giữa tính độc lập, độ tin cậy và chi phí vận hành. Bảng 4.1 tổng hợp những quyết định lớn, lý do lựa chọn và các hạn chế mà nhóm chấp nhận."))
A(("table", "Bảng 4.1. Quyết định kiến trúc và đánh đổi",
   ["Quyết định", "Lý do", "Đánh đổi chấp nhận"],
   [["Tách bốn service thay vì giữ kiến trúc monolith", "Mỗi service có ranh giới dữ liệu, đặc thù tải và kiểu lỗi riêng. Đáp ứng yêu cầu đề bài", "Phát sinh độ trễ gọi qua mạng, thêm điểm có nguy cơ lỗi cục bộ và gỡ lỗi phức tạp hơn một process"],
    ["Dừng ở bốn service thay vì tách thành bảy service", "Giữ số lượng container, database và call mạng ở mức nhóm ba người kiểm soát tốt", "Phạm vi mỗi service lớn hơn, chẳng hạn core đảm nhận cả quản lý hộ gia đình lẫn tính hóa đơn"],
    ["Quy định chiều gọi đồng bộ một chiều", "Không có phụ thuộc vòng. Sự cố ở một service chỉ ảnh hưởng tầng ngay phía trên", "Copilot phải đi vòng qua insight để lấy dữ liệu tiêu thụ, thêm một chặng gọi mạng so với đọc trực tiếp"],
    ["Truyền sự kiện qua RabbitMQ cho hai luồng phụ", "Bên gửi không phải chờ bên nhận xử lý xong. Có sẵn DLQ để lưu giữ message lỗi và chạy lại", "Read model của insight có độ trễ ngắn so với core (eventual consistency). Phải duy trì thêm bảng outbox và inbox"],
    ["Dùng một PostgreSQL server cho năm database", "Giữ tổng số container ở mức tám trong khi vẫn tách biệt quyền theo từng database role", "PostgreSQL server là điểm lỗi chung (single point of failure) về hạ tầng, các service chia sẻ tài nguyên trên cùng server"],
    ["Bốn service cùng ngôn ngữ Python và chung thư viện", "Viết phần fault tolerance, log, outbox và inbox một lần. Giảm số công nghệ phải học", "Backend gắn chặt với hệ sinh thái Python. Cập nhật thư viện chung ảnh hưởng tới cả bốn service"],
    ["Mỗi service chạy trong một container (API, consumer, relay chung process)", "Dễ khởi chạy và gom toàn bộ log của một service về một luồng duy nhất", "Không scale riêng được phần API và phần background job. Các job nền nặng cạnh tranh tài nguyên với API"],
    ["Tự viết circuit breaker và bulkhead trong thư viện chung", "Thư viện sẵn có không tương thích gọn với mô hình async của FastAPI", "Phải tự viết bộ kiểm thử kỹ lưỡng và thiếu các tính năng giám sát nâng cao của những thư viện phổ biến"]],
   [2500, 3200, 3371]))

A(("h2", "4.2. Rủi ro còn lại và hướng xử lý"))
A(("p", "Bảng 4.2 liệt kê các rủi ro kỹ thuật mà nhóm đã nhận diện ở mức kiến trúc cùng phương án xử lý tương ứng. Cấu hình chi tiết và số liệu thực nghiệm sẽ được trình bày ở các chương về độ tin cậy và đánh giá."))
A(("table", "Bảng 4.2. Rủi ro và hướng xử lý",
   ["Rủi ro", "Biểu hiện", "Hướng xử lý"],
   [["Service nilm quá tải hoặc ngừng phản hồi", "core không nhận được kết quả chạy inference ngay khi lưu batch", "Giữ nguyên dữ liệu sensor gốc, đánh dấu batch `PENDING_INFERENCE` và dùng background job retry có backoff. Kết hợp circuit breaker ở core và bulkhead ở nilm"],
    ["Nhà cung cấp LLM phản hồi chậm hoặc lỗi", "Copilot không trả lời kịp. Không được kéo theo nghẽn dashboard", "Áp timeout 20 giây, mở circuit breaker và trả mã lỗi 503 rõ ràng. Dashboard và phân tích không phụ thuộc vào LLM"],
    ["Message đến lặp lại hoặc xử lý thất bại", "Read model của insight bị cộng trùng hoặc thiếu dữ liệu mới", "Dùng bảng inbox chống xử lý trùng, bảng outbox chống mất sự kiện và đẩy message lỗi vào DLQ để kiểm tra, chạy lại"],
    ["Read model của insight lệch so với core", "Số liệu trên biểu đồ phân tích khác với số liệu hóa đơn", "Quy định số liệu hóa đơn chính thức luôn lấy trực tiếp từ core. Cơ chế đồng bộ lại read model khi lệch sẽ được xác định ở phần triển khai"],
    ["Copilot trả lời sai số liệu thực tế", "Người dùng nhận phải con số tiền điện hoặc công suất sai", "Mọi con số đều do tool tính toán từ dữ liệu hộ gia đình. Module Verifier loại bỏ câu trả lời sai số liệu, đơn vị hoặc nguồn (BR8)"],
    ["Lộ thông tin cá nhân qua LLM hoặc Text-to-SQL", "Prompt gửi đi chứa PII hoặc câu SQL tự sinh chạm dữ liệu nguồn", "Module Guardrail ẩn PII trước khi gọi LLM. Truy vấn SQL chạy qua endpoint của insight với SQL guard trên database phân tích riêng"],
    ["Container PostgreSQL ngừng hoạt động", "Mọi service mất kết nối dữ liệu cùng lúc", "Chấp nhận trong phạm vi bài tập lớn. Hướng nâng cấp thực tế là tách database sang server riêng hoặc cấu hình replica dự phòng"]],
   [2300, 2700, 4071]))
