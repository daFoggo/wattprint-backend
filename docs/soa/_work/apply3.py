"""Vòng 3: bỏ danh sách in đậm đầu mục, sửa 'Đảm bảo', bộ ba đệm, ô bảng. Chạy trong _work."""
import importlib.util, shutil
spec = importlib.util.spec_from_file_location('old', '../draft/content.py')
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
B = [list(x) if x[0] != 'table' else list(x) for x in old.BODY]

def setp(i, t): assert B[i][0] == 'p', i; B[i] = ['p', t]
def cell(i, r, c, t):
    assert B[i][0] == 'table'
    rows = [list(x) for x in B[i][3]]; rows[r][c] = t; B[i][3] = rows

# 1.2 bốn module, bỏ nhãn in đậm
B[7] = ['ol', [
    'Module NILM dùng NILMFormer [@nilmformer], mô hình Transformer tách tải tốt cả khi tổng công suất biến động mạnh, kèm bước calibration theo từng hộ.',
    'Module dashboard và hóa đơn hiển thị điện năng từng thiết bị theo giờ, ngày, tuần, tháng, quy ra tiền theo biểu giá sinh hoạt 5 bậc.',
    'Module phân tích và dự báo cảnh báo thiết bị chạy lâu bất thường, phát hiện tiêu thụ ngầm (standby), so sánh với tháng trước và với các hộ tương đồng, dự báo hóa đơn cuối tháng và thời điểm chạm bậc giá kế tiếp.',
    'Energy Copilot trả lời câu hỏi của người dùng (pull) và chủ động gợi ý tiết kiệm (push). Mọi con số do các tool tính từ dữ liệu của hộ, LLM chỉ diễn giải. Copilot còn lập kế hoạch tiết kiệm và so sánh kết quả trước và sau khi áp dụng.']]

# 3.3.1 ba tiêu chí thành văn xuôi
setp(45, 'Nhóm tách monolith theo ba tiêu chí, xếp theo thứ tự ưu tiên.')
B[46] = ['p', 'Tiêu chí đầu tiên là data ownership. Dữ liệu vận hành (hộ, dữ liệu sensor, hóa đơn), inference học máy, phân tích thống kê và tương tác AI nằm trên các nhóm bảng riêng, mảng này chỉ đọc kết quả của mảng kia chứ không sửa chéo. Đây là tiêu chí chính vì mỗi microservice cần tự chủ dữ liệu của mình [@newman].']
B.insert(47, ['p', 'Tiêu chí thứ hai là workload. Inference NILMFormer chạy PyTorch, tốn nhiều CPU và RAM. Ingest dữ liệu sensor cần phản hồi nhanh và ổn định. Phân tích chạy theo batch và lịch định kỳ. Copilot phần lớn thời gian chờ phản hồi từ LLM bên ngoài.'])
B.insert(48, ['p', 'Tiêu chí thứ ba là fault isolation. LLM bên ngoài có độ trễ cao và hay lỗi mạng, nên phải tách để sự cố này không chặn ingest hay dashboard. Khi model NILM quá tải, ingest vẫn lưu dữ liệu mới và đánh dấu batch chờ xử lý.'])
OFF = 2  # các chỉ số sau 46 dịch +2

# 3.5 hai cách đọc chéo, bỏ nhãn in đậm
i82 = 82 + OFF
assert B[i82][0] == 'ul'
B[i82] = ['ul', [
    'Dùng event theo pattern CQRS [@richardson]. `insight` giữ một read model dữ liệu tiêu thụ đã tổng hợp theo giờ, cập nhật bất đồng bộ từ event của `core`. `core` lo luồng ghi và là `source of truth`, `insight` tổ chức dữ liệu cho truy vấn phân tích.',
    'Gọi REST API khi cần dữ liệu mới nhất hoặc dữ liệu cấu hình nhỏ. Service cần dữ liệu hỏi thẳng service sở hữu, ví dụ `insight` lấy biểu giá và danh mục thiết bị từ `core`.']]

# câu bộ ba đệm
setp(104 + OFF, 'Mỗi quyết định ở Chương 3 đều có cái giá. Bảng 4.1 ghi các quyết định lớn, lý do chọn và đánh đổi nhóm chấp nhận.')
setp(51 + OFF, 'Bảng 3.2 là kết quả: bốn service, mỗi service có database, trách nhiệm và chiều gọi đồng bộ riêng.')

# ô bảng
T = lambda i: i + (OFF if i > 46 else 0)
cell(27, 1, 2, 'Dữ liệu sensor luôn gắn đúng hộ')
cell(27, 3, 2, 'Hóa đơn đã chốt không đổi khi cập nhật biểu giá mới')
cell(27, 5, 2, 'Mô hình kinh doanh có hai gói thuê bao')
cell(27, 6, 2, 'Hạn chế thông báo dồn dập')
cell(27, 7, 2, 'Mọi con số tư vấn chính xác và kiểm chứng được')
cell(T(49), 0, 2, 'Không đạt tối thiểu ba service nghiệp vụ của đề bài, và gộp hai khối có tải trái ngược: nilm tốn CPU/RAM, copilot chủ yếu chờ I/O mạng từ LLM')
cell(T(49), 1, 2, 'Mỗi service có miền dữ liệu, kiểu tải và đặc thù lỗi riêng. Số lượng vừa với nhóm ba người triển khai và vận hành')
cell(T(52), 0, 1, B[T(52)][3][0][1].replace('Giữ vai trò `source of truth`', 'Là `source of truth`'))
cell(T(108), 1, 2, B[T(108)][3][1][2].replace('trả mã lỗi 503 rõ ràng', 'trả mã 503'))

src = open('../draft/content.py', encoding='utf-8').read()
shutil.copy('../draft/content.py', 'content.before_round3.py')
head = src[:src.index('BODY = []')]
out = head + 'BODY = []\nA = BODY.append\n\n' + ''.join('A(' + repr(tuple(x)) + ')\n' for x in B)
open('../draft/content.py', 'w', encoding='utf-8').write(out)
print('written', len(B))
