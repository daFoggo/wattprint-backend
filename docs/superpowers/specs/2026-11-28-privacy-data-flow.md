# WattPrint: phân tích luồng dữ liệu theo góc nhìn quyền riêng tư

Ngày: 2026-11-28. Trạng thái: đang soạn. Phục vụ minh chứng "Sơ đồ luồng dữ liệu" của yêu cầu cải tiến 1
"Bảo vệ dữ liệu nếp sinh hoạt".

Tài liệu gồm năm phần, làm lần lượt:

1. Tác nhân tham gia hệ thống (mục 1, tài liệu này)
2. Sơ đồ phân rã chức năng (BFD)
3. Ma trận tác nhân – chức năng
4. Ma trận tác nhân – quyền truy cập dữ liệu
5. Sơ đồ luồng dữ liệu (DFD) mức ngữ cảnh, mức 0, mức 1

### Quy ước chung

Các hình và bảng dùng chung một quy ước để đối chiếu được với nhau:

| Quy ước | Áp dụng |
|---|---|
| Chức năng, tiến trình | Chữ nhật bo góc, ô trên ghi số hiệu (ký hiệu Gane–Sarson). Số hiệu giống nhau trên BFD, DFD và ma trận: chức năng 7.4 trên BFD là tiến trình 7.4 trên DFD mức 1 và dòng 7.4 trên ma trận |
| Tác nhân | Hình vuông có bóng, ghi mã TN01–TN15 và tên như mục 1.2 |
| Dữ liệu | Mã D01–D18 như mục 4.1, dùng cho kho dữ liệu trên DFD và cho dòng của ma trận quyền truy cập |
| Đường nối | Chỉ ngang hoặc dọc, không chéo. BFD dùng đường không mũi tên (quan hệ phân rã); DFD dùng mũi tên một chiều (luồng dữ liệu) |
| Màu | Đen trắng là chính. Nền xanh nhạt đánh dấu phần bổ sung hoặc điều chỉnh cho yêu cầu bảo vệ dữ liệu nếp sinh hoạt. Khung đỏ nét đứt đánh dấu bên xử lý ở nước ngoài |
| Chữ | Arial. Tiêu đề in hoa đặt trên cùng. Chú giải hoặc chú thích đặt dưới cùng bên trái |

---

## 1. Tác nhân tham gia hệ thống

### 1.1 Hệ thống được phân tích và ranh giới

**Hệ thống**: WattPrint sau cải tiến. Đây là dịch vụ theo dõi điện năng cho hộ gia đình. Hệ thống nhận số đo
điện tổng của nhà, tách ra mức dùng của từng thiết bị, đưa ra cảnh báo, dự báo hóa đơn và lời khuyên tiết kiệm.
Hệ thống có trợ lý hỏi đáp Wappi. Người dùng dùng hệ thống qua ứng dụng web và ứng dụng điện thoại. Máy chủ và
kho dữ liệu đặt tại Việt Nam.

**Bên trong ranh giới** (là chức năng của hệ thống, không phải tác nhân):

- ứng dụng web, ứng dụng điện thoại và máy chủ xử lý;
- kho dữ liệu: số đo, bản tổng hợp, thiết bị, hóa đơn, trò chuyện, nhật ký;
- việc tách thiết bị, phát hiện bất thường, dự báo;
- phần điều phối của trợ lý Wappi: hiểu câu hỏi, lấy số liệu, che thông tin cá nhân, ghép câu trả lời;
- dịch vụ đăng nhập do WattPrint tự vận hành.

**Bên ngoài ranh giới** là các tác nhân: những người, thiết bị, hệ thống và tổ chức gửi dữ liệu vào hoặc nhận
dữ liệu ra khỏi WattPrint.

Hai quy ước khi xác định tác nhân:

- **Tác nhân là vai trò, không phải con người cụ thể.** Một người có thể giữ nhiều vai. Ví dụ, chủ dự án vừa là
  quản trị viên vừa là người phụ trách bảo vệ dữ liệu. Tách vai để phân quyền theo nhiệm vụ.
- **Trợ lý Wappi không phải tác nhân, nhà cung cấp mô hình AI mới là tác nhân.**
  - Phần quyết định lấy số liệu nào, che gì và gửi gì nằm trong hệ thống và chịu quy tắc của hệ thống.
  - Phần sinh câu trả lời chạy ở máy chủ của bên ngoài. Đó là chỗ dữ liệu rời khỏi WattPrint.

### 1.2 Danh sách tác nhân

| Mã | Tác nhân | Loại | Vai trò với hệ thống |
|---|---|---|---|
| TN01 | Khách vãng lai | Con người | Xem trang giới thiệu, chính sách quyền riêng tư; đăng ký hoặc chọn dùng thử |
| TN02 | Khách dùng thử | Con người | Xem các nhà mẫu dựng từ dữ liệu công khai, thử mọi tính năng mà không cần nhà riêng |
| TN03 | Chủ hộ | Con người | Người đăng ký nhà, gắn thiết bị đo, dùng toàn bộ tính năng, quyết định mọi cài đặt riêng tư của nhà |
| TN04 | Thành viên hộ | Con người | Người thân được chủ hộ mời, xem dữ liệu nhà theo mức chủ hộ cấp |
| TN05 | Quản trị viên | Con người | Vận hành hệ thống, quản lý tài khoản và cấu hình; không mặc nhiên xem dữ liệu sinh hoạt của hộ |
| TN06 | Người phụ trách bảo vệ dữ liệu cá nhân | Con người | Tiếp nhận yêu cầu thực hiện quyền, quản lý đồng ý, lập hồ sơ đánh giá tác động, xử lý sự cố lộ lọt |
| TN07 | Thiết bị đo điện tại nhà | Thiết bị | Đo và gửi số đo điện tổng của nhà theo chu kỳ ngắn |
| TN08 | Nguồn dữ liệu mẫu công khai | Nguồn dữ liệu | Cung cấp chuỗi số đo của các nhà mẫu (bộ dữ liệu nghiên cứu REFIT, Plegma, ENERTALK) |
| TN09 | Dịch vụ xác thực danh tính | Hệ thống ngoài | Xác minh danh tính khi đăng nhập (hiện là Google) |
| TN10 | Dịch vụ mô hình ngôn ngữ | Hệ thống ngoài | Sinh câu trả lời cho trợ lý Wappi từ câu hỏi và số liệu đã được tối giản |
| TN11 | Dịch vụ giọng nói | Hệ thống ngoài | Chuyển lời nói thành chữ và chữ thành lời nói |
| TN12 | Dịch vụ thời tiết | Hệ thống ngoài | Cung cấp thời tiết theo vị trí cấp tỉnh để hiệu chỉnh dự báo |
| TN13 | Dịch vụ thư điện tử | Hệ thống ngoài | Chuyển thư xác minh, mã mời, thông báo tới người dùng |
| TN14 | Dịch vụ nhắn tin cho người vận hành | Hệ thống ngoài | Chuyển phản hồi chất lượng câu trả lời tới quản trị viên (hiện là Telegram) |
| TN15 | Cơ quan chuyên trách bảo vệ dữ liệu cá nhân | Tổ chức | Cơ quan thuộc Bộ Công an. Nhận hồ sơ đánh giá tác động và thông báo vi phạm; kiểm tra |

Phân nhóm:

- **Tác nhân chính** dùng hệ thống để đạt mục tiêu của mình: TN01–TN06.
- **Tác nhân phụ** cung cấp hoặc nhận dữ liệu để hệ thống làm được việc: TN07–TN14.
- **TN15** là tác nhân thủ tục. Luồng dữ liệu tới cơ quan này do con người thực hiện theo luật, không qua phần mềm.

### 1.3 Quan hệ kế thừa giữa các tác nhân người dùng

```mermaid
flowchart BT
    KV["TN01 Khách vãng lai"]
    ND["Người dùng đã đăng nhập<br/>(vai trừu tượng)"]
    KT["TN02 Khách dùng thử"]
    TV["TN04 Thành viên hộ"]
    CH["TN03 Chủ hộ"]
    QT["TN05 Quản trị viên"]
    BV["TN06 Người phụ trách BVDLCN"]

    KV -.->|đăng nhập thì trở thành| ND
    KT -->|là một| ND
    TV -->|là một| ND
    CH -->|có mọi quyền của thành viên mức đầy đủ, thêm quyền quản lý nhà| TV
    QT -->|là một| ND
    BV -->|là một| ND
```

- **Người dùng đã đăng nhập** là vai trừu tượng. Mọi người dùng đều làm được ba việc chung với tài khoản của mình:
  - xem và sửa hồ sơ;
  - bật hoặc tắt sự đồng ý của mình;
  - xóa trò chuyện, xóa tài khoản.
- **Chủ hộ kế thừa Thành viên hộ ở mức xem đầy đủ** và có thêm các quyền chỉ chủ hộ mới có:
  - đổi mức lưu;
  - mời hoặc gỡ thành viên;
  - xóa lịch sử của nhà;
  - quyết định mức dữ liệu được gửi tới dịch vụ AI.
- **Khách dùng thử không kế thừa Chủ hộ.** Họ được xem đầy đủ nhà mẫu nhưng không sửa được cài đặt chung của nhà
  mẫu. Mỗi khách chỉ thấy trò chuyện và kế hoạch của chính mình.
- **Quản trị viên và Người phụ trách bảo vệ dữ liệu không kế thừa Chủ hộ.**
  - Họ không có quyền xem dữ liệu sinh hoạt của bất kỳ nhà nào chỉ vì giữ vai này.
  - Mọi truy cập vào dữ liệu của một nhà để hỗ trợ phải được chủ hộ cho phép, có thời hạn và được ghi nhật ký.

### 1.4 Đặc tả từng tác nhân

Cột "Đưa vào" là dữ liệu tác nhân cung cấp cho hệ thống; cột "Nhận ra" là dữ liệu hệ thống trả cho tác nhân; cột
"Ràng buộc riêng tư" là quy tắc hệ thống phải giữ với tác nhân đó.

| Tác nhân | Mục tiêu | Đưa vào | Nhận ra | Ràng buộc riêng tư |
|---|---|---|---|---|
| **TN01** Khách vãng lai | Tìm hiểu sản phẩm, đọc chính sách, quyết định đăng ký hay dùng thử | Lựa chọn đăng nhập hoặc dùng thử | Trang giới thiệu, chính sách quyền riêng tư, danh sách dịch vụ bên ngoài | Chưa thu thập dữ liệu cá nhân. Chính sách chỉ nêu điều hệ thống thực sự làm |
| **TN02** Khách dùng thử | Trải nghiệm đủ tính năng trên nhà mẫu, không cần gắn thiết bị; ban giám khảo dùng vai này | Câu hỏi cho Wappi, kế hoạch thử, đồng ý dùng dịch vụ AI | Biểu đồ, thiết bị, cảnh báo, hóa đơn của nhà mẫu; câu trả lời; trang Quyền riêng tư dạng minh họa | Nhà mẫu là dữ liệu công khai. Dữ liệu riêng của khách được cách ly và tự xóa khi hết hạn dùng thử. Vẫn phải đồng ý trước khi gửi câu hỏi ra dịch vụ AI |
| **TN03** Chủ hộ | Hiểu nhà mình dùng điện vào việc gì, giảm hóa đơn, kiểm soát ai thấy nếp sinh hoạt của gia đình | Thông tin nhà, mã gắn thiết bị, tên thiết bị và phòng; câu hỏi bằng chữ hoặc giọng nói; mức lưu, mức gửi AI, đồng ý, lời mời thành viên; yêu cầu xóa lịch sử | Số đo và bản tổng hợp, ước tính theo thiết bị, cảnh báo, dự báo, hóa đơn; câu trả lời kèm dữ liệu đã gửi ra ngoài; nhật ký gửi ra ngoài; xác nhận xóa | Là người duy nhất quyết định thay cả nhà (mức lưu, ai được xem, mức gửi ra ngoài, xóa lịch sử), kể cả thay người không có tài khoản như trẻ em. Không ghi đè quyền của thành viên với tài khoản và trò chuyện của chính họ |
| **TN04** Thành viên hộ | Theo dõi điện của nhà, hỏi trợ lý, đặt nhắc việc tiết kiệm | Mã mời; câu hỏi; kế hoạch, nhắc việc, đồng ý của riêng mình; yêu cầu rời nhà | Dữ liệu nhà và câu trả lời ở mức xem chủ hộ cấp | Mặc định mức "chỉ theo ngày": không thấy số theo giờ hay giờ bật/tắt, kể cả khi hỏi trợ lý. Không xóa được lịch sử chung, nhưng xóa được trò chuyện của mình và tự rời nhà. Tránh việc người cùng nhà theo dõi giờ giấc của nhau |
| **TN05** Quản trị viên | Giữ hệ thống ổn định, quản lý tài khoản, cấu hình dịch vụ ngoài, cải thiện trợ lý | Cấu hình hệ thống; danh mục dịch vụ ngoài; lệnh nạp dữ liệu mẫu; lệnh khóa, mở tài khoản | Danh sách tài khoản (không kèm dữ liệu điện); trạng thái vận hành; phản hồi người dùng tự gửi kèm nội dung | Không mặc nhiên xem dữ liệu sinh hoạt của hộ. Chỉ xem dữ liệu một nhà khi chủ hộ cấp quyền hỗ trợ có thời hạn, mọi lần xem được ghi lại. Chỉ thấy nội dung trò chuyện khi người dùng tự gửi kèm |
| **TN06** Người phụ trách bảo vệ dữ liệu cá nhân | Bảo đảm tuân thủ Luật 91/2025/QH15 và Nghị định 356/2025/NĐ-CP | Thông báo xử lý dữ liệu, chính sách; quy định thời hạn lưu; kết quả xử lý yêu cầu; hồ sơ đánh giá tác động; biên bản sự cố | Yêu cầu của chủ thể và hạn xử lý; bằng chứng đồng ý; nhật ký gửi ra ngoài; nhật ký truy cập hỗ trợ | Làm việc trên dữ liệu quản lý và nhật ký, không xem số đo từng nhà. Là bộ phận, nhân sự bảo vệ dữ liệu theo Luật 91/2025 Điều 33 khoản 1 điểm b; tách riêng khỏi TN05 vì quyền và nhiệm vụ khác nhau |
| **TN07** Thiết bị đo điện tại nhà | Gửi số đo điện tổng của nhà đều đặn, không mất, không trùng | Lô số đo công suất theo thời gian, kèm khóa thiết bị | Xác nhận nhận lô hoặc lý do từ chối (ví dụ lô cũ hơn mốc đã xóa) | Nguồn của dữ liệu nhạy cảm nhất, suy ra được giờ thức, ngủ, vắng nhà. Khóa thiết bị chỉ cho ghi vào đúng nhà đã gắn, không cho đọc |
| **TN08** Nguồn dữ liệu mẫu công khai | Cung cấp dữ liệu thật để trình diễn | Chuỗi số đo và nhãn thiết bị của bộ dữ liệu nghiên cứu | Không có | Dữ liệu đã khử nhận dạng; chỉ dùng cho nhà mẫu, không ghép với dữ liệu hộ thật |
| **TN09** Dịch vụ xác thực danh tính | Xác minh người đăng nhập | Kết quả xác thực kèm email, họ tên | Yêu cầu đăng nhập | Không nhận dữ liệu điện hay dữ liệu nhà; hệ thống chỉ lấy email và họ tên |
| **TN10** Dịch vụ mô hình ngôn ngữ (OpenRouter, ở nước ngoài; dự phòng AstralX, tại Việt Nam) | Sinh câu trả lời cho câu hỏi của người dùng | Câu trả lời sinh ra | Câu hỏi đã che thông tin cá nhân; số liệu ở mức theo giờ hoặc theo ngày | Chỉ gọi khi người hỏi đã đồng ý. Không nhận số theo phút, tên nhà, địa chỉ, mã bưu chính, số người. Mỗi lần gọi được báo trong khung trò chuyện và ghi nhật ký. Gọi nhà cung cấp chính là chuyển dữ liệu xuyên biên giới (Luật 91/2025 Điều 20). Nhà cung cấp cam kết không giữ dữ liệu để huấn luyện |
| **TN11** Dịch vụ giọng nói (AstralX, tại Việt Nam) | Cho phép hỏi bằng lời và nghe câu trả lời | Chữ nhận dạng từ lời nói, âm thanh đọc câu trả lời | Âm thanh câu hỏi, chữ của câu trả lời | Âm thanh không che được thông tin cá nhân nên cần đồng ý riêng, nói rõ điều này. Tắt giọng nói vẫn dùng được trợ lý bằng chữ. Không chuyển ra nước ngoài; mỗi lần gửi vẫn ghi nhật ký |
| **TN12** Dịch vụ thời tiết (OpenWeather) | Cung cấp nhiệt độ, độ ẩm cho dự báo mức dùng | Dữ liệu thời tiết | Tọa độ trung tâm tỉnh | Vị trí cấp tỉnh dùng chung cho mọi nhà trong tỉnh, không phải dữ liệu cá nhân; vẫn được công khai trong danh mục bên nhận |
| **TN13** Dịch vụ thư điện tử | Chuyển thư tới người dùng | Trạng thái gửi | Địa chỉ thư và nội dung thư (mã mời, thông báo) | Nội dung thư không chứa số liệu điện hay giờ giấc sinh hoạt |
| **TN14** Dịch vụ nhắn tin cho người vận hành (Telegram, ở nước ngoài) | Báo cho quản trị viên khi câu trả lời bị đánh giá chưa tốt | Không có | Điểm đánh giá; câu hỏi và câu trả lời chỉ khi người dùng chọn gửi kèm | Mặc định không có nội dung trò chuyện. Khi có nội dung là chuyển dữ liệu ra nước ngoài, phải báo trước và ghi nhật ký |
| **TN15** Cơ quan chuyên trách bảo vệ dữ liệu cá nhân (Bộ Công an, Luật 91/2025 Điều 33 khoản 1 điểm a) | Quản lý nhà nước về bảo vệ dữ liệu cá nhân | Yêu cầu hoàn thiện hồ sơ, quyết định kiểm tra | Hồ sơ đánh giá tác động xử lý dữ liệu (60 ngày, Điều 21); hồ sơ chuyển dữ liệu xuyên biên giới (60 ngày, Điều 20); thông báo vi phạm (72 giờ, Điều 23) | Hồ sơ chỉ mô tả hoạt động xử lý, không kèm dữ liệu của từng hộ |

### 1.5 Đối tượng liên quan không tương tác trực tiếp

Các đối tượng dưới đây không gửi hay nhận dữ liệu qua giao diện của hệ thống, nên không vẽ trên DFD. Hệ thống vẫn
phải tính đến họ.

| Đối tượng | Vì sao liên quan | Hệ thống tính đến bằng cách |
|---|---|---|
| **Người cư trú không có tài khoản** (trẻ em, người già, người thuê, khách lưu trú) | Số đo điện phản ánh giờ giấc của mọi người trong nhà. Theo Luật 91/2025 Điều 2 khoản 5, họ là chủ thể dữ liệu dù không dùng hệ thống | Chủ hộ thay mặt họ quyết định mức lưu và xóa. Dữ liệu trẻ em do người đại diện theo pháp luật thực hiện quyền (Điều 24 khoản 2). Màn hình quyền riêng tư nhắc chủ hộ rằng dữ liệu phản ánh cả nhà |
| **Nhà cung cấp hạ tầng máy chủ** | Lưu giữ toàn bộ dữ liệu thay hệ thống | Là bên xử lý dữ liệu (Điều 2 khoản 8), cần hợp đồng. Máy chủ đặt tại Việt Nam nên việc lưu giữ không phát sinh chuyển dữ liệu ra nước ngoài |
| **Ban giám khảo** | Đánh giá sản phẩm | Dùng vai Khách dùng thử (TN02). Mọi minh chứng phải xem được từ vai này |

### 1.6 Vai trò pháp lý của các bên

Theo định nghĩa ở Luật 91/2025 Điều 2.

| Vai trò pháp lý | Định nghĩa (Điều 2) | Bên đảm nhận |
|---|---|---|
| Chủ thể dữ liệu cá nhân | Khoản 5: "người được dữ liệu cá nhân phản ánh" | TN02, TN03, TN04 (với tài khoản và trò chuyện của mình); người cư trú không có tài khoản (với số đo của nhà); TN05, TN06 (với tài khoản của mình) |
| Bên kiểm soát và xử lý dữ liệu cá nhân | Khoản 9: quyết định mục đích, phương tiện và trực tiếp xử lý | Đơn vị vận hành WattPrint (đội dự án), qua TN05 và TN06 |
| Bên xử lý dữ liệu cá nhân | Khoản 8: xử lý theo yêu cầu của bên kiểm soát, thông qua hợp đồng | TN10, TN11, TN14 khi có nội dung, nhà cung cấp hạ tầng máy chủ, TN13 |
| Bên kiểm soát dữ liệu (cho mục đích riêng của họ) | Khoản 7: quyết định mục đích và phương tiện | TN09, đối với tài khoản người dùng tự tạo với họ. Hệ thống chỉ nhận lại email và họ tên |
| Không phát sinh vai trò | Không nhận dữ liệu cá nhân | TN07 (thiết bị của chính hộ), TN08 (dữ liệu đã khử nhận dạng), TN12 (chỉ vị trí cấp tỉnh) |
| Cơ quan quản lý | Điều 33 khoản 1 điểm a | TN15 |

Hệ quả cho các phần sau:

- **Ranh giới xuyên biên giới.** Máy chủ và dịch vụ giọng nói (TN11) đặt tại Việt Nam, nên dữ liệu cá nhân chỉ ra
  nước ngoài qua các luồng tới TN10 và TN14. Trên DFD hai tác nhân này được đánh dấu riêng. Mỗi luồng phải có ba
  thứ:
  - đồng ý của người dùng;
  - ghi nhật ký;
  - nêu trong hồ sơ theo Điều 20.
- **Ranh giới trong nhà.** Chủ hộ và thành viên cùng là chủ thể dữ liệu nhưng có lợi ích có thể khác nhau. Vì vậy
  ma trận quyền truy cập (phần 4) tách mức xem của thành viên khỏi chủ hộ, chứ không gộp chung thành "người trong
  nhà".

---

## 2. Sơ đồ phân rã chức năng (BFD)

![Sơ đồ phân rã chức năng WattPrint](../../diagrams/privacy/01-bfd.svg)

## 3. Ma trận tác nhân – chức năng

**Phạm vi**: 26 chức năng bổ sung hoặc điều chỉnh cho yêu cầu cải tiến (các ô nền xanh trên BFD). Các chức năng
nghiệp vụ giữ nguyên không đưa vào.

**Ký hiệu trong ô:**

| Ký hiệu | Nghĩa |
|---|---|
| **K** | Khởi xướng: tác nhân yêu cầu hoặc bắt đầu chức năng |
| **T** | Tham gia: tác nhân xử lý, cung cấp hoặc nhận dữ liệu trong lúc chức năng chạy |
| **N** | Nhận kết quả hoặc thông báo sau khi chức năng xong, không tham gia xử lý |
| (trống) | Không liên quan |
| <sup>a</sup>…<sup>h</sup> | Điều kiện, ghi ở chú thích dưới bảng |

**Các cột tác nhân:**

| Cột | Tác nhân | Cột | Tác nhân |
|---|---|---|---|
| TN01 | Khách vãng lai | TN07 | Thiết bị đo |
| TN02 | Khách dùng thử | TN10 | Dịch vụ mô hình ngôn ngữ |
| TN03 | Chủ hộ | TN11 | Dịch vụ giọng nói |
| TN04 | Thành viên hộ | TN13 | Dịch vụ thư điện tử |
| TN05 | Quản trị viên | TN14 | Dịch vụ nhắn tin cho người vận hành |
| TN06 | Người phụ trách bảo vệ dữ liệu cá nhân | TN15 | Cơ quan chuyên trách bảo vệ dữ liệu cá nhân |

Ba tác nhân TN08 (nguồn dữ liệu mẫu), TN09 (xác thực danh tính) và TN12 (thời tiết) không tham gia chức năng nào
trong 26 chức năng này, nên không có cột.

### 3.1 Ma trận

| Mã | Chức năng | TN01 | TN02 | TN03 | TN04 | TN05 | TN06 | TN07 | TN10 | TN11 | TN13 | TN14 | TN15 |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 1.4 | Xóa tài khoản | | K | K | K | | | | | | | | |
| 2.4 | Mời thành viên | | | K | T | | | | | | T | | |
| 2.5 | Phân mức xem cho thành viên | | | K | N | | | | | | | | |
| 2.6 | Gỡ thành viên, rời nhà | | | K | K | | | | | | | | |
| 3.2 | Kiểm tra lô trùng, lô trước mốc đã xóa | | | | | | | K | | | | | |
| 3.4 | Hạ độ chi tiết khi hết hạn lưu<sup>a</sup> | | | | | | | | | | | | |
| 5.1 | Xem biểu đồ tiêu thụ | | K | K | K<sup>b</sup> | K<sup>c</sup> | | | | | | | |
| 6.1 | Tiếp nhận câu hỏi bằng chữ, giọng nói | | K | K | K | | | | | T<sup>d</sup> | | | |
| 6.2 | Lấy số liệu trong mức được phép<sup>e</sup> | | K | K | K<sup>b</sup> | | | | | | | | |
| 6.3 | Che thông tin cá nhân<sup>e</sup> | | K | K | K | | | | | | | | |
| 6.4 | Gọi dịch vụ AI bên ngoài<sup>e</sup> | | K | K | K | | | | T<sup>f</sup> | | | | |
| 6.5 | Trả lời kèm dữ liệu đã gửi<sup>e</sup> | | N | N | N | | | | | | | | |
| 6.6 | Ghi nhận đánh giá câu trả lời | | K | K | K | N<sup>g</sup> | | | | | | T<sup>g</sup> | |
| 7.1 | Đặt thời hạn lưu của nhà | | | K | N | | | | | | | | |
| 7.2 | Đặt mức chi tiết gửi AI | | | K | N | | | | | | | | |
| 7.3 | Cho, rút đồng ý dịch vụ ngoài | | K | K | K | | | | | | | | |
| 7.4 | Xóa lịch sử điện | | | K | N | | | | | | | | |
| 7.5 | Xóa trò chuyện | | K | K | K | | | | | | | | |
| 7.6 | Xem nhật ký gửi ra ngoài | | K | K | K | | | | | | | | |
| 7.7 | Cấp quyền hỗ trợ có thời hạn | | | K | | N | | | | | | | |
| 8.1 | Tiếp nhận yêu cầu của chủ thể dữ liệu | | K | K | K | | T | | | | | | |
| 8.2 | Theo dõi hạn xử lý yêu cầu | | N | N | N | | K | | | | | | |
| 8.3 | Quản lý danh mục bên nhận dữ liệu | N | N | N | N | T | K | | | | | | |
| 8.4 | Lập hồ sơ đánh giá tác động | | | | | | K | | | | | | N |
| 8.5 | Xử lý, thông báo sự cố | | | N<sup>h</sup> | N<sup>h</sup> | T | K | | | | | | N |
| 8.6 | Rà soát nhật ký truy cập | | | | | | K | | | | | | |

**Chú thích:**

- <sup>a</sup> Chạy tự động hằng ngày, không có tác nhân khởi xướng. Thời hạn áp dụng lấy từ lựa chọn của chủ hộ ở 7.1.
- <sup>b</sup> Chỉ ở mức xem chủ hộ cấp. Thành viên mức "chỉ theo ngày" chỉ nhận số liệu theo ngày.
- <sup>c</sup> Chỉ khi chủ hộ đã cấp quyền hỗ trợ (7.7) và quyền còn hạn. Mỗi lần xem được ghi vào nhật ký truy cập.
- <sup>d</sup> Chỉ khi hỏi bằng giọng nói và người hỏi đã đồng ý dùng giọng nói.
- <sup>e</sup> 6.2 đến 6.5 chạy nối tiếp 6.1 trong cùng một lượt hỏi. Người hỏi là người khởi xướng cả lượt.
- <sup>f</sup> Chỉ khi người hỏi đã đồng ý dùng dịch vụ AI bên ngoài. Dịch vụ chỉ nhận câu hỏi đã che thông tin cá nhân
  và số liệu đã tối giản.
- <sup>g</sup> Nội dung câu hỏi và câu trả lời chỉ đi qua TN14 tới TN05 khi người dùng tự chọn gửi kèm. Mặc định chỉ có
  điểm đánh giá.
- <sup>h</sup> Chỉ người dùng bị ảnh hưởng bởi sự cố.

## 4. Ma trận tác nhân – quyền truy cập dữ liệu

**Phạm vi**: các loại dữ liệu mà 26 chức năng ở mục 3 tạo ra, đọc, sửa hoặc xóa. Trong đó có các loại dữ liệu
nhạy cảm mà các chức năng này phải bảo vệ: số đo, ước tính thiết bị, trò chuyện.

**Ký hiệu trong ô:**

| Ký hiệu | Nghĩa |
|---|---|
| **C** | Tạo |
| **R** | Đọc |
| **U** | Sửa |
| **D** | Xóa |
| **–** | Không có quyền. Mọi ô "–" là một ca thử phân quyền phải bị từ chối |
| <sup>1</sup>…<sup>14</sup> | Giới hạn, ghi ở chú thích dưới bảng |

**Thành viên hộ (TN04) tách thành hai cột theo mức xem**, vì đây là điểm khác biệt chính của phân quyền:

- **TN04-Đ**: mức đầy đủ.
- **TN04-N**: mức chỉ theo ngày. Đây là mặc định khi được mời.

**Quản trị viên (TN05) cũng tách thành hai cột:**

- **TN05**: khi chỉ có quyền của vai.
- **TN05-H**: khi chủ hộ đã cấp quyền hỗ trợ còn hạn.

### 4.1 Danh mục dữ liệu

| Mã | Dữ liệu | Độ nhạy | Ghi chú |
|---|---|---|---|
| D01 | Số đo chi tiết (khoảng 10 giây) | Rất cao | Suy ra được giờ thức, ngủ, vắng nhà, thiết bị đang chạy |
| D02 | Tổng hợp theo phút | Rất cao | Như D01 |
| D03 | Tổng hợp theo giờ | Cao | Vẫn lộ lịch sinh hoạt trong ngày (đúng nhận xét của đề) |
| D04 | Tổng hợp theo ngày, hóa đơn | Trung bình | Chỉ lộ xu hướng, ngày vắng nhà dài |
| D05 | Ước tính theo thiết bị, giờ bật/tắt thiết bị | Rất cao | Lộ hoạt động cụ thể: nấu ăn, giặt, tắm |
| D06 | Cảnh báo, dự báo, gợi ý tiết kiệm | Cao | Cảnh báo có thể kèm giờ xảy ra |
| D07 | Hồ sơ nhà (tỉnh, loại nhà, diện tích, số người, tên thiết bị và phòng) | Cao | Tên do người dùng đặt có thể lộ người trong nhà ("phòng bé An") |
| D08 | Thành viên và mức xem | Trung bình | |
| D09 | Cài đặt riêng tư của nhà (thời hạn lưu, mức gửi AI, mốc đã xóa) | Thấp | |
| D10 | Đồng ý và bằng chứng đồng ý | Trung bình | Lưu theo từng người |
| D11 | Trò chuyện với Wappi (câu hỏi, câu trả lời, âm thanh) | Cao | Lời nói tự do, có thể chứa bất cứ điều gì |
| D12 | Nhật ký gửi ra ngoài | Trung bình | Không chứa nội dung, chỉ ghi lúc nào, bên nào, loại và mức chi tiết |
| D13 | Quyền hỗ trợ và nhật ký truy cập hỗ trợ | Trung bình | |
| D14 | Yêu cầu của chủ thể dữ liệu | Trung bình | |
| D15 | Danh mục bên nhận dữ liệu | Công khai | |
| D16 | Hồ sơ đánh giá tác động, biên bản sự cố | Nội bộ | |
| D17 | Tài khoản (email, họ tên) | Trung bình | |
| D18 | Kế hoạch, nhắc việc | Thấp | Lưu theo từng người |

### 4.2 Ma trận

| Dữ liệu | TN02 | TN03 | TN04-Đ | TN04-N | TN05 | TN05-H | TN06 | TN07 | TN10 | TN11 | TN13 | TN14 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| D01 Số đo chi tiết | – | D | – | – | – | – | – | C | – | – | – | – |
| D02 Tổng hợp theo phút | R<sup>1</sup> | R D | R | – | – | R | – | – | – | – | – | – |
| D03 Tổng hợp theo giờ | R<sup>1</sup> | R D | R | – | – | R | – | – | R<sup>2</sup> | – | – | – |
| D04 Tổng hợp theo ngày, hóa đơn | R<sup>1</sup> | R D | R | R | – | R | – | – | R<sup>3</sup> | – | – | – |
| D05 Ước tính thiết bị, giờ bật/tắt | R<sup>1</sup> | R D | R | R<sup>4</sup> | – | R | – | – | R<sup>5</sup> | – | – | – |
| D06 Cảnh báo, dự báo, gợi ý | R<sup>1</sup> | R D | R | R<sup>4</sup> | – | R | – | – | R<sup>3</sup> | – | – | – |
| D07 Hồ sơ nhà | R<sup>1</sup> | C R U D | R | R | – | R | – | – | – | – | – | – |
| D08 Thành viên và mức xem | – | C R U D | R<sup>6</sup> D<sup>6</sup> | R<sup>6</sup> D<sup>6</sup> | – | – | – | – | – | – | R<sup>7</sup> | – |
| D09 Cài đặt riêng tư của nhà | R<sup>1</sup> | R U | R | R | – | R | – | – | – | – | – | – |
| D10 Đồng ý | C R U<sup>8</sup> | C R U<sup>8</sup> | C R U<sup>8</sup> | C R U<sup>8</sup> | – | – | R | – | – | – | – | – |
| D11 Trò chuyện với Wappi | C R D<sup>8</sup> | C R D<sup>8</sup> | C R D<sup>8</sup> | C R D<sup>8</sup> | R<sup>9</sup> | R<sup>9</sup> | – | – | R<sup>10</sup> | R<sup>11</sup> | – | R<sup>9</sup> |
| D12 Nhật ký gửi ra ngoài | R<sup>8</sup> | R<sup>12</sup> | R<sup>8</sup> | R<sup>8</sup> | – | – | R | – | – | – | – | – |
| D13 Quyền hỗ trợ, nhật ký truy cập hỗ trợ | – | C R D | – | – | R<sup>8</sup> | R<sup>8</sup> | R | – | – | – | – | – |
| D14 Yêu cầu của chủ thể dữ liệu | C R<sup>8</sup> | C R<sup>8</sup> | C R<sup>8</sup> | C R<sup>8</sup> | – | – | R U | – | – | – | – | – |
| D15 Danh mục bên nhận dữ liệu | R | R | R | R | R | R | C R U D | – | – | – | – | – |
| D16 Hồ sơ đánh giá tác động, biên bản sự cố | – | – | – | – | R<sup>13</sup> | R<sup>13</sup> | C R U D | – | – | – | – | – |
| D17 Tài khoản | R U D<sup>8</sup> | R U D<sup>8</sup> | R U D<sup>8</sup> | R U D<sup>8</sup> | R U<sup>14</sup> | R U<sup>14</sup> | – | – | – | – | R<sup>7</sup> | – |
| D18 Kế hoạch, nhắc việc | C R U D<sup>8</sup> | C R U D<sup>8</sup> | C R U D<sup>8</sup> | C R U D<sup>8</sup> | – | – | – | – | – | – | – | – |

**Chú thích:**

1. Chỉ dữ liệu của nhà mẫu (dữ liệu công khai). Không có quyền nào với nhà thật.
2. Chỉ khi chủ hộ đặt mức gửi AI là "theo giờ" (7.2), người hỏi có mức xem đầy đủ, và người hỏi đã đồng ý (7.3).
   Chỉ gồm các dòng cần cho câu trả lời của lượt đó.
3. Chỉ khi người hỏi đã đồng ý. Chỉ gồm các dòng cần cho câu trả lời.
4. Chỉ tổng theo ngày. Không có giờ bật/tắt thiết bị, không có giờ xảy ra cảnh báo.
5. Như chú thích 2 hoặc 3 tùy mức gửi AI. Không bao giờ gồm giờ bật/tắt chi tiết. Tên thiết bị và tên phòng do
   người dùng đặt được thay bằng tên loại thiết bị.
6. Chỉ dòng của chính mình. Xóa dòng của mình nghĩa là rời nhà.
7. Chỉ địa chỉ thư người nhận và nội dung thư (mã mời, thông báo).
8. Chỉ dữ liệu của chính người đó.
9. Chỉ những lượt người dùng tự chọn gửi kèm khi đánh giá câu trả lời (6.6). Quyền hỗ trợ (TN05-H) không mở thêm
   quyền đọc trò chuyện, vì trò chuyện thuộc về từng người, không thuộc về nhà.
10. Chỉ lượt đang hỏi, sau khi đã che thông tin cá nhân. Nhà cung cấp phải cam kết không giữ để huấn luyện.
11. Chỉ âm thanh của lượt đang hỏi, khi người hỏi đã đồng ý dùng giọng nói. Âm thanh không che được thông tin cá
    nhân.
12. Các lần gửi do chính mình gây ra, cộng với các lần gửi nhân danh cả nhà.
13. Chỉ biên bản sự cố mà quản trị viên tham gia xử lý.
14. Chỉ danh sách tài khoản (email, họ tên, trạng thái), không kèm dữ liệu nhà. Sửa ở đây là khóa hoặc mở tài
    khoản (1.5).

**Ngoài bảng:**

- TN01 chỉ đọc D15, qua trang chính sách.
- TN09 tạo D17 khi người dùng đăng nhập lần đầu.
- TN12 không đọc dữ liệu nào trong bảng. TN12 chỉ nhận tọa độ cấp tỉnh, dùng chung cho mọi nhà trong tỉnh.
- TN15 nhận bản chính của D16 qua thủ tục hành chính, ngoài hệ thống.

## 5. Sơ đồ luồng dữ liệu (DFD)

### 5.1 DFD mức ngữ cảnh

![DFD mức ngữ cảnh WattPrint](../../diagrams/privacy/02-dfd-context.svg)

#### Từ điển luồng dữ liệu mức ngữ cảnh

Cột "Riêng tư" ghi ràng buộc gắn với luồng và chức năng BFD thực hiện ràng buộc đó.

| Mã | Luồng | Từ → Đến | Thành phần | Riêng tư |
|---|---|---|---|---|
| L01 | Yêu cầu dùng thử | TN01 → 0 | Lựa chọn dùng thử | Chưa thu thập dữ liệu cá nhân |
| L02 | Thông tin công khai | 0 → TN01 | Giới thiệu, chính sách quyền riêng tư, danh mục bên nhận dữ liệu | Danh mục lấy từ D15, khớp với thực tế (8.3) |
| L03 | Câu hỏi, lựa chọn cá nhân | TN02 → 0 | Hồ sơ cá nhân, yêu cầu xóa tài khoản; yêu cầu xem, kế hoạch thử; câu hỏi bằng chữ hoặc giọng nói, đánh giá câu trả lời; đồng ý hoặc rút đồng ý; yêu cầu xóa trò chuyện, yêu cầu xem nhật ký; yêu cầu của chủ thể | Đồng ý được ghi kèm thời điểm và nội dung thông báo (7.3) |
| L04 | Báo cáo nhà mẫu, câu trả lời | 0 → TN02 | Tài khoản dùng thử, hồ sơ cá nhân, xác nhận xóa; biểu đồ, thiết bị, cảnh báo, hóa đơn của nhà mẫu; câu trả lời kèm mục "Đã gửi ra ngoài"; thông báo xử lý dữ liệu; nhật ký gửi ra ngoài của chính mình; kết quả xử lý yêu cầu | Chỉ dữ liệu công khai của nhà mẫu (1.2, 5.1, 6.5) |
| L05 | Thông tin nhà, câu hỏi, quyết định riêng tư | TN03 → 0 | Hồ sơ cá nhân, yêu cầu xóa tài khoản; hồ sơ nhà, mã gắn thiết bị đo, tên thiết bị; lời mời, mức xem thành viên, yêu cầu gỡ thành viên; yêu cầu xem, kế hoạch; câu hỏi, đánh giá câu trả lời; thời hạn lưu, mức gửi AI, yêu cầu xóa lịch sử, quyền hỗ trợ; đồng ý; yêu cầu xóa trò chuyện, yêu cầu xem nhật ký; yêu cầu của chủ thể | Chỉ chủ hộ gửi được các quyết định thay cả nhà (2.4, 2.5, 7.1, 7.2, 7.4, 7.7) |
| L06 | Báo cáo điện năng, câu trả lời, thông tin quyền riêng tư | 0 → TN03 | Hồ sơ cá nhân, xác nhận xóa; hồ sơ nhà, mã mời, kết quả gắn thiết bị; biểu đồ, thiết bị, cảnh báo, dự báo, hóa đơn, nhắc tiết kiệm; câu trả lời kèm dữ liệu đã gửi; dữ liệu đang giữ ở từng mức; thông báo xử lý dữ liệu; nhật ký gửi ra ngoài; nhật ký truy cập hỗ trợ; kết quả xử lý yêu cầu | Biểu đồ hạ mức chi tiết khi quá hạn lưu (5.1). Có nhật ký gửi ra ngoài (7.6) |
| L07 | Mã mời, câu hỏi, lựa chọn cá nhân | TN04 → 0 | Hồ sơ cá nhân, yêu cầu xóa tài khoản; mã mời, yêu cầu rời nhà; yêu cầu xem, kế hoạch; câu hỏi, đánh giá câu trả lời; đồng ý của mình; yêu cầu xóa trò chuyện, yêu cầu xem nhật ký; yêu cầu của chủ thể | Thành viên không gửi được quyết định thay cả nhà |
| L08 | Báo cáo theo mức xem, câu trả lời | 0 → TN04 | Mức xem được cấp; còn lại như L06 nhưng ở mức xem chủ hộ cấp, không có thông tin quản lý nhà, và chỉ kèm nhật ký gửi ra ngoài của chính thành viên | Mức "chỉ theo ngày" không có số theo giờ hay giờ bật/tắt (2.5, 6.2) |
| L09 | Cấu hình, lệnh khóa/mở tài khoản | TN05 → 0 | Lệnh khóa hoặc mở tài khoản; lệnh nạp dữ liệu nhà mẫu; yêu cầu xem dữ liệu nhà khi hỗ trợ; thông tin dịch vụ ngoài đang dùng; thông tin sự cố | Yêu cầu xem dữ liệu nhà chỉ được chấp nhận khi chủ hộ đã cấp quyền hỗ trợ còn hạn (5.1, 7.7) |
| L10 | Danh sách tài khoản, dữ liệu hỗ trợ được cấp | 0 → TN05 | Email, họ tên, trạng thái tài khoản; thông báo được cấp quyền hỗ trợ; dữ liệu điện của nhà đã cấp quyền hỗ trợ | Dữ liệu nhà chỉ có khi quyền hỗ trợ còn hạn, mỗi lần xem được ghi nhật ký (7.7) |
| L11 | Danh mục bên nhận, kết quả xử lý yêu cầu | TN06 → 0 | Danh mục bên nhận dữ liệu; kết quả xử lý yêu cầu của chủ thể; nội dung hồ sơ đánh giá tác động; biên bản sự cố | (8.2–8.5) |
| L12 | Yêu cầu của chủ thể, bằng chứng đồng ý, nhật ký | 0 → TN06 | Yêu cầu và hạn xử lý; bằng chứng đồng ý; nhật ký gửi ra ngoài; nhật ký truy cập hỗ trợ | Không kèm số đo của từng nhà (8.2, 8.6) |
| L13 | Yêu cầu hoàn thiện hồ sơ | TN15 → 0 | Yêu cầu bổ sung hồ sơ; quyết định kiểm tra | Luồng thủ tục |
| L14 | Hồ sơ đánh giá tác động, thông báo vi phạm | 0 → TN15 | Hồ sơ đánh giá tác động xử lý dữ liệu (Luật 91/2025 Điều 21) và chuyển dữ liệu xuyên biên giới (Điều 20); thông báo vi phạm trong 72 giờ (Điều 23) | Mô tả hoạt động xử lý, không kèm dữ liệu của hộ (8.4, 8.5) |
| L15 | Câu hỏi đã che, số liệu tối giản | 0 → TN10 | Câu hỏi đã thay tên, địa chỉ, số điện thoại bằng nhãn; các dòng số liệu cần cho câu trả lời, ở mức theo giờ hoặc theo ngày; tên loại thiết bị thay cho tên do người dùng đặt | **Xuyên biên giới.** Chỉ khi người hỏi đã đồng ý. Không có số theo phút, tên nhà, mã bưu chính, số người. Mỗi lần gửi được ghi nhật ký (6.2–6.4) |
| L16 | Câu trả lời sinh ra | TN10 → 0 | Văn bản trả lời | Nhà cung cấp cam kết không giữ dữ liệu để huấn luyện |
| L17 | Âm thanh câu hỏi, chữ cần đọc | 0 → TN11 | Âm thanh câu hỏi; văn bản câu trả lời cần đọc thành tiếng | Bên nhận đặt tại Việt Nam. Chỉ khi đã đồng ý dùng giọng nói. Âm thanh không che được thông tin cá nhân. Có ghi nhật ký (6.1) |
| L18 | Chữ nhận dạng, âm thanh đọc | TN11 → 0 | Văn bản nhận dạng từ lời nói; âm thanh câu trả lời | Văn bản nhận dạng được che thông tin cá nhân trước khi dùng tiếp (6.3) |
| L19 | Đánh giá câu trả lời | 0 → TN14 | Điểm đánh giá; câu hỏi và câu trả lời chỉ khi người dùng tích "gửi kèm nội dung" | **Xuyên biên giới khi có nội dung.** Mặc định không có nội dung. Có ghi nhật ký (6.6) |
| L20 | Yêu cầu xác thực | 0 → TN09 | Chuyển hướng đăng nhập | Không kèm dữ liệu điện hay dữ liệu nhà |
| L21 | Kết quả xác thực | TN09 → 0 | Mã định danh, email, họ tên | Chỉ lấy ba trường này |
| L22 | Tọa độ cấp tỉnh | 0 → TN12 | Tọa độ trung tâm tỉnh | Không phải dữ liệu cá nhân: dùng chung cho mọi nhà trong tỉnh |
| L23 | Dữ liệu thời tiết | TN12 → 0 | Nhiệt độ, độ ẩm theo giờ | |
| L24 | Lô số đo | TN07 → 0 | Khóa thiết bị; chuỗi công suất theo thời gian; mã lô | Dữ liệu nhạy cảm nhất của hệ thống. Lô cũ hơn mốc đã xóa bị từ chối (3.2) |
| L25 | Xác nhận nhận lô | 0 → TN07 | Đã nhận, trùng, hoặc từ chối kèm lý do | Không chứa dữ liệu cá nhân |
| L26 | Số đo nhà mẫu | TN08 → 0 | Chuỗi số đo và nhãn thiết bị của các nhà trong bộ dữ liệu công khai | Đã khử nhận dạng; không ghép với dữ liệu hộ thật |
| L27 | Thư gửi người dùng | 0 → TN13 | Địa chỉ thư; thư mời, thư thông báo kết quả xử lý yêu cầu, thư thông báo sự cố | Không chứa số liệu điện hay giờ giấc sinh hoạt (2.4, 8.2, 8.5) |

### 5.2 DFD mức 0

![Tiến trình 1: Quản lý tài khoản](../../diagrams/privacy/03-dfd-level0-1.svg)

![Tiến trình 2: Quản lý hộ gia đình](../../diagrams/privacy/03-dfd-level0-2.svg)

![Tiến trình 3: Thu nhận và lưu trữ số đo](../../diagrams/privacy/03-dfd-level0-3.svg)

![Tiến trình 4: Phân tích điện năng](../../diagrams/privacy/03-dfd-level0-4.svg)

![Tiến trình 5: Tra cứu và theo dõi](../../diagrams/privacy/03-dfd-level0-5.svg)

![Tiến trình 6: Hỏi đáp với trợ lý Wappi](../../diagrams/privacy/03-dfd-level0-6.svg)

![Tiến trình 7: Quản lý quyền riêng tư](../../diagrams/privacy/03-dfd-level0-7.svg)

![Tiến trình 8: Tuân thủ bảo vệ dữ liệu](../../diagrams/privacy/03-dfd-level0-8.svg)

Cách bố trí sơ đồ:

- Tiến trình 0 ở mức ngữ cảnh được phân rã thành 8 tiến trình, khớp 8 nhánh của BFD (mục 2), xếp theo số hiệu
  và vẽ mỗi tiến trình trên một hình. Tác nhân của tiến trình nằm ở hàng phía trên, kho dữ liệu ở hàng phía dưới;
  mỗi luồng là một đường thẳng đứng nối phần tử với tiến trình.
- Tiến trình 7 (Quản lý quyền riêng tư) và 8 (Tuân thủ bảo vệ dữ liệu) là hai nhánh bổ sung cho yêu cầu bảo vệ dữ
  liệu nếp sinh hoạt, tô nền xanh.
- Hai bên ở nước ngoài (TN10, TN14) chỉ nối với tiến trình 6 (Hỏi đáp với trợ lý Wappi). Đây là tiến trình
  duy nhất đưa dữ liệu cá nhân ra khỏi Việt Nam.
- Tiến trình 4 (Phân tích điện năng) chỉ trao đổi với tác nhân TN12, bằng tọa độ cấp tỉnh. Mọi phân tích trên số
  đo chạy trong hệ thống.

#### Nhóm kho dữ liệu ở mức 0

| Kho ở mức 0 | Gồm các kho ở mức 1 |
|---|---|
| D01–D04 Số đo và bản tổng hợp | D01 Số đo chi tiết; D02 Tổng hợp theo phút; D03 Tổng hợp theo giờ; D04 Tổng hợp theo ngày, hóa đơn |
| D05–D06 Kết quả phân tích | D05 Ước tính thiết bị, giờ bật/tắt; D06 Cảnh báo, dự báo, gợi ý |
| D07–D09 Hộ gia đình | D07 Hồ sơ nhà; D08 Thành viên và mức xem; D09 Cài đặt riêng tư của nhà |
| D12–D13 Nhật ký và quyền hỗ trợ | D12 Nhật ký gửi ra ngoài; D13 Quyền hỗ trợ, nhật ký truy cập hỗ trợ |
| D15–D16 Hồ sơ tuân thủ | D15 Danh mục bên nhận dữ liệu; D16 Hồ sơ đánh giá tác động, biên bản sự cố |

Các kho D10, D11, D14, D17, D18 vẽ riêng ở cả hai mức.

#### Cân bằng với mức ngữ cảnh

Mỗi luồng ở mức ngữ cảnh được tách thành các luồng của một hoặc nhiều tiến trình mức 0. Thành phần của từng luồng
mức ngữ cảnh (cột "Thành phần" ở mục 5.1) bằng hợp các luồng mức 0 tương ứng.

| Luồng mức ngữ cảnh | Tác nhân | Tiến trình mức 0 |
|---|---|---|
| L01 | TN01 | 1 |
| L02 | TN01 | 8 |
| L03, L04 | TN02 | 1, 5, 6, 7, 8 |
| L05, L06 | TN03 | 1, 2, 5, 6, 7, 8 |
| L07, L08 | TN04 | 1, 2, 5, 6, 7, 8 |
| L09 | TN05 | 1, 3, 5, 8 |
| L10 | TN05 | 1, 5, 7 |
| L11, L12 | TN06 | 8 |
| L13, L14 | TN15 | 8 |
| L15, L16 | TN10 | 6 |
| L17, L18 | TN11 | 6 |
| L19 | TN14 | 6 |
| L20, L21 | TN09 | 1 |
| L22, L23 | TN12 | 4 |
| L24, L25 | TN07 | 3 |
| L26 | TN08 | 3 |
| L27 | TN13 | 2, 8 |

Ở tiến trình 1, 6, 7, 8, ba tác nhân TN02, TN03, TN04 được vẽ gộp vì cùng gửi và nhận một loại luồng. Ở tiến
trình 2 và 5 chúng được vẽ riêng vì quyền khác nhau: chỉ chủ hộ quản lý nhà; khách dùng thử chỉ thấy nhà mẫu;
thành viên chỉ thấy dữ liệu theo mức xem được cấp.

### 5.3 DFD mức 1

Mỗi tiến trình mức 0 được phân rã ở một mục riêng, mỗi tiến trình con vẽ trên một hình. Tiến trình con mang số
hiệu và tên của chức năng lá tương ứng trên BFD (mục 2), nên 8 mục có đủ 45 tiến trình con. Khi hai tiến trình con
nối tiếp nhau, tiến trình liền kề được vẽ thu nhỏ ở cạnh hình để thể hiện luồng nối giữa chúng. Tiến trình con tô nền xanh là 26 chức
năng bổ sung hoặc điều chỉnh, được đặc tả ở mục 5.3.9.

Cân bằng với mức 0:

- Mỗi luồng giữa tiến trình mức 0 và tác nhân xuất hiện ở ít nhất một tiến trình con, với cùng tác nhân.
- Mỗi kho nhóm ở mức 0 được tách thành các kho thành phần theo bảng ở mục 5.2.

#### 5.3.1 Tiến trình 1: Quản lý tài khoản

![Tiến trình 1.1: Đăng ký, đăng nhập](../../diagrams/privacy/04-dfd-level1-1-1.svg)

![Tiến trình 1.2: Tạo tài khoản dùng thử](../../diagrams/privacy/04-dfd-level1-1-2.svg)

![Tiến trình 1.3: Cập nhật hồ sơ cá nhân](../../diagrams/privacy/04-dfd-level1-1-3.svg)

![Tiến trình 1.4: Xóa tài khoản](../../diagrams/privacy/04-dfd-level1-1-4.svg)

![Tiến trình 1.5: Khóa, mở tài khoản](../../diagrams/privacy/04-dfd-level1-1-5.svg)

#### 5.3.2 Tiến trình 2: Quản lý hộ gia đình

![Tiến trình 2.1: Khai báo thông tin nhà](../../diagrams/privacy/04-dfd-level1-2-1.svg)

![Tiến trình 2.2: Gắn thiết bị đo](../../diagrams/privacy/04-dfd-level1-2-2.svg)

![Tiến trình 2.3: Quản lý thiết bị điện](../../diagrams/privacy/04-dfd-level1-2-3.svg)

![Tiến trình 2.4: Mời thành viên](../../diagrams/privacy/04-dfd-level1-2-4.svg)

![Tiến trình 2.5: Phân mức xem cho thành viên](../../diagrams/privacy/04-dfd-level1-2-5.svg)

![Tiến trình 2.6: Gỡ thành viên, rời nhà](../../diagrams/privacy/04-dfd-level1-2-6.svg)

#### 5.3.3 Tiến trình 3: Thu nhận và lưu trữ số đo

![Tiến trình 3.1: Tiếp nhận lô số đo](../../diagrams/privacy/04-dfd-level1-3-1.svg)

![Tiến trình 3.2: Kiểm tra lô trùng, lô trước mốc đã xóa](../../diagrams/privacy/04-dfd-level1-3-2.svg)

![Tiến trình 3.3: Tổng hợp số đo theo phút, giờ, ngày](../../diagrams/privacy/04-dfd-level1-3-3.svg)

![Tiến trình 3.4: Hạ độ chi tiết khi hết hạn lưu](../../diagrams/privacy/04-dfd-level1-3-4.svg)

![Tiến trình 3.5: Nạp dữ liệu nhà mẫu](../../diagrams/privacy/04-dfd-level1-3-5.svg)

Luồng "Lô đã xác thực" đi thẳng từ 3.1 sang 3.2. Lô chỉ được ghi vào D01 sau khi đã qua kiểm tra trùng và kiểm tra
mốc đã xóa.

#### 5.3.4 Tiến trình 4: Phân tích điện năng

![Tiến trình 4.1: Tách điện năng theo thiết bị](../../diagrams/privacy/04-dfd-level1-4-1.svg)

![Tiến trình 4.2: Phát hiện bất thường](../../diagrams/privacy/04-dfd-level1-4-2.svg)

![Tiến trình 4.3: Dự báo mức dùng](../../diagrams/privacy/04-dfd-level1-4-3.svg)

![Tiến trình 4.4: Tính hóa đơn bậc thang](../../diagrams/privacy/04-dfd-level1-4-4.svg)

![Tiến trình 4.5: Đề xuất cách tiết kiệm](../../diagrams/privacy/04-dfd-level1-4-5.svg)

#### 5.3.5 Tiến trình 5: Tra cứu và theo dõi

![Tiến trình 5.1: Xem biểu đồ tiêu thụ](../../diagrams/privacy/04-dfd-level1-5-1.svg)

![Tiến trình 5.2: Xem điện theo thiết bị](../../diagrams/privacy/04-dfd-level1-5-2.svg)

![Tiến trình 5.3: Xem cảnh báo](../../diagrams/privacy/04-dfd-level1-5-3.svg)

![Tiến trình 5.4: Xem dự báo, hóa đơn](../../diagrams/privacy/04-dfd-level1-5-4.svg)

![Tiến trình 5.5: Lập kế hoạch, nhắc tiết kiệm](../../diagrams/privacy/04-dfd-level1-5-5.svg)

#### 5.3.6 Tiến trình 6: Hỏi đáp với trợ lý Wappi

![Tiến trình 6.1: Tiếp nhận câu hỏi bằng chữ, giọng nói](../../diagrams/privacy/04-dfd-level1-6-1.svg)

![Tiến trình 6.2: Lấy số liệu trong mức được phép](../../diagrams/privacy/04-dfd-level1-6-2.svg)

![Tiến trình 6.3: Che thông tin cá nhân](../../diagrams/privacy/04-dfd-level1-6-3.svg)

![Tiến trình 6.4: Gọi dịch vụ AI bên ngoài](../../diagrams/privacy/04-dfd-level1-6-4.svg)

![Tiến trình 6.5: Trả lời kèm dữ liệu đã gửi](../../diagrams/privacy/04-dfd-level1-6-5.svg)

![Tiến trình 6.6: Ghi nhận đánh giá câu trả lời](../../diagrams/privacy/04-dfd-level1-6-6.svg)

Năm tiến trình 6.1 đến 6.5 nối thành một chuỗi. Câu hỏi chỉ tới được dịch vụ AI ở nước ngoài (TN10) sau khi đã qua
6.2 (lọc theo mức được phép) và 6.3 (che thông tin cá nhân). Không có đường nào đi từ kho số đo tới TN10 mà không
qua hai bước này.

#### 5.3.7 Tiến trình 7: Quản lý quyền riêng tư

![Tiến trình 7.1: Đặt thời hạn lưu của nhà](../../diagrams/privacy/04-dfd-level1-7-1.svg)

![Tiến trình 7.2: Đặt mức chi tiết gửi AI](../../diagrams/privacy/04-dfd-level1-7-2.svg)

![Tiến trình 7.3: Cho, rút đồng ý dịch vụ ngoài](../../diagrams/privacy/04-dfd-level1-7-3.svg)

![Tiến trình 7.4: Xóa lịch sử điện](../../diagrams/privacy/04-dfd-level1-7-4.svg)

![Tiến trình 7.5: Xóa trò chuyện](../../diagrams/privacy/04-dfd-level1-7-5.svg)

![Tiến trình 7.6: Xem nhật ký gửi ra ngoài](../../diagrams/privacy/04-dfd-level1-7-6.svg)

![Tiến trình 7.7: Cấp quyền hỗ trợ có thời hạn](../../diagrams/privacy/04-dfd-level1-7-7.svg)

#### 5.3.8 Tiến trình 8: Tuân thủ bảo vệ dữ liệu

![Tiến trình 8.1: Tiếp nhận yêu cầu của chủ thể dữ liệu](../../diagrams/privacy/04-dfd-level1-8-1.svg)

![Tiến trình 8.2: Theo dõi hạn xử lý yêu cầu](../../diagrams/privacy/04-dfd-level1-8-2.svg)

![Tiến trình 8.3: Quản lý danh mục bên nhận dữ liệu](../../diagrams/privacy/04-dfd-level1-8-3.svg)

![Tiến trình 8.4: Lập hồ sơ đánh giá tác động](../../diagrams/privacy/04-dfd-level1-8-4.svg)

![Tiến trình 8.5: Xử lý, thông báo sự cố](../../diagrams/privacy/04-dfd-level1-8-5.svg)

![Tiến trình 8.6: Rà soát nhật ký truy cập](../../diagrams/privacy/04-dfd-level1-8-6.svg)

#### 5.3.9 Đặc tả các tiến trình bổ sung, điều chỉnh

Các mốc thời gian trích từ Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15 (gọi tắt "Luật") và Nghị định 356/2025/NĐ-CP
(gọi tắt "Nghị định").

| Mã | Vào | Ra | Quy tắc xử lý |
|---|---|---|---|
| 1.4 Xóa tài khoản | Yêu cầu xóa tài khoản (người dùng) | Xác nhận xóa; dữ liệu cần xóa tới D17, D07–D09, D01–D04, D05–D06, D10, D11, D18 | Người dùng xác nhận lại trước khi xóa. Chủ hộ xóa tài khoản thì nhà và mọi dữ liệu của nhà bị xóa theo. Thành viên xóa tài khoản thì chỉ xóa dữ liệu của chính người đó và tư cách thành viên. Hoàn tất trong 20 ngày (Nghị định Điều 5 khoản 4). Dữ liệu đã xóa không khôi phục được (Luật Điều 14 khoản 3, 4) |
| 2.4 Mời thành viên | Yêu cầu mời (TN03); mã mời (TN04); lời mời còn hạn (D08) | Mã mời (TN03); thư mời (TN13); lời mời, thành viên mới (D08) | Mã mời dùng một lần và có hạn dùng. Thành viên mới nhận mức xem mặc định "chỉ theo ngày" cho tới khi chủ hộ đổi. Thư mời chỉ chứa mã mời và tên người mời, không chứa số liệu điện |
| 2.5 Phân mức xem cho thành viên | Mức xem của thành viên (TN03) | Mức xem (D08); mức xem được cấp (TN04) | Hai mức: "đầy đủ" (theo phút, theo giờ, theo ngày, giờ bật/tắt thiết bị) và "chỉ theo ngày" (tổng theo ngày, không có giờ). Chỉ chủ hộ đổi được. Mức mới áp dụng ngay cho cả biểu đồ (5.1) và câu trả lời của Wappi (6.2) |
| 2.6 Gỡ thành viên, rời nhà | Yêu cầu gỡ thành viên (TN03); yêu cầu rời nhà (TN04) | Thành viên cần xóa (D08) | Người bị gỡ hoặc rời nhà mất quyền xem dữ liệu nhà ngay lập tức. Trò chuyện và đồng ý của người đó vẫn thuộc tài khoản của họ, chủ hộ không đọc được |
| 3.2 Kiểm tra lô trùng, lô trước mốc đã xóa | Lô đã xác thực (3.1); mốc đã xóa (D09); mã lô đã nhận (D01) | Số đo hợp lệ (D01); xác nhận nhận lô (TN07) | Lô có mã đã nhận thì báo "trùng" và không ghi lại. Lô có số đo trước mốc chủ hộ đã xóa (7.4) thì bị từ chối kèm lý do, để dữ liệu đã xóa không quay lại khi thiết bị gửi lại |
| 3.4 Hạ độ chi tiết khi hết hạn lưu | Thời hạn lưu của nhà (D09) | Số đo, bản theo phút, bản theo giờ, giờ bật/tắt hết hạn cần xóa (D01, D02, D03, D05) | Chạy hằng ngày. Dữ liệu quá thời hạn lưu của mức nào thì xóa ở mức đó. Một mức chỉ bị xóa sau khi bản tổng hợp ở mức thô hơn đã có đủ cho cùng khoảng thời gian. Tổng theo ngày và hóa đơn (D04) được giữ đến khi chủ hộ xóa (7.4) |
| 5.1 Xem biểu đồ tiêu thụ | Yêu cầu xem (TN02, TN03, TN04, TN05); D02, D03, D04; mức xem (D08); thời hạn lưu (D09); quyền hỗ trợ còn hạn (D13) | Biểu đồ theo đúng người xem; nhật ký truy cập hỗ trợ (D13) | Độ chi tiết trả về là mức thô hơn giữa mức xem của người xem và mức dữ liệu nhà còn giữ. Khách dùng thử chỉ xem nhà mẫu. Quản trị viên chỉ xem được khi có quyền hỗ trợ còn hạn của đúng nhà đó; mỗi lần xem được ghi một dòng nhật ký |
| 6.1 Tiếp nhận câu hỏi bằng chữ, giọng nói | Câu hỏi bằng chữ hoặc giọng nói (người dùng); chữ nhận dạng (TN11); đồng ý dùng giọng nói (D10) | Âm thanh câu hỏi (TN11); nhật ký gửi ra ngoài (D12); câu hỏi dạng chữ (6.2) | Âm thanh chỉ được gửi sang TN11 khi người hỏi đã đồng ý dùng giọng nói; chưa đồng ý thì chỉ nhận câu hỏi bằng chữ. Mỗi lần gửi âm thanh được ghi nhật ký |
| 6.2 Lấy số liệu trong mức được phép | Câu hỏi dạng chữ (6.1); mức xem của người hỏi (D08); mức gửi AI của nhà (D09); D03, D04, D05, D06 | Câu hỏi, số liệu trong mức được phép (6.3) | Mức số liệu được dùng là mức thô hơn giữa mức xem của người hỏi và mức gửi AI của nhà. Mức "chỉ theo ngày" không lấy D03 và giờ bật/tắt thiết bị. Không bao giờ đọc D01, D02. Chỉ lấy các dòng cần cho câu hỏi |
| 6.3 Che thông tin cá nhân | Câu hỏi, số liệu (6.2); lịch sử trò chuyện (D11); tên thiết bị, tên phòng (D07) | Câu hỏi đã che, số liệu tối giản (6.4) | Thay tên người, địa chỉ, số điện thoại, email bằng nhãn. Thay tên thiết bị và tên phòng do người dùng đặt bằng tên loại thiết bị. Bỏ tên nhà, mã bưu chính, số người trong nhà. Lịch sử trò chuyện đưa kèm cũng được che như vậy |
| 6.4 Gọi dịch vụ AI bên ngoài | Câu hỏi đã che, số liệu tối giản (6.3); đồng ý dùng AI (D10); câu trả lời sinh ra (TN10) | Câu hỏi đã che, số liệu tối giản (TN10); nhật ký gửi ra ngoài (D12); câu trả lời, dữ liệu đã gửi (6.5) | Người hỏi chưa đồng ý dùng AI thì không gửi gì sang TN10 và báo người hỏi cần đồng ý. Mỗi lần gửi được ghi nhật ký: thời điểm, bên nhận, mục đích, loại và mức chi tiết dữ liệu, không ghi nội dung. Đây là luồng chuyển dữ liệu ra nước ngoài, được kê khai trong hồ sơ ở 8.4 (Luật Điều 20) |
| 6.5 Trả lời kèm dữ liệu đã gửi | Câu trả lời, dữ liệu đã gửi (6.4); đồng ý dùng giọng nói (D10); âm thanh đọc (TN11) | Câu trả lời kèm dữ liệu đã gửi (người dùng); chữ cần đọc (TN11); lượt hỏi, câu trả lời (D11); nhật ký gửi ra ngoài (D12) | Mỗi câu trả lời kèm mục "Đã gửi ra ngoài", liệt kê bên nhận, loại và mức chi tiết dữ liệu đã gửi trong lượt đó. Câu trả lời chỉ được đọc thành tiếng khi người hỏi đã đồng ý dùng giọng nói |
| 6.6 Ghi nhận đánh giá câu trả lời | Đánh giá, lựa chọn gửi kèm (người dùng); lượt được đánh giá (D11) | Đánh giá (D11); đánh giá câu trả lời (TN14); nhật ký gửi ra ngoài (D12) | Mặc định chỉ gửi điểm đánh giá. Câu hỏi và câu trả lời chỉ được gửi kèm khi người dùng tự chọn cho đúng lượt đó |
| 7.1 Đặt thời hạn lưu của nhà | Mức lưu (TN03); ngày cũ nhất còn giữ (D01–D04) | Thời hạn lưu (D09); dữ liệu đang giữ ở từng mức (TN03) | Chỉ chủ hộ đặt. Trước khi lưu, hiển thị khoảng dữ liệu sẽ bị xóa theo thời hạn mới. Rút ngắn thời hạn thì 3.4 xóa phần quá hạn ở lần chạy kế tiếp |
| 7.2 Đặt mức chi tiết gửi AI | Mức gửi AI (TN03) | Mức gửi AI (D09) | Hai mức: "theo ngày" (mặc định) và "theo giờ". Chỉ chủ hộ đổi được. Áp dụng cho mọi người hỏi trong nhà, kết hợp với mức xem của từng người ở 6.2 |
| 7.3 Cho, rút đồng ý dịch vụ ngoài | Đồng ý, rút đồng ý (người dùng); danh mục bên nhận (D15) | Đồng ý kèm nội dung thông báo (D10); thông báo xử lý dữ liệu (người dùng) | Mặc định là chưa đồng ý. Đồng ý tách riêng cho từng mục đích: dùng AI, dùng giọng nói. Trước khi đồng ý, người dùng xem thông báo xử lý lấy từ danh mục bên nhận (bên nhận, quốc gia, dữ liệu, mục đích). Đồng ý được lưu kèm thời điểm và bản thông báo đã hiển thị (Luật Điều 9). Rút đồng ý có hiệu lực cho các lượt sau, không áp dụng cho lượt đã xử lý trước đó (Luật Điều 10 khoản 4) |
| 7.4 Xóa lịch sử điện | Yêu cầu xóa trước ngày (TN03) | Dữ liệu trước mốc cần xóa (D01–D04, D05–D06); mốc đã xóa (D09); xác nhận xóa (TN03) | Chỉ chủ hộ yêu cầu được. Xóa mọi mức chi tiết trước ngày đã chọn (hoặc toàn bộ), giữ tài khoản và nhà, gồm cả kết quả phân tích suy ra từ đó. Ghi mốc đã xóa để 3.2 từ chối lô cũ gửi lại. Dữ liệu đã xóa không khôi phục được (Luật Điều 14 khoản 3, 4) |
| 7.5 Xóa trò chuyện | Yêu cầu xóa trò chuyện (người dùng) | Trò chuyện cần xóa (D11); xác nhận xóa (người dùng) | Mỗi người chỉ xóa được trò chuyện của chính mình, gồm cả âm thanh. Chủ hộ không xóa hay đọc được trò chuyện của thành viên |
| 7.6 Xem nhật ký gửi ra ngoài | Yêu cầu xem nhật ký (người dùng); nhật ký gửi ra ngoài (D12) | Nhật ký gửi ra ngoài (người dùng) | Chủ hộ thấy các lần gửi do mình gây ra và các lần gửi nhân danh cả nhà. Thành viên và khách dùng thử chỉ thấy các lần gửi do mình gây ra. Nhật ký không chứa nội dung đã gửi |
| 7.7 Cấp quyền hỗ trợ có thời hạn | Quyền hỗ trợ có thời hạn (TN03); nhật ký truy cập hỗ trợ (D13) | Quyền hỗ trợ (D13); thông báo được cấp quyền (TN05); nhật ký truy cập hỗ trợ (TN03) | Chủ hộ chọn thời hạn. Hết hạn thì quyền tự mất; chủ hộ thu hồi được sớm hơn. Quyền chỉ mở dữ liệu điện và hồ sơ nhà, không mở trò chuyện. Chủ hộ xem được mọi lần quản trị viên truy cập |
| 8.1 Tiếp nhận yêu cầu của chủ thể dữ liệu | Yêu cầu của chủ thể (người dùng) | Yêu cầu mới (D14) | Loại yêu cầu: xem, chỉnh sửa, cung cấp, xóa dữ liệu; rút đồng ý, hạn chế, phản đối xử lý. Ghi thời điểm nhận để tính hạn ở 8.2 |
| 8.2 Theo dõi hạn xử lý yêu cầu | Yêu cầu đang mở (D14); kết quả xử lý (TN06) | Yêu cầu, hạn xử lý (TN06); kết quả xử lý (D14); kết quả xử lý yêu cầu (người dùng); thư thông báo kết quả (TN13) | Phản hồi người yêu cầu trong 02 ngày làm việc. Thực hiện xong trong 10 ngày với yêu cầu xem, chỉnh sửa, cung cấp; 15 ngày với rút đồng ý, hạn chế, phản đối; 20 ngày với yêu cầu xóa. Khi cần bên xử lý khác thực hiện thì áp dụng thời hạn dài hơn theo cùng điều. Gia hạn tối đa một lần và phải báo lý do cho người yêu cầu (Nghị định Điều 5 khoản 2, 3, 4) |
| 8.3 Quản lý danh mục bên nhận dữ liệu | Danh mục bên nhận (TN06); thông tin dịch vụ ngoài (TN05) | Danh mục bên nhận (D15); thông tin công khai (TN01) | Mỗi bên nhận ghi tên, quốc gia, dữ liệu nhận, mục đích, cam kết lưu giữ. Trang công khai và thông báo xử lý ở 7.3 đọc cùng một danh mục. Thêm hoặc đổi bên nhận thì hồ sơ ở 8.4 phải được cập nhật |
| 8.4 Lập hồ sơ đánh giá tác động | Nội dung hồ sơ (TN06); danh mục bên nhận (D15); hồ sơ đã lập (D16); yêu cầu hoàn thiện hồ sơ (TN15) | Hồ sơ (D16); hồ sơ đánh giá tác động (TN15) | Lập hai hồ sơ: đánh giá tác động xử lý dữ liệu (Luật Điều 21) và đánh giá tác động chuyển dữ liệu ra nước ngoài, vì TN10, TN14 ở nước ngoài (Luật Điều 20). Gửi bản chính trong 60 ngày kể từ ngày đầu tiên xử lý hoặc chuyển dữ liệu. Cập nhật định kỳ 06 tháng khi có thay đổi, và cập nhật ngay trong các trường hợp ở Luật Điều 22 khoản 2. Hoàn thiện hồ sơ khi TN15 yêu cầu |
| 8.5 Xử lý, thông báo sự cố | Thông tin sự cố (TN05); biên bản sự cố (TN06) | Biên bản sự cố (D16); thông báo vi phạm (TN15); thư thông báo sự cố (TN13) | Lập biên bản xác nhận vi phạm. Thông báo cho TN15 chậm nhất 72 giờ kể từ khi phát hiện (Luật Điều 23). Gửi thư thông báo cho người dùng bị ảnh hưởng |
| 8.6 Rà soát nhật ký truy cập | Nhật ký gửi ra ngoài (D12); nhật ký truy cập hỗ trợ (D13); bằng chứng đồng ý (D10) | Nhật ký, bằng chứng đồng ý (TN06) | Đối chiếu mỗi lần gửi ra ngoài với một đồng ý còn hiệu lực tại thời điểm gửi. Đối chiếu mỗi lần quản trị viên truy cập với một quyền hỗ trợ còn hạn. Chỉ đọc dữ liệu quản lý, không đọc số đo của từng nhà |
