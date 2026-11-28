# Ảnh minh chứng quyền riêng tư (28/11/2026)

Hiện trạng môi trường dev; việc chặn theo đồng ý đang **tắt** trên máy chủ; chưa triển khai lên prod.
Ảnh `man-hinh` chụp từ dashboard dev bằng tài khoản và nhà thử; một số ảnh đã cắt hoặc che.

## Tổng quan: sơ đồ luồng dữ liệu và màn hình quyền riêng tư

| Ảnh | Chứng minh điều gì |
|---|---|
| [0-man-hinh-01-quyen-rieng-tu-chu-nha](0-man-hinh-01-quyen-rieng-tu-chu-nha.png) | Trang Quyền riêng tư của chủ nhà: đang giữ gì, ai xem được, gửi gì ra ngoài, xóa. |
| [0-man-hinh-02-quyen-rieng-tu-dien-thoai](0-man-hinh-02-quyen-rieng-tu-dien-thoai.png) | Trang đó trên điện thoại. |
| [0-man-hinh-03-loi-vao-tu-cai-dat](0-man-hinh-03-loi-vao-tu-cai-dat.png) | Lối vào Quyền riêng tư ở đầu trang Cài đặt. |
| [0-so-do-01-tong-quan-luong-du-lieu](0-so-do-01-tong-quan-luong-du-lieu.png) | Sơ đồ tổng quan luồng dữ liệu (nguồn docs/diagrams/privacy-data-flow.svg). |
| [0-so-do-02-tac-nhan](0-so-do-02-tac-nhan.png) | Các tác nhân (nguồn docs/diagrams/privacy/actors.svg). |
| [0-so-do-03-chuc-nang](0-so-do-03-chuc-nang.png) | Phân rã chức năng (nguồn docs/diagrams/privacy/bfd.svg). |
| [0-so-do-04-ma-tran-chuc-nang](0-so-do-04-ma-tran-chuc-nang.png) | Ma trận chức năng (nguồn docs/diagrams/privacy/function-matrix.svg). |
| [0-so-do-05-ma-tran-chuc-nang-quan-ly](0-so-do-05-ma-tran-chuc-nang-quan-ly.png) | Ma trận chức năng quản lý (nguồn docs/diagrams/privacy/function-matrix-manage.svg). |
| [0-so-do-06-ma-tran-truy-cap](0-so-do-06-ma-tran-truy-cap.png) | Ma trận truy cập dữ liệu (nguồn docs/diagrams/privacy/data-access-matrix.svg). |
| [0-so-do-07-ma-tran-truy-cap-he-thong](0-so-do-07-ma-tran-truy-cap-he-thong.png) | Ma trận truy cập của hệ thống (nguồn docs/diagrams/privacy/data-access-matrix-system.svg). |
| [0-so-do-08-nguoi-doc](0-so-do-08-nguoi-doc.png) | Ai đọc dữ liệu (nguồn docs/diagrams/privacy/readers.svg). |
| [0-so-do-09-gui-ra-ngoai](0-so-do-09-gui-ra-ngoai.png) | Dữ liệu gửi ra ngoài (nguồn docs/diagrams/privacy/outbound.svg). |
| [0-so-do-10-ngu-canh](0-so-do-10-ngu-canh.png) | Sơ đồ ngữ cảnh (nguồn docs/diagrams/privacy/context.svg). |
| [0-so-do-11-ngu-canh-ben-ngoai](0-so-do-11-ngu-canh-ben-ngoai.png) | Ngữ cảnh với bên ngoài (nguồn docs/diagrams/privacy/context-external.svg). |
| [0-so-do-12-dfd-muc-0](0-so-do-12-dfd-muc-0.png) | DFD mức 0 (nguồn docs/diagrams/privacy/level0.svg). |
| [0-so-do-13-dfd-muc-0-canh-bao](0-so-do-13-dfd-muc-0-canh-bao.png) | DFD mức 0, phần cảnh báo và kế hoạch (nguồn docs/diagrams/privacy/level0-insight.svg). |
| [0-so-do-14-dfd-muc-0-wappi](0-so-do-14-dfd-muc-0-wappi.png) | DFD mức 0, Wappi (nguồn docs/diagrams/privacy/level0-wappi.svg). |
| [0-so-do-15-dfd-muc-1](0-so-do-15-dfd-muc-1.png) | DFD mức 1 (nguồn docs/diagrams/privacy/level1.svg). |
| [0-so-do-16-dfd-muc-1-ai](0-so-do-16-dfd-muc-1-ai.png) | DFD mức 1, AI (nguồn docs/diagrams/privacy/level1-ai.svg). |
| [0-so-do-17-dfd-muc-1-tra-loi](0-so-do-17-dfd-muc-1-tra-loi.png) | DFD mức 1, trả lời (nguồn docs/diagrams/privacy/level1-reply.svg). |
| [0-so-do-18-dfd-muc-1-quyen-rieng-tu](0-so-do-18-dfd-muc-1-quyen-rieng-tu.png) | DFD mức 1, quyền riêng tư (nguồn docs/diagrams/privacy/level1-privacy.svg). |
| [0-so-do-19-dfd-muc-1-xoa](0-so-do-19-dfd-muc-1-xoa.png) | DFD mức 1, xóa dữ liệu (nguồn docs/diagrams/privacy/level1-erase.svg). |

## 1. Giảm độ chi tiết phải lưu và chia sẻ

| Ảnh | Chứng minh điều gì |
|---|---|
| [1-giam-chi-tiet-01-thoi-han-luu](1-giam-chi-tiet-01-thoi-han-luu.png) | Thời hạn lưu đã rút ngắn, database còn 1165 MB, hóa đơn không đổi. |
| [1-giam-chi-tiet-02-ma-thoi-han](1-giam-chi-tiet-02-ma-thoi-han.png) | Thời hạn mới được đặt bằng chính sách của database, có chạy thử trước. |
| [1-giam-chi-tiet-03-view-cho-ai](1-giam-chi-tiet-03-view-cho-ai.png) | Giới hạn độ chi tiết cho AI nằm ngay trong SQL của database. |
| [1-giam-chi-tiet-04-rui-ro-theo-do-min](1-giam-chi-tiet-04-rui-ro-theo-do-min.png) | Dữ liệu theo ngày không cho ra giờ thức dậy, đi ngủ. |
| [1-giam-chi-tiet-05-man-hinh-dang-giu-gi](1-giam-chi-tiet-05-man-hinh-dang-giu-gi.png) | Người dùng thấy từng mức chi tiết được giữ bao lâu. |
| [1-giam-chi-tiet-06-man-hinh-chon-muc-wappi](1-giam-chi-tiet-06-man-hinh-chon-muc-wappi.png) | Chủ nhà chọn Wappi xem theo ngày hay theo giờ. |

## 2. Giới hạn quyền truy cập

| Ảnh | Chứng minh điều gì |
|---|---|
| [2-gioi-han-quyen-01-bang-quyen-truoc](2-gioi-han-quyen-01-bang-quyen-truoc.png) | Bản gốc 45 thao tác, chưa có mức "chỉ theo ngày". |
| [2-gioi-han-quyen-02-bang-quyen-sau](2-gioi-han-quyen-02-bang-quyen-sau.png) | Bản mới 57 thao tác, thêm cột thành viên chỉ theo ngày và quyền riêng của chủ nhà. |
| [2-gioi-han-quyen-03-ma-kiem-muc-thanh-vien](2-gioi-han-quyen-03-ma-kiem-muc-thanh-vien.png) | Mức quyền được kiểm trên máy chủ. |
| [2-gioi-han-quyen-04-thu-tan-cong](2-gioi-han-quyen-04-thu-tan-cong.png) | Đã thử tấn công, ghi lỗ đã vá và phần còn mở. |
| [2-gioi-han-quyen-05-chay-thu-quyen](2-gioi-han-quyen-05-chay-thu-quyen.png) | Mọi thao tác API trả đúng mã cho từng loại người dùng. |
| [2-gioi-han-quyen-06-chay-thu-tan-cong](2-gioi-han-quyen-06-chay-thu-tan-cong.png) | Các đòn thử đều bị chặn trong lần chạy thật. |
| [2-gioi-han-quyen-07-man-hinh-thanh-vien-va-ma-moi](2-gioi-han-quyen-07-man-hinh-thanh-vien-va-ma-moi.png) | Chủ nhà mời bằng mã dùng một lần, đổi mức xem, gỡ người (mã đã che). |
| [2-gioi-han-quyen-08-man-hinh-nhap-ma-moi](2-gioi-han-quyen-08-man-hinh-nhap-ma-moi.png) | Màn nhập mã mời; mã sai, đã dùng hoặc quá hạn bị từ chối. |
| [2-gioi-han-quyen-09-man-hinh-thanh-vien-theo-ngay](2-gioi-han-quyen-09-man-hinh-thanh-vien-theo-ngay.png) | Thành viên theo ngày chỉ được xem danh sách, không đổi được mức (một tên người đã che). |
| [2-gioi-han-quyen-10-man-hinh-tong-quan-theo-ngay](2-gioi-han-quyen-10-man-hinh-tong-quan-theo-ngay.png) | Tổng quan của thành viên theo ngày: phần theo giờ không hiện, có ghi lý do. |
| [2-gioi-han-quyen-11-man-hinh-thong-ke-theo-ngay](2-gioi-han-quyen-11-man-hinh-thong-ke-theo-ngay.png) | Thống kê của thành viên theo ngày chỉ có số theo ngày. |

## 3. Cho phép xóa lịch sử

| Ảnh | Chứng minh điều gì |
|---|---|
| [3-xoa-lich-su-01-ma-xoa](3-xoa-lich-su-01-ma-xoa.png) | Xóa thật ở cả bảng thô và các tổng đã tính sẵn. |
| [3-xoa-lich-su-02-chay-thu-xoa](3-xoa-lich-su-02-chay-thu-xoa.png) | Xóa đúng phạm vi, nhà khác không đổi, công tơ không gửi lại được. |
| [3-xoa-lich-su-03-man-hinh-xac-nhan-xoa](3-xoa-lich-su-03-man-hinh-xac-nhan-xoa.png) | Hộp xác nhận nói rõ cái gì mất, cái gì giữ, cái gì không xóa được. |
| [3-xoa-lich-su-04-man-hinh-da-xoa](3-xoa-lich-su-04-man-hinh-da-xoa.png) | Sau khi xóa: báo "Deleted", ghi mốc đã xóa (giao diện tiếng Anh, nhà thử). |
| [3-xoa-lich-su-05-man-hinh-xoa-tro-chuyen](3-xoa-lich-su-05-man-hinh-xoa-tro-chuyen.png) | Xóa mọi trò chuyện với Wappi kèm bản đọc thành tiếng. |
| [3-xoa-lich-su-06-man-hinh-xoa-tai-khoan](3-xoa-lich-su-06-man-hinh-xoa-tai-khoan.png) | Hộp xác nhận xóa tài khoản. |

## 4. Nêu rõ khi gọi dịch vụ ngoài

| Ảnh | Chứng minh điều gì |
|---|---|
| [4-dich-vu-ngoai-01-ma-cua-ra-chung](4-dich-vu-ngoai-01-ma-cua-ra-chung.png) | Mọi lời gọi ra ngoài đi qua một chỗ có kiểm đồng ý và ghi nhật ký. |
| [4-dich-vu-ngoai-02-ben-nhan](4-dich-vu-ngoai-02-ben-nhan.png) | Nêu rõ bên nhận và loại dữ liệu. |
| [4-dich-vu-ngoai-03-chay-thu-dong-y](4-dich-vu-ngoai-03-chay-thu-dong-y.png) | Khi bật chặn, không đồng ý thì không gửi; mỗi lần gửi có nhật ký. |
| [4-dich-vu-ngoai-04-man-hinh-dong-y-wappi](4-dich-vu-ngoai-04-man-hinh-dong-y-wappi.png) | Trước khi dùng Wappi: gửi gì, cho ai, ở đâu, tắt ở đâu. |
| [4-dich-vu-ngoai-05-man-hinh-dong-y-giong-noi](4-dich-vu-ngoai-05-man-hinh-dong-y-giong-noi.png) | Đồng ý riêng cho giọng nói, nói rõ âm thanh không che được. |
| [4-dich-vu-ngoai-06-man-hinh-thong-bao-va-da-gui](4-dich-vu-ngoai-06-man-hinh-thong-bao-va-da-gui.png) | Dòng báo dưới ô chat và mục "Đã gửi ra ngoài" của từng câu trả lời. |
| [4-dich-vu-ngoai-07-man-hinh-nhat-ky-gui](4-dich-vu-ngoai-07-man-hinh-nhat-ky-gui.png) | Nhật ký 30 ngày: bên nhận và loại dữ liệu, không ghi nội dung. |
| [4-dich-vu-ngoai-08-man-hinh-danh-gia-kem-noi-dung](4-dich-vu-ngoai-08-man-hinh-danh-gia-kem-noi-dung.png) | Nội dung chỉ gửi cho người bảo trì khi người dùng tự tích. |
