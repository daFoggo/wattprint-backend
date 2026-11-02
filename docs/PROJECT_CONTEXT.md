# WattPrint — Tóm tắt context dự án

> Tổng hợp từ 2 tài liệu nguồn. Mỗi ý có trích dẫn dạng `[Deck:Lx]` / `[Note:trang]`. Chỉ ghi điều có trong nguồn; phần suy luận của người tóm tắt được đánh dấu rõ ở mục 7.
>
> - **[Deck]** = [WattPrint Pitch Deck.md](WattPrint%20Pitch%20Deck.md) (12 slide; `Lx` = số dòng trong file)
> - **[Note]** = [concept_energy_copilot_note_en.pdf](concept_energy_copilot_note_en.pdf) (4 trang; concept note về EnergyCopilot)

## 1. Dự án là gì
- **WattPrint**: hệ thống theo dõi tiêu thụ điện theo thiết bị + trợ lý năng lượng cá nhân hóa cho hộ gia đình. Đội thi: UDU.S4U. [Deck:L5-L6]
- Cách làm: chỉ **một cảm biến duy nhất ở aptomat**, dùng AI tách điện năng từng thiết bị thay vì lắp nhiều cảm biến. [Deck:L22]
- Trạng thái: đang **mô phỏng trong môi trường nghiên cứu**, dự kiến thí điểm thực tế trong 3–6 tháng tới. [Deck:L50]
- Các số liệu ví dụ trong deck (vd. điều hòa 151,6 kWh / 426.669 đồng) là **dữ liệu minh họa của bản mẫu**. [Deck:L31, L45]

## 2. Mục tiêu / vấn đề giải quyết
- Giúp người dùng chủ động tiết kiệm điện nhờ thông tin rõ hơn: thí nghiệm 45.000 hộ VN cho thấy thông tin hóa đơn theo ngày giúp giảm tiêu thụ. [Deck:L10]
- Người dùng khó biết tiết kiệm ở đâu (đoán thấp điện năng thiết bị ~2,8 lần, Mỹ). [Deck:L11]
- App EVN chỉ cho số tổng hộ theo ngày, không theo thiết bị. [Deck:L12]
- Theo dõi từng thiết bị bằng phần cứng tự lắp tốn ước tính 4–10 triệu đồng/10 điểm đo. [Deck:L13]
- **Câu hỏi cốt lõi**: có cách ước tính điện từng thiết bị với chi phí thấp hơn nhiều không? [Deck:L14]
- Mục tiêu tác động: đổi nhận thức → đổi hành vi → tiết kiệm điện/chi phí, sức khỏe & tiện nghi, đóng góp xã hội (CO₂). Phần hành vi là **giả thuyết của nhóm, sẽ kiểm chứng**. [Deck:L52-L56]

## 3. Giải pháp: 4 khối [Deck:L23]
| # | Khối | Nội dung chính | Nguồn |
|---|------|----------------|-------|
| 1 | **NILMFormer** | NILM dựa trên Transformer tách từng thiết bị từ số đo tổng; nhóm bổ sung bước hiệu chỉnh theo từng hộ. EDF (Pháp) đã dùng cho hàng triệu khách hàng. | [Deck:L24-L27] |
| 2 | **Dashboard BI & Billing** | Tiêu thụ từng thiết bị theo giờ/ngày/tuần/tháng, nhật ký hoạt động; mọi số liệu kèm tiền theo **biểu giá 6 bậc**. | [Deck:L28-L31] |
| 3 | **Dự báo & phát hiện bất thường** | Cảnh báo thiết bị chạy bất thường, phát hiện chạy ngầm (TV chờ, sạc…), so sánh với tháng trước/hộ khác, dự đoán hóa đơn cuối tháng và lúc chạm bậc giá tiếp theo. | [Deck:L32-L37] |
| 4 | **Energy Copilot hai chiều** | LLM + Text-to-SQL + RAG; trả lời khi được hỏi (pull) và chủ động gợi ý (push), tính từ dữ liệu thật của nhà + thời tiết + biểu giá. | [Deck:L38-L44] |

## 4. Energy Copilot — chi tiết kiến trúc (từ concept note)
Concept note mô tả EnergyCopilot như một **trợ lý LLM nhận biết ngữ cảnh, hai chiều, cho tòa nhà** (comfort, sức khỏe, hiệu quả năng lượng). [Note:1]

- **Hai chiều**: *Pull* (người dùng hỏi, nhận câu trả lời dựa trên dữ liệu cảm biến + tiêu chuẩn + hành động cụ thể) và *Push* (theo dõi luồng cảm biến, phát hiện lãng phí/khó chịu, gửi gợi ý kèm mức tiết kiệm, học từ việc người dùng có chấp nhận hay không). [Note:1]
- **Nguyên tắc dẫn đường: "tools first, language second"** — LLM lập kế hoạch và giải thích; **mọi con số đến từ công cụ xác định, kiểm toán được**. [Note:1] Deck diễn đạt tương tự: "số liệu do công cụ tính, mô hình chỉ giải thích". [Deck:L44]
- **5 công cụ**: (1) Text-to-SQL trên dữ liệu cảm biến, phân giải phòng/điểm đo qua mô hình ngữ nghĩa Brick; (2) Graph-RAG trên tri thức chuyên gia (ISO 7730, ASHRAE 55, WHO, quy chuẩn năng lượng) có trích dẫn; (3) đánh giá comfort/sức khỏe (PMV/PPD, mô hình thích nghi, ngưỡng IAQ); (4) mô phỏng what-if (EnergyPlus hoặc surrogate nhanh) kiểm tra hành động trước khi đề xuất; (5) dự báo & phát hiện bất thường để kích hoạt vòng proactive. Một **verifier** kiểm lại truy vấn, đơn vị, trích dẫn trước khi hiển thị. [Note:1]
- **Công thức xếp hạng hành động** (Eq. 1): chọn hành động `a` tối thiểu hóa `ΔE(a) − λ·log p̂_u(a)` với ràng buộc `|PMV| ≤ 0,5` và `CO₂ ≤ C_max` (ΔE = thay đổi năng lượng dự đoán, p̂_u = xác suất người dùng u chấp nhận). [Note:1]
- **Kiến trúc 4 tầng** (Figure 1): L1 dữ liệu & tri thức (IoT, BMS/HVAC, time-series DB TimescaleDB/InfluxDB, Brick/BOT, kho tri thức, thời tiết/tariff/lịch, mô hình năng lượng đã hiệu chuẩn); L2 tool layer T1–T5; L3 orchestration (ReAct planner, trigger engine, verifier & guardrails); L4 tương tác (cư dân, quản lý, hỏi đáp/cảnh báo). [Note:2]
- **Hai vòng lặp** (Figure 2): reactive (hỏi → phân giải thực thể → SQL → ngưỡng/bằng chứng → verifier → trả lời) và proactive (theo dõi → trigger → what-if → xếp hạng theo Eq.1 → nudge → feedback cập nhật mô hình cá nhân hóa). [Note:2]
- **Điểm mới** tuyên bố: một vòng lặp gộp dữ liệu–ngữ nghĩa–tri thức; lời khuyên được định lượng tác động (mô phỏng, ràng buộc comfort); hai chiều & cá nhân hóa; benchmark mở **EnergyQA**. [Note:1]
- **Câu hỏi mở cho chuyên gia** (E1–E7): dataset Q&A, nguồn thẩm quyền, bằng chứng mâu thuẫn (vd. CO₂–nhận thức), bản quyền tiêu chuẩn ASHRAE/ISO, kiểm định bộ Q&A, ranh giới an toàn, quyền truy cập dữ liệu tòa nhà. [Note:3]

## 5. Mô hình kinh doanh & thị trường
- **Thuê bao theo tháng** cho hộ gia đình; phần cứng & lắp đặt do đối tác. Hai gói: thường (thiết bị, phân rã, hiển thị, phân tích) và **Pro** (thêm AI Energy Copilot). Giá/chi phí chưa xác định, sẽ chốt cùng số liệu thí điểm. [Deck:L65-L71]
- **Chứng minh tiết kiệm** theo nguyên tắc M&V (so trước/sau, hiệu chỉnh thời tiết). [Deck:L73]
- **Mục tiêu lớn**: hợp tác EVN, chạy trên công tơ thông minh (tham chiếu Sense, Mỹ). [Deck:L75, L109]
- **Thị trường**: TAM ~28 triệu hộ; SAM >10 triệu hộ đô thị; SOM ~10.000 hộ đầu (0,1% SAM). [Deck:L87-L89]
- **Lộ trình tiếp cận**: (1) thí điểm hộ đồng ý bằng văn bản → (2) qua ban quản lý chung cư/cộng đồng, mở rộng sang nhà riêng lẻ → nhà trọ (cần thêm cách tính định mức) → hộ kinh doanh (cần biểu giá riêng) → (3) hợp tác EVN. [Deck:L103-L109]
- **Đối thủ**: app EVN CSKH (theo ngày, không theo thiết bị), EVNHANOI (ước tính do người dùng tự nhập), tự lắp nhiều ổ cắm đo; EDF/Sense chưa dành cho hộ VN. [Deck:L116-L118]

## 6. Kế hoạch & đề nghị
- Mục tiêu 12 tháng: thí điểm 3–6 tháng trên **5–10 hộ**, thu dữ liệu thực địa, kiểm chuẩn mô hình, đo thay đổi nhận thức/hành vi/tiết kiệm trước–sau → bước đầu tới 10.000 hộ. [Deck:L143]
- Đề nghị EVN: kết nối hộ thí điểm, kiểm chuẩn bằng công tơ tham chiếu, thảo luận tích hợp vào EVN CSKH/công tơ thông minh và xây bộ dữ liệu từng thiết bị cho hộ VN. [Deck:L139-L141]
- Đội ngũ: Project Lead Nguyễn Trường Giang, Tech Lead Nguyễn Đình Đạt, 3 thành viên AIOT; cố vấn TS. Phan Lý Huỳnh (PTIT), GS. Stephane Ploix (Grenoble INP). [Deck:L128-L134]

## 7. Quan hệ giữa 2 tài liệu & điểm cần lưu ý (nhận xét của người tóm tắt)
- **Quan hệ**: Deck mô tả Khối 4 là "Energy Copilot hai chiều – LLM, Text-to-SQL, RAG" [Deck:L38]; concept note là thiết kế chi tiết của ý tưởng đó (Text-to-SQL, RAG, verifier, vòng pull/push khớp với [Deck:L40-L44]).
- **Khác biệt miền ứng dụng** (suy từ nội dung, không phải nguồn nói thẳng): note viết cho **tòa nhà** (phòng, BMS, Brick, CO₂/PM2.5, PMV, cư dân/quản lý cơ sở) [Note:1-2]; deck áp dụng cho **hộ gia đình** (biểu giá 6 bậc, hóa đơn, thiết bị). Phần comfort/sức khỏe xuất hiện ở deck chỉ ở mức gợi ý theo thời tiết (nắng nóng, điều hòa) [Deck:L43, L55]. Note **không** nhắc NILM, WattPrint hay biểu giá điện VN.
- **Chưa rõ trong nguồn**: stack kỹ thuật triển khai cụ thể của WattPrint (note đề cập TimescaleDB/InfluxDB, EnergyPlus ở mức khái niệm [Note:2]); độ chính xác NILM; giá gói thuê bao; mức tiết kiệm thực đo (hiện chỉ trích từ nghiên cứu trước: 2–4%, 4–7% Đà Nẵng [Deck:L54]).
- Tài liệu repo hiện tại là backend FastAPI; hai file nguồn **không** mô tả backend này, nên không suy ra thiết kế API từ chúng.
