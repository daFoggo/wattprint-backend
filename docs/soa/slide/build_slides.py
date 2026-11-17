"""Dựng slide SOA WattPrint (14 trang, 1920x1080 px = 20x11.25 in). Chạy: python build_slides.py out.pptx"""
import sys, os
from pptx import Presentation
from pptx.util import Emu, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
A = lambda n: os.path.join(HERE, "assets", n)
INK, GREEN, SAGE, PALE, MUTED, HAIR, LIME = "16392C", "278453", "DFECDD", "F1F7EF", "526B5E", "CBDACE", "C9EB88"
AMBER, AMBER_BG, PURPLE_BG, PURPLE, TEAL_BG, TEAL, WHITE = "C2570C", "FDEBD6", "E9E3FF", "6D4FD8", "D6F5EC", "0F7B73", "FFFFFF"
REG, SEMI, BOLD, MONO = "Geist", "Geist SemiBold", "Geist", "Geist Mono"
SLIDE_W, SLIDE_H = 1920, 1080

prs = Presentation()
prs.slide_width, prs.slide_height = Emu(SLIDE_W * 9525), Emu(SLIDE_H * 9525)
BLANK = prs.slide_layouts[6]
px = lambda v: Emu(int(round(v * 9525)))
rgb = lambda h: RGBColor.from_string(h)


def rect(s, x, y, w, h, fill=None, line=None, r=0, lw=2, dash=False, shape=None):
    shp = s.shapes.add_shape(shape or (MSO_SHAPE.ROUNDED_RECTANGLE if r else MSO_SHAPE.RECTANGLE), px(x), px(y), px(w), px(h))
    if r and shape is None:
        shp.adjustments[0] = min(0.5, r / min(w, h))
    if fill: shp.fill.solid(); shp.fill.fore_color.rgb = rgb(fill)
    else: shp.fill.background()
    if line:
        shp.line.color.rgb = rgb(line); shp.line.width = Pt(lw * .75)
        if dash: shp.line.dash_style = 4
    else: shp.line.fill.background()
    shp.shadow.inherit = False
    shp.text_frame.text = ""
    return shp


def text(s, x, y, w, h, paras, size=26, color=INK, font=REG, align="l", anchor="t", lh=1.2, after=0):
    """paras: str | list of paragraphs; paragraph = str | list of runs; run = str | (str, {size,color,font})"""
    tb = s.shapes.add_textbox(px(x), px(y), px(w), px(h))
    tf = tb.text_frame; tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    if isinstance(paras, str): paras = [paras]
    for i, p in enumerate(paras):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        para.line_spacing = lh; para.space_after = Pt(after * .75)
        for r in ([p] if isinstance(p, (str, tuple)) else p):
            t, o = (r, {}) if isinstance(r, str) else r
            run = para.add_run(); run.text = t
            f = run.font; f.size = Pt(o.get("size", size) * .75); f.name = o.get("font", font)
            f.color.rgb = rgb(o.get("color", color)); f.bold = False
    return tb


def arrow(s, x1, y1, x2, y2, color=GREEN, dash=False, lw=3, both=False):
    c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, px(x1), px(y1), px(x2), px(y2))
    c.line.color.rgb = rgb(color); c.line.width = Pt(lw * .75)
    ln = c.line._get_or_add_ln()
    if dash: ln.append(etree.SubElement(ln, qn("a:prstDash"), val="dash"))
    for tag in (["a:tailEnd"] + (["a:headEnd"] if both else [])):
        ln.append(etree.SubElement(ln, qn(tag), type="triangle", w="med", len="med"))
    return c


def img(s, name, x, y, w, h):
    iw, ih = Image.open(A(name)).size
    k = min(w / iw, h / ih); w2, h2 = iw * k, ih * k
    s.shapes.add_picture(A(name), px(x + (w - w2) / 2), px(y + (h - h2) / 2), px(w2), px(h2))


TOTAL = 14


def base(n, title, kicker=None):  # kicker = dòng mô tả dưới tiêu đề
    s = prs.slides.add_slide(BLANK)
    text(s, 86, 36, 300, 34, "WattPrint", 28, INK, SEMI)
    text(s, 1100, 42, 560, 30, "SOA · Nhóm 6", 22, MUTED, REG, "r")
    img(s, "logo-ptit.png", 1752, 24, 90, 58)
    text(s, 1834 - 80, 1030, 80, 26, f"{n}/{TOTAL}", 20, MUTED, REG, "r")
    text(s, 86, 98, 1748, 70, title, 56, INK, SEMI, lh=1.1)
    if kicker: text(s, 86, 176, 1748, 40, kicker, 27, MUTED, REG)
    return s


def chip(s, x, y, w, h, label, fill=SAGE, color=INK, size=24, font=SEMI, line=None, r=14):
    rect(s, x, y, w, h, fill, line, r)
    text(s, x, y, w, h, label, size, color, font, "c", "m")


# ───────────── 1. Bìa ─────────────
s = prs.slides.add_slide(BLANK)
rect(s, 1080, 0, 840, 1080, PALE)
text(s, 86, 60, 900, 30, "BÀI TẬP LỚN · PHÁT TRIỂN PHẦN MỀM HƯỚNG DỊCH VỤ", 22, GREEN, SEMI)
img(s, "logo-ptit.png", 1752, 40, 90, 58)
text(s, 80, 250, 940, 180, "WattPrint", 170, INK, SEMI, lh=1.0)
text(s, 86, 450, 900, 140, "Kiến trúc hướng dịch vụ cho hệ thống theo dõi điện năng từng thiết bị trong hộ gia đình", 40, INK, REG, lh=1.25)
rect(s, 86, 650, 120, 6, GREEN)
text(s, 86, 690, 900, 40, "Nhóm 6 · Lớp INT1448-20261-01", 30, INK, SEMI)
text(s, 86, 740, 900, 40, "Giảng viên: Nguyễn Việt Dũng", 28, MUTED)
text(s, 86, 810, 900, 150, [[("B23DCCC055", {"font": MONO, "color": GREEN}), "   Nguyễn Trường Giang"],
                            [("B23DCCC056", {"font": MONO, "color": GREEN}), "   Lê Thị Hà"],
                            [("B23DCCC160", {"font": MONO, "color": GREEN}), "   Nguyễn Thị Quỳnh Trang"]], 26, INK, REG, lh=1.45)
text(s, 86, 1010, 400, 30, "Hà Nội, 2026", 22, MUTED)
# minh họa: gateway + năm service, xếp theo luồng nghiệp vụ
text(s, 1170, 200, 660, 30, "MỘT GATEWAY, NĂM SERVICE ĐỘC LẬP", 21, GREEN, SEMI)
rect(s, 1170, 250, 660, 78, PURPLE_BG, PURPLE, 18, 2)
text(s, 1170, 250, 660, 78, "API Gateway · Envoy", 30, INK, SEMI, "c", "m")
names = ["nilm", "core", "insight", "copilot", "text2sql"]
w = 120
for i, nm in enumerate(names):
    x = 1170 + i * (w + 15)
    arrow(s, x + w / 2, 328, x + w / 2, 430, MUTED if nm in ("nilm", "text2sql") else GREEN, dash=nm in ("nilm", "text2sql"), lw=3)
    rect(s, x, 430, w, 150, SAGE, GREEN, 22, 3)
    text(s, x, 430, w, 150, nm, 23, INK, SEMI, "c", "m")
    rect(s, x + 6, 640, w - 12, 70, TEAL_BG, TEAL, 16, 2)
    text(s, x + 6, 640, w - 12, 70, nm + "_db", 15, INK, REG, "c", "m")
    arrow(s, x + w / 2, 580, x + w / 2, 640, TEAL, lw=3)
text(s, 1170, 760, 660, 80, "Sắp xếp theo luồng biến đổi dữ liệu: bên cần số liệu chủ động gọi đồng bộ, cập nhật trạng thái phát tán qua event.", 25, MUTED, REG, lh=1.3)

# ───────────── 2. WattPrint là gì ─────────────
s = base(2, "Bài toán và giải pháp WattPrint", "Tách công suất từng thiết bị chỉ từ một điểm đo tại aptomat tổng và tư vấn tiết kiệm cá nhân hóa.")
# dải ý tưởng
fy = 300
chip(s, 86, fy, 330, 74, "Sensor CT ở aptomat", PALE, INK, 25, SEMI, HAIR)
arrow(s, 420, fy + 37, 486, fy + 37)
chip(s, 490, fy, 330, 74, "Chuỗi công suất tổng", PALE, INK, 25, SEMI, HAIR)
arrow(s, 824, fy + 37, 890, fy + 37)
chip(s, 894, fy, 330, 74, "Mô hình NILM bóc tách", GREEN, WHITE, 25, SEMI, GREEN)
arrow(s, 1228, fy + 37, 1294, fy + 37)
chip(s, 1298, fy, 536, 74, "Chi phí và khuyến nghị từng thiết bị", PALE, INK, 25, SEMI, HAIR)
mods = [("Tách phụ tải (NILM)", "Mô hình NILMFormer bóc tách công suất từng thiết bị từ đường cong tổng, hiệu chỉnh theo hộ.", "phone-03_device_01_detail.png"),
        ("Dashboard và hóa đơn", "Tổng hợp kWh theo giờ, ngày, tuần, tháng và quy đổi ra tiền theo biểu giá sinh hoạt 5 bậc.", "phone-02_usage_02_device_breakdown.png"),
        ("Phân tích và dự báo", "Phát hiện thiết bị chạy bất thường hoặc chạy ngầm, dự báo hóa đơn, đối chiếu với nhóm hộ tương đồng.", "phone-02_usage_01_chart.png"),
        ("Energy Copilot", "Hỏi đáp hai chiều, chủ động gợi ý và lập kế hoạch tiết kiệm, mọi con số đều do công cụ tính.", "phone-04_copilot_01_thread_chat.png")]
cw, gap, cy, ch = 410, 36, 420, 570
for i, (t, d, im) in enumerate(mods):
    x = 86 + i * (cw + gap)
    rect(s, x, cy, cw, ch, PALE, None, 24)
    img(s, im, x + 40, cy + 24, cw - 80, 270)
    text(s, x + 32, cy + 318, cw - 64, 40, t, 31, INK, SEMI)
    text(s, x + 32, cy + 366, cw - 64, 190, d, 24, MUTED, REG, lh=1.3)
text(s, 86, 1004, 1640, 30, [[("Tác nhân  ", {"font": SEMI, "color": GREEN}), "thành viên hộ gia đình (app, web), nhóm vận hành (quản trị model, DLQ, catalog).   ", ("Nguồn đo  ", {"font": SEMI, "color": GREEN}), "sensor CT tại tủ điện (trong đồ án giả lập bằng REFIT replayer)."]], 21, MUTED)

# ───────────── 3. Quy tắc nghiệp vụ ─────────────
s = base(3, "Quy tắc nghiệp vụ và ranh giới dữ liệu", "Mỗi quy tắc gắn với một miền dữ liệu và do đúng một service kiểm soát bằng mã trả về 4xx.")
# tác nhân
actors = [("Thành viên hộ gia đình", "tra cứu điện năng, hóa đơn, tương tác Copilot"), ("Nhóm vận hành", "quản lý model, catalog, xử lý message DLQ"),
          ("Sensor tại aptomat", "đẩy định kỳ từng batch mẫu đo công suất")]
aw = (1748 - 2 * 24) / 3
for i, (t, d) in enumerate(actors):
    x = 86 + i * (aw + 24)
    rect(s, x, 250, aw, 86, PALE, None, 18)
    rect(s, x, 250, 8, 86, GREEN)
    text(s, x + 30, 250, aw - 40, 86, [[(t, {"font": SEMI, "size": 25})], [(d, {"size": 20, "color": MUTED})]], 22, INK, REG, "l", "m", 1.2)
# bảng quy tắc → service → khi vi phạm
cols = [("Quy tắc nghiệp vụ (BR1 – BR9)", 610), ("Tình huống vi phạm", 520), ("Service thực thi", 250), ("Phản hồi của hệ thống", 350)]
x = 86
for t, w in cols:
    rect(s, x, 362, w, 50, GREEN, None, 12)
    text(s, x + 18, 362, w - 30, 50, t, 21, WHITE, SEMI, "l", "m")
    x += w + 6
rules = [("BR1 · Mỗi tài khoản thuộc một hộ, mã mời dùng một lần có hạn", "Nhập lại mã mời đã sử dụng hoặc hết hạn", "core", "Từ chối, trả 4xx kèm lý do"),
         ("BR2 · Chỉ nhận mẫu đo từ công tơ đã ghép nối kèm API key", "Thiết bị chưa ghép nối đẩy dữ liệu lên", "core", "Từ chối batch, trả 401/403"),
         ("BR3 · Batch mẫu đo phải idempotent, không hở hoặc chồng lấp", "Cảm biến gửi lặp batch cũ khi rớt mạng", "core", "409 Conflict, không ghi lặp"),
         ("BR4 · Tính tiền theo đúng phiên bản biểu giá 5 bậc của kỳ", "Biểu giá nhà nước thay đổi sang kỳ mới", "core", "Áp dụng bản hiệu lực của kỳ"),
         ("BR5 · Ngưỡng dữ liệu tối thiểu: dự báo 7 ngày, nhóm 10 hộ, M&V 14 ngày", "Hộ mới lắp đặt 3 ngày yêu cầu dự báo tháng", "insight", "422 kèm nguyên nhân"),
         ("BR6, BR7 · Copilot chỉ mở cho gói Pro, giới hạn số thông báo/ngày", "Tài khoản gói thường gọi API hội thoại", "copilot", "403 Forbidden"),
         ("BR8 · Con số phải do tool tính từ dữ liệu hộ, LLM chỉ diễn giải", "LLM tự sinh số tiền lệch kết quả tool", "copilot", "Verifier chặn và loại bỏ"),
         ("BR9 · Ẩn PII trước khi gọi LLM, cô lập truy vấn theo hộ đang hỏi", "Truy vấn cố đọc dữ liệu của hộ khác", "copilot · text2sql", "View lọc theo app.home_id")]
for i, row in enumerate(rules):
    y = 420 + i * 70
    rect(s, 86, y, 1748, 64, PALE if i % 2 == 0 else WHITE, None if i % 2 == 0 else HAIR, 12)
    x = 86
    for k, (v, (_, w)) in enumerate(zip(row, cols)):
        if k == 2: chip(s, x + 14, y + 12, w - 28, 40, v, SAGE, INK, 19, SEMI, GREEN, 10)
        else: text(s, x + 18, y, w - 30, 64, v, 20, AMBER if k == 3 and v[0].isdigit() else INK, SEMI if k == 3 and v[0].isdigit() else REG, "l", "m", 1.15)
        x += w + 6

# ───────────── 4. Năm service ─────────────
s = base(4, "Phân rã hệ thống thành năm service", "Tách từ monolith theo ba tiêu chí ưu tiên: quyền sở hữu dữ liệu, đặc thù tải và phạm vi cô lập lỗi.")
labx, colx0, colw, colgap = 86, 400, 272, 12
svc = [("core", "Hồ sơ hộ, thiết bị, ingest mẫu đo, tính hóa đơn. Giữ vai trò source of truth.", "core_db · TimescaleDB", "Tần suất ghi đều, đòi hỏi độ trễ thấp", "Bảo toàn tuyệt đối chuỗi mẫu đo từ công tơ"),
       ("nilm", "Chạy inference NILMFormer, hiệu chỉnh theo hộ, quản lý model.", "nilm_db · volume model", "Chạy PyTorch, tiêu tốn nhiều CPU và RAM", "Khi quá tải, batch ở core chuyển sang chờ PENDING"),
       ("insight", "Read model tiêu thụ, cảnh báo, dự báo, M&V, view cho text2sql.", "insight_db · TimescaleDB", "Quét phân tích theo lô và theo lịch định kỳ", "Nếu tạm dừng, luồng ingest ở core vẫn chạy bình thường"),
       ("copilot", "Hỏi đáp, gợi ý chủ động, guardrail, RAG, điều phối saga tiết kiệm.", "copilot_db · Qdrant", "Phần lớn thời gian chờ phản hồi mạng từ LLM", "Cô lập độ trễ của LLM, không làm nghẽn dashboard"),
       ("text2sql", "Truy vấn số liệu tự do: quản lý catalog, lập plan, biên dịch SQL.", "text2sql_db · Qdrant", "Chờ LLM lập plan, worker đồng bộ vector catalog", "Nếu lỗi, copilot tự chuyển sang bộ tool cố định của insight")]
rows = [("Trách nhiệm chính", 156), ("1  Data ownership", 90), ("2  Workload", 110), ("3  Fault isolation", 126)]
y0 = 270
for i, (nm, *_) in enumerate(svc):
    x = colx0 + i * (colw + colgap)
    chip(s, x, y0, colw, 70, nm, GREEN, WHITE, 30, SEMI, None, 16)
yy = y0 + 90
for ri, (lab, h) in enumerate(rows):
    fill = PALE if ri % 2 == 0 else WHITE
    rect(s, labx, yy, 1748, h, fill, None, 14)
    text(s, labx + 20, yy, 290, h, lab, 24, GREEN if ri else MUTED, SEMI, "l", "m")
    for i, v in enumerate(svc):
        x = colx0 + i * (colw + colgap)
        txt = v[ri + 1]
        text(s, x + 12, yy + 10, colw - 24, h - 20, txt, 21, INK, REG, "l", "m", 1.22)
    yy += h + 8
rect(s, 86, yy + 14, 1748, 110, GREEN, None, 20)
text(s, 126, yy + 14, 1670, 110, [[("Tính tự chủ (Service Autonomy): ", {"font": SEMI}), "mỗi service làm chủ schema dữ liệu riêng, đóng gói độc lập và chỉ giao tiếp qua hợp đồng API hoặc sự kiện."]], 28, WHITE, REG, "l", "m", 1.3)

# ───────────── 5. Kiến trúc tổng quan ─────────────
s = base(5, "Kiến trúc tổng quan mức Container (C4)", "Mọi yêu cầu đi qua cổng Envoy Gateway, năm service xếp theo luồng biến đổi dữ liệu.")
X0, W = 86, 1330
# clients
cl = [("App Expo", GREEN), ("Web Next.js", GREEN), ("REFIT replayer", AMBER)]
for i, (nm, col) in enumerate(cl):
    x = X0 + 20 + i * 330
    chip(s, x, 290, 260, 64, nm, SAGE if col == GREEN else AMBER_BG, INK, 24, SEMI, col, 16)
    arrow(s, x + 130, 354, x + 130, 410)
text(s, X0 + 20 + 2 * 330 + 274, 296, 170, 60, "giả lập sensor CT từ dataset REFIT", 17, MUTED, REG, "l", "m", 1.15)
# keycloak (trên) + gateway (toàn chiều ngang để route tới đủ 5 service)
rect(s, X0 + 1130, 282, 200, 80, PURPLE_BG, PURPLE, 18, 2)
text(s, X0 + 1130, 282, 200, 80, [[("Keycloak", {"font": SEMI})], [("định danh · JWKS", {"size": 19, "color": MUTED})]], 26, INK, REG, "c", "m", 1.15)
arrow(s, X0 + 1230, 410, X0 + 1230, 362, PURPLE, lw=2)
rect(s, X0, 410, 1330, 80, PURPLE_BG, PURPLE, 18, 2)
text(s, X0, 410, 1330, 80, [[("API Gateway · Envoy", {"font": SEMI, "size": 29})], [("xác thực JWT · định tuyến · rate limit · nhánh /nilm và /text2sql chỉ mở cho admin", {"size": 20, "color": MUTED})]], 26, INK, REG, "c", "m", 1.15)
# services row: theo luồng dữ liệu, mọi call nối hai ô kề nhau
order = [("nilm", "tách phụ tải NILM", "nilm_db", "PostgreSQL"), ("core", "hộ · mẫu đo · hóa đơn", "core_db", "TimescaleDB"),
         ("insight", "cảnh báo · dự báo · M&V", "insight_db", "TimescaleDB"), ("copilot", "hỏi đáp · gợi ý · RAG", "copilot_db", "PostgreSQL"),
         ("text2sql", "truy vấn số liệu", "text2sql_db", "PostgreSQL")]
sw, sgap = 226, 50
sx = [X0 + i * (sw + sgap) for i in range(5)]
for i, (nm, sub, db, ext) in enumerate(order):
    x = sx[i]
    is_admin = nm in ("nilm", "text2sql")
    arrow(s, x + sw / 2, 490, x + sw / 2, 580, MUTED if is_admin else GREEN, dash=is_admin)
    rect(s, x, 580, sw, 130, SAGE, GREEN, 22, 3)
    text(s, x, 580, sw, 130, [[(nm, {"font": SEMI, "size": 30})], [(sub, {"size": 18, "color": MUTED})]], 26, INK, REG, "c", "m", 1.2)
    arrow(s, x + sw / 2, 710, x + sw / 2, 780, TEAL)
    rect(s, x + 13, 780, sw - 26, 84, TEAL_BG, TEAL, 16, 2)
    text(s, x + 13, 780, sw - 26, 84, [[(db, {"font": SEMI, "size": 21})], [(ext, {"size": 17, "color": MUTED})]], 22, INK, REG, "c", "m", 1.15)
# call đồng bộ: (bên gọi, bên bị gọi); event: core → insight → copilot
for a, b in ((1, 0), (2, 1), (3, 2), (3, 4)):
    xl, xr = sx[min(a, b)] + sw, sx[max(a, b)]
    arrow(s, xr - 4 if a > b else xl + 4, 628, xl + 4 if a > b else xr - 4, 628, INK, lw=3)
    text(s, xl - 6, 592, xr - xl + 12, 26, "REST", 17, MUTED, REG, "c")
for a, b in ((1, 2), (2, 3)):
    xl, xr = sx[a] + sw, sx[b]
    arrow(s, xl + 4, 672, xr - 4, 672, AMBER, dash=True, lw=3)
    text(s, xl - 10, 678, xr - xl + 20, 26, "event", 16, AMBER, REG, "c")
# hạ tầng chung
rect(s, X0, 900, 1330, 80, PURPLE_BG, PURPLE, 18, 2)
text(s, X0, 900, 1330, 80, [[("Hạ tầng dùng chung  ", {"font": SEMI}), "PostgreSQL 18 (6 database tách theo role) · Qdrant (2 collection vector) · RabbitMQ"]], 21, INK, REG, "c", "m")
# LLM ngoài
text(s, X0, 990, 900, 30, "Dịch vụ ngoài: LLM provider (copilot, text2sql), Open-Meteo (insight), Expo Push & Telegram (copilot)", 17, AMBER, REG, "l")
# cột ghi chú
nx = 1500
notes = [("Loose coupling", "Đồ thị gọi đồng bộ không tạo vòng: core → nilm, insight → core, copilot → insight, copilot → text2sql."),
         ("Event choreography", "Luồng cập nhật core → insight → copilot đi qua RabbitMQ, bên phát không phải chờ bên nhận."),
         ("Database per service", "Mỗi service sở hữu database riêng. Ngoại lệ duy nhất: text2sql đọc view công bố của insight.")]
for i, (t, d) in enumerate(notes):
    y = 290 + i * 230
    rect(s, nx, y, 334, 6, [INK, AMBER, TEAL][i])
    text(s, nx, y + 22, 334, 40, t, 27, INK, SEMI)
    text(s, nx, y + 70, 334, 150, d, 22, MUTED, REG, lh=1.3)

# ───────────── 6. Dữ liệu ─────────────
s = base(6, "Tổ chức và cô lập dữ liệu", "Sáu database tách biệt bằng DB role trên PostgreSQL 18, kết hợp hai collection vector trên Qdrant.")
rect(s, 86, 290, 880, 690, TEAL_BG, TEAL, 24, 2)
text(s, 120, 316, 800, 34, "MỘT INSTANCE PostgreSQL 18 · TimescaleDB 2.31 · 6 DATABASE", 21, TEAL, SEMI)
dbs = [("nilm_db", "PostgreSQL", "nhật ký chạy model", "role nilm"), ("core_db", "TimescaleDB", "mẫu đo, hóa đơn", "role core"),
       ("insight_db", "TimescaleDB", "read model, view", "role insight"), ("copilot_db", "PostgreSQL", "hội thoại, tài liệu RAG", "role copilot"),
       ("text2sql_db", "PostgreSQL", "catalog, phiên truy vấn", "role text2sql"), ("keycloak_db", "PostgreSQL", "định danh, realm", "role keycloak")]
for i, (nm, ext, d, role) in enumerate(dbs):
    col, row = i % 2, i // 2
    x, y = 120 + col * 420, 372 + row * 148
    rect(s, x, y, 396, 134, WHITE, TEAL, 18, 2)
    text(s, x + 22, y + 12, 352, 36, nm, 27, INK, SEMI)
    text(s, x + 22, y + 52, 352, 30, ext + " · " + d, 20, MUTED)
    text(s, x + 22, y + 92, 352, 30, role, 18, TEAL, MONO)
text(s, 120, 824, 816, 140, "Chỉ mục vector đặt trên Qdrant (collection riêng cho copilot và text2sql), văn bản gốc vẫn giữ ở PostgreSQL. Không service nào có quyền vào DB của service khác, trừ role chỉ đọc text2sql_ro.", 20, INK, REG, lh=1.3)
text(s, 1010, 290, 824, 34, "CƠ CHẾ CHIA SẺ DỮ LIỆU LIÊN SERVICE", 21, GREEN, SEMI)
for i, (t, d) in enumerate([("Đồng bộ bản sao qua sự kiện (CQRS)", "core tối ưu cho luồng ghi và giữ source of truth, còn insight duy trì read model tiêu thụ tổng hợp theo giờ từ sự kiện của core."),
                            ("Truy vấn trực tiếp qua REST API", "Khi cần dữ liệu cấu hình nhỏ hoặc mới nhất, service gọi thẳng API của bên sở hữu (như insight lấy biểu giá và thiết bị từ core).")]):
    y = 340 + i * 160
    rect(s, 1010, y, 824, 140, PALE, None, 20)
    rect(s, 1010, y, 10, 140, GREEN)
    text(s, 1048, y + 16, 760, 36, t, 27, INK, SEMI)
    text(s, 1048, y + 58, 760, 80, d, 22, MUTED, REG, lh=1.28)
rect(s, 1010, 670, 824, 310, GREEN, None, 24)
text(s, 1046, 692, 750, 36, "Ba lớp bảo vệ truy vấn Text-to-SQL", 28, WHITE, SEMI)
text(s, 1046, 740, 750, 230, "1. LLM không tự viết SQL mà chỉ lập plan theo ID trong catalog, bộ biên dịch sqlglot tự dựng câu SELECT.\n2. Thực thi bằng role chỉ đọc text2sql_ro trên các view công bố của insight_db.\n3. View khóa cứng điều kiện lọc theo nhà người hỏi (app.home_id), không chạm vào core_db.", 21, WHITE, REG, lh=1.28)

# ───────────── 7. API REST ─────────────
s = base(7, "Hợp đồng giao tiếp: REST API và OpenAPI", "Mỗi service tự xuất đặc tả OpenAPI từ FastAPI, pipeline CI kiểm tra tự động để tránh lệch hợp đồng.")
cols = [("Service", 210), ("Các REST endpoint tiêu biểu", 900), ("Thực thi quy tắc nghiệp vụ (4xx)", 610)]
api = [("nilm", "POST /inferences · GET /models · POST /models · PUT /models/{id}/active", "422 cửa sổ mẫu đo sai chu kỳ hoặc thiếu điểm dữ liệu"),
       ("core", "POST /homes · POST /homes/{id}/invites · POST /meters/pair · POST /ingest/batches · GET /bills/{period}", "409 batch trùng Idempotency-Key, bị hở hoặc chồng lấp thời gian"),
       ("insight", "GET /usage · GET /forecast · PUT /homes/{id}/budget · POST /what-if · POST|DELETE /savings-measures", "422 dự báo dưới 7 ngày, nhóm dưới 10 hộ, M&V dưới 14 ngày"),
       ("copilot", "POST /conversations · POST /conversations/{id}/messages · POST /plans · POST /suggestions/{id}/feedback", "403 tài khoản chưa đăng ký gói Pro, 409 vướng kiểm duyệt"),
       ("text2sql", "POST /text2sql/chat (SSE nội bộ) · GET|POST /metrics · GET|POST /glossary · POST /ingestion/sync", "409 câu hỏi chạm nhiều đường nối bảng, cần người hỏi xác nhận")]
x = 86
for t, w in cols:
    rect(s, x, 270, w - 8, 52, GREEN, None, 12)
    text(s, x + 18, 270, w - 40, 52, t, 22, WHITE, SEMI, "l", "m")
    x += w + 6
for i, (nm, eps, rule) in enumerate(api):
    y = 334 + i * 118
    rect(s, 86, y, 1748, 108, PALE if i % 2 == 0 else WHITE, HAIR if i % 2 else None, 14)
    text(s, 104, y, 190, 108, nm, 27, INK, SEMI, "l", "m")
    text(s, 302, y + 8, 880, 92, eps, 19, INK, MONO, "l", "m", 1.3)
    text(s, 1208, y + 8, 610, 92, rule, 20, INK, REG, "l", "m", 1.25)
text(s, 86, 930, 1748, 70, [[("Quy ước mã trạng thái  ", {"font": SEMI, "color": GREEN}), "201 hoàn tất tạo mới · 202 đã ghi nhận và chờ xử lý nền (PENDING) · 4xx vi phạm quy tắc nghiệp vụ · 503, 504 sự cố hạ tầng. Mọi service đều mở GET /health và GET /ready."]], 21, MUTED, REG, "l", "m", 1.3)

# ───────────── 8. Đồng bộ hay bất đồng bộ ─────────────
s = base(8, "Phân định giao tiếp đồng bộ và bất đồng bộ", "Gọi REST đồng bộ khi cần ngay kết quả để xử lý bước tiếp. Phát sự kiện AMQP khi chỉ thông báo thay đổi trạng thái.")
kinds = [("Đồng bộ · HTTP REST / SSE (Orchestration)", GREEN, PALE,
          ["Cần dữ liệu trả về ngay để phản hồi thao tác người dùng", "Truy vấn cấu hình nhỏ cần giá trị mới nhất tại nguồn", "Cần biết rõ bước hiện tại thành công hay thất bại để rẽ nhánh"],
          "Đánh đổi: phụ thuộc thời gian chạy giữa hai bên, bắt buộc bọc timeout, retry, circuit breaker"),
         ("Bất đồng bộ · RabbitMQ Event (Choreography)", AMBER, AMBER_BG,
          ["Thông báo một sự kiện đã hoàn tất, bên phát không cần đợi", "Tác vụ phía sau tốn thời gian (cập nhật read model, gọi LLM)", "Bảo toàn thông điệp trong hàng đợi ngay cả khi bên nhận tạm dừng"],
          "Đánh đổi: nhất quán cuối cùng (eventual consistency), cần bảng outbox, inbox và hàng đợi DLQ")]
kw = (1748 - 28) / 2
for i, (t, col, bg, pts, cost) in enumerate(kinds):
    x = 86 + i * (kw + 28)
    rect(s, x, 250, kw, 300, bg, None, 22)
    rect(s, x, 250, kw, 8, col)
    text(s, x + 30, 274, kw - 60, 36, t, 26, col, SEMI)
    text(s, x + 30, 324, kw - 60, 150, [["•  " + p] for p in pts], 22, INK, REG, lh=1.3, after=4)
    text(s, x + 30, 486, kw - 60, 40, cost, 20, MUTED, REG)
cols = [("Tương tác liên service trong WattPrint", 640), ("Cơ chế", 250), ("Lý do thiết kế", 846)]
x = 86
for t, w in cols:
    rect(s, x, 578, w, 46, GREEN, None, 12)
    text(s, x + 18, 578, w - 30, 46, t, 20, WHITE, SEMI, "l", "m")
    x += w + 6
cases = [("core → nilm (tách phụ tải khi nhận batch)", 0, "Cần kết quả ước tính ngay để lưu, nếu nilm lỗi thì chuyển batch sang PENDING"),
         ("insight → core (lấy biểu giá, danh mục thiết bị)", 0, "Dữ liệu cấu hình nhỏ, cần bản mới nhất khi tính dự báo"),
         ("copilot → insight, text2sql (lấy số liệu trả lời chat)", 0, "Người dùng đang đợi câu trả lời trực tiếp trên màn hình hội thoại"),
         ("core phát event energy.usage.updated", 1, "Thông báo có số liệu mới, nếu insight bảo trì thì luồng ingest ở core vẫn thông suốt"),
         ("core phát event core.device.changed", 1, "Đồng bộ danh mục thiết bị sang read model của insight, chấp nhận độ trễ vài giây"),
         ("insight phát event insight.alert.created", 1, "Tác vụ gọi LLM biên soạn lời khuyên ở copilot chạy chậm, tách khỏi luồng quét cảnh báo")]
for i, (t, k, why) in enumerate(cases):
    y = 630 + i * 62
    rect(s, 86, y, 1748, 56, PALE if i % 2 == 0 else WHITE, None if i % 2 == 0 else HAIR, 10)
    text(s, 104, y, 620, 56, t, 20, INK, MONO if "." in t.split()[-1] else REG, "l", "m")
    chip(s, 86 + 640 + 6 + 14, y + 9, 222, 38, ["Đồng bộ", "Bất đồng bộ"][k], [SAGE, AMBER_BG][k], INK, 18, SEMI, [GREEN, AMBER][k], 10)
    text(s, 86 + 640 + 250 + 12 + 18, y, 820, 56, why, 20, INK, REG, "l", "m")

# ───────────── 9. Giao tiếp đồng bộ ─────────────
s = base(9, "Độ tin cậy cho giao tiếp đồng bộ (REST)", "Đồ thị gọi một chiều không chu trình, kết hợp năm lớp bảo vệ chịu lỗi dùng chung trong thư viện libs/common.")
# đồ thị gọi, không vòng
for i, nm in enumerate(["nilm", "core", "insight", "copilot", "text2sql"]):
    x = 86 + i * 196
    chip(s, x, 262, 156, 64, nm, SAGE, INK, 23, SEMI, GREEN, 14)
    if i < 4:
        if i == 3: arrow(s, x + 158, 294, x + 194, 294, INK, lw=3)
        else: arrow(s, x + 194, 294, x + 158, 294, INK, lw=3)
text(s, 1086, 256, 748, 76, [[("Đồ thị phụ thuộc không chu trình (DAG)", {"font": SEMI, "color": GREEN})],
                             [("Gọi trực tiếp qua mạng nội bộ Compose, truyền tiếp X-User-*, X-Request-ID và lấy địa chỉ đích từ biến môi trường.", {"size": 18, "color": MUTED})]], 21, INK, REG, "l", "m", 1.2)
cols = [("Cơ chế bảo vệ", 290), ("Rủi ro cần chặn", 430), ("Thiết lập trong WattPrint", 690), ("Phản hồi khi kích hoạt", 320)]
x = 86
for t, w in cols:
    rect(s, x, 356, w, 48, GREEN, None, 12)
    text(s, x + 18, 356, w - 30, 48, t, 21, WHITE, SEMI, "l", "m")
    x += w + 6
mech = [("Timeout", "Service đích bị treo làm giữ chặt worker của bên gọi", "connect 1 s, read 3 s · gọi LLM 20 s · copilot → text2sql 30 s", "504 Gateway Timeout"),
        ("Retry có giới hạn", "Lỗi mạng hoặc kết nối chập chờn thoáng qua", "Tối đa 2 lần kèm backoff + jitter, chỉ áp dụng cho request idempotent. Không retry lỗi 4xx", "Phục hồi ngay ở lần gọi lại"),
        ("Circuit breaker", "Tiếp tục dồn request vào service đang gặp sự cố", "Đặt tại core → nilm, copilot → LLM, copilot → text2sql, text2sql → LLM. Tự mở mạch khi lỗi liên tiếp", "503 + Retry-After tức thì"),
        ("Bulkhead", "Một nhánh xử lý nặng chiếm cạn tài nguyên hệ thống", "Dùng asyncio.Semaphore giới hạn luồng đồng thời vào nilm và LLM, đặt mem_limit, cpus cho từng container", "Các nhánh khác vẫn ổn định"),
        ("Fallback", "Sự cố ở service phụ làm gián đoạn toàn bộ tính năng", "Khi text2sql lỗi, copilot dùng bộ tool cố định của insight. Khi nilm lỗi, core lưu mẫu đo ở trạng thái PENDING", "Giảm nhẹ tính năng, không sập")]
for i, row in enumerate(mech):
    y = 410 + i * 104
    rect(s, 86, y, 1748, 98, PALE if i % 2 == 0 else WHITE, None if i % 2 == 0 else HAIR, 12)
    x = 86
    for k, (v, (_, w)) in enumerate(zip(row, cols)):
        st = [(SEMI, 24, INK), (REG, 20, MUTED), (REG, 20, INK), (SEMI, 20, AMBER if v[0].isdigit() else GREEN)][k]
        text(s, x + 18, y, w - 30, 98, v, st[1], st[2], st[0], "l", "m", 1.2)
        x += w + 6
rect(s, 86, 936, 1748, 74, GREEN, None, 18)
text(s, 118, 936, 1700, 74, [[("Phân biệt mã lỗi  ", {"font": SEMI}), "Giữ nguyên mã 4xx từ service đích (lỗi nghiệp vụ) · Quá hạn chờ trả 504 · Đứt kết nối hoặc ngắt mạch trả 503 · Probe /health và /ready tách biệt"]], 20, WHITE, REG, "l", "m")

# ───────────── 10. Giao tiếp bất đồng bộ ─────────────
s = base(10, "Độ tin cậy cho sự kiện bất đồng bộ (RabbitMQ)", "Kết hợp Transactional Outbox ở đầu phát, Idempotent Inbox ở đầu nhận và Quorum Queue kèm DLQ.")
flow = [("core", "ghi DB + bảng outbox", SAGE, GREEN), ("Outbox relay", "publish, đợi confirm", WHITE, GREEN),
        ("Exchange", "wattprint.events · topic", PURPLE_BG, PURPLE), ("Queue", "insight.usage · quorum", PURPLE_BG, PURPLE),
        ("Consumer insight", "bảng inbox + read model", SAGE, GREEN)]
fw, fg = 300, 62
for i, (t, d, f, l) in enumerate(flow):
    x = 86 + i * (fw + fg)
    rect(s, x, 262, fw, 100, f, l, 16, 2)
    text(s, x, 262, fw, 100, [[(t, {"font": SEMI, "size": 24})], [(d, {"size": 18, "color": MUTED})]], 22, INK, REG, "c", "m", 1.2)
    if i < 4: arrow(s, x + fw + 4, 312, x + fw + fg - 4, 312, GREEN, lw=3)
qx = 86 + 3 * (fw + fg)
arrow(s, qx + fw / 2, 362, qx + fw / 2, 408, AMBER, dash=True)
rect(s, qx - 130, 408, fw + 260, 64, AMBER_BG, AMBER, 14, 2)
text(s, qx - 130, 408, fw + 260, 64, "redeliver quá 3 lần → wattprint.dlx → insight.usage.dlq", 18, INK, SEMI, "c", "m")
text(s, 86, 392, 1000, 90, [[("Ba sự kiện chính  ", {"font": SEMI, "color": GREEN}), ("energy.usage.updated", {"font": MONO}), ", ", ("core.device.changed", {"font": MONO}), " (core → insight)"],
                            [("", {}), ("insight.alert.created", {"font": MONO}), " (insight → copilot). Mỗi nhánh tiêu thụ dùng một quorum queue riêng."]], 19, INK, REG, "l", "t", 1.35)
risks = [("Rơi mất sự kiện", "Tiến trình sập ngay sau khi lưu DB nhưng chưa kịp publish", "Transactional Outbox", "Ghi dữ liệu nghiệp vụ và bản ghi outbox trong cùng một transaction. Tiến trình Relay quét bằng FOR UPDATE SKIP LOCKED và đợi broker confirm."),
         ("Xử lý trùng sự kiện", "Broker giao lại (at-least-once) khiến một message đến hai lần", "Idempotent Consumer", "Kiểm tra khóa message_id trong bảng inbox: nếu đã có thì bỏ qua, nếu chưa có thì cập nhật read model và ghi inbox trong cùng transaction rồi mới ack."),
         ("Kẹt hàng đợi vì lỗi", "Message hỏng (poison message) gây lỗi lặp đi lặp lại", "Delivery-limit + DLQ", "Quorum queue tự đếm số lần nack, vượt quá 3 lần sẽ chuyển sang DLQ để bảo toàn dữ liệu và giải phóng luồng chính cho các message sau.")]
cw = (1748 - 2 * 28) / 3
for i, (r, rd, m, md) in enumerate(risks):
    x = 86 + i * (cw + 28)
    rect(s, x, 510, cw, 370, PALE, None, 22)
    rect(s, x, 510, cw, 130, AMBER_BG, None, 22)
    text(s, x + 28, 526, cw - 56, 100, [[("Rủi ro · " + r, {"font": SEMI, "color": AMBER, "size": 25})], [(rd, {"size": 20})]], 20, INK, REG, "l", "t", 1.25, 6)
    arrow(s, x + cw / 2, 644, x + cw / 2, 690, GREEN, lw=3)
    text(s, x + 28, 696, cw - 56, 40, m, 28, GREEN, SEMI)
    text(s, x + 28, 748, cw - 56, 130, md, 21, INK, REG, lh=1.32)
rect(s, 86, 904, 1748, 96, GREEN, None, 20)
text(s, 118, 904, 1700, 96, [[("At-least-once delivery + Idempotent consumer = Effectively-once.  ", {"font": SEMI}), "Đảm bảo mỗi sự kiện chỉ làm thay đổi số liệu trên read model đúng một lần duy nhất."]], 22, WHITE, REG, "l", "m", 1.3)

# ───────────── 11. Lỗi giữa chừng ─────────────
s = base(11, "Xử lý lỗi giữa chừng ở luồng đa bước", "Tùy tính chất dữ liệu bước đầu để chọn giữ trạng thái chờ thử lại (Ingest) hay bù trừ ngược theo Saga (Kế hoạch tiết kiệm).")
def lane(y, h, label, sub):
    rect(s, 86, y, 1748, h, PALE, None, 24)
    text(s, 122, y + 18, 740, 36, label, 28, INK, SEMI)
    text(s, 122, y + 62, 740, 60, sub, 21, MUTED, REG, lh=1.25)
def node(x, y, w, h, t, d, fill, line, tc=INK):
    rect(s, x, y, w, h, fill, line, 16, 2)
    text(s, x + 10, y, w - 20, h, [[(t, {"font": SEMI, "size": 23, "color": tc})], [(d, {"size": 19, "color": MUTED if tc == INK else WHITE})]], 22, INK, REG, "c", "m", 1.2)
lane(290, 330, "Luồng 1 · Ingest mẫu đo và tách phụ tải NILM", "Không rollback mẫu đo thực tế đã lưu, chỉ đánh dấu chờ suy luận bù.")
node(122, 400, 330, 120, "core lưu mẫu đo thô", "kiểm API key, công tơ, tính liên tục", WHITE, GREEN)
arrow(s, 456, 460, 520, 460)
node(524, 400, 250, 120, "gọi sang nilm", "bọc timeout, retry, breaker", WHITE, GREEN)
arrow(s, 778, 430, 880, 360, GREEN)
arrow(s, 778, 490, 880, 540, AMBER)
node(884, 316, 330, 90, "DONE · 201", "lưu ước tính thiết bị, ghi outbox", GREEN, GREEN, WHITE)
node(884, 480, 330, 110, "PENDING_INFERENCE · 202", "nilm quá hạn, trả 5xx hoặc ngắt mạch", AMBER_BG, AMBER)
arrow(s, 1218, 535, 1290, 535, AMBER, lw=3)
node(1294, 480, 250, 110, "PendingRetrier", "backoff 1, 2, 4 phút", WHITE, AMBER)
arrow(s, 1548, 535, 1590, 535, AMBER, lw=3)
node(1594, 480, 210, 110, "FAILED", "quá 5 lần, báo vận hành", WHITE, AMBER)
lane(650, 330, "Luồng 2 · Kích hoạt kế hoạch tiết kiệm (Saga)", "Service copilot điều phối hai bước qua insight, tách rõ lỗi 4xx và timeout.")
node(122, 760, 300, 120, "Bước 1 · Tạo baseline M&V", "yêu cầu ≥ 14 ngày dữ liệu", WHITE, GREEN)
arrow(s, 426, 820, 490, 820)
node(494, 760, 300, 120, "Bước 2 · Đặt ngân sách", "áp hạn mức tháng mới", WHITE, GREEN)
for k, (yy, t, d, f, l, tc) in enumerate([(682, "ACTIVE", "cả hai bước hoàn tất", GREEN, GREEN, WHITE),
                                           (792, "CANCELLED", "bước 2 trả 4xx → gọi DELETE xóa baseline bước 1", AMBER_BG, AMBER, INK),
                                           (902, "PENDING", "bước 2 timeout 504 → reconciler đối soát lại sau", AMBER_BG, AMBER, INK)]):
    arrow(s, 798, 820, 900, yy + 36, GREEN if k == 0 else AMBER)
    node(904, yy, 480, 74, t, d, f, l, tc)
text(s, 1430, 700, 380, 260, [[("Nguyên tắc xử lý lỗi Saga", {"font": SEMI, "color": GREEN, "size": 25})],
                              [("Lỗi nghiệp vụ (4xx): biết chắc bước 2 bị từ chối, thực thi bù trừ (compensate) ngay.", {})],
                              [("Lỗi hạ tầng (timeout, 5xx): chưa rõ bước 2 đã ghi DB hay chưa, giữ PENDING để đối soát.", {})]], 22, INK, REG, lh=1.32, after=10)

# ───────────── 12. Triển khai ─────────────
s = base(12, "Đóng gói triển khai và bảo mật tại Gateway", "Mười container phân thành ba lớp mạng trên Docker Compose, mọi lưu lượng ngoài đi qua Envoy Gateway.")
text(s, 86, 270, 1000, 28, "MÔI TRƯỜNG DEMO · MỘT MÁY CÁ NHÂN ≥ 16 GB RAM · TỔNG GIỚI HẠN BỘ NHỚ ≈ 8 GB", 20, MUTED, SEMI)
def layer(y, h, label, color, bg):
    rect(s, 86, y, 1090, h, None, color, 24, 2, True)
    text(s, 110, y + 14, 700, 28, label, 20, color, SEMI)
layer(310, 170, "LỚP BIÊN (EDGE) · có mở cổng giao tiếp ra ngoài", PURPLE, PURPLE_BG)
for i, (nm, sub) in enumerate([("gateway", "Envoy 1.40 · 256 MB"), ("keycloak", "Keycloak 26 · 1 GB")]):
    x = 116 + i * 520
    rect(s, x, 356, 500, 100, PURPLE_BG, PURPLE, 18, 2)
    text(s, x, 356, 500, 100, [[(nm, {"font": SEMI, "size": 30})], [(sub, {"size": 21, "color": MUTED})]], 26, INK, REG, "c", "m", 1.2)
layer(510, 210, "LỚP SERVICE NGHIỆP VỤ · mạng nội bộ, không mở cổng ra host", GREEN, SAGE)
for i, (nm, sub) in enumerate([("nilm", "2 GB · 2 CPU"), ("core", "512 MB · 1 CPU"), ("insight", "512 MB · 1 CPU"), ("copilot", "512 MB · 1 CPU"), ("text2sql", "512 MB · 1 CPU")]):
    x = 108 + i * 210
    rect(s, x, 556, 198, 134, SAGE, GREEN, 18, 2)
    text(s, x, 556, 198, 134, [[(nm, {"font": SEMI, "size": 27})], [(sub, {"size": 18, "color": MUTED})], [("API + tác vụ nền", {"size": 16, "color": MUTED})]], 26, INK, REG, "c", "m", 1.2)
layer(750, 220, "LỚP LƯU TRỮ VÀ TRUYỀN THÔNG ĐIỆP · mạng nội bộ", TEAL, TEAL_BG)
dat = [("postgres", "6 database · 1,5 GB", TEAL_BG, TEAL), ("rabbitmq", "Quorum queue · DLQ", PURPLE_BG, PURPLE), ("qdrant", "2 collection vector", TEAL_BG, TEAL), ("models", "Volume trọng số NILM", TEAL_BG, TEAL)]
for i, (nm, sub, bg, ln) in enumerate(dat):
    x = 108 + i * 262
    rect(s, x, 796, 250, 140, bg, ln, 18, 2)
    text(s, x + 8, 796, 234, 140, [[(nm, {"font": SEMI, "size": 26})], [(sub, {"size": 18, "color": MUTED})]], 26, INK, REG, "c", "m", 1.25)
text(s, 86, 986, 1700, 30, "Mỗi service có Dockerfile riêng, đọc cấu hình qua biến môi trường và mở sẵn /health, /ready để sẵn sàng đưa lên Kubernetes.", 20, MUTED, REG)
arrow(s, 600, 480, 600, 510, INK, lw=3)
arrow(s, 600, 720, 600, 750, INK, lw=3)
# cột chính sách gateway
rect(s, 1230, 270, 604, 700, PALE, None, 24)
text(s, 1264, 296, 540, 40, "Chính sách kiểm soát tại Envoy Gateway", 27, INK, SEMI, lh=1.15)
pts = [("Định tuyến theo tiền tố", "/api/core, /insight, /copilot cho người dùng, còn /nilm và /text2sql khóa riêng cho admin. Chỉ tự động retry phương thức GET."),
       ("Xác thực JWT tập trung", "Bộ lọc jwt_authn kiểm tra chữ ký RS256 qua JWKS của Keycloak, trích xuất X-User-Id, X-User-Roles và xóa header giả mạo từ client."),
       ("Kiểm soát lưu lượng", "Áp dụng local_ratelimit, giới hạn kích thước request body và gắn mã vết x-request-id xuyên suốt."),
       ("Ngoại lệ cho thiết bị đo", "Nhánh ingest mẫu đo không dùng JWT người dùng, core tự xác thực bằng API key thiết bị và trạng thái ghép công tơ.")]
yy = 384
for t, d in pts:
    rect(s, 1264, yy + 4, 8, 120 if t in ("Định tuyến theo tiền tố", "Xác thực JWT tập trung") else 80, GREEN)
    text(s, 1292, yy, 510, 30, t, 24, GREEN, SEMI)
    text(s, 1292, yy + 34, 510, 120, d, 21, INK, REG, lh=1.28)
    yy += 168 if t in ("Định tuyến theo tiền tố", "Xác thực JWT tập trung") else 128

# ───────────── 13. Kiểm thử ─────────────
s = base(13, "Kiểm thử tích hợp và thực nghiệm chịu lỗi", "Bộ kiểm thử Postman chạy qua gateway, kết hợp tiêm lỗi đo đạc trước/sau và tự động hóa trên GitHub Actions.")
rect(s, 86, 270, 640, 630, PALE, None, 24)
text(s, 118, 292, 590, 30, "POSTMAN COLLECTION · ≥ 10 KỊCH BẢN QUA GATEWAY", 20, GREEN, SEMI)
reqs = [("201", "Ingest batch mẫu đo khi nilm phản hồi bình thường"), ("409", "Gửi lặp batch có cùng khóa Idempotency-Key"), ("202", "Ingest khi nilm tạm dừng → giữ trạng thái PENDING"),
        ("200", "Tra cứu hóa đơn tiền điện theo kỳ"), ("422", "Yêu cầu dự báo khi hộ chưa đủ 7 ngày dữ liệu"), ("403", "Gọi Energy Copilot bằng tài khoản gói thường"),
        ("200", "Hỏi số liệu tự do qua chuỗi copilot → text2sql"), ("201", "Kích hoạt kế hoạch tiết kiệm, Saga chuyển ACTIVE"), ("422", "Bước 2 của Saga bị từ chối → tự động xóa baseline"),
        ("401", "Gọi API nghiệp vụ không đính kèm JWT hợp lệ")]
for i, (code, d) in enumerate(reqs):
    y = 342 + i * 54
    chip(s, 118, y, 76, 40, code, WHITE, GREEN if code[0] == "2" else AMBER, 20, MONO, HAIR, 10)
    text(s, 212, y, 500, 40, d, 21, INK, REG, "l", "m")
# hai kịch bản lỗi
text(s, 766, 270, 1068, 30, "HAI KỊCH BẢN TIÊM LỖI · ĐỐI CHIẾU TRƯỚC VÀ SAU KHI BẬT FAULT TOLERANCE", 20, AMBER, SEMI)
cases = [("Kịch bản 1 · Service nilm dừng đột ngột khi đang ingest", "docker compose stop nilm",
          "Request ingest bị treo chờ tới khi đứt kết nối, trả lỗi 500 và làm gián đoạn luồng nhận mẫu đo",
          "Mẫu đo thô vẫn lưu an toàn, trả mã 202 PENDING_INFERENCE dưới 2 giây. Khi bật lại nilm, batch tự chuyển sang DONE"),
         ("Kịch bản 2 · Nhà cung cấp LLM phản hồi chậm quá 20 giây", "giả lập độ trễ > 20s trên đường gọi LLM",
          "Mỗi câu hỏi giữ chặt worker suốt 20 giây, các request đến sau dồn ứ gây nghẽn toàn service",
          "Circuit breaker tự động ngắt mạch, trả 503 kèm Retry-After ngay lập tức. Màn hình dashboard và luồng ingest hoạt động bình thường")]
for i, (t, how, before, after) in enumerate(cases):
    y = 312 + i * 300
    rect(s, 766, y, 1068, 280, AMBER_BG, None, 22)
    text(s, 798, y + 18, 1000, 36, t, 28, INK, SEMI)
    text(s, 798, y + 60, 1000, 30, how, 20, MUTED, MONO)
    for k, (lab, d) in enumerate([("Trước khi có cơ chế chịu lỗi", before), ("Sau khi bật cơ chế chịu lỗi", after)]):
        rect(s, 798 + k * 510, y + 104, 490, 156, WHITE, AMBER if k == 0 else GREEN, 14, 2)
        text(s, 818 + k * 510, y + 114, 450, 136, [[(lab, {"font": SEMI, "size": 21, "color": AMBER if k == 0 else GREEN})], [(d, {"size": 19})]], 19, INK, REG, "l", "t", 1.26, 6)
rect(s, 86, 920, 1748, 80, GREEN, None, 20)
text(s, 118, 920, 1700, 80, [[("Pipeline CI · GitHub Actions  ", {"font": SEMI}), "chạy ruff & pytest từng service · đóng gói Docker image · khởi chạy compose · bắn Newman kiểm thử · đối chiếu file OpenAPI"]], 22, WHITE, REG, "l", "m")

# ───────────── 14. Cảm ơn ─────────────
s = prs.slides.add_slide(BLANK)
rect(s, 1080, 0, 840, 1080, PALE)
text(s, 86, 60, 900, 30, "WATTPRINT · NHÓM 6", 22, GREEN, SEMI)
img(s, "logo-ptit.png", 1752, 40, 90, 58)
text(s, 80, 330, 940, 200, "Cảm ơn thầy và các bạn đã lắng nghe", 96, INK, SEMI, lh=1.08)
rect(s, 86, 640, 120, 6, GREEN)
text(s, 86, 680, 900, 40, "Câu hỏi và thảo luận", 34, INK, SEMI)
text(s, 86, 750, 900, 40, "Học phần Phát triển phần mềm hướng dịch vụ · INT1448-20261-01", 26, MUTED)
text(s, 86, 800, 900, 40, "Giảng viên hướng dẫn: Nguyễn Việt Dũng", 26, MUTED)
text(s, 1170, 200, 660, 30, "ĐIỂM NHẤN KIẾN TRÚC", 21, GREEN, SEMI)
for i, (t, d) in enumerate([("9 quy tắc nghiệp vụ", "phân tách rõ ba miền dữ liệu để vạch ranh giới service"), ("5 service độc lập", "nilm, core, insight, copilot, text2sql"),
                            ("6 DB + Qdrant", "cô lập quyền theo DB role, tách riêng vector store"), ("RabbitMQ + Outbox", "giao tiếp sự kiện không mất, không trùng, có DLQ"),
                            ("Envoy Gateway", "xác thực JWT tập trung, không chứa logic nghiệp vụ")]):
    y = 250 + i * 130
    rect(s, 1170, y, 660, 110, WHITE, HAIR, 18, 2)
    text(s, 1196, y, 300, 110, t, 28, GREEN, SEMI, "l", "m")
    text(s, 1480, y, 330, 110, d, 21, INK, REG, "l", "m", 1.25)

# ───────────── Script thuyết trình (speaker notes) ─────────────
NOTES = [
# 1. Bìa
"""Em chào thầy và các bạn. Hôm nay Nhóm 6 xin trình bày bài tập lớn môn Phát triển phần mềm hướng dịch vụ với đề tài WattPrint: thiết kế kiến trúc microservices cho hệ thống theo dõi điện năng từng thiết bị trong hộ gia đình.

Sơ đồ bên phải tóm tắt cấu trúc tổng thể mà nhóm hướng tới: mọi yêu cầu từ bên ngoài đều đi qua một cổng API Gateway duy nhất là Envoy, phía sau là năm service nghiệp vụ độc lập, mỗi service quản lý một cơ sở dữ liệu riêng. Các service xếp theo đúng luồng biến đổi dữ liệu: khi cần lấy số liệu tức thời thì gọi đồng bộ, còn khi thông báo thay đổi trạng thái thì phát sự kiện qua RabbitMQ.""",

# 2. Bài toán
"""Trước hết, nhóm xin điểm qua bài toán thực tế của WattPrint. Hóa đơn tiền điện hằng tháng chỉ cho gia đình biết tổng số tiền phải trả, chứ không cho biết điều hòa, bình nóng lạnh hay tủ lạnh chiếm bao nhiêu phần trăm trong đó. Nếu tự mua ổ cắm thông minh lắp cho từng thiết bị thì chi phí lên tới vài triệu đồng và cũng không đo được các thiết bị đấu âm tường.

Giải pháp của WattPrint là chỉ lắp một cảm biến dòng điện duy nhất tại aptomat tổng để đo công suất toàn nhà, sau đó dùng mô hình học máy NILMFormer bóc tách ra công suất của từng thiết bị. Từ dữ liệu đã tách, hệ thống cung cấp bốn nhóm tính năng: thứ nhất là phân rã phụ tải theo thiết bị, thứ hai là dashboard theo dõi và tính hóa đơn theo biểu giá 5 bậc, thứ ba là phát hiện bất thường và dự báo chi phí cuối tháng, và thứ tư là trợ lý AI Energy Copilot hỗ trợ hỏi đáp cũng như gợi ý tiết kiệm dựa trên số liệu thực của gia đình. Trong phạm vi đồ án, nguồn dữ liệu cảm biến được giả lập bằng công cụ phát lại bộ dữ liệu công khai REFIT.""",

# 3. Quy tắc nghiệp vụ
"""Từ bài toán trên, nhóm xác định ba tác nhân tương tác với hệ thống gồm thành viên hộ gia đình, nhóm vận hành và cảm biến tại aptomat, đồng thời chốt chín quy tắc nghiệp vụ từ BR1 đến BR9 có thể kiểm chứng trực tiếp bằng code.

Trên bảng, mỗi hàng thể hiện một quy tắc, tình huống vi phạm cụ thể, service chịu trách nhiệm kiểm soát và mã trạng thái HTTP trả về. Chẳng hạn, nếu cảm biến gửi lặp một batch mẫu đo cũ do mạng chập chờn, service core sẽ chặn lại bằng mã 409 Conflict để không cộng trùng sản lượng điện. Nếu một hộ mới lắp thiết bị được 3 ngày đã yêu cầu dự báo hóa đơn tháng, service insight sẽ trả lỗi 422 vì chưa đủ ngưỡng 7 ngày dữ liệu tối thiểu. Hoặc khi người dùng hỏi số liệu qua trợ lý AI, cơ chế lọc tại copilot và text2sql chỉ cho phép đọc dữ liệu thuộc đúng ngôi nhà của người đang hỏi.

Điểm đáng chú ý ở bảng này là chín quy tắc tự động gom thành ba cụm dữ liệu tách biệt: cụm vận hành và hóa đơn ở core, cụm thống kê dự báo ở insight, và cụm kiểm soát trợ lý AI ở copilot cùng text2sql. Đây chính là căn cứ để nhóm phân rã service ở slide tiếp theo.""",

# 4. Phân rã service
"""Khi tách ứng dụng monolith sang microservices, nhóm áp dụng ba tiêu chí theo thứ tự ưu tiên: quyền sở hữu dữ liệu (data ownership), đặc thù tải (workload) và phạm vi cô lập lỗi (fault isolation).

Cụ thể, service core nắm giữ dữ liệu gốc của hộ gia đình, chuỗi mẫu đo từ công tơ và hóa đơn chính thức, đòi hỏi luồng ghi luôn ổn định và không được phép mất dữ liệu.
Service nilm được tách riêng vì chạy mô hình PyTorch rất nặng về CPU và RAM, nếu nilm quá tải thì core vẫn lưu được mẫu đo mới rồi đánh dấu chờ xử lý sau.
Service insight chuyên chạy các thuật toán quét bất thường, dự báo và đo kiểm M&V theo lô định kỳ, nếu insight bảo trì thì việc thu thập dữ liệu bên core vẫn diễn ra bình thường.
Service copilot đảm nhận luồng hội thoại AI và gợi ý chủ động, vốn dành phần lớn thời gian chờ phản hồi mạng từ nhà cung cấp LLM bên ngoài.
Cuối cùng, nhóm tách riêng phần truy vấn số liệu tự nhiên thành service text2sql để tái sử dụng nguyên vẹn một ứng dụng Text-to-SQL sẵn có, nơi quản lý bộ catalog ngữ nghĩa và tiến trình đồng bộ vector riêng. Nhờ vậy, mỗi service hoàn toàn tự chủ về dữ liệu và chu kỳ triển khai.""",

# 5. Kiến trúc tổng quan
"""Khi ghép năm service lại ở cấp độ Container theo mô hình C4, kiến trúc tổng thể có dạng như trên hình. Ứng dụng di động Expo, ứng dụng web Next.js và công cụ REFIT replayer đều gọi vào cổng duy nhất là Envoy Gateway. Gateway đối chiếu khóa công khai từ Keycloak để xác thực JWT trước khi định tuyến vào bên trong, trong đó hai nhánh nilm và text2sql vẽ nét đứt vì chỉ mở riêng cho quản trị viên.

Ở hàng giữa, nhóm sắp xếp năm service theo thứ tự nilm, core, insight, copilot và text2sql để mọi lời gọi REST đồng bộ (mũi tên liền màu đen) đều chỉ nối hai ô nằm sát nhau: core gọi nilm, insight gọi core, còn copilot gọi sang insight và text2sql. Đồ thị gọi này hoàn toàn không có chu trình, giúp các service ghép lỏng với nhau (loose coupling). Ở chiều ngược lại, khi core có dữ liệu mới hoặc khi insight phát hiện cảnh báo, thông tin được đẩy đi bất đồng bộ bằng sự kiện qua RabbitMQ (mũi tên nét đứt màu cam) theo mô hình choreography.""",

# 6. Dữ liệu
"""Về tầng lưu trữ, nhóm triển khai mẫu Database per Service trên một máy chủ PostgreSQL 18 duy nhất chia thành sáu cơ sở dữ liệu độc lập, mỗi database gắn với một tài khoản role riêng. Hai database có dữ liệu chuỗi thời gian là core_db và insight_db được bật extension TimescaleDB để nén và tổng hợp tự động. Với dữ liệu vector phục vụ RAG và tìm kiếm metric, cả copilot và text2sql cùng dùng chung một container Qdrant nhưng tách thành hai collection riêng biệt, còn văn bản gốc vẫn nằm trong PostgreSQL nên có thể tái tạo chỉ mục bất cứ lúc nào.

Khi các database đã cô lập, việc đọc dữ liệu chéo được giải quyết theo hai cách. Cách thứ nhất là đồng bộ bản sao qua sự kiện theo mẫu CQRS, trong đó insight duy trì read model tiêu thụ theo giờ từ sự kiện của core. Cách thứ hai là gọi trực tiếp REST API đối với các dữ liệu cấu hình nhỏ như biểu giá hay danh sách thiết bị.

Ngoại lệ duy nhất được cấp phép là cho service text2sql đọc dữ liệu phân tích thông qua tài khoản chỉ đọc text2sql_ro trên các view do insight công bố. Cơ chế này được bảo vệ qua ba lớp: LLM không bao giờ tự viết câu lệnh SQL mà chỉ chọn mã ID của metric trong catalog để bộ biên dịch sqlglot tự dựng câu SELECT, truy vấn chỉ chạy trên các view của insight_db với timeout 5 giây, và bản thân mỗi view đều khóa cứng điều kiện lọc theo mã nhà của người hỏi (app.home_id), nên dù kế hoạch truy vấn có sai sót cũng không thể đọc sang dữ liệu của hộ khác.""",

# 7. API REST
"""Trong kiến trúc hướng dịch vụ, mọi tương tác đồng bộ đều dựa trên hợp đồng giao tiếp rõ ràng. Tại đây mỗi service sử dụng FastAPI để tự động sinh tài liệu đặc tả OpenAPI từ các schema dữ liệu, và pipeline CI sẽ chặn lại nếu phát hiện file đặc tả đã commit bị lệch so với mã nguồn hiện tại.

Bảng trên liệt kê các endpoint tiêu biểu của cả năm service cùng cách từng service phản ánh quy tắc nghiệp vụ thành mã lỗi 4xx. Ví dụ, core trả mã 409 khi phát hiện batch mẫu đo trùng Idempotency-Key hoặc bị hở khoảng thời gian, insight trả 422 khi hộ gia đình chưa tích lũy đủ số ngày dữ liệu tối thiểu, copilot trả 403 nếu tài khoản chưa nâng cấp gói Pro, còn text2sql trả 409 khi câu hỏi có nhiều cách nối bảng cần người dùng xác nhận lại. Nhóm cũng thống nhất quy ước mã trạng thái trên toàn hệ thống: 201 cho tạo mới thành công, 202 khi đã tiếp nhận và chuyển sang xử lý nền, 4xx cho lỗi nghiệp vụ và 503, 504 cho lỗi hạ tầng.""",

# 8. Đồng bộ hay bất đồng bộ
"""Trước khi đi sâu vào cơ chế chịu lỗi của từng kênh truyền thông, slide này làm rõ tiêu chí để nhóm quyết định khi nào dùng lời gọi đồng bộ và khi nào phát sự kiện bất đồng bộ.

Tiêu chí chọn rất rõ ràng: bên gửi có bắt buộc phải nhận câu trả lời ngay để hoàn tất bước tiếp theo hay không. Nếu cần kết quả tức thời để trả lời người dùng, cần lấy cấu hình mới nhất, hoặc cần biết thao tác thành công hay thất bại để rẽ nhánh xử lý, nhóm dùng giao tiếp đồng bộ qua REST hoặc SSE. Đổi lại, hai service sẽ phụ thuộc nhau về thời gian chạy nên bắt buộc phải có cơ chế bảo vệ chống treo.
Ngược lại, nếu chỉ thông báo một việc đã xảy ra mà bên phát không cần đợi, hoặc tác vụ phía sau tốn nhiều thời gian như cập nhật bảng tổng hợp hay gọi LLM soạn gợi ý, nhóm chuyển sang phát sự kiện qua RabbitMQ. Cái giá phải trả là độ trễ vài giây trên dữ liệu đọc (eventual consistency) và chi phí quản lý các bảng chống mất, chống trùng thông điệp.""",

# 9. Giao tiếp đồng bộ
"""Khi sử dụng lời gọi đồng bộ, rủi ro lớn nhất là một service phía sau bị chậm hoặc treo sẽ kéo sập dây chuyền các service gọi vào nó. Để ngăn chặn tình huống này, mọi lời gọi HTTP nội bộ giữa năm service đều đi qua một thư viện dùng chung là libs/common với năm lớp bảo vệ:

Thứ nhất là Timeout: giới hạn thời gian kết nối 1 giây, đọc dữ liệu 3 giây, riêng các lệnh gọi LLM cho phép 20 đến 30 giây, nếu quá hạn sẽ cắt ngay và trả mã 504.
Thứ hai là Retry có giới hạn: chỉ tự động thử lại tối đa 2 lần kèm thời gian chờ tăng dần và độ lệch ngẫu nhiên (backoff + jitter) đối với các request idempotent. Các lỗi nghiệp vụ 4xx tuyệt đối không retry.
Thứ ba là Circuit breaker: đặt tại các điểm nối nhạy cảm như từ core sang nilm hay từ copilot sang LLM và text2sql. Khi gặp lỗi liên tiếp, mạch tự động ngắt để trả mã 503 ngay lập tức thay vì tiếp tục dồn tải vào nơi đang hỏng.
Thứ tư là Bulkhead: dùng Semaphore giới hạn số luồng gọi đồng thời vào nilm và LLM, kết hợp giới hạn bộ nhớ và CPU trên từng container.
Và thứ năm là Fallback: khi text2sql gặp sự cố, copilot tự động chuyển về dùng bộ công cụ tra cứu cố định của insight để cuộc trò chuyện không bị đứt quãng.""",

# 10. Giao tiếp bất đồng bộ
"""Ở kênh giao tiếp bất đồng bộ qua RabbitMQ, bài toán khó nhất là làm sao để không rơi mất sự kiện và không xử lý trùng khi mạng lỗi. Sơ đồ phía trên mô tả đường đi chuẩn của một sự kiện từ core sang insight, đi kèm cách nhóm giải quyết ba rủi ro kinh điển:

Rủi ro thứ nhất là mất thông điệp nếu service vừa ghi database xong nhưng kịp sập nguồn trước khi gửi lên RabbitMQ. Nhóm khắc phục bằng mẫu Transactional Outbox: dữ liệu nghiệp vụ và bản ghi sự kiện được chèn vào bảng outbox trong cùng một giao dịch SQL. Tiến trình nền OutboxRelay quét các dòng chưa gửi bằng khóa FOR UPDATE SKIP LOCKED, đẩy lên exchange và phải nhận được xác nhận từ broker rồi mới đánh dấu hoàn tất.
Rủi ro thứ hai là trùng thông điệp do RabbitMQ hoạt động theo cơ chế giao ít nhất một lần (at-least-once). Tại đầu nhận, consumer của insight tra cứu mã message_id trong bảng inbox, nếu chưa có mới cập nhật read model và ghi vào inbox trong cùng một giao dịch.
Rủi ro thứ ba là một thông điệp lỗi cứ giao đi giao lại làm tắc hàng đợi. Nhóm dùng hàng đợi kiểu Quorum Queue với cấu hình delivery-limit bằng 3: sau 3 lần xử lý thất bại, thông điệp tự động chuyển sang DLQ để nhóm vận hành kiểm tra và đẩy chạy lại sau.""",

# 11. Lỗi giữa chừng
"""Slide thứ 11 minh họa cách hệ thống xử lý lỗi xảy ra giữa chừng trên hai luồng nghiệp vụ đi qua nhiều service.

Ở luồng thứ nhất là nhận mẫu đo từ cảm biến rồi gọi mô hình tách phụ tải NILM: sau khi core kiểm tra hợp lệ và lưu chuỗi công suất thô vào cơ sở dữ liệu, core gọi đồng bộ sang nilm. Nếu nilm đang quá tải hoặc ngừng phản hồi, core tuyệt đối không rollback dữ liệu công suất vừa lưu vì đó là số đo thực tế từ công tơ. Thay vào đó, core đánh dấu lô dữ liệu ở trạng thái PENDING_INFERENCE, trả mã 202 cho thiết bị và để tiến trình nền tự động thử lại sau 1, 2 và 4 phút.
Ở luồng thứ hai là kích hoạt kế hoạch tiết kiệm do copilot điều phối theo mẫu Saga qua hai bước bên insight: bước 1 tạo đường cơ sở M&V, bước 2 đặt hạn mức ngân sách tháng. Nếu bước 2 bị từ chối bởi lỗi nghiệp vụ 4xx, tức là chắc chắn chưa làm thay đổi dữ liệu, copilot lập tức chạy giao dịch bù trừ ngược bằng cách gọi API xóa baseline vừa tạo ở bước 1 và hủy kế hoạch. Nhưng nếu bước 2 bị lỗi timeout 504, copilot chưa thể biết yêu cầu đặt ngân sách đã chạy xong ở insight hay chưa, nên phải giữ kế hoạch ở trạng thái PENDING để tiến trình đối soát kiểm tra lại sau.""",

# 12. Triển khai
"""Về phương án triển khai, toàn bộ hệ thống phía server gồm đúng 10 container được định nghĩa trong Docker Compose và chia thành ba lớp mạng tách biệt. Chỉ có lớp biên gồm Envoy Gateway và Keycloak mới mở cổng giao tiếp ra ngoài máy chủ, còn toàn bộ năm service nghiệp vụ cùng lớp lưu trữ PostgreSQL, RabbitMQ, Qdrant đều nằm kín trong mạng nội bộ. Để tiết kiệm bộ nhớ RAM khi chạy demo trên một máy tính cá nhân, trong mỗi service nhóm gom cả HTTP API, message consumer và các tác vụ nền vào chung một tiến trình của FastAPI, giữ tổng dung lượng giới hạn của cả cụm ở mức khoảng 8 GB.

Khung bên phải tóm tắt các chính sách thực thi tại Envoy Gateway: định tuyến theo tiền tố đường dẫn, kiểm tra chữ ký JWT bằng tập khóa JWKS của Keycloak, xóa sạch các header định danh giả mạo từ phía client trước khi gán X-User-Id và X-User-Roles, đồng thời gắn mã x-request-id để gom log JSON xuyên suốt các container.""",

# 13. Kiểm thử
"""Để kiểm chứng toàn bộ thiết kế trên, nhóm xây dựng quy trình kiểm thử gồm ba phần.

Phần bên trái là bộ kiểm thử Postman gồm hơn 10 kịch bản gọi trực tiếp qua cổng Envoy Gateway, bao phủ cả các luồng thành công (mã 200, 201) lẫn các tình huống vi phạm quy tắc nghiệp vụ và bảo mật (mã 401, 403, 409, 422) cũng như trạng thái xử lý nền 202.
Phần bên phải là hai kịch bản tiêm lỗi thực nghiệm để đo đạc sự khác biệt trước và sau khi trang bị cơ chế chịu lỗi. Ở kịch bản 1, nhóm chủ động tắt container nilm trong lúc đang đẩy dữ liệu đo: thay vì bị treo rồi trả lỗi 500 như trước, core vẫn lưu an toàn dữ liệu và trả mã 202 dưới 2 giây, đến khi bật lại nilm thì lô dữ liệu tự động hoàn tất. Ở kịch bản 2, nhóm giả lập nhà cung cấp LLM phản hồi chậm quá 20 giây: circuit breaker tự động mở mạch để trả mã 503 tức thì cho các yêu cầu tiếp theo, giữ cho dashboard và luồng ingest hoàn toàn không bị ảnh hưởng.
Toàn bộ các bước từ kiểm tra mã tĩnh, chạy pytest, dựng cụm Docker Compose cho tới bắn Newman và đối chiếu hợp đồng OpenAPI đều được tự động hóa trên GitHub Actions.""",

# 14. Cảm ơn
"""Tổng kết lại, từ chín quy tắc nghiệp vụ của bài toán theo dõi điện năng hộ gia đình, Nhóm 6 đã phân rã hệ thống thành năm service tự chủ đứng sau cổng Envoy Gateway, cô lập dữ liệu trên sáu database PostgreSQL cùng Qdrant, và kết hợp chặt chẽ giữa giao tiếp đồng bộ có bảo vệ với giao tiếp sự kiện qua RabbitMQ.

Phần trình bày của Nhóm 6 đến đây là kết thúc. Nhóm rất mong nhận được câu hỏi và ý kiến đóng góp của thầy cùng các bạn."""
]
assert len(NOTES) == len(prs.slides) == TOTAL
for sl, note in zip(prs.slides, NOTES):
    sl.notes_slide.notes_text_frame.text = note

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SOA-WattPrint-Slide.pptx")
prs.core_properties.title = "WattPrint - Kiến trúc hướng dịch vụ"
prs.core_properties.author = "Nhóm 6"
prs.save(out)
print("saved", out)
