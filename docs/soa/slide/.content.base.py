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
 ("AMQP", "Giao thức nhắn tin mà RabbitMQ sử dụng (Advanced Message Queuing Protocol)"),
 ("BR", "Quy tắc nghiệp vụ (Business Rule), đánh mã BR1 đến BR9 ở mục 2.3"),
 ("C4", "Mô hình vẽ kiến trúc theo bốn cấp: Context, Container, Component, Code"),
 ("CQRS", "Tách mô hình ghi và mô hình đọc dữ liệu (Command Query Responsibility Segregation)"),
 ("CT", "Cảm biến dòng điện kẹp ngoài dây (Current Transformer)"),
 ("DLQ", "Hàng đợi chứa message lỗi (Dead Letter Queue)"),
 ("EVN", "Tập đoàn Điện lực Việt Nam"),
 ("Gateway", "Cổng vào duy nhất của hệ thống, chỉ định tuyến và áp chính sách"),
 ("JWT", "Chuỗi định danh có chữ ký do Keycloak cấp (JSON Web Token)"),
 ("JWKS", "Tập khóa công khai để kiểm chữ ký JWT (JSON Web Key Set)"),
 ("LLM", "Mô hình ngôn ngữ lớn (Large Language Model)"),
 ("M&V", "Đo lường và kiểm chứng mức tiết kiệm (Measurement and Verification)"),
 ("NILM", "Tách điện năng từng thiết bị từ số đo tổng (Non-Intrusive Load Monitoring)"),
 ("OIDC", "Giao thức đăng nhập OpenID Connect"),
 ("Outbox, Inbox", "Hai bảng trong database của service để gửi và nhận sự kiện không mất, không trùng (mục 3.5)"),
 ("PII", "Thông tin định danh cá nhân (Personally Identifiable Information)"),
 ("RAG", "Truy xuất tri thức rồi mới sinh câu trả lời (Retrieval-Augmented Generation)"),
 ("REFIT", "Bộ dữ liệu công khai về điện năng hộ gia đình ở Vương quốc Anh"),
 ("REST", "Kiểu thiết kế API qua HTTP (Representational State Transfer)"),
 ("SOA", "Kiến trúc hướng dịch vụ (Service-Oriented Architecture)"),
]

SUMMARY = [
 "Báo cáo trình bày quá trình phân tích và chốt kiến trúc microservices cho WattPrint, hệ thống giúp hộ gia đình biết điện năng của từng thiết bị chỉ từ một điểm đo ở aptomat và nhận khuyến nghị tiết kiệm điện từ trợ lý Energy Copilot. Xuất phát từ bài toán và người dùng, nhóm rút ra chín quy tắc nghiệp vụ, rồi dựa vào ranh giới dữ liệu, kiểu tải và kiểu lỗi để chia hệ thống thành bốn service nghiệp vụ là core, nilm, insight và copilot.",
 "Các service đứng sau một API Gateway, mỗi service có database riêng, gọi nhau đồng bộ theo một chiều và trao đổi sự kiện qua RabbitMQ bằng mẫu outbox và inbox. Báo cáo ghi lại các phương án đã cân nhắc, lý do chọn và những đánh đổi mà nhóm chấp nhận. Phần thiết kế API, độ tin cậy, triển khai và đánh giá sẽ được viết ở các chương tiếp theo.",
]
KEYWORDS = "microservices, SOA, API Gateway, NILM, RabbitMQ, transactional outbox, Energy Copilot."

# ---- Thân báo cáo ----
# ("h1",t) ("h2",t) ("h3",t) ("p",t) ("ul",[..]) ("ol",[..]) ("table",cap,headers,rows,widths) ("fig",key,cap,w_cm,h_cm)
BODY = []
A = BODY.append

A(("h1", "CHƯƠNG 1. GIỚI THIỆU"))
A(("h2", "1.1. Bối cảnh"))
A(("p", "Tiền điện là khoản chi cố định hằng tháng của mỗi hộ gia đình, nhưng người dùng thường chỉ biết con số cuối tháng chứ không biết khoản nào tạo ra nó. Một thí nghiệm trên 45.000 hộ ở Việt Nam cho thấy chỉ cần cho hộ xem ước tính tiền điện theo ngày, nhóm được xem đã giảm tiêu thụ so với nhóm không được xem [@ta]. Thông tin đơn giản đã đủ để thay đổi hành vi, nhưng muốn biết nên tiết kiệm ở đâu thì người dùng cần thông tin đến từng thiết bị. Một nghiên cứu ở Mỹ cho thấy người dùng đoán thấp điện năng của các thiết bị khoảng 2,8 lần, và đoán sai nhiều nhất ở những thiết bị tốn điện nhất [@attari]."))
A(("p", "Công cụ hiện có chưa giải quyết được điều này. Ứng dụng của EVN chỉ cho xem tổng điện năng của cả hộ theo ngày [@sggp]. Muốn đo từng thiết bị bằng ổ cắm đo điện, mỗi ổ có giá khoảng 235.000 đồng [@tuya]. Với khoảng 10 điểm đo cộng bộ điều khiển trung tâm [@ha], chi phí ước tính từ 4 đến 10 triệu đồng, hộ còn phải tự lắp và kết nối, và ổ cắm không đo được thiết bị đấu trực tiếp như điều hòa hay đèn trần."))
A(("p", "Câu hỏi của dự án vì vậy là có cách nào ước tính điện năng từng thiết bị với chi phí thấp hơn nhiều hay không. Hướng trả lời của nhóm là Non-Intrusive Load Monitoring (NILM), kỹ thuật do Hart đề xuất từ năm 1992 [@hart]: chỉ đo tổng công suất tại aptomat, rồi dùng mô hình để tách ra phần của từng thiết bị."))

A(("h2", "1.2. Giải pháp WattPrint"))
A(("p", "WattPrint gồm bốn khối chức năng, đi từ số đo thô đến lời khuyên cụ thể:"))
A(("ol", [
 "**Phân rã điện năng.** Dùng NILMFormer [@nilmformer], mô hình dựa trên Transformer xử lý tốt khi điện năng tổng biến động thất thường, kèm bước hiệu chỉnh theo từng hộ.",
 "**Dashboard và hóa đơn.** Điện năng từng thiết bị theo giờ, ngày, tuần, tháng, mọi số liệu đi kèm số tiền theo biểu giá sinh hoạt 5 bậc.",
 "**Phân tích.** Cảnh báo thiết bị chạy lâu bất thường, phát hiện thiết bị chạy ngầm, so sánh với tháng trước và với nhóm hộ khác, dự báo hóa đơn cuối tháng và thời điểm chạm bậc giá kế tiếp.",
 "**Energy Copilot.** Trợ lý hai chiều: trả lời câu hỏi của người dùng (pull) và chủ động gợi ý (push). Số liệu do công cụ tính từ dữ liệu của hộ, mô hình ngôn ngữ chỉ diễn giải. Copilot còn lập kế hoạch tiết kiệm và so sánh kết quả trước và sau khi thực hiện.",
]))
A(("p", "Về tác động kỳ vọng, các nghiên cứu trước cho thấy phản hồi thông tin điện năng giúp hộ giảm khoảng 2-4% [@buckley], và một thử nghiệm ở Đà Nẵng trên khoảng 1.000 hộ ghi nhận mức giảm 4-7% [@nguyen]. Đây là kết quả của các nghiên cứu đó, chưa phải kết quả đo được của WattPrint."))

A(("h2", "1.3. Phạm vi của bài tập lớn"))
A(("p", "Hệ thống hiện có một bản nguyên khối (một ứng dụng FastAPI) chạy đủ các chức năng trên. Bài tập lớn tách bản này thành các service độc lập, nên phần phân tích tập trung vào việc quyết định tách ở đâu và vì sao. Phạm vi gồm:"))
A(("ul", [
 "Bốn service nghiệp vụ cùng API Gateway, xác thực, database riêng cho từng service và hàng đợi sự kiện, chạy bằng một lệnh `docker compose up`.",
 "Mô hình NILMFormer ở dạng suy luận. Việc huấn luyện và đánh giá mô hình nằm ngoài bài tập này.",
 "Nguồn số đo: nhóm không có cảm biến thật nên dùng bộ dữ liệu công khai REFIT [@refit], phát lại qua gateway (mục 2.5).",
 "Hai ứng dụng client đã có (app Expo và web Next.js) được giữ nguyên, chỉ đổi địa chỉ API về gateway.",
]))

A(("h2", "1.4. Yêu cầu của đề bài"))
A(("p", "Đề bài yêu cầu một hệ thống microservices có API Gateway và đóng gói bằng container. Với nhóm ba người, hệ thống cần tối thiểu ba service nghiệp vụ không kể gateway, mỗi service có mã nguồn và dữ liệu riêng. Mỗi service cần ít nhất bốn endpoint REST kèm tệp OpenAPI, lời gọi giữa các service phải có timeout và quy tắc thử lại, và ít nhất một luồng nghiệp vụ đi qua hai service phải xử lý được lỗi giữa chừng. Phần thử nghiệm yêu cầu Postman collection và ít nhất hai tình huống lỗi có số liệu trước và sau khi xử lý."))
A(("p", "Ngoài phần bắt buộc, nhóm làm cả bốn mục điểm cộng: hàng đợi RabbitMQ có consumer idempotent và DLQ, xác thực JWT tại gateway, circuit breaker và bulkhead, cùng CI chạy test tự động. Chương 3 và Chương 4 cho thấy mỗi yêu cầu ảnh hưởng thế nào đến kiến trúc."))

A(("h2", "1.5. Cấu trúc báo cáo"))
A(("p", "Chương 2 phân tích nghiệp vụ: người dùng, các nhóm chức năng, quy tắc nghiệp vụ, yêu cầu phi chức năng và nguồn số đo. Chương 3 đi từ phân tích đến kiến trúc: cách chia service, các khối triển khai, giao tiếp, dữ liệu, gateway, công nghệ và thành phần bên trong từng service. Chương 4 liệt kê các đánh đổi và rủi ro của kiến trúc đã chọn. Thiết kế API, độ tin cậy và xử lý lỗi có số liệu, triển khai và kiểm thử, đánh giá và hạn chế sẽ được bổ sung thành các chương tiếp theo khi phần hiện thực hoàn tất."))

# ---------------- Chương 2 ----------------
A(("h1", "CHƯƠNG 2. PHÂN TÍCH NGHIỆP VỤ"))
A(("h2", "2.1. Người dùng và các bên liên quan"))
A(("p", "Hệ thống có hai nhóm người dùng, một nguồn dữ liệu tự động và năm hệ thống bên ngoài. Bảng 2.1 tóm tắt từng đối tượng và cách họ tương tác với WattPrint."))
A(("table", "Bảng 2.1. Người dùng, nguồn dữ liệu và hệ thống bên ngoài",
   ["Đối tượng", "Vai trò", "Tương tác chính"],
   [["Thành viên hộ gia đình", "Người dùng cuối. Chủ hộ tạo nhà và mời thành viên", "Xem điện từng thiết bị, hóa đơn, cảnh báo. Hỏi Energy Copilot. Nhận gợi ý qua thông báo đẩy"],
    ["Nhóm vận hành", "Quản trị WattPrint", "Quản lý nhà, công tơ, phiên bản model. Xem log và hàng đợi lỗi. Nhận phản hồi và báo sự cố qua Telegram"],
    ["Cảm biến ở aptomat (REFIT replayer trong đồ án)", "Nguồn số đo", "Gửi định kỳ từng batch công suất tổng, xác thực bằng API key của thiết bị"],
    ["Nhà cung cấp LLM", "Hệ thống ngoài", "Sinh câu trả lời và embedding cho Copilot. Chỉ nhận prompt đã ẩn PII"],
    ["Open-Meteo", "Hệ thống ngoài", "Cung cấp nhiệt độ và độ ẩm theo giờ cho phân tích và gợi ý theo thời tiết"],
    ["Expo Push, Telegram", "Hệ thống ngoài", "Chuyển thông báo tới điện thoại người dùng và tới nhóm vận hành"],
    ["Google Identity", "Hệ thống ngoài", "Đăng nhập bằng tài khoản Google, liên kết qua Keycloak"]],
   [2400, 2600, 4071]))

A(("h2", "2.2. Các nhóm nghiệp vụ"))
A(("p", "Nghiệp vụ của WattPrint chia thành sáu nhóm, được sắp theo đường đi của dữ liệu từ lúc nhà được thiết lập đến lúc người dùng nhận lời khuyên (bảng 2.2). Đường đi này là cơ sở cho cách chia service ở chương 3."))
A(("table", "Bảng 2.2. Sáu nhóm nghiệp vụ của WattPrint",
   ["Nhóm", "Nội dung", "Dữ liệu tạo ra"],
   [["1. Quản lý nhà và thiết bị", "Tạo nhà, mời thành viên bằng mã, ghép công tơ, khai báo danh mục thiết bị theo phòng", "Nhà, thành viên, công tơ, thiết bị"],
    ["2. Thu thập số đo", "Nhận batch công suất tổng từ cảm biến, kiểm tra tính liên tục, lưu chuỗi thời gian", "Số đo theo thời gian"],
    ["3. Phân rã điện năng", "Ước tính công suất từng thiết bị từ số đo tổng, hiệu chỉnh theo hộ, quản lý phiên bản model", "Ước tính theo thiết bị, lần chạy NILM"],
    ["4. Tính tiền", "Tổng hợp kWh theo giờ, ngày, tháng và tính tiền theo biểu giá 5 bậc", "Hóa đơn, biểu giá"],
    ["5. Phân tích", "Cảnh báo bất thường, phát hiện chạy ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh nhóm, what-if, M&V", "Cảnh báo, dự báo, kế hoạch"],
    ["6. Trợ lý Copilot", "Hỏi đáp, gợi ý chủ động, kế hoạch tiết kiệm, thông báo, ghi nhận phản hồi", "Hội thoại, gợi ý, tri thức RAG"]],
   [2300, 4571, 2200]))
A(("p", "Luồng chính của hệ thống đi từ trên xuống dưới bảng. Cảm biến gửi số đo tổng, hệ thống tách thành từng thiết bị rồi tính tiền (nhóm 2 đến 4). Dữ liệu đã tách là đầu vào để phát hiện bất thường và dự báo (nhóm 5). Cuối cùng Copilot dùng kết quả phân tích để trả lời và chủ động nhắc người dùng (nhóm 6). Chỗ nối giữa nhóm 2 và 3, và giữa nhóm 5 và 6, là những nơi có thể lỗi từng phần, và đó là các luồng nhiều bước mà đề bài yêu cầu xử lý (mục 3.6)."))

A(("h2", "2.3. Quy tắc nghiệp vụ"))
A(("p", "Nhóm chốt chín quy tắc nghiệp vụ (bảng 2.3). Một quy tắc được đưa vào bảng khi nó có thể bị vi phạm và hệ thống phải từ chối hoặc xử lý khác đi, thường bằng một mã lỗi 4xx có lý do."))
A(("table", "Bảng 2.3. Quy tắc nghiệp vụ",
   ["Mã", "Quy tắc", "Lý do"],
   [["BR1", "Mỗi tài khoản thuộc đúng một nhà. Người mới vào nhà bằng mã mời, mã chỉ dùng được một lần và có hạn", "Một người không xem được dữ liệu của nhiều nhà. Mã bị lộ chỉ có tác dụng trong thời gian ngắn"],
    ["BR2", "Mỗi công tơ chỉ ghép với một nhà bằng mã ghép. Số đo chỉ được nhận từ công tơ đã ghép, kèm API key của thiết bị", "Số đo luôn gắn đúng nhà"],
    ["BR3", "Batch số đo phải idempotent và liên tục: gửi lại cùng `Idempotency-Key` không ghi hai lần. Batch không được để hở hoặc chồng khoảng thời gian so với batch trước", "Mạng lỗi hoặc cảm biến gửi lại không làm sai điện năng"],
    ["BR4", "Tiền điện tính theo biểu giá sinh hoạt 5 bậc, dùng đúng phiên bản biểu giá có hiệu lực trong kỳ tính", "Hóa đơn đã tính không đổi khi có biểu giá mới"],
    ["BR5", "Dự báo hóa đơn cần ít nhất 7 ngày dữ liệu, so sánh nhóm cần ít nhất 10 hộ, M&V cần ít nhất 14 ngày. Không đủ điều kiện thì trả lỗi 4xx kèm lý do", "Không đưa ra con số thiếu cơ sở. So sánh nhóm không lộ hộ cụ thể"],
    ["BR6", "Energy Copilot chỉ dành cho gói Pro. Gói thường vẫn dùng đủ dashboard và phân tích", "Phản ánh mô hình hai gói của dự án"],
    ["BR7", "Thông báo chủ động có giới hạn N thông báo mỗi ngày (N cấu hình được) và không gửi trong giờ yên tĩnh. Gợi ý bị từ chối được xếp hạng thấp ở lần sau", "Tránh làm phiền người dùng"],
    ["BR8", "Mọi con số trong câu trả lời của Copilot do công cụ tính từ dữ liệu của hộ, mô hình chỉ diễn giải. Câu trả lời sai số liệu, đơn vị hoặc nguồn bị loại trước khi gửi", "Câu trả lời kiểm chứng được"],
    ["BR9", "PII được ẩn trước khi gửi cho nhà cung cấp LLM. Copilot chỉ đọc dữ liệu của chính hộ đang hỏi", "Bảo vệ riêng tư"]],
   [800, 5071, 3200]))
A(("p", "Các quy tắc cũng cho thấy dữ liệu nào thuộc về đâu. BR1 đến BR4 là quy tắc trên dữ liệu ghi nhận (nhà, công tơ, số đo, hóa đơn) và cần một nguồn sự thật duy nhất. BR5 là quy tắc của phần phân tích, còn BR6 đến BR9 thuộc về trợ lý AI. Chương 3 dùng chính ranh giới này để chia service."))

A(("h2", "2.4. Yêu cầu phi chức năng"))
A(("p", "Năm yêu cầu dưới đây không nằm trong chức năng nhưng quyết định hình dạng kiến trúc (bảng 2.4)."))
A(("table", "Bảng 2.4. Yêu cầu phi chức năng và ảnh hưởng đến kiến trúc",
   ["Yêu cầu", "Diễn giải", "Ảnh hưởng đến kiến trúc"],
   [["Không mất, không trùng số đo", "Cảm biến có thể gửi lại khi mất mạng. Số đo sai làm sai mọi con số phía sau", "Idempotency key, kiểm tra batch liên tục, ghi dữ liệu và sự kiện trong cùng transaction"],
    ["Lỗi một thành phần không lan ra toàn hệ thống", "LLM chậm hoặc model NILM quá tải không được làm dashboard ngừng hoạt động", "Tách service theo kiểu lỗi. Timeout, retry, circuit breaker. Trạng thái PENDING"],
    ["Bảo mật và riêng tư", "Dữ liệu điện năng phản ánh sinh hoạt của gia đình", "JWT kiểm tại gateway. Ẩn PII trước khi gọi LLM. Mỗi service một database và một role"],
    ["Chạy được trên máy của nhóm bằng một lệnh", "Đề bài yêu cầu demo trực tiếp", "Dockerfile cho từng service, một file compose. Ít container"],
    ["Đội ba người vẫn bảo trì được", "Mỗi công nghệ thêm vào là thêm một thứ phải học và sửa lỗi", "Một ngôn ngữ cho backend, thư viện dùng chung, ưu tiên phần mềm có sẵn thay vì tự viết"]],
   [2300, 3200, 3571]))

A(("h2", "2.5. Nguồn số đo và dữ liệu thử"))
A(("p", "Ngoài đời, mỗi nhà gắn một cảm biến dòng (CT) ở aptomat tổng, ví dụ Shelly EM hoặc ESP32 chạy ESPHome. Cảm biến đo công suất tổng và gửi từng batch qua HTTPS tới gateway. Nhóm không có thiết bị này, nên dùng một công cụ gọi là REFIT replayer thay cho nó."))
A(("p", "REFIT [@refit] là bộ dữ liệu công khai về điện năng của các hộ gia đình ở Vương quốc Anh, đo liên tục trong khoảng hai năm với chu kỳ 8 giây, gồm công suất tổng và công suất của từng thiết bị. Replayer là một script Python đọc các file CSV của REFIT và gửi batch qua gateway, dùng đúng endpoint, API key và `Idempotency-Key` như cảm biến thật, có thể tua nhanh thời gian để demo. Nhờ vậy phần còn lại của hệ thống không phân biệt được hai nguồn. Trên các sơ đồ kiến trúc, replayer được vẽ như một nguồn số đo bên ngoài, kèm ghi chú rằng nó thay cho cảm biến thật và dữ liệu là public dataset."))

# ---------------- Chương 3 ----------------
A(("h1", "CHƯƠNG 3. PHÂN TÍCH VÀ THIẾT KẾ KIẾN TRÚC"))
A(("h2", "3.1. Tổng quan kiến trúc"))
A(("p", "Nhóm vẽ kiến trúc theo mô hình C4 [@c4], gồm ba cấp: Context cho thấy hệ thống và những gì bên ngoài nó, Container cho thấy các khối chạy độc lập bên trong, Component cho thấy các module bên trong từng container. Cấp Code không được vẽ. Hình 3.1 là bản tổng quan một trang."))
A(("p", "Người dùng và replayer gọi vào API Gateway (Envoy). Gateway kiểm JWT rồi chuyển yêu cầu tới bốn service nghiệp vụ. Các service gọi nhau đồng bộ theo một chiều copilot → insight → core → nilm, và đẩy thông tin ngược lại bằng sự kiện qua RabbitMQ. Mỗi service có database riêng, tất cả chạy trên một PostgreSQL server dùng chung hạ tầng."))
A(("fig", "00-overview", "Hình 3.1. Kiến trúc tổng quan của WattPrint. Mũi tên liền là lời gọi đồng bộ, mũi tên đứt là sự kiện bất đồng bộ qua RabbitMQ", 25.0, 12.0))

A(("h2", "3.2. Bối cảnh hệ thống"))
A(("p", "Hình 3.2 là sơ đồ Context. WattPrint được xem là một khối duy nhất, xung quanh là hai nhóm người dùng, nguồn số đo và các hệ thống ngoài đã nêu ở mục 2.1. Sơ đồ cho thấy hai điều. Thứ nhất, WattPrint không tự lưu mật khẩu: đăng nhập đi qua Keycloak, và Keycloak liên kết với Google Identity khi người dùng chọn đăng nhập bằng Google. Thứ hai, mọi dữ liệu gửi cho nhà cung cấp LLM đều đã được ẩn PII (BR9), nên nhà cung cấp này được coi là bên ngoài ranh giới tin cậy."))
A(("fig", "01-system-context", "Hình 3.2. Sơ đồ System Context của WattPrint", 22.0, 13.9))

A(("h2", "3.3. Phân rã thành service"))
A(("h3", "3.3.1. Căn cứ để chia"))
A(("p", "Nhóm chia theo ba căn cứ, theo thứ tự ưu tiên:"))
A(("ol", [
 "**Ranh giới dữ liệu và nghiệp vụ.** Dữ liệu ghi nhận (nhà, số đo, hóa đơn), tính toán ML, phân tích và tương tác AI mỗi mảng có bộ bảng riêng. Mảng này chỉ cần đọc dữ liệu của mảng kia, không cần sửa. Đây là căn cứ chính, vì mục tiêu của microservices là mỗi service sở hữu dữ liệu của mình [@newman].",
 "**Khác nhau về tài nguyên.** Suy luận NILMFormer chạy trên PyTorch và cần nhiều CPU và RAM. Nhận số đo cần ổn định và nhanh. Phân tích chạy theo lô và theo lịch. Copilot phần lớn thời gian chờ LLM bên ngoài.",
 "**Khác nhau về kiểu lỗi.** LLM bên ngoài chậm và hay lỗi, nên cần cô lập để lỗi này không lan sang việc nhận số đo. Model NILM quá tải thì phần nhận số đo vẫn phải chạy và đánh dấu batch chờ xử lý.",
]))
A(("h3", "3.3.2. Các phương án đã cân nhắc"))
A(("p", "Bảng 3.1 so sánh ba mức độ chia. Nhóm chọn phương án B."))
A(("table", "Bảng 3.1. Các phương án phân rã service",
   ["Phương án", "Cách chia", "Nhận xét"],
   [["A. Hai service", "Gộp core và insight. Gộp nilm và copilot", "Không đạt tối thiểu ba service nghiệp vụ. Còn gộp hai khối khác hẳn nhau: nilm tốn CPU, copilot chủ yếu chờ LLM"],
    ["B. Bốn service (chọn)", "core, nilm, insight, copilot", "Mỗi service có một nhóm dữ liệu, một kiểu tải và một kiểu lỗi riêng. Số lượng vừa sức ba người"],
    ["C. Bảy service trở lên", "Tách thêm billing, device, alert, notification", "Mỗi service chỉ có vài bảng nhưng thêm database, lời gọi mạng và việc vận hành. Billing cần đọc số đo của core nên phụ thuộc dữ liệu rất chặt, tách ra không thêm được độc lập nào"]],
   [2000, 2800, 4271]))
A(("h3", "3.3.3. Kết quả phân rã"))
A(("p", "Bảng 3.2 là kết quả: bốn service, mỗi service một database, với trách nhiệm và hướng gọi rõ ràng."))
A(("table", "Bảng 3.2. Service, trách nhiệm, dữ liệu riêng và đối tượng gọi tới",
   ["Service", "Trách nhiệm", "Dữ liệu riêng", "Gọi tới"],
   [["core", "Nhà, thành viên, mã mời, ghép công tơ, thiết bị, nhận batch số đo, biểu giá 5 bậc, hóa đơn. Là nguồn sự thật", "core_db (TimescaleDB)", "nilm"],
    ["nilm", "Suy luận NILMFormer, hiệu chỉnh theo hộ, quản lý phiên bản model", "nilm_db và volume chứa model", "Không gọi service nào"],
    ["insight", "Read model tiêu thụ, bất thường, chạy ngầm, dự báo hóa đơn và bậc giá, ngân sách, so sánh nhóm, what-if, M&V, truy vấn an toàn cho Text-to-SQL", "insight_db (TimescaleDB)", "core, Open-Meteo"],
    ["copilot", "Hỏi đáp, gợi ý chủ động, guardrail PII và prompt injection, verifier, RAG, xếp hạng theo phản hồi, thông báo, thống kê token, kế hoạch tiết kiệm", "copilot_db (pgvector)", "insight, LLM, Expo Push, Telegram"]],
   [1100, 4300, 2100, 1571]))
A(("p", "Bảng 3.2 kéo theo ba điều cần nói rõ. Thứ nhất, hóa đơn chính thức nằm ở core vì nó được tính từ số đo ghi nhận và phải nhất quán với nguồn sự thật, trong khi dự báo hóa đơn là ước tính nên nằm ở insight. Thứ hai, nilm không gọi service nào và chỉ nhận yêu cầu suy luận, nên là điểm cuối của chuỗi gọi. Thứ ba, copilot không đọc trực tiếp dữ liệu tiêu thụ mà đi qua insight, lý do nằm ở mục 3.7."))
A(("p", "Hướng gọi đồng bộ chỉ đi một chiều copilot → insight → core → nilm. Nhờ vậy không có vòng phụ thuộc, và một service ngừng chỉ ảnh hưởng các service nằm ngay phía trên nó trong chuỗi."))

A(("h2", "3.4. Các khối triển khai"))
A(("p", "Hình 3.3 là sơ đồ Container. Ngoài bốn service do nhóm viết, hệ thống dùng bốn phần mềm có sẵn: Envoy làm gateway, Keycloak làm identity, RabbitMQ làm broker và PostgreSQL làm database. Cộng lại là tám container, chưa kể hai ứng dụng client chạy ngoài compose. Mỗi service là một container duy nhất: API, consumer sự kiện, outbox relay và các job định kỳ chạy chung một process dưới dạng background task. Cách này giữ số container ở mức máy của nhóm chạy được, thay vì tách thêm worker riêng cho từng việc."))
A(("p", "Theo quy ước của C4, mỗi queue được vẽ như một container lưu message, còn RabbitMQ (broker) chỉ là chi tiết triển khai [@c4]. Vì vậy sơ đồ có bốn khối queue màu vàng: `insight.usage`, `copilot.alerts` và hai hàng đợi lỗi `.dlq` của chúng."))
A(("fig", "02-container", "Hình 3.3. Sơ đồ Container của WattPrint. Nét đứt là message AMQP: mũi tên đi tới queue là bên gửi, đi ra khỏi queue là bên nhận", 25.0, 16.5))

A(("h2", "3.5. Giao tiếp giữa các service"))
A(("h3", "3.5.1. Gọi đồng bộ qua REST"))
A(("p", "Lời gọi cần kết quả ngay (core hỏi nilm, insight hỏi core, copilot hỏi insight) dùng REST qua HTTP, đi thẳng trong mạng nội bộ của compose mà không qua gateway. Service gọi chuyển tiếp danh tính người dùng và mã yêu cầu, địa chỉ của service phía sau lấy từ biến môi trường. Phía gọi phải đặt timeout, thử lại có giới hạn và phân biệt lỗi nghiệp vụ (4xx, giữ nguyên) với lỗi hạ tầng (timeout là 504, không kết nối được hoặc breaker mở là 503). Chi tiết thiết kế phần này thuộc chương về độ tin cậy."))
A(("h3", "3.5.2. Sự kiện bất đồng bộ qua RabbitMQ"))
A(("p", "Có những thông tin không nên bắt service gửi phải chờ. Khi core có số liệu tiêu thụ mới, core không cần biết insight cập nhật xong lúc nào. Khi insight phát hiện bất thường, insight không cần chờ copilot soạn xong gợi ý. Hai trường hợp này dùng sự kiện qua RabbitMQ (bảng 3.3). Mỗi consumer có một quorum queue [@rabbit] với giới hạn giao lại `delivery-limit = 3` và một hàng đợi lỗi đi kèm."))
A(("table", "Bảng 3.3. Các sự kiện trên exchange `wattprint.events` (kiểu topic)",
   ["Routing key", "Bên phát", "Bên nhận", "Mục đích"],
   [["`energy.usage.updated`", "core", "insight", "Có ước tính mới, kèm tổng theo giờ của từng thiết bị"],
    ["`core.device.changed`", "core", "insight", "Đồng bộ danh mục thiết bị vào read model"],
    ["`insight.alert.created`", "insight", "copilot", "Kích hoạt gợi ý chủ động"]],
   [2500, 1100, 1200, 4271]))
A(("p", "Một sự kiện đi qua chín bước, minh họa ở hình 3.4 bằng sự kiện `energy.usage.updated` từ core tới insight:"))
A(("ol", [
 "core lưu kết quả NILM và một dòng vào bảng `outbox` trong cùng một transaction.",
 "Outbox relay (vòng lặp nền trong core) đọc các dòng chưa gửi bằng `SELECT ... FOR UPDATE SKIP LOCKED`, nên chạy nhiều tiến trình cũng không gửi trùng.",
 "Relay publish lên exchange `wattprint.events` kèm routing key, đợi broker xác nhận rồi mới đánh dấu đã gửi.",
 "Exchange chép message vào mọi queue có binding khớp. `insight.usage` bind `energy.usage.*` và `core.device.*`.",
 "RabbitMQ giao message cho consumer của insight. Consumer lỗi thì nack và RabbitMQ giao lại.",
 "Consumer tra `message_id` trong bảng `inbox`. Đã có thì bỏ qua. Chưa có thì cập nhật read model và ghi inbox trong cùng một transaction, rồi ack.",
 "Giao quá ba lần vẫn lỗi, queue chuyển message sang dead-letter exchange `wattprint.dlx`.",
 "`wattprint.dlx` chép message vào `insight.usage.dlq`, message nằm chờ ở đó chứ không mất.",
 "Nhóm vận hành xem hàng đợi lỗi trên giao diện RabbitMQ, sửa nguyên nhân rồi chuyển message về `insight.usage` để chạy lại.",
]))
A(("p", "Hai bảng outbox và inbox giải quyết hai lỗi khác nhau. Nếu chỉ lưu database rồi publish riêng, tiến trình chết giữa hai việc sẽ làm insight thiếu hoặc thừa dữ liệu. Ghi sự kiện vào bảng outbox cùng transaction với dữ liệu loại bỏ lỗi đó, và mẫu này được gọi là transactional outbox [@richardson]. Phía nhận, RabbitMQ chỉ bảo đảm giao ít nhất một lần, nên một message có thể đến hai lần. Bảng inbox lưu `message_id` đã xử lý để consumer bỏ qua bản trùng, nhờ đó consumer là idempotent."))
A(("fig", "x6-dynamic-messaging-rabbitmq", "Hình 3.4. Một sự kiện đi qua RabbitMQ: outbox, exchange, queue, consumer, hàng đợi lỗi (DLQ)", 25.0, 10.5))

A(("h2", "3.6. Luồng nghiệp vụ nhiều bước và xử lý lỗi giữa chừng"))
A(("p", "Đề bài yêu cầu ít nhất một luồng đi qua hai service và có cách xử lý khi lỗi giữa chừng. WattPrint có hai luồng như vậy, mỗi luồng dùng một cách xử lý khác nhau tùy việc có thể hoàn tác hay không."))
A(("h3", "3.6.1. Nhận số đo và suy luận NILM"))
A(("p", "Khi nhận một batch, core kiểm API key, kiểm công tơ thuộc nhà và kiểm batch liên tục (BR2, BR3), lưu số đo rồi gọi nilm. Nếu nilm trả lời kịp, core lưu ước tính, ghi sự kiện vào outbox và trả 201 với trạng thái `DONE`. Nếu nilm hết thời gian, báo lỗi 5xx hoặc breaker đang mở, core không biết kết quả suy luận. Core không hoàn tác số đo, vì số đo là dữ liệu thật và không được mất. Thay vào đó core đánh dấu batch là `PENDING_INFERENCE`, trả 202, và một tác vụ nền gửi lại với backoff 1, 2, 4 phút. Quá năm lần vẫn lỗi thì batch chuyển sang `FAILED` và phát cảnh báo cho nhóm vận hành. Đây là cách xử lý bằng trạng thái PENDING (hình 3.5)."))
A(("fig", "x2-dynamic-ingest-nilm", "Hình 3.5. Luồng nhận số đo và suy luận NILM, có trạng thái PENDING_INFERENCE khi nilm không trả lời", 25.0, 14.0))
A(("h3", "3.6.2. Kích hoạt kế hoạch tiết kiệm"))
A(("p", "Khi người dùng chấp nhận một gợi ý, copilot chạy một saga qua insight. Bước một tạo baseline M&V ở insight (cần ít nhất 14 ngày dữ liệu, thiếu thì insight trả 422). Bước hai đặt ngân sách tháng theo kế hoạch. Có ba kết cục. Bước hai thành công thì kế hoạch chuyển `ACTIVE`. Bước hai bị insight từ chối bằng lỗi nghiệp vụ 4xx thì copilot hoàn tác bước một theo thứ tự ngược bằng cách xóa baseline, rồi đánh dấu kế hoạch `CANCELLED` kèm lý do. Bước hai hết thời gian (lỗi hạ tầng, 504) thì copilot không biết insight đã ghi hay chưa, nên giữ kế hoạch ở `PENDING`, và một tác vụ reconciler hỏi lại insight để hoàn tất hoặc bù trừ sau. Hình 3.6 mô tả cả ba nhánh."))
A(("p", "Luồng này phụ thuộc vào việc phân biệt hai loại lỗi: lỗi nghiệp vụ cho biết chắc chắn bước chưa xảy ra nên hoàn tác được ngay, còn lỗi hạ tầng không cho biết gì nên phải chờ và kiểm tra lại."))
A(("fig", "x5-dynamic-saving-plan-saga", "Hình 3.6. Luồng kích hoạt kế hoạch tiết kiệm (saga): thành công, hoàn tác theo thứ tự ngược và PENDING", 24.0, 14.0))

A(("h2", "3.7. Dữ liệu"))
A(("p", "Dữ liệu dùng một PostgreSQL server với năm database: `core_db`, `insight_db`, `copilot_db`, `nilm_db` và `keycloak_db`. Mỗi database có một role riêng, và không service nào có quyền vào database của service khác. Dùng một server cho cả năm database giữ số container ở mức tám, trong khi ranh giới dữ liệu vẫn tách bạch như mẫu database per service [@newman]. Khi cần, mỗi database có thể chuyển sang server riêng, vì địa chỉ kết nối của từng service lấy từ biến môi trường."))
A(("p", "Server dùng PostgreSQL 18 với hai extension. TimescaleDB lo chuỗi thời gian ở `core_db` (số đo, tổng hợp theo giờ và ngày, nén, xóa theo hạn lưu) và ở `insight_db` (read model tiêu thụ). pgvector lo việc tìm kiếm vector cho RAG ở `copilot_db`."))
A(("p", "Vì không service nào đọc database của service khác, mọi nhu cầu đọc chéo được giải quyết bằng một trong hai cách:"))
A(("ul", [
 "**Sự kiện.** insight giữ một bản sao dữ liệu tiêu thụ đã tổng hợp theo giờ, cập nhật từ sự kiện của core. Đây là mẫu CQRS [@richardson]: core lo phần ghi và là nguồn sự thật, insight lo phần đọc và phân tích.",
 "**API.** Khi cần dữ liệu mới nhất hoặc dữ liệu nhỏ, service hỏi thẳng service sở hữu, ví dụ insight lấy biểu giá và danh sách thiết bị từ core.",
]))
A(("p", "Quyết định này ảnh hưởng nhiều nhất đến Copilot. Copilot dùng Text-to-SQL để trả lời các câu hỏi tự do về điện năng, tức là mô hình ngôn ngữ sinh câu SQL. Nếu câu SQL chạy trên database ghi nhận của core, một câu lệnh sai hoặc bị prompt injection có thể chạm vào dữ liệu nguồn. Vì vậy Copilot gửi câu SQL tới endpoint truy vấn an toàn của insight. Endpoint này chỉ cho SELECT trên các view được phép, ép điều kiện nhà của người hỏi và đặt timeout 2 giây, và nó chạy trên database phân tích của insight chứ không phải của core. Khi chia service, các bảng đổi chủ theo đúng nhóm nghiệp vụ ở bảng 3.2: các bảng phân tích đi cùng insight, bảng lần chạy suy luận đi cùng nilm, hội thoại và tri thức đi cùng copilot."))

A(("h2", "3.8. Gateway và bảo mật"))
A(("p", "Gateway là Envoy, cấu hình trong một file `envoy.yaml`. Theo đề bài, gateway chỉ định tuyến và áp chính sách, không chứa luật nghiệp vụ. Mọi chính sách đều là bộ lọc có sẵn của Envoy:"))
A(("ul", [
 "Định tuyến theo tiền tố `/api/core/`, `/api/insight/`, `/api/copilot/` và `/api/nilm/` (chỉ admin), mỗi route có timeout và quy tắc thử lại. Chỉ yêu cầu GET được thử lại khi lỗi kết nối, yêu cầu POST thì không, để không ghi hai lần.",
 "Bộ lọc `jwt_authn` kiểm chữ ký RS256, `issuer` và `audience` của JWT với khóa công khai (JWKS) lấy từ Keycloak [@envoy]. Sau khi kiểm, Envoy gán `sub` và role của token vào header `X-User-Id` và `X-User-Roles`, đồng thời xóa header cùng tên do client tự gửi, nên service phía sau tin được hai header này.",
 "Giới hạn tốc độ (rate limit), giới hạn kích thước body và gán mã yêu cầu `x-request-id` để lần theo log.",
 "Route nhận số đo của cảm biến không yêu cầu JWT, vì thiết bị không đăng nhập. Core tự kiểm API key và công tơ thuộc nhà (BR2).",
]))
A(("p", "Quyền theo nhà, theo gói Pro và theo role admin do từng service kiểm, vì đó là luật nghiệp vụ. Service không mở cổng ra ngoài nên chỉ gateway và các service khác trong mạng nội bộ gọi được."))

A(("h2", "3.9. Công nghệ sử dụng"))
A(("p", "Nguyên tắc chọn công nghệ là giữ số loại công nghệ nhỏ và ưu tiên cấu hình có sẵn hơn mã tự viết, vì nhóm chỉ có ba người (bảng 3.4). Toàn bộ backend dùng một ngôn ngữ (Python). Client dùng TypeScript."))
A(("table", "Bảng 3.4. Công nghệ sử dụng và lý do chọn",
   ["Lớp", "Chọn", "Lý do"],
   [["Gateway", "Envoy 1.40", "Kiểm JWT, rate limit, request id, timeout, retry đều là bộ lọc có sẵn, không phải viết mã. Chuẩn công nghiệp, là lõi của nhiều service mesh"],
    ["Identity", "Keycloak 26", "Cấp JWT, liên kết đăng nhập Google. Dùng database `keycloak_db` trên server chung"],
    ["Database", "PostgreSQL 18, TimescaleDB 2.31, pgvector", "Một server cho cả dữ liệu quan hệ, chuỗi thời gian và vector. Không cần ba loại database khác nhau"],
    ["Message broker", "RabbitMQ 4, quorum queue", "Giới hạn giao lại và dead-letter exchange có sẵn, không cần tự viết cơ chế retry"],
    ["Service", "Python 3.12, FastAPI, SQLAlchemy async, Alembic", "Giữ nguyên mã đang có. FastAPI tự sinh OpenAPI"],
    ["Messaging trong service", "FastStream", "Viết consumer như route FastAPI, tự sinh tài liệu AsyncAPI, có broker giả lập trong bộ nhớ để kiểm thử"],
    ["Gọi HTTP và chịu lỗi", "httpx, tenacity. Circuit breaker và bulkhead tự viết trong thư viện chung", "Thư viện circuit breaker phổ biến chỉ hỗ trợ async qua Tornado, nên nhóm tự viết khoảng 30 dòng và dùng `asyncio.Semaphore` làm bulkhead [@nygard]"],
    ["Mã nguồn", "Monorepo uv workspace: `services/` và `libs/common`", "Một lockfile. Phần chịu lỗi, log, outbox và inbox viết một lần cho cả bốn service"],
    ["Kiểm tra", "ruff, pytest, Postman với Newman, GitHub Actions", "Chạy test, build image, dựng compose và chạy Postman collection tự động"]],
   [1700, 2800, 4571]))
A(("p", "Nhóm cố ý không dùng Prometheus, Grafana, Loki, Jaeger, container worker riêng và container database riêng cho Keycloak. Log của mỗi container ghi JSON ra stdout kèm `request_id`, xem được bằng `docker compose logs`, đủ để lần theo một yêu cầu qua các service."))

A(("h2", "3.10. Thành phần bên trong từng service"))
A(("p", "Các sơ đồ Component dưới đây cho thấy bên trong mỗi container có những module nào và module nào gọi ra ngoài. Các mũi tên không ghi nhãn là lời gọi hàm trong cùng process. Màu sắc theo quy ước chung của các sơ đồ: xanh lá là phần do nhóm viết, tím là phần mềm có sẵn, vàng là queue, xanh ngọc là kho dữ liệu, cam là hệ thống ngoài, còn nét đứt là sự kiện bất đồng bộ."))
A(("p", "**core** (hình 3.7) có ba nhóm API là nhà và thiết bị, nhận số đo (ingest) và hóa đơn. `IngestService` ghi số đo và sự kiện qua `Repositories` trong cùng một transaction. `OutboxRelay` và `PendingRetrier` là hai tác vụ nền: một gửi sự kiện, một gửi lại các batch đang chờ suy luận. `NilmClient` là nơi duy nhất core gọi ra service khác, nên timeout, retry và circuit breaker tập trung ở đó."))
A(("p", "**nilm** (hình 3.8) tách làm API suy luận và API quản lý model (chỉ admin). `InferenceEngine` chạy NILMFormer, `Calibrator` hiệu chỉnh theo từng hộ và `ModelLoader` nạp trọng số một lần rồi giữ trong RAM. API suy luận giới hạn số yêu cầu chạy đồng thời để một đợt tải cao không làm cạn bộ nhớ (bulkhead)."))
A(("p", "**insight** (hình 3.9) nhận sự kiện qua `Usage consumer` và cập nhật read model, sau đó các bộ phát hiện (`Detectors`) kiểm tra bất thường, chạm bậc giá và vượt ngân sách, rồi phát `insight.alert.created` qua `OutboxRelay`. Phía API có phần phân tích và dự báo, cùng `SQL guard` bảo vệ endpoint truy vấn an toàn (mục 3.7)."))
A(("p", "**copilot** (hình 3.10) có hai đường vào. Đường hỏi đáp đi từ `Chat API` qua `Guardrail` (ẩn PII, chặn prompt injection, kiểm gói Pro) tới `Orchestrator`, nơi mô hình gọi công cụ để lấy số liệu từ insight, rồi `Verifier` kiểm số liệu, đơn vị và trích dẫn trước khi trả lời. Đường chủ động đi từ `Alert consumer` qua `Ranker` (xếp hạng theo phản hồi, giờ yên tĩnh, chống trùng) tới `Notifier`. `Saga orchestrator` điều phối kế hoạch tiết kiệm (mục 3.6.2)."))
A(("fig", "03-component-core", "Hình 3.7. Sơ đồ Component của service core", 22.0, 15.5))
A(("fig", "04-component-nilm", "Hình 3.8. Sơ đồ Component của service nilm", 18.5, 15.5))
A(("fig", "05-component-insight", "Hình 3.9. Sơ đồ Component của service insight", 22.0, 15.5))
A(("fig", "06-component-copilot", "Hình 3.10. Sơ đồ Component của service copilot", 25.0, 14.8))

# ---------------- Chương 4 ----------------
A(("h1", "CHƯƠNG 4. ĐÁNH ĐỔI VÀ RỦI RO CỦA KIẾN TRÚC"))
A(("h2", "4.1. Các quyết định chính và đánh đổi"))
A(("p", "Mỗi quyết định ở chương 3 đều có giá phải trả. Bảng 4.1 ghi lại những quyết định lớn, lý do và đánh đổi mà nhóm chấp nhận."))
A(("table", "Bảng 4.1. Quyết định kiến trúc và đánh đổi",
   ["Quyết định", "Lý do", "Đánh đổi chấp nhận"],
   [["Chia bốn service thay vì giữ nguyên khối", "Mỗi service có dữ liệu, tải và kiểu lỗi riêng. Đáp ứng yêu cầu đề bài", "Thêm lời gọi mạng, thêm chỗ có thể lỗi từng phần, khó gỡ lỗi hơn một process"],
    ["Không chia thành bảy service", "Giữ số container, database và lời gọi mạng ở mức ba người quản lý được", "Mỗi service lớn hơn. Core giữ cả hóa đơn lẫn quản lý nhà"],
    ["Gọi đồng bộ một chiều", "Không có vòng phụ thuộc. Lỗi chỉ lan lên một tầng", "Copilot phải đi qua insight để tới dữ liệu, thêm một bước so với đọc trực tiếp"],
    ["Sự kiện qua RabbitMQ cho hai luồng phụ", "Bên gửi không phải chờ bên nhận. Có hàng đợi lỗi để kiểm tra và chạy lại", "Dữ liệu insight chậm hơn core một chút (nhất quán sau cùng). Phải có bảng outbox và inbox"],
    ["Một PostgreSQL server cho năm database", "Giữ tám container. Vẫn tách quyền theo role", "Server là điểm lỗi chung về hạ tầng. Tài nguyên dùng chung giữa các service"],
    ["Bốn service cùng một ngôn ngữ, chung thư viện", "Viết phần chịu lỗi, outbox, inbox một lần. Ít thứ để học", "Phụ thuộc vào Python cho backend. Cập nhật thư viện chung ảnh hưởng cả bốn service"],
    ["Một container cho mỗi service (API, consumer, relay chung process)", "Dễ chạy và dễ theo dõi log", "Không co giãn riêng từng phần. Tác vụ nền nặng cạnh tranh tài nguyên với API"],
    ["Tự viết circuit breaker và bulkhead", "Thư viện sẵn có không hợp với async của FastAPI", "Phải tự kiểm thử. Có thể thiếu tính năng của thư viện trưởng thành"]],
   [2500, 3200, 3371]))

A(("h2", "4.2. Rủi ro còn lại và hướng xử lý"))
A(("p", "Bảng 4.2 liệt kê các rủi ro nhóm đã nhận diện ở mức kiến trúc. Cách xử lý chi tiết và số liệu thử nghiệm sẽ nằm ở các chương về độ tin cậy và đánh giá."))
A(("table", "Bảng 4.2. Rủi ro và hướng xử lý",
   ["Rủi ro", "Biểu hiện", "Hướng xử lý"],
   [["nilm quá tải hoặc ngừng", "core không nhận được kết quả suy luận", "Trạng thái `PENDING_INFERENCE` và gửi lại có backoff. Circuit breaker. Bulkhead ở nilm"],
    ["LLM chậm hoặc lỗi", "Copilot không trả lời. Không được kéo theo dashboard", "Timeout 20 giây, circuit breaker, thông báo lỗi 503 rõ ràng. Dashboard và phân tích không phụ thuộc LLM"],
    ["Message đến hai lần hoặc không đến", "Read model của insight thừa hoặc thiếu", "Inbox chống trùng. Outbox chống mất. Hàng đợi lỗi giữ message để chạy lại"],
    ["Read model lệch so với core", "Số liệu phân tích khác số liệu hóa đơn", "Số liệu hóa đơn chính thức luôn lấy từ core. Cách đồng bộ lại read model khi phát hiện lệch sẽ được xác định ở phần triển khai"],
    ["Copilot trả lời sai số liệu", "Người dùng tin vào con số sai", "Số liệu do công cụ tính. Verifier loại câu trả lời sai số, đơn vị hoặc nguồn (BR8)"],
    ["Lộ thông tin cá nhân qua LLM hoặc Text-to-SQL", "Prompt chứa PII. Câu SQL chạm dữ liệu nguồn", "Guardrail ẩn PII. Truy vấn chạy qua endpoint của insight với SQL guard và database phân tích riêng"],
    ["PostgreSQL ngừng", "Mọi service mất dữ liệu cùng lúc", "Chấp nhận trong phạm vi bài tập. Hướng nâng cấp là tách database sang server riêng hoặc replica"]],
   [2300, 2700, 4071]))
