# -*- coding: utf-8 -*-
"""Dựng báo cáo: lấy ref_style.docx làm nền (style, mục lục, bảng, chú thích), thay bìa bằng bìa của template.docx,
xóa nội dung cũ và ghi nội dung mới từ content.py.  Chạy: python build_report.py <ref> <template> <out.docx>"""
import copy, io, re, sys
from pathlib import Path
import docx
from docx.shared import Cm
from docx.oxml import parse_xml
from docx.oxml.ns import qn, nsdecls
from PIL import Image
import content as C

REF, TPL, OUT = sys.argv[1:4]
FIG = Path(__file__).parent / "figures"
W = nsdecls("w")
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

doc = docx.Document(REF)
tpl = docx.Document(TPL)
body = doc.element.body
kids = list(body.iterchildren())
final_sect = kids[-1]
assert final_sect.tag == qn("w:sectPr")
footer_rid = final_sect.find(qn("w:footerReference")).get(qn("r:id"))


def esc(t):
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------- trích dẫn tự đánh số ----------
cites = {}
def cite(k):
    if k not in cites:
        cites[k] = len(cites) + 1
    return cites[k]

TOK = re.compile(r"(\*\*.+?\*\*|//.+?//|`.+?`|\[@\w+\])")

def runs(text, size=None, bold=False, italic=False):
    out = []
    for part in TOK.split(text):
        if not part:
            continue
        b, i, mono = bold, italic, False
        if part.startswith("**"):
            part, b = part[2:-2], True
        elif part.startswith("//"):
            part, i = part[2:-2], True
        elif part.startswith("`"):
            part, mono = part[1:-1], True
        elif part.startswith("[@"):
            part = "[%d]" % cite(part[2:-1])
        rpr = ""
        if mono:
            rpr += '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
        if b:
            rpr += "<w:b/><w:bCs/>"
        if i:
            rpr += "<w:i/><w:iCs/>"
        sz = (size if size else (22 if mono else None))
        if sz:
            rpr += '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (sz, sz)
        out.append('<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r>' % ("<w:rPr>%s</w:rPr>" % rpr if rpr else "", esc(part)))
    return "".join(out)


def P(ppr, inner):
    return parse_xml('<w:p %s><w:pPr>%s</w:pPr>%s</w:p>' % (W, ppr, inner))


def add(el):
    final_sect.addprevious(el)


BODYPPR = '<w:spacing w:after="120" w:line="312" w:lineRule="auto"/><w:ind w:firstLine="567"/><w:jc w:val="both"/>'
LISTPPR = '<w:spacing w:after="120" w:line="312" w:lineRule="auto"/><w:ind w:left="567" w:hanging="360"/><w:jc w:val="both"/>'
CELL_B = '<w:tcBorders>' + "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="808080"/>' % s for s in ("top", "left", "bottom", "right")) + '</w:tcBorders>'
CELL_M = '<w:tcMar><w:top w:w="40" w:type="dxa"/><w:left w:w="80" w:type="dxa"/><w:bottom w:w="40" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tcMar><w:vAlign w:val="center"/>'


def table(headers, rows, widths):
    assert sum(widths) == 9071, sum(widths)
    def cell(w, text, head):
        shd = '<w:shd w:val="clear" w:color="auto" w:fill="E7E6E6"/>' if head else ""
        return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/>%s%s%s</w:tcPr><w:p><w:pPr><w:spacing w:line="264" w:lineRule="auto"/></w:pPr>%s</w:p></w:tc>'
                % (w, CELL_B, shd, CELL_M, runs(text, size=22, bold=head)))
    pre = '<w:tblPrEx><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPrEx>'
    def row(cells, head):
        return '<w:tr>%s<w:trPr><w:cantSplit/>%s</w:trPr>%s</w:tr>' % (pre, "<w:tblHeader/>" if head else "", "".join(cell(w, t, head) for w, t in zip(widths, cells)))
    xml = ('<w:tbl %s><w:tblPr><w:tblW w:w="9071" w:type="dxa"/><w:tblBorders>%s</w:tblBorders><w:tblCellMar><w:left w:w="10" w:type="dxa"/><w:right w:w="10" w:type="dxa"/></w:tblCellMar>'
           '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>%s</w:tblGrid>%s%s</w:tbl>'
           % (W, "".join('<w:%s w:val="single" w:sz="4" w:space="0" w:color="auto"/>' % s for s in ("top", "left", "bottom", "right", "insideH", "insideV")),
              "".join('<w:gridCol w:w="%d"/>' % w for w in widths), row(headers, True), "".join(row(r, False) for r in rows)))
    return parse_xml(xml)


# ---------- 1. bìa: lấy khung, logo từ template ----------
tkids = list(tpl.element.body.iterchildren())
rid_map = {}
def import_rids(el):
    for node in el.iter():
        for attr in (qn("r:embed"), qn("r:id"), qn("r:link")):
            v = node.get(attr)
            if v:
                if v not in rid_map:
                    blob = tpl.part.related_parts[v].blob
                    rid_map[v], _ = doc.part.get_or_add_image(io.BytesIO(blob))
                node.set(attr, rid_map[v])
    return el

frame = import_rids(copy.deepcopy(tkids[0]))
for e in frame.findall(qn("w:pPr")):
    for s in e.findall(qn("w:pStyle")):
        e.remove(s)
head1, head2, logos = (import_rids(copy.deepcopy(tkids[i])) for i in (1, 2, 3))
for bm in list(head1.iter(qn("w:bookmarkStart"))) + list(head1.iter(qn("w:bookmarkEnd"))):
    bm.getparent().remove(bm)

def cover_p(text, size=28, bold=True, italic=False, before=0, after=0):
    rpr = ("<w:b/><w:bCs/>" if bold else "") + ("<w:i/><w:iCs/>" if italic else "") + '<w:sz w:val="%d"/><w:szCs w:val="%d"/>' % (size, size)
    return parse_xml('<w:p %s><w:pPr><w:spacing w:before="%d" w:after="%d" w:line="360" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr><w:r><w:rPr>%s</w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p>'
                     % (W, before, after, rpr, esc(text)))

def info_table(rows):
    cols = (3400, 500, 3700)
    def cell(w, t, b, left):
        return ('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/></w:tcPr><w:p><w:pPr><w:spacing w:before="40" w:after="40"/><w:ind w:left="%d"/></w:pPr><w:r><w:rPr>%s<w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr><w:t xml:space="preserve">%s</w:t></w:r></w:p></w:tc>'
                % (w, left, "<w:b/>" if b else "", esc(t)))
    trs = "".join("<w:tr>%s</w:tr>" % "".join(cell(w, t, r[3][0], r[3][1] if i == 0 else 0) for i, (w, t) in enumerate(zip(cols, r[:3]))) for r in rows)
    return parse_xml('<w:tbl %s><w:tblPr><w:tblW w:w="0" w:type="auto"/><w:jc w:val="center"/><w:tblLayout w:type="fixed"/><w:tblCellMar><w:left w:w="0" w:type="dxa"/><w:right w:w="0" w:type="dxa"/></w:tblCellMar></w:tblPr><w:tblGrid>%s</w:tblGrid>%s</w:tbl>'
                     % (W, "".join('<w:gridCol w:w="%d"/>' % w for w in cols), trs))

hb, nb = (True, 0), (False, 300)
cover = [frame, head1, head2, logos,
         cover_p("MÔN: PHÁT TRIỂN PHẦN MỀM HƯỚNG DỊCH VỤ", before=1400),
         cover_p("BÀI TẬP LỚN: HỆ THỐNG WATTPRINT", before=120),
         cover_p("Theo dõi điện năng từng thiết bị và trợ lý năng lượng cá nhân hóa cho hộ gia đình", size=26, bold=False, after=360),
         info_table([("Giảng viên", ":", "Nguyễn Việt Dũng", (True, 0)),
                     ("Mã lớp", ":", "INT1448-20261-01", (True, 0)),
                     ("Nhóm", ":", "Nhóm 6", (True, 0)),
                     ("Họ và tên", ":", "MSV", (True, 0)),
                     ("Nguyễn Trường Giang", ":", "B23DCCC055", nb),
                     ("Lê Thị Hà", ":", "B23DCCC056", nb),
                     ("Nguyễn Thị Quỳnh Trang", ":", "B23DCCC160", nb)]),
         cover_p("HÀ NỘI, 2026", bold=True, italic=True, before=1500)]

# phần tử cũ: 0-11 là bìa của ref, 12 là đoạn chứa sectPr của bìa
cover_sect = kids[12]
sp = cover_sect.find(qn("w:pPr")).find(qn("w:sectPr"))
for e in sp.findall(qn("w:pgBorders")):
    sp.remove(e)
mar = sp.find(qn("w:pgMar"))
for k in ("top", "right", "bottom", "left"):
    mar.set(qn("w:" + k), "1440")
for el in kids[:12]:
    body.remove(el)
for el in cover:
    cover_sect.addprevious(el)

# ---------- 2. tóm tắt, từ khóa, bảng viết tắt ----------
summary_el, kw_el, abbr_tbl = kids[14], kids[15], kids[23]
for t in C.SUMMARY:
    summary_el.addprevious(P(BODYPPR, runs(t)))
body.remove(summary_el)
kw_el.getparent().replace(kw_el, P('<w:spacing w:after="120" w:line="312" w:lineRule="auto"/><w:jc w:val="both"/>', runs("Từ khóa: " + C.KEYWORDS, italic=True)))

trs = abbr_tbl.findall(qn("w:tr"))
proto = trs[1]
for tr in trs[1:]:
    abbr_tbl.remove(tr)
for k, v in C.ABBR:
    tr = copy.deepcopy(proto)
    tcs = tr.findall(qn("w:tc"))
    for tc, text in zip(tcs, (k, v)):
        ts = list(tc.iter(qn("w:t")))
        ts[0].text = text
        for extra in ts[1:]:
            extra.getparent().getparent().remove(extra.getparent())
    abbr_tbl.append(tr)

# mục lục: dùng style tự đặt tên Heading1..3 nên chỉ định rõ cho TOC
for it in doc.element.body.iter(qn("w:instrText")):
    if it.text and it.text.strip().startswith("TOC \\h \\o"):
        it.text = 'TOC \\h \\t "Heading1,1,Heading2,2"'

# ---------- 3. xóa thân cũ (từ CHƯƠNG 1 đến hết, trừ sectPr cuối) ----------
for el in kids[26:-1]:
    body.remove(el)

# ---------- 4. ghi thân mới ----------
LEGEND_CROP = {"03-component-core", "04-component-nilm", "05-component-insight", "06-component-copilot",
               "x2-dynamic-ingest-nilm", "x5-dynamic-saving-plan-saga"}

def figure_path(key):
    """Cắt bỏ khung chú giải bên phải (đã giải thích bằng lời) để chữ trong sơ đồ lớn hơn khi thu về bề rộng trang."""
    src = FIG / (key + ".png")
    if key not in LEGEND_CROP:
        return src
    import numpy as np
    im = Image.open(src).convert("RGB")
    a = np.array(im.convert("L"))
    nonwhite = (a < 245).sum(axis=0)
    run, cut = 0, None
    for x in range(int(im.width * 0.6), im.width):
        if nonwhite[x] == 0:
            run += 1
        else:
            if run > 40 and cut is None:
                cut = x - run
            run = 0
    out = FIG / "_crop"
    out.mkdir(exist_ok=True)
    dst = out / (key + ".png")
    im.crop((0, 0, min(im.width, (cut or im.width) + 30), im.height)).save(dst)
    return dst

def figure(key, caption, w, h):
    png = figure_path(key)
    p = doc.add_paragraph()
    p._p.insert(0, parse_xml('<w:pPr %s><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:jc w:val="center"/></w:pPr>' % W))
    im = Image.open(png)
    p.add_run().add_picture(str(png), width=Cm(min(16.0, 17.0 * im.width / im.height)))
    add(P('<w:pStyle w:val="HinhCaption"/>', runs(caption)))

n_h1 = 0
for blk in C.BODY:
    kind = blk[0]
    if kind == "h1":
        n_h1 += 1
        add(P('<w:pStyle w:val="Heading1"/>%s<w:jc w:val="center"/>' % ("<w:pageBreakBefore/>" if n_h1 > 1 else ""), runs(blk[1])))
    elif kind in ("h2", "h3"):
        add(P('<w:pStyle w:val="Heading%s"/>' % kind[1], runs(blk[1])))
    elif kind == "p":
        add(P(BODYPPR, runs(blk[1])))
    elif kind in ("ul", "ol"):
        for i, item in enumerate(blk[1], 1):
            mark = "%d. " % i if kind == "ol" else "• "
            add(P(LISTPPR, runs(mark + item)))
    elif kind == "table":
        add(P('<w:pStyle w:val="BangCaption"/>', runs(blk[1])))
        add(table(blk[2], blk[3], blk[4]))
        add(P('<w:spacing w:after="0"/>', ""))
    elif kind == "fig":
        figure(*blk[1:])
    else:
        raise ValueError(kind)

add(P('<w:pStyle w:val="Heading1"/><w:pageBreakBefore/><w:jc w:val="center"/>', runs("TÀI LIỆU THAM KHẢO")))
for k, n in sorted(cites.items(), key=lambda x: x[1]):
    add(P('<w:spacing w:after="120" w:line="312" w:lineRule="auto"/><w:ind w:left="567" w:hanging="567"/>', runs("[%d] %s" % (n, C.REFS[k]))))
unused = set(C.REFS) - set(cites)
assert not unused, unused

# ---------- 5. dọn ảnh mồ côi của ref ----------
xml = body.xml if hasattr(body, "xml") else ""
from lxml import etree
used = set(re.findall(r'r:(?:embed|id|link)="(rId\d+)"', etree.tostring(doc.element, encoding="unicode")))
for rid, rel in list(doc.part.rels.items()):
    if rel.reltype.endswith("/image") and rid not in used:
        del doc.part.rels[rid]

cp = doc.core_properties
cp.title = "WattPrint - Báo cáo bài tập lớn Phát triển phần mềm hướng dịch vụ"
cp.author = "Nhóm WattPrint"
doc.save(OUT)
print("saved", OUT, "cites", len(cites))
