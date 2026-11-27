# Ghi chú văn phong cho báo cáo Chặng 1

## Yêu cầu của bạn (nguyên tắc cần giữ)
1. Tối đa 35 trang, ngắn gọn nhất có thể. Chỉ trình bày phần trọng tâm, trừ phần NILM eval.
2. Các phần còn lại chỉ nêu cốt lõi công nghệ, tổng quan kiến trúc, chức năng đã hoàn thiện.
3. Viết đứng ở góc nhóm đề xuất ("nhóm đề xuất", "nhóm xây", "nhóm quyết định", "bước tiếp theo của nhóm"). Không viết như ghi chú của AI, không giải thích kiểu "được nêu rõ để tránh hiểu nhầm".
4. Số trình bày bằng chữ số, dạng 0x, xx (04 nhà demo, 03 worker, 09 mô-đun), không viết bằng chữ.
5. Nội dung NILM giữ nguyên theo eval đã làm, lấy từ bài đã cập nhật.
6. Dùng "bản cũ", không dùng "bản bán kết".
7. Dùng các skill: unslop, technical-writing (pstack của Cursor) và tránh dấu hiệu văn AI theo Wikipedia "Signs of AI writing".

## Quy tắc unslop (rút gọn)
- Không đuôi "-ing" thừa kiểu "nhấn mạnh…, đảm bảo…". Không "không chỉ X mà còn Y". Không ép ý thành bộ ba.
- Không từ AI: additionally, crucial, pivotal, vibrant, landscape, showcase, underscore, foster, leverage.
- Dùng "là", "có" thay cho "đóng vai trò", "sở hữu", "đặc trưng bởi".
- Một thứ một tên, lặp lại tên đó. Không "từ X đến Y" nếu X, Y không nằm trên một thang thật.
- Không gạch ngang (— –) và không dùng ngoặc đơn thay gạch ngang. Dấu hai chấm chỉ đứng trước danh sách hoặc ví dụ.
- Không in đậm mọi danh từ riêng. Nhãn đậm kết thúc bằng dấu chấm và thêm ý mới thì được.
- Tiêu đề chỉ viết hoa chữ đầu. Không emoji. Dấu nháy thẳng.
- Cắt từ đệm ("để mà", "cần lưu ý rằng"). Tối đa 1 từ rào đón ("có thể").
- Không kết luận chung chung. Nêu việc cụ thể hoặc số liệu.
- Nêu cơ chế hoặc con số, không nêu cảm giác. Câu nào đặt sang dự án khác vẫn dùng được thì bỏ.
- Mỗi câu một ý. Dùng chủ động, nêu rõ ai làm gì. Dùng từ thường ("dùng", không "tận dụng").
- Không ẩn dụ, không động từ bóng bẩy khi có cách nói đúng nghĩa. Viết câu đủ chủ vị, không viết tắt khó hiểu.

## Quy tắc technical-writing (rút gọn)
- Cắt mọi từ không làm việc. Dùng từ ngắn, quen thuộc. Viết đúng tên ký hiệu, tệp, lệnh.
- Trộn câu dài và ngắn. Câu có nhận định chỉ ở phần giải thích. Phần tra cứu khô và đủ.
- Mỗi câu một việc. Câu dài hơn khoảng 25 từ thì tách.
- Mỗi vật một tên, dùng nhất quán. Không thành ngữ, không ẩn dụ.
- Dùng dấu chấm thay dấu chấm phẩy và dấu gạch ngang. Dùng "bạn" và hiện tại khi hướng dẫn.
- Tiêu đề nêu ý chính. Danh sách phải song song và mở đầu bằng một câu đủ.

## Dấu hiệu văn AI (Wikipedia, mục Content)
- Phóng đại tầm quan trọng, di sản, xu hướng chung ("đóng vai trò then chốt", "phản ánh xu hướng rộng hơn").
- Phân tích hời hợt bằng cụm "-ing" ở cuối câu. Nguồn mơ hồ ("các chuyên gia cho rằng").
- Mục "Thách thức và triển vọng" dạng dàn ý, kết bằng nhận định tích cực chung chung.
- Từ vựng AI dày đặc, né "là/có", cấu trúc "không chỉ… mà còn…", bộ ba máy móc.
- Giọng quảng cáo, khẳng định tầm quan trọng của chủ đề mà không có dữ kiện cụ thể.

## Nguồn và skill đã dùng
| Thứ | Chi tiết |
|---|---|
| Bộ skill | pstack của Cursor: https://github.com/cursor/plugins/tree/main/pstack |
| Skill `unslop` | https://github.com/cursor/plugins/tree/main/pstack/skills/unslop (mô tả: "Cut AI tells from any writing", 33 quy tắc đánh số) |
| Skill `technical-writing` | https://github.com/cursor/plugins/tree/main/pstack/skills/technical-writing (Diátaxis, Google developer style, STE, Global English; bắt buộc áp `unslop` cho mọi tài liệu) |
| Danh mục dấu hiệu văn AI | https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing#Content (đọc mục Content; bản raw tải về lúc làm: 26/11/2026) |
| Bản cài trên máy | `~/.claude/skills/unslop` và `~/.claude/skills/technical-writing` (chép từ bản clone cursor/plugins, đã đọc trước khi cài) |
| Cách gọi | Cả hai skill đặt `disable-model-invocation: true`, nên chỉ chạy khi bạn gõ `/unslop` hoặc `/technical-writing` |

Ghi chú: hai skill viết cho tiếng Anh. Khi viết tiếng Việt, áp dụng theo tinh thần (câu ngắn, chủ động, không từ sáo, không gạch ngang), không chạy tự động.

## Bổ sung (26/11/2026)
- text2sql là thành phần lõi của Wappi, không viết là "dịch vụ riêng" hay "tùy chọn".
- Số 2 đến 9 đứng trước danh từ đếm viết dạng 0x (script `fix_so.py` đổi lại sau mỗi lần sinh lại `tex/nilm.tex`).
- Dấu hai chấm chỉ đứng trước danh sách. Câu quá 25 từ thì tách.
- Mục 2.4 trả lời yêu cầu "Minh bạch nguồn gốc giá trị hiển thị" của đề bài.
- Quy trình dựng phần NILM: `python3 refine_md.py <md nguồn> work/nilm_tinh.md` (tách câu dài, bỏ dấu chấm phẩy, đổi cách gọi "bài báo" thành "nhóm"; không sửa file nguồn), rồi `python3 md2tex.py work/nilm_tinh.md tex/nilm.tex`, rồi build.
