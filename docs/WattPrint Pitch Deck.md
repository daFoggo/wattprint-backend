---
aliases:
---
# Slide 1 - Giới thiệu
- Tên dự án: WattPrint - Hệ thống theo dõi tiêu thụ thiết bị và Trợ lý năng lượng cá nhân hóa cho gia đình
- Đội thi: UDU.S4U
# Slide 2 - Bài toán
- Tiêu đề: Thông tin rõ ràng hơn có thể giúp người dung chủ động thay đổi hành vi tiết kiệm điện
- Nội dung:
	- Một thí nghiệm trên 45.000 hộ dân Việt Nam chia thành các nhóm được xem thông tin ước tính hóa đơn tiêu thụ theo ngày, giúp họ chủ động giảm tiêu thụ so với cùng kỳ của nhóm không được xem. Điều đó cho thấy rằng chỉ cần thông tin đơn giản cũng có thể là cú huých giúp người dùng chủ động hơn trong việc tiết kiệm năng lượng [1].
	- Một nghiên cứu ở Mỹ cho thấy người dùng đoán thấp điện năng của các thiết bị khoảng 2,8 lần, và đoán thấp nhiều nhất ở những thiết bị tốn điện nhất [2]. Họ khó biết nên tiết kiệm ở đâu.
	- EVN gần đây cũng đã cung cấp công cụ mới để theo dõi điện năng, song chỉ ngưng lại ở việc cung cấp con số tiêu thụ tổng của hộ trong ngày [3]. Nếu người dùng có cái nhìn chi tiết hơn về tiêu thụ của từng thiết bị trong gia đình, họ có thể chủ động hơn trong việc tiết kiệm đúng thiết bị thay vì chỉ dựa trên những lời khuyên chung hay phỏng đoán.
	- Để người dùng theo dõi được chi tiết từng thiết bị, họ cần chi ra số tiền ước tính ít nhất từ 4 đến 10 triệu đồng với trung bình một hộ muốn theo dõi 10 điểm đo, và cần tự lắp đặt, kết nối các thiết bị [4][5].
- Vậy câu hỏi đặt ra: Có cách nào ước tính điện năng từng thiết bị với chi phí thấp hơn nhiều không?
- Nguồn:
1. Ta, C. (2025). _Usage information to save electricity in Vietnam_. IGC. [https://www.theigc.org/blogs/usage-information-vietnam-save-electricity](https://www.theigc.org/blogs/usage-information-vietnam-save-electricity)
2. Attari, S. Z. et al. (2010). Public perceptions of energy consumption and savings. _PNAS_. [https://pmc.ncbi.nlm.nih.gov/articles/PMC2941272/](https://pmc.ncbi.nlm.nih.gov/articles/PMC2941272/)
3. Báo Sài Gòn Giải Phóng (2026, 22/06). Tra cứu tiền điện hằng ngày trên app dùng chung của EVN. [https://www.sggp.org.vn/tra-cuu-tien-dien-hang-ngay-tren-app-dung-chung-cua-evn-post858550.html](https://www.sggp.org.vn/tra-cuu-tien-dien-hang-ngay-tren-app-dung-chung-cua-evn-post858550.html)
4. Tuya.vn. Ổ cắm WiFi đo điện TC1, 235.000 đ. [https://tuya.vn/o-cam-c-smart-series-wifi-cong-suat-lon-16a-tuya-tc1-p40701967.html](https://tuya.vn/o-cam-c-smart-series-wifi-cong-suat-lon-16a-tuya-tc1-p40701967.html)
5. Home Assistant. Home Assistant Green, 199 USD. [https://www.home-assistant.io/green/](https://www.home-assistant.io/green/)
# Slide 3 & 4 - Giải pháp & Sản phẩm
Câu trả lời của nhóm là WattPrint - hệ thống AI giúp hộ gia đình hiểu điện năng của từng thiết bị và đưa ra khuyến nghị hành vi để tiết kiệm điện. Thay vì cần nhiều cảm biến để theo dõi từng thiết bị, WattPrint chỉ cần một cảm biến duy nhất ở aptomat.
* WattPrint không chỉ hiển thị số liệu bị động. Hệ thống dùng AI biến dữ liệu thô thành thông tin hữu ích, giúp người dùng chủ động quản lý năng lượng. Giải pháp gồm bốn khối:
   1. NILMFormer - Phân rã dữ liệu từ một điểm đo duy nhất
      * Mục tiêu: chi phí thấp, hộ không cần hiểu kỹ thuật để lắp đặt, dễ bảo trì.
      * Cách làm: kỹ thuật NILM tách điện năng từng thiết bị từ số liệu đo tổng ở aptomat. NILMFormer là mô hình NILM dựa trên Transformer, xử lý tốt khi điện tổng lên xuống thất thường, điều làm nhiều mô hình khác nhầm thiết bị [1]. Nhóm bổ sung bước hiệu chỉnh theo từng hộ.
      * Thực tế: EDF (Pháp) đã dùng NILMFormer cho hàng triệu khách hàng [1].
   2. Dashboard BI & Billing - Trực quan hóa dữ liệu đã phân rã
      * Mục tiêu: giúp người dùng nắm bắt nhanh, và nâng nhận thức về mức tiêu thụ nhờ tiền điện đi kèm, tránh tư duy tiêu dùng sai lệch từ biểu giá 6 bậc.
      * Tính năng: tiêu thụ từng thiết bị theo giờ, ngày, tuần, tháng; nhật ký hoạt động trong ngày; mọi số liệu kèm số tiền theo biểu giá 6 bậc.
      * Ví dụ: trong tháng, điều hòa dùng 151,6 kWh, chiếm 42% điện cả nhà, tương ứng 426.669 đồng.
   3. Phân tích dự báo và phát hiện bất thường
      * Mục tiêu: giảm lãng phí và cho thấy các insight hữu ích mà biểu đồ không giải đáp như: tiền điện cao vì đâu, nguồn điện ngầm nào đang lãng phí, mình dùng nhiều hay ít so với người khác, cuối tháng phải trả bao nhiêu.
      * Cảnh báo bất thường: thiết bị tốn điện hoặc chạy lâu hơn thông thường để xử lý kịp thời. Ví dụ: điều hòa chạy liên tục hơn 3 giờ, khoảng 3,0 kWh.
      * Phát hiện chạy ngầm: thiết bị đáng ra có thể tắt (TV chờ, đầu thu, bộ sạc), để cắt điện lãng phí mà không thay đổi thói quen.
      * So sánh tiêu thụ với tháng trước và các hộ khác, để biết mình dùng nhiều hay ít.
      * Dự đoán hóa đơn cuối tháng và lúc chạm bậc giá tiếp theo, để điều chỉnh sớm hành vi.
   4. Energy Copilot hai chiều - LLM, Text-to-SQL, RAG
      * Vì sao cần: dashboard cho số nhưng không giải thích, còn chatbot thông thường không biết dữ liệu nhà bạn và có thể trả lời sai.
      * Vai trò và tác động: trợ lý hai chiều, trả lời khi được hỏi và chủ động gợi ý, giúp người dùng đi từ hiểu sang hành động và biết hành động đó tiết kiệm bao nhiêu.
      * Điểm mới: câu trả lời được tính từ dữ liệu thật của nhà, thời tiết và biểu giá điện, cá nhân hóa theo hộ gia đình, không chung chung.
      * Hỏi, đáp: giải đáp kèm nguyên nhân và việc nên làm. Ví dụ: "Tại sao tháng này tiền điện cao bất thường so với tháng trước?"
      * Chủ động gợi ý: tự phát hiện lãng phí và nhắc kèm mức tiết kiệm dự kiến; đề xuất hành vi bảo vệ sức khỏe theo thời gian thực, ví dụ nắng nóng nên mở cửa sổ, bật điều hòa ở mức nào và trong bao lâu; lập kế hoạch tiết kiệm, so kết quả trước và sau. Ví dụ: gói "tiết kiệm cân bằng" dự kiến giảm khoảng 29,8 kWh, tương đương 107.900 đồng mỗi tháng.
      * Lời khuyên đáng tin cậy: số liệu do công cụ tính, mô hình chỉ giải thích. Trước khi trả lời luôn kiểm tra truy vấn, đơn vị và nguồn để trích dẫn vào câu trả lời, đảm bảo thông tin luôn minh bạch. Trợ lý cũng học hỏi dần từ phản hồi của người dùng để các thông báo, hỏi đáp không lặp lại, gây phiền toái.
- (Các số liệu ví dụ là dữ liệu minh họa của bản mẫu.)
- Nguồn:
1. Petralia, A., Charpentier, P., Kadhi, Y., Palpanas, T. (2025). NILMFormer: Non-Intrusive Load Monitoring that Accounts for Non-Stationarity. ACM SIGKDD 2025. [https://arxiv.org/abs/2506.05880](https://arxiv.org/abs/2506.05880)
# Slide 5 - Tác động
- **Tiêu đề:** Thúc đẩy gia đình làm chủ và tiết kiệm năng lượng, xã hội tiết kiệm tài nguyên và phát triển bền vững.
- WattPrint đang được mô phỏng trong môi trường nghiên cứu, dự kiến thí điểm thực tế trong 3-6 tháng tới. Các tác động dưới đây là dự tính từ nghiên cứu trước, và sẽ được đo lại trong thí điểm.
- **Nội dung:**
    - **Thay đổi nhận thức:** Người dùng thấy rõ tiêu thụ từng thiết bị theo thời gian, thay vì phỏng đoán hay đợi cuối tháng mới biết, nên giảm bất ngờ, hoài nghi về tiền điện. Nhóm sẽ đo bằng độ lệch giữa mức người dùng đoán và số thật, trước và sau khi dùng.
    - **Thay đổi hành vi:** Nhận thức thôi chưa đủ để thúc đẩy hành vi, nên Energy Copilot gợi ý hành động cụ thể, ví dụ tắt thiết bị chạy ngầm hoặc điều chỉnh điều hòa ở mức nhiệt độ và thời gian cụ thể. Đây là giả thuyết của nhóm và sẽ được kiểm chứng.
    - **Tiết kiệm điện và chi phí:** Khi hộ gia đình được xem thông tin về lượng điện mình dùng, họ giảm khoảng 2-4% điện [1]. Ở Đà Nẵng, một thử nghiệm trên khoảng 1.000 hộ cho thấy giảm 4-7% [2]. Vì biểu giá điện có 6 bậc, mỗi kWh giảm ở bậc cao tiết kiệm được nhiều tiền hơn ở bậc thấp.
    - **Sức khỏe và tiện nghi:** Tiết kiệm không có nghĩa là phải chịu nóng. Energy Copilot gợi ý cách dùng điều hòa theo thời tiết thực tế, vừa đủ mát vừa đỡ tốn điện.
    - **Đóng góp cho xã hội:** Nếu 10.000 hộ, mỗi hộ dùng khoảng 3.500 kWh/năm (ước tính của nhóm), giảm 2-6% thì mỗi năm tiết kiệm khoảng 0,7-2 triệu kWh, tương đương 500-1.400 tấn CO₂ [3]. Đây là đóng góp nhỏ nhưng cùng hướng với chính sách quốc gia: mục tiêu tiết kiệm 8-10% năng lượng đến năm 2030 [4], mục tiêu phát thải ròng bằng 0 vào năm 2050 [5] và Luật Sử dụng năng lượng tiết kiệm và hiệu quả sửa đổi, hiệu lực từ 01/01/2026 [6].
- Nguồn:
1. Buckley, P. (2020). Prices, information and nudges for residential electricity conservation: A meta-analysis. Ecological Economics 172. https://econpapers.repec.org/RePEc:hal:journl:hal-02500507
2. Nguyen, N. N., Goto, D., Tran, D., Vu, H. T. (2024). Nudging households to save electricity with feedback: Experimental evidence from Vietnam. Energy Policy 195. https://ideas.repec.org/a/eee/enepol/v195y2024ics0301421524003987.html
3. Viet Nam News (18/04/2025). Hệ số phát thải lưới điện 0,681 tCO₂/MWh. https://vietnamnews.vn/environment/1716087/study-shows-coal-power-dominant-as-viet-nam-s-grid-emissions-climbed-in-2024.html
4. Thủ tướng Chính phủ (2019). Quyết định 280/QĐ-TTg. https://caselaw.vn/van-ban-phap-luat/338231-quyet-dinh-so-280-qd-ttg-ngay-13-03-2019-cua-thu-tuong-chinh-phu-phe-duyet-chuong-trinh-quoc-gia-ve-su-dung-nang-luong-tiet-kiem-va-hieu-qua-giai-doan-2019-2030
5. Thủ tướng Chính phủ (26/07/2022). Quyết định 896/QĐ-TTg, Chiến lược quốc gia về biến đổi khí hậu giai đoạn đến năm 2050. https://vmrcc.gov.vn/data/upload/files/2022.7.26.Q896.TTg.ChinlcQGvBKHgnnm2050.pdf
6. Quốc hội (18/06/2025). Luật số 77/2025/QH15 sửa đổi, bổ sung một số điều của Luật Sử dụng năng lượng tiết kiệm và hiệu quả. https://luatvietnam.vn/cong-nghiep/luat-su-dung-nang-luong-tiet-kiem-va-hieu-qua-sua-doi-2025-so-77-2025-qh15-404895-d1.html
## Slide 6 - Mô hình kinh doanh
- **Tiêu đề:** WattPrint là dịch vụ thuê bao theo tháng cho hộ gia đình; phần cứng và lắp đặt do đối tác đảm nhận.
- Mô hình dự kiến; giá và chi phí cụ thể sẽ xác định cùng số liệu từ thí điểm.
- **Nội dung:**
    - **Khách hàng:** Hộ gia đình vừa dùng, vừa mua, vừa trả tiền (với nhà trọ, chủ trọ là đầu mối lắp đặt).
    - **Dịch vụ:** Theo dõi, phân tích dữ liệu và trợ lý AI, gồm cả thiết bị. Chưa cam kết mức tiết kiệm ngay từ đầu, nên hộ trải nghiệm với chi phí thấp để tự thấy tác động.
    - **Cách trả:** Phí thuê bao hằng tháng, hai gói: gói thường (thiết bị, phân rã, hiển thị, phân tích dữ liệu) và gói Pro (thêm AI Energy Copilot).
    - **Chi phí và đối tác:** WattPrint vận hành nền tảng phần mềm và AI. Đối tác sản xuất, lắp đặt, bảo trì và thu hồi thiết bị.
    - **Hoàn vốn (dự kiến):** WattPrint chi trước thiết bị và lắp đặt, thu lại dần qua phí thuê. Hoàn vốn khi phí thuê, sau khi trừ chi phí cloud, AI và bảo trì, bằng chi phí thiết bị và lắp đặt. Thiết bị được thu hồi để dùng lại khi hộ dừng thuê.
    - **Chứng minh tiết kiệm:** Copilot theo nguyên tắc M&V (đo lường và kiểm chứng): so điện dùng trước và sau khi làm theo khuyến nghị, có hiệu chỉnh thời tiết, để biết hộ tiết kiệm bao nhiêu kWh và bao nhiêu tiền so với phí thuê [1].
    - **Lợi ích không chỉ của hộ:** Điện lực đỡ áp lực cung ứng, xã hội giảm phát thải. Ở Anh, EDF Energy tặng điện miễn phí cho hộ giảm điện giờ cao điểm [2]. EVN đã có điều chỉnh phụ tải cho khách hàng dùng điện lớn [3]; nếu mở rộng sang hộ gia đình, số liệu đã kiểm chứng của WattPrint có thể xác nhận mức giảm từng hộ.
    - **Mục tiêu lớn - hợp tác với EVN:** App của EVN cho xem điện theo ngày, chưa theo thiết bị [4]. WattPrint bổ sung điện từng thiết bị và khuyến nghị riêng, minh bạch hóa đơn để tăng niềm tin vào điện lực, và số liệu tiết kiệm đã kiểm chứng. Hướng đi: chạy trên công tơ thông minh, như Sense đang làm ở Mỹ [5].
* Nguồn:
1. Langlois, P. Measurement & Verification at the core of Energy Performance Contracting. UNEP Copenhagen Climate Centre. https://c2e2.unepccc.org/wp-content/uploads/sites/3/2021/11/measurement-verification-at-the-core-of-energy-performance-contracting.pdf
2. EDF Energy. Flexing (Weekend Saver, Sunday Saver). https://edfenergy.com/flexing
3a. Trung Dũng (21/07/2026). Hơn 19.000 khách hàng tham gia chương trình điều chỉnh phụ tải điện. Báo Nông nghiệp và Môi trường. https://nongnghiepmoitruong.vn/hon-19000-khach-hang-tham-gia-chuong-trinh-dieu-chinh-phu-tai-d822467.html
3b. Hương Trang (26/09/2019). Điều chỉnh phụ tải điện: Khách hàng hưởng lợi. Pháp Luật TP.HCM. https://tuoitre.vn/plo/dieu-chinh-phu-tai-dien-khach-hang-huong-loi-post542730.html
4. Báo Sài Gòn Giải Phóng (22/06/2026). Tra cứu tiền điện hằng ngày trên app dùng chung của EVN. https://www.sggp.org.vn/tra-cuu-tien-dien-hang-ngay-tren-app-dung-chung-cua-evn-post858550.html
5. Sense (2025). Looking Ahead: The Next Chapter for Sense. https://sense.com/consumer-blog/looking-ahead-the-next-chapter-for-sense/
# Slide 7 - Quy mô thị trường
- **Tiêu đề:** Hơn 28 triệu hộ dùng điện; điểm vào là hơn 10 triệu hộ đô thị, thế giới đang đề cao xu hướng tiết kiệm năng lượng.
- **Nội dung:**
    - **Trong nước:**
        - **TAM:** Khoảng 28 triệu hộ cả nước, đều trả tiền điện theo biểu giá 6 bậc [1].
        - **SAM:** Hơn 10 triệu hộ đô thị (ước tính từ 38,2% dân số sống ở thành thị), dễ lắp đặt, bảo trì và tiếp cận hơn [1].
        - **SOM:** Khoảng 10.000 hộ đầu tiên, 0,1% của SAM.
    - **Ngoài nước:** Khoảng 1,4 tỷ công tơ điện thông minh cuối 2025, dự kiến khoảng 2,4 tỷ vào 2035 [2]. Dữ liệu tiêu thụ ngày càng có sẵn.
    - **Chính sách thế giới:** Khoảng 200 chính phủ cam kết tại COP28 nhân đôi tốc độ cải thiện hiệu quả năng lượng lên 4%/năm vào 2030, năm 2025 mới đạt khoảng 1,8% [3]. EU có chỉ thị 2023/1791 trao quyền cho người tiêu dùng [4].
    - **Chính sách Việt Nam:** Ngoài các văn bản ở Slide 5, Nghị quyết 70-NQ/TW (2025) bảo đảm an ninh năng lượng quốc gia đến 2030 [5].
- **Kết luận:** Chỉ cần khoảng 0,1% hộ đô thị để bắt đầu; thách thức là tiếp cận những hộ đầu tiên và mở rộng.
* Nguồn:
1. NSO (2024). Điều tra dân số và nhà ở giữa kỳ, 01/04/2024. https://www.nso.gov.vn/du-lieu-va-so-lieu-thong-ke/2025/01/thong-cao-bao-chi-ket-qua-dieu-tra-dan-so-va-nha-o-giua-ky-nam-2024/
2. Transforma Insights (20/03/2026). Smart meter installations forecast. https://transformainsights.com/news/smart-meter-installations-forecast
3. IEA (21/11/2025). Energy Efficiency 2025. https://www.iea.org/reports/energy-efficiency-2025
4. Nghị viện và Hội đồng châu Âu (2023). Directive (EU) 2023/1791 về hiệu quả năng lượng. https://eur-lex.europa.eu/eli/dir/2023/1791/oj
5. Bộ Chính trị (20/08/2025). Nghị quyết 70-NQ/TW về bảo đảm an ninh năng lượng quốc gia đến năm 2030, tầm nhìn đến năm 2045. https://luatvietnam.vn/cong-nghiep/nghi-quyet-70-nq-tw-cua-bo-chinh-tri-ve-bao-dam-an-ninh-nang-luong-quoc-gia-den-nam-2030-tam-nhin-den-nam-2045-410231-d1.html
## Slide 8 - Chiến lược tiếp cận
- **Tiêu đề:** Từ thí điểm nhỏ, tiếp cận qua các kênh cộng đồng dân cư và mở rộng toàn quốc.
- **Vậy để tiếp cận 0,1% hộ gia đình đầu tiên, phương án của đội như sau:**
    - **Bước 1 - Thí điểm:** Kiểm chứng tại khu vực làm việc, sau đó triển khai ở một nhóm nhỏ hộ gia đình đồng ý bằng văn bản. Nhóm đo mức hiểu biết về tiêu thụ và thay đổi hành vi của người dùng. Thuê trọn gói giúp hộ thử với chi phí thấp.
    - **Bước 2 - Kênh tiếp cận:** Đi qua ban quản lý chung cư và cộng đồng cư dân để giới thiệu và tạo niềm tin. Đối tác kỹ thuật đến lắp tại tủ điện, hộ không phải tự lắp. Sau đó mở rộng từng nhóm, từ ít đến nhiều thay đổi về cách tính tiền điện:
        - **Chung cư:** mỗi căn hộ tính tiền theo biểu giá sinh hoạt 6 bậc, đúng với sản phẩm hiện tại.
        - **Nhà ở riêng lẻ (nhà phố, nhà mặt đất):** cùng cách tính tiền như chung cư, nhưng không có ban quản lý làm đầu mối, nên tiếp cận qua cộng đồng khu dân cư và điện lực địa phương.
        - **Nhà trọ:** chủ trọ là đầu mối lắp đặt; tiền điện chia theo định mức theo số người thuê, nên cần bổ sung cách tính này [1].
        - **Hộ kinh doanh:** biểu giá kinh doanh theo cấp điện áp và khung giờ, không theo bậc thang, nên cần bổ sung biểu giá riêng [2].
    - **Bước 3 - Hợp tác với tập đoàn điện lực:** Hợp tác với EVN để đưa phần mềm vào công tơ thông minh và triển khai quy mô lớn trên toàn quốc.
- Nguồn:
1. Bộ Công Thương (2025). Thông tư 60/2025/TT-BCT (hiệu lực 02/12/2025), quy định cách tính tiền điện cho người thuê nhà (bài tóm tắt). https://luatvietnam.vn/linh-vuc-khac/cach-tinh-tien-dien-sinh-hoat-cua-nguoi-thue-nha-tu-02-12-2025-the-nao-883-105708-article.html
2. Bộ Công Thương (09/05/2025). Quyết định 1279/QĐ-BCT về giá bán điện. https://luatvietnam.vn/dien-luc/quyet-dinh-1279-qd-bct-cua-bo-cong-thuong-quy-dinh-ve-gia-ban-dien-399752-d1.html
# Slide 9 - Đối thủ
- Tiêu đề: Việt Nam chưa có giải pháp tương tự; WattPrint cạnh tranh bằng chi phí, tính tiện nghi và dễ tiếp cận.
- Nội dung:
    - **Ứng dụng của điện lực:** EVN CSKH (đang thử nghiệm từ 06/2026) cho xem điện theo ngày và so sánh theo ngày, tháng, năm, nhưng chưa có chi tiết từng thiết bị [1]. Ứng dụng EVNHANOI có đặt ngưỡng cảnh báo và ước tính điện từng thiết bị, nhưng do người dùng tự nhập loại, số lượng và tần suất dùng, không phải đo thật [2].
    - **Tự lắp nhiều ổ cắm đo điện:** Đo được từng thiết bị, nhưng mỗi ổ cắm khoảng 235.000 đồng [3], 10 ổ cắm khoảng 2,4 triệu đồng, cộng bộ điều khiển trung tâm [6] thì ước tính 4-10 triệu đồng, chưa kể thiết bị đấu trực tiếp như điều hòa, đèn trần mà ổ cắm không đo được. Hộ lại phải tự lắp và kết nối. Đây là lựa chọn thay thế thực tế của hộ gia đình.
    - **Giải pháp ở thị trường khác:** EDF (Pháp) đã dùng NILMFormer tách điện theo thiết bị cho hàng triệu khách hàng [4]. Sense (Mỹ) cũng chuyển từ bán thiết bị sang đưa phần mềm vào công tơ thông minh của điện lực [5]. Cả hai chưa dành cho hộ Việt Nam.
- Nguồn:
1. Báo Sài Gòn Giải Phóng (22/06/2026). Tra cứu tiền điện hằng ngày trên app dùng chung của EVN. https://www.sggp.org.vn/tra-cuu-tien-dien-hang-ngay-tren-app-dung-chung-cua-evn-post858550.html
2. Báo Nhà đầu tư (02/04/2024). Giờ đây, người dân có thể theo dõi lượng điện sử dụng theo ngày thật dễ dàng. https://nhadautu.vn/gio-day-nguoi-dan-co-the-theo-doi-luong-dien-su-dung-theo-ngay-that-de-dang-d84849.html
3. Tuya.vn. Ổ cắm WiFi đo điện TC1, 235.000 đ. https://tuya.vn/o-cam-c-smart-series-wifi-cong-suat-lon-16a-tuya-tc1-p40701967.html
4. Petralia, A., Charpentier, P., Kadhi, Y., Palpanas, T. (2025). NILMFormer: Non-Intrusive Load Monitoring that Accounts for Non-Stationarity. ACM SIGKDD 2025. https://arxiv.org/abs/2506.05880
5. Sense (2025). Looking ahead: the next chapter for Sense. https://sense.com/consumer-blog/looking-ahead-the-next-chapter-for-sense/
6. Home Assistant. Home Assistant Green, 199 USD. https://www.home-assistant.io/green/
# Slide 10 - Đội ngũ
- Tiêu đề: Đội UDU.S4U phát triển WattPrint: sinh viên có kinh nghiệm trong triển khai các giải pháp AIOT, cố vấn bởi chuyên gia trong lĩnh vực tối ưu năng lượng.
	- Project Lead: Nguyễn Trường Giang - sinh viên năm 4 ngành Cử nhân Công nghệ thông tin PTIT. Định hướng tầm nhìn, giải pháp, sản phẩm, mô hình kinh doanh. Có kinh nghiệm trong phát triển phần mềm ứng dụng AI, tham gia dự án nghiên cứu tối ưu năng lượng. Đạt nhiều giải thưởng ở các cuộc thi sản phẩm như Coding Fest, Asia Impact Hackathon, Intel Global AI Impact Festival.
	- Tech Lead: Nguyễn Đình Đạt -  sinh viên năm 4 ngành Công nghệ thông tin. Chịu trách nhiệm kĩ thuật của dự án, có kinh nghiệm nghiên cứu dày dặn trong lĩnh vực năng lượng thông minh. Đạt các giải thưởng ở cả cuộc thi sản phẩm và học thuật như Olympic AI, Coding Fest, Asia Impact Hackathon, Intel Global AI Impact Festival.
	- AIOT: Lưu Huy Vũ, Đặng Nguyễn Đức Anh, Đinh Tuấn Minh, sinh viên năm 2 ngành Công nghệ thông tin PTIT, có kinh nghiệm trong thu thập, xử lý dữ liệu cảm biến, nghiên cứu về AI trong lĩnh vực năng lượng thông minh.
	- Cố vấn và đối tác:
		- TS. Phan Lý Huỳnh: giảng viên Học viện Công nghệ Bưu chính Viễn thông, có 7 năm nghiên cứu AI và tối ưu năng lượng trong tòa nhà.
		- GS. Stephane Ploix, Đại học Grenoble INP (Pháp), hơn 30 năm nghiên cứu tối ưu năng lượng và nhà thông minh.
		- Đơn vị: Viện Khoa học Kỹ thuật Bưu điện (Học viện Công nghệ Bưu chính Viễn thông) và Lab G-SCOP (Đại học Grenoble).
# Slide 11 - Đề nghị và liên hệ
- **Tiêu đề:** WattPrint tìm đối tác điện lực để kiểm chứng giải pháp tại hộ gia đình Việt Nam.
- **Nội dung:**
    - **Với EVN và các công ty điện lực, chúng tôi mong muốn hợp tác để:**
        - Kết nối nhóm hộ khách hàng tham gia thí điểm, bắt đầu từ 5-10 hộ.
        - Hỗ trợ kiểm chuẩn mô hình bằng công tơ tham chiếu của các hộ đồng ý tham gia.
        - Cùng thảo luận hướng tích hợp phần mềm vào ứng dụng EVN CSKH hoặc công tơ thông minh, và xây dựng bộ dữ liệu tiêu thụ điện từng thiết bị của hộ gia đình Việt Nam.
    - **Với SIHUB, cố vấn và quỹ:** cần cố vấn kinh doanh, tài chính, kỹ thuật; kết nối đối tác phần cứng và lắp đặt; và kết nối với quỹ cùng chương trình hỗ trợ giai đoạn sớm về khí hậu và năng lượng.
    - **Mục tiêu 12 tháng tới:** bắt đầu thí điểm trong 3-6 tháng, thử nghiệm trên 5-10 hộ, thu dữ liệu thực địa, kiểm chuẩn mô hình, đo thay đổi nhận thức, hành vi và mức tiết kiệm trước và sau. Đây là bước đầu để tiến tới 10.000 hộ đầu tiên.
# Slide 12 - Quote & Cảm ơn

Cảm ơn vì đã lắng nghe. 

“Trợ lý năng lượng AI đồng hành cùng mọi gia đình: Thấu hiểu năng lượng, tiết kiệm hợp lý, bảo vệ tài nguyên cho tương lai.”