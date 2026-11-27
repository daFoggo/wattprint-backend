# Quy ước code trong dự án NILM

## 1. Ngôn ngữ và encoding

- Toàn bộ comment trong mã, reports, báo cáo và tài liệu Markdown phải viết bằng
  **tiếng Việt có dấu**, dùng câu rõ nghĩa và đúng chính tả.
- Thông báo lỗi do dự án viết trong các lệnh `raise` và `assert` cũng phải dùng
  **tiếng Việt có dấu**. Giữ nguyên tên loại ngoại lệ và định danh kỹ thuật;
  cập nhật các test kiểm tra nội dung thông báo khi thay đổi câu chữ.
- Dùng `assert điều_kiện_hợp_lệ, "Thông báo tiếng Việt có dấu"` để kiểm tra
  cấu hình, shape và tính hợp lệ của dữ liệu, thay cho `if ...: raise ...`.
  Giữ `if/else` cho phân nhánh tính toán và `try/except` cho xử lý ngoại lệ.
  Các kiểm tra `assert` được thực thi khi chạy Python ở chế độ thông thường;
  không dùng tùy chọn `-O` khi cần thực hiện các kiểm tra này.
- Lưu các tệp văn bản bằng **UTF-8**. Không chuyển tiếng Việt thành không dấu
  để né lỗi encoding.
- Có thể giữ tên mô hình, định danh mã, thuật ngữ kỹ thuật và ký hiệu tensor
  khi cần thiết; phần diễn giải phải bằng tiếng Việt có dấu.
- Giữ nguyên thông tin bản quyền, giấy phép và trích dẫn nguồn cần bảo toàn.
- Sau khi sửa, kiểm tra lại khả năng đọc UTF-8 và hiển thị dấu tiếng Việt;
  không để xuất hiện ký tự thay thế Unicode `U+FFFD` hoặc nội dung bị lỗi mã hóa.
- Với tệp Python đã thay đổi, chạy kiểm tra biên dịch bằng interpreter của
  project, ví dụ `.venv/bin/python -m compileall -q training`.
  Kiểm tra biên dịch không thay thế việc kiểm tra nội dung tiếng Việt: cần
  kiểm tra cả hai. Với Markdown, kiểm tra UTF-8 và nội dung hiển thị.

## 2. Comment và docstring

- Không cần viết docstring cho module hoặc function trong phạm vi công việc
  người dùng yêu cầu. Không tự thêm docstring chỉ để mô tả lại tên hàm hoặc
  mã đã rõ nghĩa; khi người dùng yêu cầu riêng thì thực hiện theo yêu cầu đó.
- Đoạn mã cần giải thích để dễ hiểu phải có comment bằng tiếng Việt có dấu,
  theo quy định ở mục 1.
- Ưu tiên giải thích mục đích, giả định, điều kiện quan trọng hoặc lý do chọn
  cách xử lý. Tránh comment lặp lại nguyên nghĩa một câu lệnh đơn giản.

## 3. Chú thích chiều tensor trong mô hình học sâu

- Khi viết hoặc sửa mô hình DL, đặc biệt chú ý comment sự biến đổi chiều tensor
  qua các phép biến đổi và các lớp.
- Ghi rõ shape đầu vào, đầu ra và ý nghĩa các trục. Dùng ký hiệu nhất quán,
  chẳng hạn `B`: số mẫu trong batch, `C`: số kênh, `L`: độ dài chuỗi,
  `D`: chiều biểu diễn, `H`: số attention head.
- Chú thích tại các bước đổi thứ tự trục, reshape, ghép/tách tensor, pooling,
  embedding, attention, head dự đoán và nhân mask; chỉ rõ trục thao tác hoặc
  cơ chế broadcast khi có thể gây nhầm lẫn.
- Shape ghi trong comment phải khớp với code thực tế và cấu hình mô hình;
  cập nhật comment khi thay đổi lớp hoặc phép biến đổi.

Ví dụ:

```python
# Đầu vào: (B, C, L); chuyển trục kênh về cuối để đưa vào GRU.
x_embed = x_embed.transpose(1, 2)  # (B, C, L) → (B, L, C)

# Ghép token thống kê vào cuối chuỗi theo trục thời gian.
x_tokens = torch.cat([x_tokens, token_stats], dim=1)  # (B, L + 1, D)

# Áp dụng mask bật/tắt tại từng thiết bị và thời điểm; hai tensor cùng shape.
prediction = power * mask  # (B, C, L) × (B, C, L) → (B, C, L)
```

## 4. Định dạng và kiểm tra mã bằng Ruff

- Dùng Ruff để định dạng, kiểm tra mã và sắp xếp import. Giới hạn chiều dài dòng
  là **200 ký tự**, không phải 120; cấu hình được lưu trong `pyproject.toml`.
- Giữ các quy ước ở trên khi định dạng: tiếng Việt có dấu, kiểm tra bằng `assert`,
  không thêm docstring không cần thiết và chú thích rõ chiều tensor.
- Giữ nhóm rule mặc định của Ruff (`E4`, `E7`, `E9`, `F`), bổ sung `E501` để
  kiểm tra dòng dài và `I` để sắp xếp import. Ruff không tự kiểm chứng ngôn ngữ
  tiếng Việt hoặc tính đúng đắn của chú thích tensor; vẫn cần rà soát thủ công.
- Chạy `uv run ruff check .` để kiểm tra và `uv run ruff format --check .` để
  kiểm tra định dạng. Dùng `uv run ruff check --fix .` và `uv run ruff format .`
  khi cần sửa. Có thể dùng trực tiếp `.venv/bin/ruff` thay cho `uv run ruff`.
- VS Code đã được cấu hình dùng extension `charliermarsh.ruff` cho Python,
  định dạng khi lưu và hiển thị mốc 200 ký tự; cần cài extension để dùng tính năng này.
