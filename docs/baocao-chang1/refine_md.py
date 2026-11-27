#!/usr/bin/env python3
"""Tinh chinh van phong cho ban md NILM truoc khi chuyen sang LaTeX. Khong sua file nguon.
Dung: python3 refine_md.py nguon.md dich.md"""
import re, sys
src, dst = sys.argv[1], sys.argv[2]
L = open(src).read().split('\n')
out = []; intab = False
SAFE = {'mô', 'nhóm', 'hộ', 'bộ', 'các', 'khi', 'trong', 'số', 'kết', 'công', 'điện', 'lớp', 'sai', 'mức', 'tải', 'lỗi', 'chiều', 'sự', 'năng', 'ở', 'nếu', 'chồng', 'detector', 'cả', 'cùng', 'phần', 'thiết', 'một', 'hai', 'ba', 'bốn', 'baseline', '2stage', 'dishwasher', 'kettle', 'washingmachine', 'microwave', 'recall', 'precision', 'accuracy', 'sae', 'mae', 'nde', 'f1'}
KEEP = {'là', 'và', 'với', 'nên', 'tức', 'vì', 'nhưng', 'còn', 'mà', 'nhờ', 'kể', 'cùng', 'rồi', 'hay', 'hoặc', 'thì', 'để', 'của'}
def split_semicolons(s):
    # ';' ngoai ngoac -> '. ' + viet hoa (chi khi ky tu sau la chu thuong)
    res = []; depth = 0; i = 0
    while i < len(s):
        ch = s[i]
        if ch in '([': depth += 1
        elif ch in ')]': depth = max(0, depth - 1)
        if ch == ';' and depth == 0 and s[i+1:i+2] == ' ' and i + 2 < len(s) and s[i+2].isalpha() and re.match(r'\S+', s[i+2:]).group(0).strip('.,:') not in KEEP:
            res.append('. ' + s[i+2].upper()); i += 3; continue
        res.append(ch); i += 1
    return ''.join(res)
def split_colons(s):
    # dau hai cham noi giua cau (khong phai nhan dam, khong trong ngoac) -> dau cham khi cau truoc du dai
    res = []; depth = 0; start = 0
    for i, ch in enumerate(s):
        if ch in '([': depth += 1
        elif ch in ')]': depth = max(0, depth - 1)
        if ch == ':' and depth == 0 and s[i+1:i+2] == ' ' and i + 2 < len(s) and s[i+2].isalpha() and s[i+2].islower():
            prev = s[start:i]
            first = s[i+2:].split(' ')[0].strip('.,')
            if len(prev.split()) >= 7 and '**' not in prev[-3:] and first in SAFE and 'Yêu cầu' not in prev and not prev.rstrip().endswith('Ký hiệu'):
                res.append(s[start:i] + '. ' + s[i+2].upper()); start = i + 3
    res.append(s[start:])
    return ''.join(res)

for l in L:
    if l.startswith('<table'): intab = True
    if intab:
        out.append(l)
        if '</table>' in l: intab = False
        continue
    if l.startswith('|') or l.startswith('![') or l.startswith('#') or l.startswith('<'):
        out.append(l); continue
    out.append(l if l.startswith('**Đề bài') else split_colons(split_semicolons(l)))
t = '\n'.join(out)
# thay the cac cau khung kieu ghi chu
for a, b in [
    ('Phần này trả lời', 'Nhóm trả lời'),
]:
    t = t.replace(a, b)
MANUAL = [["(0,479), chỉ cần cảm biến tổng, train khoảng 66 phút","(0,479). Mô hình chung chỉ cần cảm biến tổng, train khoảng 66 phút"],["tại tủ điện, NILM để phân rã điện năng theo thiết bị, rồi đưa kết quả vào Dashboard","tại tủ điện và NILM để phân rã điện năng theo thiết bị. Kết quả đi vào Dashboard"],["cơ sở dữ liệu, rồi chuyển chúng thành câu trả lời cho câu hỏi của người dùng, chẳng hạn","cơ sở dữ liệu. Từ đó nó trả lời câu hỏi của người dùng, chẳng hạn"],["đủ để tách tập kiểm tra theo hộ; là một trong các bộ dữ liệu bài NILMFormer gốc dùng","đủ để tách tập kiểm tra theo hộ. Bộ này là một trong các bộ dữ liệu bài NILMFormer gốc dùng"],["[3]; và được phát hành","[3], và được phát hành"],["Dishwasher 1,69%), nên một mô hình luôn dự đoán \"tắt\", không phát hiện được lần bật nào (F1 = 0), vẫn đạt Accuracy 0,9897 với cùng cách","Dishwasher 1,69%). Vì vậy một mô hình luôn dự đoán \"tắt\" vẫn đạt Accuracy 0,9897, dù không phát hiện được lần bật nào (F1 = 0), với cùng cách"],["0,468; với ba thiết bị","0,468. Với ba thiết bị"],[": Recall của 2Stage giảm từ 0,541",". Recall của 2Stage giảm từ 0,541"],["; 41/42 ô RMSE và 42/42 ô NDE kém hơn",". Có 41/42 ô RMSE và 42/42 ô NDE kém hơn"],["các ma trận này có dạng theo cột, vì đây là sai số tuyệt đối tính bằng W, nên hộ dùng","các ma trận này có dạng theo cột vì đây là sai số tuyệt đối tính bằng W. Hộ dùng"],["không; với hộ 2, 3, 13","không. Với hộ 2, 3, 13"],["không đồng đều: Dishwasher và Kettle","không đồng đều. Dishwasher và Kettle"],["và Kettle: 2Stage kém Baseline về F1 trên hộ được train","và Kettle. Ở mức này, 2Stage kém Baseline về F1 trên hộ được train"]]
MANUAL += [["Mục này trả lời Y1.1 và Y1.2 của đề bài 1","Nhóm trả lời Y1.1 và Y1.2 của đề bài 1"],["Mục này trả lời Y1.1 của đề bài 1","Nhóm trả lời Y1.1 của đề bài 1"],["Mục này trả lời đề bài 2","Nhóm trả lời đề bài 2"],["Mục này kiểm tra giả thuyết","Nhóm kiểm tra giả thuyết"],["Bài báo trả lời","Nhóm trả lời"],["Bài báo giữ","Nhóm giữ"],["Non-Intrusive Load Monitoring – giám sát","Non-Intrusive Load Monitoring, giám sát"]]
for a, b in MANUAL:
    t = t.replace(a, b)
open(dst, 'w').write(t)
print('ok')
