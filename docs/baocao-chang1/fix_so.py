#!/usr/bin/env python3
"""Doi so viet bang chu (hai..chin) thanh dang 0x trong tex/nilm.tex. Chay lai sau moi lan sinh lai nilm.tex."""
import re, sys
P = sys.argv[1] if len(sys.argv) > 1 else 'tex/nilm.tex'
DIG = {'hai': '02', 'ba': '03', 'bốn': '04', 'sáu': '06', 'bảy': '07', 'tám': '08', 'chín': '09'}
NOUN = r'(?:thiết bị|mô hình|cấu hình|thiết kế|nhóm hộ|nhóm|đề bài|đầu ra|hộ|việc|mức|cửa sổ|chỉ số|cách|câu hỏi|thành phần|bước|giai đoạn|lượt|loại|seed|trạng thái|yêu cầu|bảng|hình|cột|ô|phút|ngày|giờ)'
RX = re.compile(r'(?<![\wà-ỹ])(hai|ba|bốn|sáu|bảy|tám|chín) (?=' + NOUN + r'\b)', re.I)
t = open(P).read()
n = 0
def sub(m):
    global n; n += 1
    return DIG[m.group(1).lower()] + ' '
t2 = RX.sub(sub, t)
open(P, 'w').write(t2)
print('doi', n)
