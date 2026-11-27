#!/usr/bin/env python3
"""Chuyen bai_bao_thuc_nghiem.md sang LaTeX (muc 3 cua bao cao). Khong dung pandoc."""
import re, sys, html
from pathlib import Path

SRC = Path(sys.argv[1]); OUT = Path(sys.argv[2])
DROP = set()  # dong (1-based) bo qua, cap nhat sau
if len(sys.argv) > 3:
    DROP = set(int(x) for x in sys.argv[3].split(',') if x)

CITE = {'1':'hart1992','2':'zoha2012','3':'petralia2025','4':'murray2017','5':'pereira2018'}
SPECIAL = {'&':r'\&','%':r'\%','#':r'\#','_':r'\_','~':r'\textasciitilde{}','^':r'\textasciicircum{}','{':r'\{','}':r'\}','\\':r'\textbackslash{}'}

DIG = {'hai': '02', 'ba': '03', 'bốn': '04', 'sáu': '06', 'bảy': '07', 'tám': '08', 'chín': '09'}
NUMW = re.compile(r'(?<![\wà-ỹ])(hai|ba|bốn|sáu|bảy|tám|chín) (?=(?:thiết bị|mô hình|cấu hình|thiết kế|nhóm hộ|đề bài|đầu ra|hộ|việc|mức|cửa sổ|chỉ số|cách|câu hỏi|thành phần|bước|giai đoạn|lượt|loại|seed|nhóm|trạng thái|yêu cầu|bảng|hình|cột|ô)\b)')

def esc(s):
    return ''.join(SPECIAL.get(c, c) for c in s)

def inline(s):
    # tach math, code truoc
    parts = []
    pos = 0
    for m in re.finditer(r'\$[^$]+\$|`[^`]+`', s):
        parts.append(('t', s[pos:m.start()]))
        tok = m.group(0)
        parts.append(('m', tok) if tok[0] == '$' else ('c', tok[1:-1]))
        pos = m.end()
    parts.append(('t', s[pos:]))
    out = []
    for kind, txt in parts:
        if kind == 'm': out.append(txt)
        elif kind == 'c': out.append(r'\texttt{' + esc(txt) + '}')
        else: out.append(text(txt))
    return ''.join(out)

def text(t):
    # trich dan [n], [1], [2] -> natbib
    def cites(m):
        keys = [CITE[k] for k in re.findall(r'\d', m.group(0))]
        return '@@CITE:' + ','.join(keys) + '@@'
    t = re.sub(r'\[\d\](?:, \[\d\])*', cites, t)
    t = esc(t.replace('Bài báo trả lời', 'Nhóm trả lời').replace('Bài báo giữ', 'Nhóm giữ').replace('Bài báo', 'Nhóm'))
    t = re.sub(r'"([^"]+)"', lambda m: '\u201c' + m.group(1) + '\u201d', t)
    t = NUMW.sub(lambda m: DIG[m.group(1)] + ' ', t)
    t = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', t)
    t = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'\\textit{\1}', t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\\href{\2}{\1}', t)
    # tham chieu cheo
    t = re.sub(r'(Bảng|Hình) (\d+)\b', lambda m: f'{m.group(1)}~\\ref{{nilm:{"tab" if m.group(1)=="Bảng" else "fig"}{m.group(2)}}}', t)
    t = re.sub(r'mục (\d(?:\.\d)+)–(\d(?:\.\d)+)', r'mục~3.\1–3.\2', t)
    t = re.sub(r'mục (\d(?:\.\d)*)(?![–\d])', lambda m: 'mục~3.' + m.group(1), t)
    t = re.sub(r'câu hỏi (\d\.\d)', r'câu hỏi 3.\1', t)
    def cite_sub(m):
        keys = m.group(2)
        pre = m.group(1)
        if pre.endswith('cộng sự '):
            return pre + '\\citeyearpar{' + keys + '}'
        return pre.rstrip(' ') + '~\\citep{' + keys + '}' if pre.endswith(' ') else pre + '\\citep{' + keys + '}'
    t = re.sub(r'(.{0,12}?)@@CITE:([^@]+)@@', cite_sub, t)
    t = re.sub(r'(?<=\d) ?× ?(?=\d)', r'$\\times$', t)
    t = t.replace('ₜ', '$_t$')
    return t

def cell_text(c):
    c = html.unescape(c)
    c = re.sub(r'<b>(.*?)</b>', lambda m: '**' + m.group(1) + '**', c, flags=re.S)
    c = re.sub(r'<br\s*/?>', ' ', c)
    c = re.sub(r'<[^>]+>', '', c)
    r = inline(c.strip())
    return ('{}' + r) if r.startswith('[') else r

def html_table(h, caption, label):
    rows = re.findall(r'<tr>(.*?)</tr>', h, re.S)
    n_head = len(re.findall(r'<tr>(?:(?!</tr>).)*?<th', h.split('<tbody>')[0], re.S)) if '<tbody>' in h else 1
    grid = []; occ = {}
    ncols = 0
    parsed = []
    for ri, r in enumerate(rows):
        cells = re.findall(r'<(t[hd])([^>]*)>(.*?)</t[hd]>', r, re.S)
        cs = 0; row = []
        for tag, attrs, body in cells:
            while occ.get((ri, cs), 0): row.append(None); cs += 1
            colspan = int((re.search(r'colspan="(\d+)"', attrs) or [0, 1])[1])
            rowspan = int((re.search(r'rowspan="(\d+)"', attrs) or [0, 1])[1])
            right = 'align="right"' in attrs
            for dr in range(rowspan):
                for dc in range(colspan):
                    if dr or dc: occ[(ri + dr, cs + dc)] = 1
            row.append((tag, cell_text(body), colspan, rowspan, right))
            cs += colspan
            for _ in range(colspan - 1): row.append('skip')
        ncols = max(ncols, cs); parsed.append(row)
    # kieu cot tu hang du lieu dau
    first_data = next((p for p in parsed if p and p[0] and p[0] != 'skip' and p[0][0] == 'td'), None)
    spec = []
    if first_data:
        col = 0
        for c in first_data:
            if c is None or c == 'skip':
                spec.append('r'); continue
            spec.append('r' if c[4] else 'l')
    spec = (spec + ['r'] * ncols)[:ncols]
    spec = ['|'.join(spec)]
    lines = []
    for ri, row in enumerate(parsed):
        out = []; ci = 0
        i = 0
        while i < len(row):
            c = row[i]
            if c == 'skip': i += 1; continue
            if c is None:
                out.append(''); i += 1; continue
            tag, body, cspan, rspan, right = c
            if tag == 'th': body = r'\textbf{' + body + '}' if body else body
            if rspan > 1: body = r'\multirow{%d}{*}{%s}' % (rspan, body)
            if cspan > 1:
                al = 'c' if tag == 'th' else ('r' if right else 'l')
                body = r'\multicolumn{%d}{%s}{%s}' % (cspan, ('|' if not out else '') + al + '|', body)
            elif tag == 'th' and i > 0:
                body = r'\multicolumn{1}{%s}{%s}' % (('|' if not out else '') + 'c|', body)
            out.append(body); i += 1
        free = [c for c in range(ncols) if not occ.get((ri + 1, c))]
        if len(free) == ncols: hl = r'\hline'
        else:
            segs = []; s = None
            for c in range(ncols + 1):
                ok = c < ncols and c in free
                if ok and s is None: s = c
                if not ok and s is not None: segs.append((s, c - 1)); s = None
            hl = ''.join(r'\cline{%d-%d}' % (a + 1, b + 1) for a, b in segs)
        lines.append(' & '.join(out) + r' \\ ' + hl)
    body = '\n'.join(lines)
    return float_tab(caption, label, '', '|' + spec[0] + '|', body)

def float_tab(caption, label, _x, spec, body, xcols=False):
    env = 'tabularx' if xcols else 'tabular'
    head = r'\begin{tabularx}{\linewidth}{%s}' % spec if xcols else r'\begin{tabular}{%s}' % spec
    tail = r'\end{tabularx}' if xcols else r'\end{tabular}'
    res = [r'\begin{table}[H]', r'\centering'] + ([r'\caption{%s}\label{%s}' % (caption, label)] if caption is not None else []) + [r'\small' if xcols else r'\footnotesize', r'\setlength{\tabcolsep}{3.5pt}\renewcommand{\arraystretch}{1.12}']
    if not xcols: res.append(r'\begin{adjustbox}{max width=\linewidth}')
    res += [head, r'\hline', body, tail]
    if not xcols: res.append(r'\end{adjustbox}')
    res.append(r'\end{table}')
    return '\n'.join(res)

def pipe_table(rows, caption, label):
    cells = [[c.strip() for c in r.strip().strip('|').split('|')] for r in rows if not re.match(r'^\s*\|[-:| ]+\|\s*$', r)]
    n = len(cells[0])
    lens = [max(len(re.sub(r'\*', '', r[i])) for r in cells if i < len(r)) for i in range(n)]
    spec = ''.join('X' if l > 26 else 'l' for l in lens)
    if 'X' not in spec: spec = spec[:-1] + 'X'
    body = []
    for ri, r in enumerate(cells):
        cs = [('{}' + inline(c)) if inline(c).startswith('[') else inline(c) for c in r]
        if ri == 0: cs = [r'\textbf{' + c + '}' for c in cs]
        body.append(' & '.join(cs) + r' \\ \hline')
    return float_tab(caption, label, '', '|' + '|'.join(spec) + '|', '\n'.join(body), xcols=True)

lines = SRC.read_text().split('\n')
out = []
i = 0
pending_cap = None
started = False
list_stack = []   # (kind, indent)

def close_lists(to=0):
    while len(list_stack) > to:
        k, _ = list_stack.pop()
        out.append(r'\end{%s}' % k)

HEAD = {2: 'subsection', 3: 'subsubsection', 4: 'paragraph', 5: 'subparagraph'}
while i < len(lines):
    ln = lines[i]; no = i + 1
    if no in DROP: i += 1; continue
    if not started:
        if ln.startswith('## 1.'): started = True
        else: i += 1; continue
    if ln.startswith('## Tài liệu tham khảo'): break
    s = ln.rstrip()
    if not s.strip():
        close_lists(); out.append(''); i += 1; continue
    m = re.match(r'^(#{2,5}) (.*)$', s)
    if m:
        close_lists()
        lvl = len(m.group(1)); title = m.group(2)
        numbered = re.match(r'^\d+(?:\.\d+)*\.? ', title)
        title_clean = re.sub(r'^\d+(?:\.\d+)*\.? ', '', title)
        if lvl <= 4 and numbered and 'Trả lời câu hỏi' not in title:
            out.append('\\%s{%s}' % (HEAD[lvl], inline(title_clean)))
        elif 'Trả lời câu hỏi' in title:
            out.append('\\medskip\\noindent\\textbf{%s}\\par\\nopagebreak' % inline(title_clean))
        elif lvl == 4:
            out.append('\\medskip\\noindent\\textbf{%s}\\par\\nopagebreak' % inline(title_clean))
        else:
            out.append('\\medskip\\noindent\\textbf{%s}\\par\\nopagebreak' % inline(title_clean))
        i += 1; continue
    m = re.match(r'^\*\*(Bảng|Hình) (\d+)\.\*\* (.*)$', s)
    if m:
        pending_cap = (m.group(1), m.group(2), m.group(3)); i += 1; continue
    m = re.match(r'^!\[(.*?)\]\((.*?)\)(\{.*?\})?$', s)
    if m:
        cap = m.group(1); path = m.group(2)
        mm = re.match(r'Hình (\d+)\. (.*)', cap)
        num, c = mm.group(1), mm.group(2)
        out.append('\\begin{figure}[H]\\centering\\includegraphics[max width=\\linewidth,max height=0.42\\textheight]{figures/nilm/%s}\\caption{%s}\\label{nilm:fig%s}\\end{figure}' % (Path(path).name, inline(c), num))
        i += 1; continue
    if s.startswith('<table>'):
        j = i; buf = []
        while True:
            buf.append(lines[j])
            if '</table>' in lines[j]: break
            j += 1
        cap = pending_cap; pending_cap = None
        out.append(html_table('\n'.join(buf), inline(cap[2]) if cap else None, 'nilm:tab' + cap[1] if cap else None))
        i = j + 1; continue
    if s.startswith('|'):
        j = i; buf = []
        while j < len(lines) and lines[j].startswith('|'):
            buf.append(lines[j]); j += 1
        cap = pending_cap; pending_cap = None
        out.append(pipe_table(buf, inline(cap[2]) if cap else None, 'nilm:tab' + cap[1] if cap else None))
        i = j; continue
    m = re.match(r'^(\s*)([-*]|\d+\.) (.*)$', s)
    if m:
        ind = len(m.group(1)); kind = 'enumerate' if m.group(2)[0].isdigit() else 'itemize'
        while list_stack and list_stack[-1][1] > ind: close_lists(len(list_stack) - 1)
        if not list_stack or list_stack[-1][1] < ind:
            out.append(r'\begin{%s}' % kind); list_stack.append((kind, ind))
        body = m.group(3)
        # dong tiep theo thuoc cung muc
        j = i + 1
        while j < len(lines) and lines[j].strip() and re.match(r'^\s+\S', lines[j]) and not re.match(r'^\s*([-*]|\d+\.) ', lines[j]):
            body += ' ' + lines[j].strip(); j += 1
        out.append(r'\item ' + inline(body)); i = j; continue
    close_lists()
    para = s
    j = i + 1
    while j < len(lines) and lines[j].strip() and not re.match(r'^(#|\||!\[|<table|\*\*(Bảng|Hình) \d+\.|\s*([-*]|\d+\.) )', lines[j]) and (j + 1) not in DROP:
        para += ' ' + lines[j].strip(); j += 1
    out.append(inline(para)); i = j
close_lists()
OUT.write_text('\n'.join(out) + '\n')
print('ok', len(out))
