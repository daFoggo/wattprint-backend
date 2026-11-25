# Sense: tìm ra thiết bị mới và học từ cộng đồng, WattPrint làm được gì

Ngày 2026-11-25. Đây là nghiên cứu, chưa phải quyết định hay thiết kế. Nguồn của Sense là tài liệu của chính
họ (tiếp thị/hỗ trợ), nên coi là tuyên bố của công ty. Các trang help.sense.com trả 403 cho công cụ đọc
tự động, mình không vượt chặn; phần đó lấy từ trích dẫn của công cụ tìm kiếm và từ ghi chú sẵn trong
`read-only/wattprint-document/_archive/sense-va-nilm-tan-so-cao.md`.

## 1. Sense phát hiện thiết bị mới thế nào

Đã có nguồn:

- **Học không nhãn, lặp lại mới tin.** Sense cần thấy thiết bị "bật/tắt nhiều lần, ổn định" trong ngữ cảnh
  dùng quen thuộc rồi mới tách thành một thiết bị riêng. Không có "chân lý nền" (blog *How Sense Learns*).
- **Điều kiện tín hiệu** (bài của một người dùng lâu năm, blog *What to expect*): chuyển trạng thái nhanh
  (trong khoảng nửa giây), có cặp bật-tắt khớp nhau, đủ khác các thiết bị khác trong nhà nhưng lặp lại giống
  nhau. Nhiễu mỗi nhà khác nhau nên cùng một máy có nhà nhận ra, nhà không. Hai máy giống hệt nhau (hai cửa
  gara) hay bị gộp làm một; một máy nhiều pha (bếp, tủ lạnh) hay bị tách làm nhiều, người dùng phải gộp tay.
- **Ngữ cảnh thời gian.** Dùng thói quen giờ giấc ("máy sấy hay chạy sau máy giặt") để chắc hơn.
- **Thiết bị đầu tiên là loại chạy nhiều, công suất lớn, chạy đều** (tủ lạnh, điều hòa); thường vài ngày đến
  vài tuần mới thấy kha khá (trích dẫn diễn đàn qua tìm kiếm, chưa tự đọc bản gốc).
- **Từ chung chung đến cụ thể:** hiện trước là "thiết bị chưa rõ", sau đó mới đoán loại, rồi mới hỏi người
  dùng xác nhận và đặt tên. Nếu sau đó thấy sai thì tự gỡ.
- **Phần còn lại luôn được tính.** "Luôn bật" (mức thấp nhất 48 giờ gần nhất) và "Khác" (phần chưa gán).
- **Thiết bị đã theo dõi bằng ổ cắm thông minh hoặc mạch riêng thì bị loại khỏi vòng học** (có nhãn thật rồi).
- Bằng sáng chế US9443195 mô tả hai đường: model-first (chấm điểm sự kiện lạ với các mô hình có sẵn, hiện
  thông tin một phần rồi hỏi) và user-first (người dùng nói "máy rửa bát", hệ thống lấy mô hình ứng viên).
  Độ tin cậy cao tự cập nhật, thấp thì hỏi.

**Không có nguồn nào** nói rõ: số lần lặp cần thiết, ngưỡng, và điều gì xảy ra khi nhà đã ổn định rồi mua
máy mới. Câu trả lời hợp lý là suy luận (đánh dấu [Suy luận]): vì mô hình luôn chạy song song, một máy
mới tạo ra những cặp sự kiện chưa ai giải thích được, chúng rơi vào "Khác", lặp lại nhiều lần thì gom thành
cụm và được đề xuất như một thiết bị mới, cùng cơ chế với lúc mới lắp.

## 2. Học từ cộng đồng thế nào

Sense nói rõ hai điều:

1. Phát hiện tốt lên khi **có nhiều nhà dùng hơn và có mô hình mới** được phát hành.
2. Người dùng **đặt tên, nhập hãng/đời máy, "Community Names", Home Details, báo "không bật"** đều "cải thiện
   cho mọi người" và đi vào đội khoa học dữ liệu.

Sense **không nói** mô hình học ở nhà A được dùng nguyên cho nhà B hay đồng bộ ra sao. Từ bằng sáng chế
('mô hình phân cấp: lớp, hãng, phiên bản, thiết bị cụ thể trong nhà', prior theo giờ/thời tiết) và từ kiểu
làm việc thông thường, cách hợp lý nhất [Suy luận] là một **kho nhãn và mô hình gốc ở cloud do đội của họ
huấn luyện lại định kỳ**, rồi phát hành "mô hình phát hiện mới" cho tất cả các nhà; nhà người dùng chỉ
đóng góp nhãn và đoạn dữ liệu quanh sự kiện, không tải mô hình của nhau về trực tiếp. Đây đúng là hướng
"cộng đồng đóng góp, rồi lấy về dùng và tinh chỉnh cho nhà mình" mà bạn đoán, nhưng khâu trung gian là đội
của Sense huấn luyện lại, không phải từng nhà tự làm.

## 3. Cộng đồng có hiệu quả không, và vì sao bị hỏi

Bằng chứng học thuật từ các nguồn đã thấy (tự báo cáo của tác giả, chưa tự kiểm lại):

- Nhà khác nhau thì mô hình chung giảm mạnh: đã có số liệu rõ trong repo này (REFIT, trong `docs/nilm-datasets.md`),
  và trong ghi chú Sense: PLAID chia theo nhà phụ thuộc 94–98 % nhưng theo nhà độc lập chỉ 67–76 %. Nghĩa là
  "học từ nhà khác" có hiệu quả vừa phải, cần tinh chỉnh theo nhà.
- Prior theo loại thiết bị rồi tinh chỉnh bằng dữ liệu tổng của từng nhà luôn tốt hơn không tinh chỉnh (Parson).
- Vài nhãn chọn lọc đáng giá hơn nhiều dữ liệu không nhãn: nhà 4, F1 0,69 lên 0,83 chỉ với 1,7 % nhãn
  (Tanoni 2024). Hợp với việc hỏi người dùng đúng chỗ.
- Thiết bị lạ làm mô hình tĩnh sụp: độ chính xác trung vị 98,5 % xuống 26,4 % khi có thiết bị chưa biết; có
  phương pháp lọc thiết bị lạ >85 % và gom cụm >91 % (eNILM, RWTH 2026, tự báo cáo, dữ liệu FIRED/DARCK).
- Có học liên tục cho thiết bị mới (Applied Sciences 2025) và học liên kết giữa nhiều nhà
  (FedNILM arXiv 2106.07751, FederatedNILM arXiv 2108.03591). Ít bài nào làm đủ cả ba (phát hiện lạ, học
  tăng dần, nhiều nhà) cùng lúc.

Chỗ dễ bị hỏi trong phản biện: (1) nhãn người dùng nhiễu, gõ sai, hai nhà gọi cùng một tên cho hai máy
khác nhau; (2) quyền riêng tư của dữ liệu điện (lộ giờ giấc sinh hoạt); (3) chưa ai công bố số đo "cộng đồng
làm tốt hơn bao nhiêu" cho Sense; (4) lệch phân bố: mô hình học ở Mỹ không hợp thiết bị Việt (điều hòa
inverter, nồi cơm, bình nóng lạnh), nên một cộng đồng Việt Nam mới có giá trị.

## 4. Áp vào WattPrint (đề xuất, chờ bạn chọn)

Hiện trạng: mỗi nhà demo có một mô hình riêng, tải chưa gán rơi vào "Khác", chưa có luồng "phát hiện máy
mới" hay nhãn của người dùng. Gợi ý theo thứ tự rẻ đến đắt, đều chỉ dùng số đã suy luận từ NILM:

1. **Phát hiện máy mới (rẻ, làm được trước).** Trên phần "Khác" của từng nhà, tìm các đợt công suất lặp lại
   (bước lên/xuống, thời lượng, giờ), gom cụm; đủ N lần và đủ ổn định thì hiện thẻ "Có thể có thiết bị mới,
   chạy khoảng 3 lần mỗi tuần, ~1,8 kW". Người dùng xác nhận hoặc đặt tên. Nhà đã ổn định rồi lắp thêm máy:
   cùng đường này, vì "Khác" tăng đột ngột ở một cụm mới là tín hiệu.
2. **Nhãn người dùng làm dữ liệu huấn luyện.** Lưu nhãn cùng đoạn cửa sổ NILM đã suy luận (không lấy từ số
   đo thô, đúng ràng buộc của bạn), dùng để tinh chỉnh mô hình nhà đó (đã có `train_house.py`).
3. **Cộng đồng (đắt, để sau).** Chỉ khi đủ nhà: gộp nhãn ẩn danh theo loại thiết bị, huấn luyện lại mô hình
   gốc theo loại, rồi mỗi nhà tinh chỉnh. Cần đồng ý chia sẻ rõ ràng, và đủ nhà Việt Nam mới có ý nghĩa; hiện
   chỉ có 4 nhà demo nên chưa chứng minh được gì.

Việc đo được ngay trong repo: thử với REFIT/Plegma/ENERTALK, giấu một thiết bị khỏi mô hình rồi xem phần
"Khác" có gom thành cụm đúng thiết bị đó không (thước đo: cụm có khớp thiết bị bị giấu, bao nhiêu lần lặp thì
nhận ra). Đây là phép thử trung thực cho câu "nhận ra máy mới thế nào".
