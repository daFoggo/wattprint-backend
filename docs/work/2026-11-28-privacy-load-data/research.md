# Research: bảo vệ dữ liệu nếp sinh hoạt (2026-11-28)

Đi cùng `audit.md` (vấn đề trong code) và `legal.md` (Luật 91/2025, NĐ 356/2025).

## 1. Đề bài nói gì

Vấn đề: mức dùng điện theo giờ để lộ nếp sinh hoạt (giờ dậy, giờ vắng nhà, những ngày đi xa).

| Việc | Nghĩa là | Hiện WattPrint |
|---|---|---|
| Giảm độ chi tiết phải lưu/chia sẻ | Không giữ, không gửi dữ liệu mịn hơn và lâu hơn mức cần | Chưa: dữ liệu theo giờ giữ mãi; Wappi gửi được số theo phút (B1, D2) |
| Giới hạn quyền truy cập | Mỗi người chỉ thấy phần được phép | Một phần: các nhà tách biệt; viewer xem chi tiết như chủ nhà (A3) |
| Cho phép xóa lịch sử | Tự xóa dữ liệu điện mà vẫn giữ tài khoản | Chưa: chỉ xóa được cả tài khoản (C1) |
| Nêu rõ khi gọi dịch vụ ngoài | Lúc dữ liệu sắp rời hệ thống thì báo gửi gì, cho ai | Một phần: có trang chính sách, lúc dùng không báo, Telegram không được nhắc (D1, D5) |

Minh chứng: sơ đồ luồng dữ liệu, màn hình quyền riêng tư (thao tác được, không chỉ trang chữ), kết quả
thử phân quyền theo từng vai trò. Cả ba chưa có (F1–F3).

## 2. Bằng chứng nghiên cứu

| Paper | Phát hiện | Dùng được cho |
|---|---|---|
| [LoaDiff, 2609.11639](https://arxiv.org/abs/2609.11639) (Petralia đồng tác giả) | Đường phụ tải là dữ liệu cá nhân, có thể lộ lịch có người ở nhà, giờ làm, kỳ nghỉ (chỉ trích dẫn, không tự thử). Giải pháp: dữ liệu giả lập thay dữ liệu thật khi chia sẻ; tự nhận đo riêng tư bằng khoảng cách, không phải bảo đảm hình thức | Dẫn chứng cho vấn đề; không phải giải pháp cho WattPrint (không công bố dữ liệu nhiều nhà) |
| [Shieldstral, 2607.25857](https://arxiv.org/abs/2607.25857) | Bộ lọc nội dung, không liên quan | — |
| [Phát hiện thiết bị, 2305.10352](https://arxiv.org/abs/2305.10352) (Petralia) | Từ 1 phút xuống 30 phút, điểm phát hiện thiết bị giảm khoảng 0,1–0,15; ở 30 phút chỉ nhận tốt thiết bị chạy lâu | Hạ độ chi tiết che được thiết bị nhỏ (ấm, lò vi sóng) |
| [2606.03358](https://arxiv.org/html/2606.03358) (1.208 hộ, Áo) | Đoán đặc điểm hộ ở 1 giờ gần ngang 15 phút (MCC 0,57 → 0,54 với "nhà gia đình"); diện tích nhà đoán được cả từ dữ liệu thô | Hạ xuống theo giờ không đủ che đặc điểm hộ |
| [2308.14114](https://arxiv.org/abs/2308.14114) (5 hộ, ECO) | Đoán có người ở nhà từ dữ liệu theo giờ đúng 91,7%, ROC AUC 0,93; tỉ lệ có người sẵn khoảng 80% | Dữ liệu theo giờ vẫn lộ lúc vắng nhà |

Các paper khác của Petralia (NILMFormer, CamAL, DeviceScope, TransApp…) đều về NILM hoặc chuỗi thời gian,
không đo riêng tư.

## 3. Bốn việc có giải quyết được vấn đề không

Chưa hết: nếp sinh hoạt lặp lại hằng ngày, vài tuần dữ liệu theo giờ là đủ đoán, mà ứng dụng vẫn phải
lưu và hiển thị đúng loại dữ liệu đó. Bốn việc là giảm thiểu và minh bạch.

| Việc | Chặn được | Không chặn được |
|---|---|---|
| Giảm độ chi tiết | Chi tiết từng thiết bị khi dữ liệu cũ hoặc gửi đi | Theo giờ vẫn đủ đoán (mục 2); tổng theo ngày vẫn lộ ngày đi vắng |
| Giới hạn quyền | Người trong app chỉ thấy phần được phép | Máy chủ và ai chiếm được máy chủ, tài khoản |
| Xóa lịch sử | Dữ liệu cũ (kỳ nghỉ, thói quen nhiều tháng) | Vài tuần gần nhất; đa số không tự bấm xóa |
| Báo dịch vụ ngoài | Người dùng biết để tự chọn | Tự nó không giảm dữ liệu gửi đi |

Rủi ro đề không nhắc:
- **Dữ liệu trực tiếp:** mức tiêu thụ đang thấp gần như nói "nhà đang trống". Viewer đang xem được.
- **An ninh máy chủ:** text2sql không khóa (A1, A2).
- **Bên nhận giữ lại bao lâu:** báo người dùng không làm OpenRouter, Telegram lưu ít đi.

## 4. Các hướng khác từ nghiên cứu

| Nhóm | Cách | Hợp với WattPrint |
|---|---|---|
| Che tại nhà | Pin che tải: nạp/xả để làm phẳng đường tiêu thụ ([tổng quan](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-stg.2020.0129)) | Không: cần phần cứng, phá việc nhận diện thiết bị |
| Che tại nhà | NILM chạy trong nhà, chỉ gửi kết quả tổng hợp ([Pi + công tơ](https://mobile.aau.at/publications/winkler-2023-Energy_Disaggregation_with_NILM_on_a_Raspberry_Pi_with_Smart-Metering_Extension.pdf), [2505.04367](https://arxiv.org/pdf/2505.04367)) | Mạnh nhất nhưng đổi kiến trúc; hợp làm hướng phát triển |
| Che tại nhà | Học liên kết ([FederatedNILM](https://arxiv.org/pdf/2108.03591), [FedNILM](https://arxiv.org/pdf/2106.07751)) | Ít giá trị: NILM học trên dữ liệu công khai; chỉ mô hình expect học trên dữ liệu người dùng |
| Khi chia sẻ | Differential privacy ([tổng quan](https://dl.acm.org/doi/pdf/10.1145/3412841.3442360)) | Chỉ khi công bố số liệu nhiều nhà; chủ nhà không thể xem số đã làm nhiễu của nhà mình |
| Khi chia sẻ | Nhiễu chống đoán có người ([2010.12640](https://arxiv.org/pdf/2010.12640)) | Có thể cho dữ liệu gửi ra ngoài; mới ở mức nghiên cứu |
| Khi chia sẻ | Gộp nhóm, k-ẩn danh ([2002.04863](https://arxiv.org/pdf/2002.04863)) | Đã có một phần: so sánh với nhà tương tự đòi tối thiểu 10 nhà thật |
| Khi chia sẻ | Mã hóa đồng hình ([tổng quan](https://www.researchgate.net/publication/361500293_Privacy_protection_in_smart_meters_using_homomorphic_encryption_An_overview)) | Quá nặng cho nhu cầu hiện tại |
| Thông thường | Dữ liệu trực tiếp chỉ cho chủ nhà, hoặc trễ/làm thô cho người khác | Chặn người cần biết "nhà đang trống" |
| Thông thường | Mã hóa khi lưu, tách danh tính khỏi số đo | NĐ 356 Điều 12 yêu cầu mã hóa khi lưu và truyền |
| Thông thường | Đóng lỗ text2sql, xác thực hai lớp | Rẻ nhất, tác dụng lớn nhất |
| Thông thường | Nhật ký truy cập cho người dùng xem | Người dùng thấy ai đã xem dữ liệu nhà mình |
| Thông thường | Công cụ của Wappi trả bản tóm tắt thay dữ liệu thô | Giảm phần gửi cho nhà cung cấp mô hình |
| Thông thường | OpenRouter `zdr`, `data_collection: deny` | Một tham số |
| Thông thường | Mô hình AI tự host | Hết chuyển ra nước ngoài; đổi lại chi phí và chất lượng |
| Thông thường | Bỏ gửi Telegram, hoặc chỉ gửi mã tin nhắn | Người bảo trì mở trong admin để đọc |

## 5. Chưa kiểm

- Số liệu paper đọc qua công cụ đọc web (HTML); chưa đối chiếu PDF. Mục 4 chỉ từ tóm tắt tìm kiếm, chưa
  mở toàn văn. Chưa có paper so sánh chi phí và hiệu quả các cách trên cùng dữ liệu.
- Dataset nhỏ: 5 hộ (2308.14114), 1.208 hộ (2606.03358).
- Viewer xem dữ liệu trực tiếp: suy từ code, chưa thử bằng tài khoản thật.

Nguồn khác: [tổng quan có hệ thống](https://engrxiv.org/preprint/download/8557/13871/12093),
[DP cho lưới điện, 1812.02282](https://arxiv.org/pdf/1812.02282),
[dự báo có DP, 1807.02361](https://ar5iv.labs.arxiv.org/html/1807.02361),
[AMI theo luật CPUC, 2505.08237](https://arxiv.org/pdf/2505.08237).
