# Đề xuất chốt: bảo vệ dữ liệu nếp sinh hoạt

Ngày: 2026-11-28 · Trạng thái: chủ dự án đã chốt ba quyết định và cho làm (2026-11-28) · Lane L · Mốc mã: `d0a56a1` (backend)

Tài liệu này gộp kết quả phản biện của [audit.md](audit.md), [legal.md](legal.md), [proposal1.md](proposal1.md),
[proposal2.md](proposal2.md) và phần tra cứu thêm ngày 28/11. Nó thay hai bản proposal. Yêu cầu kiểm được từng dòng
nằm ở [spec.md](spec.md); việc phải làm nằm ở [checklist.md](checklist.md).

## 1. Kết luận

- Làm được toàn bộ trên hệ thống đang chạy (một app, một database), không cần đổi kiến trúc.
- Chia bốn tầng: **vá ngay** (hai lỗ bảo mật), **đề bài** (bốn ý, ba minh chứng), **làm dày** (vượt đề, có căn cứ
  nghiên cứu), **lộ trình** (nêu hướng, chưa làm).
- Thứ tự làm đi từ rủi ro thấp, ra minh chứng sớm, tới việc không đảo ngược được (thời hạn lưu) sau cùng. Dừng ở
  cuối bất kỳ đợt nào thì sản phẩm vẫn nộp được.
- Hai việc không giải quyết bằng mã: đối chiếu điều luật với bản Công báo, và hồ sơ chuyển dữ liệu ra nước ngoài.

## 2. Những điểm đã chốt sau phản biện

| Điểm tranh luận | proposal1 | proposal2 | Chốt | Vì sao |
|---|---|---|---|---|
| Số đo thô | 14 ngày | chưa chọn | **30 ngày** | NILM chỉ cần vài ngày, 30 ngày chừa chỗ cho worker dừng lâu |
| Tổng theo phút | 35 ngày | bằng số thô | **90 ngày** | Dựng lại lượt bật/tắt đọc 65 ngày, biểu đồ cho xem tới 90 ngày |
| Tổng theo giờ | 13 tháng | 400 ngày | **400 ngày** | Dự đoán mức dùng học từ 365 ngày |
| Tổng theo ngày | đến khi xóa nhà | đến khi xóa | **800 ngày** | Hóa đơn của 25 kỳ gần nhất được dựng lại từ số theo ngày ở mỗi lượt chạy (`billing/services/history.py:15-53`); 800 ngày là 25 kỳ cộng đệm |
| Mức chi tiết gửi AI | tối thiểu 1 giờ | 1 giờ trở lên | **mặc định theo ngày**, chủ nhà nâng lên theo giờ | Đề bài nói chính số theo giờ đã lộ lịch sinh hoạt; nghiên cứu cho thấy số theo giờ vẫn đoán được nhà có người hay không |
| Thời hạn riêng từng nhà | để sau | không nêu | **không làm** | Xóa riêng tầng phút của một nhà làm tầng giờ bị tính lại thành rỗng |
| Quản lý thành viên | có, ba mức xem | không làm | **có, hai mức xem, làm sau phần lõi** | Không có đường mời thì vai trò "thành viên" không thử được trên sản phẩm thật |
| Bằng chứng đồng ý | bảng có mã băm nội dung | bảng có phiên bản | **bảng chỉ ghi thêm, có phiên bản lời mời** | Đủ để chứng minh ai, lúc nào, đồng ý nội dung gì |
| Xóa theo | khoảng ngày, từng thiết bị | tất cả | **trước một ngày, hoặc tất cả** | Chặn được công tơ gửi lại dữ liệu đã xóa bằng một mốc duy nhất |
| Hóa đơn khi xóa lịch sử | giữ, cho chọn | cần quyết | **xóa cùng lịch sử**, hộp xác nhận nói rõ | Hóa đơn cũ bị ghi đè về 0 hoặc bị xóa khi số theo ngày mất; muốn giữ phải sửa phần tính tiền để đóng băng kỳ đã chốt |
| Trạng thái yêu cầu xóa, lan truyền giữa service | có | không | **không làm** | Một app, xóa xong trong một giao dịch |
| Quyền hỗ trợ có thời hạn, MFA cho admin | có | không | **không làm** | Admin không có đường đọc dữ liệu nhà; bảng thử quyền giữ điều đó |
| Thay tên thiết bị bằng bí danh | có | không | **không làm** | Chưa có chức năng tự đặt tên thiết bị |
| Xuất dữ liệu | làm ngay | để sau | **lộ trình** | Đề không nêu; trước mắt xử lý qua email |
| Mô hình AI | ưu tiên trong nước | giữ nước ngoài | **giữ nước ngoài**, kèm đồng ý và chế độ không lưu | Chưa có lựa chọn trong nước đã kiểm chứng |

## 3. Nguyên tắc

1. Chi tiết chỉ cho chính nhà đó và chỉ giữ ngắn; mọi bên khác và mọi thứ giữ lâu chỉ có số đã gộp.
2. Cái gì ra khỏi máy chủ đều phải được bật trước, được báo tại chỗ và để lại một dòng nhật ký.
3. Phạm vi nhà lấy từ tài khoản đã đăng nhập, không lấy từ đường dẫn hay từ lời của mô hình.
4. Xóa là xóa thật; phần không xóa được thì nói rõ.
5. Mỗi điều nói trên giao diện và trang chính sách đều có test hoặc đường dẫn mã đứng sau.

## 4. Phạm vi theo tầng

### Tầng 0. Vá ngay

- text2sql đang chạy không cần khóa; router quản lý kết nối cho đổi địa chỉ database (audit A1, A2).
- Chín router khác của text2sql (kết nối, từ điển dữ liệu, hội thoại…) không có xác thực; khóa dịch vụ chỉ gắn vào
  router chat và bị bỏ qua khi để trống (`router_chat.py:20-28`, `backend/main.py:62-72`).
- Chưa biết kết nối text2sql đăng nhập bằng vai nào (audit mục H).
- Vai `wattprint_ai` còn quyền đọc các view `ai.*` không lọc theo nhà. Không mã nào đang dùng vai này, nên thu quyền.

### Tầng 1. Đề bài

| Ý của đề | Làm gì | Con số, hành vi chốt |
|---|---|---|
| Giảm chi tiết **lưu** | Thời hạn theo bậc; biểu đồ tự lùi về mức thô hơn khi mức mịn đã hết hạn | Thô 30 ngày · phút và lượt bật/tắt 90 ngày · giờ 400 ngày · ngày 800 ngày · hóa đơn 25 kỳ gần nhất |
| Giảm chi tiết **chia sẻ** | AI không còn đọc số theo phút, giờ bật/tắt, tên nhà, mã bưu chính, số người. Mức mặc định theo ngày | Ở mức theo ngày: hỏi tự do chỉ đọc view ngày; công cụ "mức điện ban đêm" không chạy; cảnh báo chỉ đưa ngày |
| Giới hạn quyền | Mời người thân kèm mức xem; việc nhạy cảm chỉ chủ nhà làm; bảng thử quyền bảy chủ thể | Người được mời mặc định chỉ xem theo ngày; khách demo xem đầy đủ |
| Xóa lịch sử | Xóa lịch sử điện trước một ngày hoặc tất cả; xóa mọi trò chuyện; xóa tài khoản dọn nốt phần còn sót | Chỉ chủ nhà xóa lịch sử điện; nhà demo từ chối |
| Nêu rõ dịch vụ ngoài | Đồng ý theo từng mục đích, mặc định tắt; dòng báo cố định trong chat; mục "Đã gửi ra ngoài" ở mỗi câu trả lời; nhật ký 30 ngày | Ba mục đích: Wappi, giọng nói, email. Chưa đồng ý thì backend chặn, không có lời gọi nào ra ngoài |
| Minh chứng | Bộ sơ đồ phân tích: danh sách tác nhân, BFD phân rã chức năng, ma trận tác nhân × chức năng, ma trận tác nhân × quyền truy cập dữ liệu, DFD mức ngữ cảnh, mức 0 và mức 1 có ranh giới ra ngoài; trang Quyền riêng tư; bảng thử quyền trước và sau | Bảng in từ lần chạy test thật, không gõ tay |

### Tầng 2. Làm dày (vượt đề)

| Việc | Căn cứ | Sản phẩm |
|---|---|---|
| Bộ câu hỏi tấn công Wappi: dụ đọc nhà khác, dụ lấy số theo phút, dụ vượt mức xem | OWASP Top 10 cho ứng dụng LLM: prompt injection, lộ thông tin nhạy cảm, quyền quá rộng | Thêm kịch bản vào bộ eval Wappi đã có; kết quả vào hồ sơ minh chứng |
| Đo rủi ro theo mức chi tiết trên REFIT: ở mức phút, giờ, ngày đoán được giờ dậy, giờ ngủ, ngày vắng nhà tới đâu | Chưa tìm thấy nghiên cứu nào so trực tiếp ba mức; có nghiên cứu cho từng mức riêng lẻ | Một script và một biểu đồ, là lý do định lượng cho các con số ở Tầng 1 |
| Bảng mối đe dọa theo từng mũi tên của sơ đồ luồng dữ liệu | LINDDUN (phương pháp mô hình hóa đe dọa riêng tư dựa trên sơ đồ luồng dữ liệu) | Một bảng trong hồ sơ minh chứng |
| Yêu cầu nhà cung cấp không lưu dữ liệu ở từng lời gọi | OpenRouter có `provider.zdr` và `provider.data_collection: "deny"`; không có nhà cung cấp đạt thì lời gọi lỗi | Tham số trong lời gọi, có đường lùi khi lỗi, ghi vào nhật ký |
| Email cảnh báo không mang giờ giấc | Email hiện đang ghi "Lần chạy bắt đầu lúc HH:MM", "Thiết bị bắt đầu chạy lúc N giờ" (`insight/services/mail.py:76-80,117-119`) | Nội dung chung, chi tiết xem trong app |
| Rà log: không ghi câu hỏi, số đo, email | Luật yêu cầu chỉ xử lý trong phạm vi cần thiết | Test quét mã nguồn |
| Quy trình xử lý sự cố 72 giờ, bản nháp đầu vào cho hồ sơ đánh giá tác động | legal.md: báo sự cố trong 72 giờ, hồ sơ trong 60 ngày | Hai trang tài liệu; không phải việc nộp hồ sơ |

### Tầng 3. Lộ trình (nêu trong hồ sơ, chưa làm)

- Xuất dữ liệu của mình.
- Chế độ "Riêng tư cao" theo từng nhà, sau khi đo được chi phí xóa theo nhà trên bảng đã nén.
- Mô hình ngôn ngữ đặt trong nước hoặc tự chạy cho nhà chọn không gửi ra ngoài.
- Tách thiết bị ngay tại thiết bị đo; huấn luyện liên kết kèm nhiễu vi phân (các nghiên cứu DP2-NILM, Fed-NILM).
- Nhận diện tên và địa chỉ trong câu hỏi (nợ #14).

## 5. Thiết kế chốt theo đợt

Mỗi đợt là một thay đổi riêng đi hết quy trình sdlc. Chi tiết việc ở checklist.

| Đợt | Nội dung | Thay đổi chính |
|---|---|---|
| Đ0 | Vá text2sql và vai database | Bắt buộc khóa dịch vụ trên mọi router; xác nhận vai đăng nhập; thu hoặc lọc quyền của `wattprint_ai` |
| Đ1 | Bảng thử quyền, bản "trước" | Một file test tham số theo chủ thể × route; lệnh in bảng Markdown |
| Đ2 | Giảm chi tiết gửi AI | Migration bỏ view phút và cột định danh khỏi `copilot_ro`; cột `ai_detail` trên nhà; `detail` trên scope token; che dữ liệu ở một chỗ trước mọi lời gọi (hiện bước kiểm duyệt nhận câu hỏi chưa che, `guard.py:43-50`; bước tìm tài liệu cũng gửi câu hỏi đi); tham số không lưu dữ liệu ở cả backend lẫn text2sql (text2sql tự gọi OpenRouter) |
| Đ3 | Đồng ý, cửa ra chung, nhật ký | Bảng `tb_consent`, `tb_outbound_log`; một hàm gọi ra ngoài; hộp đồng ý lần đầu; dòng báo trong chat; nút 👎 mặc định không gửi nội dung; email mặc định tắt |
| Đ4 | Xóa lịch sử | `erase.py` nhận mốc `before`; route xóa lịch sử điện và xóa mọi trò chuyện; mốc chặn công tơ gửi lại; dọn nốt khi xóa tài khoản |
| Đ5 | Thành viên và mức xem | Route mời, danh sách, đổi mức, gỡ, rời; cột `detail` trên thành viên; chặn route mịn hơn một ngày với người "chỉ theo ngày" |
| Đ6 | Trang Quyền riêng tư | `/dashboard/settings/privacy`, năm khối: đang giữ gì · ai xem được · gửi ra ngoài · xóa · AI dùng dữ liệu thế nào |
| Đ7 | Thời hạn lưu theo bậc | Migration thời hạn; biểu đồ lùi mức; việc dọn hằng đêm; báo khi NILM chậm quá 20 ngày |
| Đ8 | Minh chứng và tài liệu | Sơ đồ mới có file nguồn (`data-flow.svg` hiện không có dịch vụ ngoài, không có thời hạn, không có file nguồn), ảnh chụp, bảng thử quyền "sau", trang chính sách, README, bản nộp, chạy lại eval |
| Đ9 | Làm dày | Các việc ở Tầng 2 |

Lời mời đồng ý cho Wappi (bản nháp, sửa câu chữ ở file JSON trước khi viết giao diện):

> Wappi trả lời bằng mô hình AI của OpenRouter (đặt ở nước ngoài), dự phòng bằng AstralX. Khi bạn hỏi, câu hỏi (đã
> che số điện thoại, căn cước, email, số thẻ) và số điện theo ngày của nhà bạn được gửi tới đó. Đây là dữ liệu về
> nếp sinh hoạt, thuộc loại nhạy cảm. WattPrint không gửi tên, địa chỉ hay giờ bật tắt thiết bị. Người chịu trách
> nhiệm dữ liệu: ghi ở trang Chính sách. Bạn tắt được bất cứ lúc nào ở Cài đặt › Quyền riêng tư; phần đã gửi trước
> khi tắt thì không lấy lại được.
> [Đồng ý và dùng Wappi] [Không, cảm ơn]

## 6. Tra cứu thêm ngày 28/11 đem lại gì

| Nguồn | Điều rút ra | Dùng vào đâu |
|---|---|---|
| Khung truy cập dữ liệu công tơ thông minh của Anh | Chia ba mức: theo tháng dùng không cần đồng ý, theo ngày cho từ chối, theo nửa giờ phải đồng ý rõ ràng | Mẫu cho "mức xem theo đối tượng": người thân và AI mặc định theo ngày, mịn hơn phải có người bật |
| Nghiên cứu suy đoán nhà có người từ số công tơ | Số theo 1 giờ vẫn cho độ chính xác cao với mô hình học sâu; chưa thấy bài nào so trực tiếp phút, giờ, ngày | Lý do đặt mặc định gửi AI ở mức ngày; lý do làm phép đo ở Tầng 2 |
| Tài liệu OpenRouter về không lưu dữ liệu | Có tham số theo từng lời gọi, có thỏa thuận xử lý dữ liệu công khai; trang đang ghi "đang cập nhật" | Đ2; mục "thỏa thuận với bên nhận" trong hồ sơ |
| OWASP Top 10 cho ứng dụng LLM | Ba rủi ro khớp Wappi: prompt injection, lộ thông tin nhạy cảm, quyền quá rộng | Bộ câu hỏi tấn công ở Tầng 2; nguyên tắc quyền tối thiểu cho công cụ |
| Hướng dẫn thiết kế trang quyền riêng tư (CNIL, CDT, CMU) | Trang phải làm được mọi thao tác, rút lại dễ như đồng ý, hỏi đúng lúc cần; lựa chọn bật sẵn làm người dùng chia sẻ nhiều hơn hẳn | Đ3, Đ6: mặc định tắt, hỏi lần đầu dùng, mọi công tắc và nút xóa ở một trang |
| Chính sách của Sense | Không tìm thấy thời hạn lưu rõ ràng hay cách tự xóa trong kết quả tra cứu | Điểm khác biệt để nêu trong hồ sơ, viết thận trọng: "chúng tôi không tìm thấy", không phải "họ không có" |
| Trang của cuộc thi | Nộp URL sản phẩm và URL minh chứng; sản phẩm phải chạy ổn định ít nhất 48 giờ trước chấm; bắt buộc nhật ký câu lệnh; bảng B, C thêm minh chứng kiểm thử; không thấy thang điểm công khai | Không áp thay đổi không đảo ngược được sát giờ chấm; hồ sơ minh chứng làm thành một trang có đường dẫn; giữ nhật ký câu lệnh của đợt này |
| Trang giới thiệu Astral-X | Trụ sở ở Hà Nội; không nói máy chủ API đặt ở đâu | Vẫn phải hỏi trực tiếp; lời báo ghi "AstralX" không kèm tên nước cho tới khi có câu trả lời |
| Luật 91/2025/QH15 và Nghị định 356/2025/NĐ-CP | Xác nhận được: ngày thông qua, hiệu lực 01/01/2026, thay Nghị định 13/2023, miễn trừ cho doanh nghiệp nhỏ không áp khi xử lý dữ liệu nhạy cảm. Chưa xác nhận được qua tra cứu: mốc 60 ngày, số điều cụ thể | Chỉ trích điều khoản sau khi đối chiếu bản Công báo |

## 7. Quyết định đang dùng làm mặc định

Chủ dự án đã chốt câu 1, 2 và 6 ngày 2026-11-28 ("1. xóa cùng 2. cho phép config 3. có làm"). Các câu còn lại là lựa
chọn của người soạn và đổi được trước khi bắt đầu đợt liên quan.

| # | Câu hỏi | Mặc định | Đợt chịu ảnh hưởng |
|---|---|---|---|
| 1 | Có làm mời người thân không | **Có (đã chốt)** | Đ5, Đ6 |
| 2 | Mức mặc định gửi AI | **Cấu hình được (đã chốt)**: một thiết lập của hệ thống, giá trị ban đầu là theo ngày; chủ nhà đổi được cho nhà mình; nhà demo đặt theo giờ vì là dữ liệu công khai | Đ2 |
| 3 | Mô hình AI | Giữ nhà cung cấp nước ngoài | Đ2, Đ3 |
| 4 | Gọi dữ liệu điện là dữ liệu nhạy cảm | Có | Đ3, Đ8 |
| 5 | Tài khoản cũ và khách demo phải đồng ý lại | Có | Đ3 |
| 6 | Hóa đơn khi xóa lịch sử | **Xóa cùng lịch sử (đã chốt)**; kỳ bị cắt ngang hiện "chưa đủ dữ liệu" | Đ4 |
| 7 | Bằng chứng đồng ý sau khi xóa tài khoản | Xóa cùng tài khoản | Đ3 |
| 8 | Tách thiết bị có cho tắt không | Không; là phần lõi của dịch vụ, lối thoát là xóa lịch sử hoặc tài khoản | Đ6, Đ8 |
| 9 | Áp thời hạn mới lên prod | Chờ yêu cầu | Đ7 |
| 10 | Ai lập hồ sơ chuyển dữ liệu ra nước ngoài | Người chịu trách nhiệm dữ liệu ghi trên trang Chính sách | ngoài mã |

## 8. Rủi ro

| Rủi ro | Giảm thế nào |
|---|---|
| Thời hạn mới xóa chi tiết cũ, không lấy lại được | Làm sau cùng; chạy thử trên bản sao; chỉ áp trên dev; test bất biến refresh |
| Mức theo ngày làm Wappi trả lời kém đi | Chạy lại eval một nhà, một lượt trước và sau; biểu đồ theo giờ vẫn vẽ cho người dùng vì không đi qua mô hình |
| Thêm bước đồng ý làm giám khảo vướng khi thử Wappi | Một lần bấm, lời mời ngắn; đây cũng là minh chứng được yêu cầu |
| Yêu cầu không lưu dữ liệu làm OpenRouter không tìm được nhà cung cấp | Thử bằng một lời gọi thật; lỗi thì lùi sang AstralX và ghi rõ giới hạn trên trang |
| Xóa lịch sử nhà A chạm số của nhà B | Test "xóa A, B không đổi", cả ở quãng cũ hơn thời hạn số thô |
| Thời hạn số theo ngày ngắn hơn 25 kỳ làm hóa đơn cũ bị ghi đè về 0 | Giữ số theo ngày 800 ngày; test: hóa đơn của kỳ thứ 25 không đổi sau khi chạy thời hạn |
| Trích sai điều luật | Chỉ trích sau khi đối chiếu Công báo; ghi rõ không phải tư vấn pháp lý |
| Sản phẩm phải ổn định 48 giờ trước chấm | Không triển khai đợt mới lên bản chấm trong 48 giờ đó |

## 9. Nguồn tra cứu thêm

- OpenRouter, Zero Data Retention: https://openrouter.ai/docs/guides/privacy/zero-data-retention ;
  thỏa thuận xử lý dữ liệu: https://openrouter.ai/data-processing-agreement
- GOV.UK, Review of the Data Access and Privacy Framework:
  https://www.gov.uk/government/publications/smart-metering-implementation-programme-review-of-the-data-access-and-privacy-framework/smart-metering-implementation-programme-review-of-the-data-access-and-privacy-framework
- Suy đoán nhà có người từ số công tơ độ phân giải thấp: https://arxiv.org/pdf/2308.14114 ;
  https://lass.cs.umass.edu/papers/pdf/buildsys13-Dchen.pdf
- NILM giữ riêng tư: DP2-NILM https://ar5iv.labs.arxiv.org/html/2207.00041 ; Fed-NILM https://arxiv.org/pdf/2105.11085v2.pdf ;
  tổng quan https://arxiv.org/pdf/2207.02009
- OWASP Top 10 cho LLM (tóm tắt): https://www.hackerone.com/ai/owasp-top-10-llms-2025
- LINDDUN: https://www.nist.gov/privacy-framework/linddun-privacy-threat-modeling-framework
- Thiết kế trang quyền riêng tư: https://design.cnil.fr/en/design-patterns/dashboard/ ;
  https://cylab.cmu.edu/news/2025/11/14-beyond-the-fine-print.html
- Sense: https://sense.com/privacy-security/
- Cuộc thi: https://ai.tainangviet.vn/lo-trinh ; https://ai.tainangviet.vn/ho-so ; https://ai.tainangviet.vn/faq
- Luật và Nghị định: https://thuvienphapluat.vn/van-ban/Quyen-dan-su/Nghi-dinh-356-2025-ND-CP-huong-dan-Luat-Bao-ve-du-lieu-ca-nhan-687428.aspx ;
  các nguồn khác ở legal.md và phụ lục B của proposal1.md
