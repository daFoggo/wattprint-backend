# Thiết kế nghiên cứu: đánh giá theo từng hộ

## Mục tiêu và đơn vị đánh giá

Đánh giá NILMFormer và TwoStageNILMFormer trên từng hộ và từng thiết bị. Mỗi mô
hình là ensemble 5 seed khởi tạo. Đơn vị kết quả là
`model × protocol × hộ train × hộ test × device`.
Notebook triển khai: `data/scripts/Preprocess_REFIT_NILMFormer.ipynb`.

## Hai nhánh thực nghiệm

| Nhánh (`protocol`) | Dữ liệu train | Dữ liệu đánh giá |
| --- | --- | --- |
| Mô hình chung (`pooled`) | Phần train của một nửa số hộ nghiên cứu | Phần test của mọi hộ nghiên cứu; nửa còn lại là hộ chưa thấy |
| Mỗi hộ một mô hình, test chéo hộ (`cross_house`) | Chỉ phần train của hộ h | Phần test của mọi hộ nghiên cứu, gồm hộ h và các hộ chưa thấy |

Nhánh `cross_house` thay cho nhánh mỗi hộ chỉ test trên chính hộ đó. Pipeline
triển khai thực tế train một mô hình bằng dữ liệu riêng của từng nhà, nên mô hình
không học từ các nhà khác; validation để early stopping cũng chỉ lấy từ hộ h.
Mỗi mô hình được test trên cùng 20% cuối của mọi hộ: ô hộ h là đối chứng hộ đã
thấy, các ô còn lại đo hộ mới. Kết quả tạo ma trận chuyển giao hộ train × hộ test;
cột `unseen_house` đánh dấu hộ test không có trong train.

Nhánh `pooled` chia hộ bằng hoán vị cố định theo seed gốc 42: nửa đầu, làm tròn
lên, dùng để train; với bảy hộ nghiên cứu là **train 6, 9, 11, 20** và **hộ chưa
thấy 2, 3, 13**. Danh sách lưu trong `pooled_train_houses` của study.json. Hai
nhánh dùng cùng tập test, nên trên các hộ 2, 3, 13 có thể so trực tiếp mô hình
chung bốn hộ với mô hình một hộ, đều chưa thấy hộ test. Chỉ một cách chia nên
kết quả hộ mới của `pooled` dựa trên ba hộ, cần diễn giải thận trọng.

Mô hình riêng được khởi tạo mới, không lấy trọng số mô hình chung. Nếu khởi tạo
từ mô hình chung, đó là nhánh fine-tuning cần tách thành thí nghiệm khác.

## Chia theo thời gian

- Mỗi hộ được xét độc lập theo thứ tự timestamp. Lấy khoảng thời gian lịch từ
  đầu phút chứa mẫu đầu đến hết phút chứa mẫu cuối, chọn mốc 80% và làm tròn lên phút.
- 80% đầu thuộc train, 20% cuối thuộc test. Tỷ lệ này áp dụng trước lọc dữ liệu;
  số cửa sổ hợp lệ không bắt buộc có tỷ lệ đúng 80/20.
- Tách dữ liệu trước forward-fill, resample và cắt cửa sổ. Không điền qua ranh giới,
  không có cửa sổ chồng lấn train/test và không ghép hai đoạn cách nhau bởi khoảng mất dữ liệu.
- CSV tiền xử lý giữ nguyên 80/20. Runner TwoStage tách 20% thời gian cuối của
  phần train gốc làm validation để early stopping; xấp xỉ 64% train, 16% validation,
  20% test theo thời gian toàn kỳ. Loại cửa sổ cắt ngang mốc train/validation.
- Chọn checkpoint theo validation loss, khôi phục trọng số tốt nhất trước khi
  đánh giá test; không dùng test chọn epoch hoặc siêu tham số.
- Không truyền test_loader vào tham số val_loader của các hàm train.
- Mặc định tối đa 150 epoch, patience 10 và min_delta=0; có thể cấu hình qua CLI.

Nhánh `pooled` và ô hộ h của `cross_house` đo khả năng dự đoán ở thời gian tương
lai của hộ đã có dữ liệu train. Các ô hộ chưa thấy của `cross_house` đo hộ mới;
phần test của hộ chưa thấy vẫn là 20% cuối để mọi nhánh dùng cùng tập test.

## Các hộ và nhãn thiết bị

Pipeline mới xét toàn bộ 20 CSV hộ REFIT trong repo, giữ thứ tự đích máy giặt,
máy rửa bát, ấm đun nước và lò vi sóng. Không lọc theo danh sách hộ thực nghiệm
từng thiết bị của tác giả. Ánh xạ mặc định dùng bảng kênh NILMFormer và lưu cạnh
mô tả trong README REFIT để kiểm tra chênh lệch.

Phạm vi thiết bị đã chốt cố định đúng bốn loại trên, theo thứ tự
`WashingMachine`, `Dishwasher`, `Kettle`, `Microwave`; cả hai mô hình dùng
`c_out=4`. Notebook kiểm tra thứ tự này bằng assert. Giữ ngưỡng tạo nhãn và các
bước xử lý tín hiệu theo cấu hình đã đối chiếu với mã nghiên cứu; chia thời gian
80/20 và hai nhánh train vẫn theo thiết kế dự án đã chốt.

Runner chỉ dùng **bảy hộ nghiên cứu 2, 3, 6, 9, 11, 13, 20**: các hộ có nhãn đủ
bốn thiết bị đích theo `channel_availability.csv`. Hộ 15 cũng đủ bốn kênh nhưng
bị loại vì kênh Kettle có thể là Hi-Fi theo mô tả nguồn. Runner kiểm tra bằng
assert rằng mỗi hộ được chọn có nhãn train hợp lệ cho cả bốn thiết bị. Notebook
tiền xử lý vẫn xuất đủ 20 hộ; có thể chọn hộ khác bằng `--houses`.

Bản cũ còn sáu hộ vì yêu cầu đồng thời: đủ bốn nhãn khớp tên và thuộc giao danh
sách thực nghiệm của bốn thiết bị. Đây là lựa chọn phục vụ đối chứng nhiều đầu
ra đầy đủ nhãn, không có nghĩa các hộ khác không có dữ liệu hoặc không train được.
Ví dụ hộ 20 bị loại khỏi giao cũ vì không nằm trong danh sách máy giặt của cấu
hình tác giả, dù bảng kênh có máy giặt. Hộ 1 không có nhãn ấm/lò vi sóng nhưng
vẫn có thể đóng góp nhãn máy giặt và máy rửa bát.

- Kênh chưa ánh xạ được có valid=False; giá trị 0 lưu trong tensor chỉ là giá trị
  thay thế và không được coi là nhãn tắt trong loss hoặc metrics.
- Giữ cửa sổ có điện tổng và các kênh đã ánh xạ hợp lệ. Kênh chưa ánh xạ không
  làm mất cửa sổ của các thiết bị khác.
- Thiết bị có hậu tố hoặc thiết bị kết hợp không tự được gộp thành một loại;
  inventory phải phản ánh các nhãn chưa ánh xạ. Điều này khác với kết luận thiết bị không tồn tại.
- Nhánh mỗi hộ không đánh giá các đầu ra không có nhãn train/test của hộ đó.
- Chênh lệch ánh xạ nguồn, chẳng hạn Kettle/Hi-Fi tại hộ 15, vẫn được ghi nhận;
  chưa coi các kênh này là nhãn đã xác minh độc lập.

## Seed và so sánh

Giữ seed dữ liệu 42 và cùng mốc chia giữa hai nhánh, hai kiến trúc và 5 seed
khởi tạo. Với 7 hộ, mỗi kiến trúc có `(1 + 7) × 5 = 40` lượt train dự kiến;
hai kiến trúc có tổng 80 lượt. Mỗi mô hình `cross_house` được test trên 7 hộ.
So sánh hộ mới nên ghép cặp theo hộ test, vì độ phân tán giữa các hộ thường lớn
hơn giữa các seed. Cùng một runner chạy cả hai kiến trúc qua `--model twostage`
hoặc `--model nilmformer`, dùng chung cách chia hộ, validation, early stopping,
hàm đánh giá, ngưỡng và quy tắc chặn dự đoán âm về 0 khi test.

## Mất cân bằng nhãn bật/tắt

Runner đếm nhãn bật/tắt hợp lệ theo từng thiết bị **chỉ trên các cửa sổ train
thực tế sau tách validation**. Không dùng nhãn validation/test để tính trọng số.
Mô hình chung lấy thống kê các hộ train của nó; mô hình riêng lấy thống kê chính hộ đó.

Trọng số lớp dương BCE là `(off_count + 1) / (on_count + 1)`, chặn trong
`[0.01, 5]` mặc định để ổn định gradient; giới hạn trên có thể cấu hình. Mức 5
được chọn trên validation, so với 10, 30 và 100 (xem `docs/train_twostage.md`).
Kênh không có mẫu bật dùng trọng số 1 và báo cờ không có mẫu bật để diễn giải
kết quả. Kênh thiếu nhãn có valid=False, không đóng góp vào số đếm hoặc loss.
Các trọng số được broadcast theo kênh trước khi lọc valid để không bị sai thứ tự.
Loss hồi quy sau mask và loss phụ trên các điểm bật vẫn giữ vai trò hiện có.

Lưu class_balance.csv và cấu hình trọng số trong từng checkpoint để truy vết.

Dùng cùng mẫu dữ liệu và mask khi so sánh. Cùng số epoch không đồng nghĩa cùng
chi phí tính toán: mô hình chung thấy nhiều mẫu hơn mỗi mô hình riêng; phải báo
số mẫu, số bước cập nhật, thời gian và chi phí cho từng nhánh.

Báo MAE/RMSE, sai số điện năng và F1 theo hộ/thiết bị; luôn kèm số điểm hợp lệ,
độ phủ nhãn và số mẫu bật. Kết quả của một mô hình là **ensemble 5 seed**: lấy
trung bình cộng công suất dự đoán của 5 seed theo từng phút và thiết bị, rồi tính
metrics một lần trên dự đoán đó; F1 suy từ công suất ensemble, không lấy trung bình
F1 các seed. Mask detector của TwoStage ensemble bằng bỏ phiếu (bật khi ít nhất
một nửa số seed bật). Sau đó macro theo các cặp hộ để hộ có nhiều mẫu không chi
phối. Metrics từng seed riêng được lưu riêng để xem độ phân tán. Khi phân tích
bật đồng thời, phân tầng theo số kênh được giám sát vì các hộ có độ phủ khác nhau.

Runner phân tầng kết quả test theo hai trục, mỗi tầng tính lại đủ metrics:

- Số thiết bị đích đang bật theo nhãn tại từng phút: 0, 1, 2, 3+. Chỉ đếm kênh
  có nhãn hợp lệ; bảy hộ nghiên cứu đều giám sát đủ bốn kênh nên các tầng so được
  giữa các hộ. Thiết bị ngoài bốn loại đích không được đếm.
- Mức tải theo điện tổng, W: [0, 500), [500, 1500), [1500, 3000), [3000, ∞).
  Ngưỡng cố định, không ước lượng từ test, dùng chung cho mọi hộ và mô hình.

Bảng phân tích lỗi đếm các điểm FP/FN của mỗi thiết bị theo bối cảnh: thiết bị
đích nào khác đang bật, hoặc không có thiết bị đích khác bật. Một điểm có thể
trùng nhiều thiết bị khác nên tổng tỷ lệ các bối cảnh có thể lớn hơn 1. Phân
tầng và bảng lỗi cũng tính trên dự đoán ensemble. Đồ thị dự đoán vẽ điện tổng,
từng thiết bị và dự đoán ensemble kèm dải min–max giữa các seed cho hai cửa sổ
của mỗi hộ test: cửa sổ sai số lớn nhất và cửa sổ có nhiều thiết bị bật đồng
thời nhất.

Các bước tín hiệu, ngưỡng, TimeRPE và scaling tiếp tục dùng cấu hình ghi trong
notebook. Chia thời gian và mask kênh thiếu là điều chỉnh của nghiên cứu hiện tại,
không gọi là tái lập nguyên thiết lập chia theo hộ trong bài NILMFormer.
