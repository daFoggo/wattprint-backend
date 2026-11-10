"""Đếm vi phạm từ điển và dấu hiệu slop. Chạy: python tracking/check_terms.py [--md]  (trong thư mục draft)
--md: sinh lại TU-DIEN-THUAT-NGU.md"""
import re, sys, os, importlib.util
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from glossary import TERMS, SLOP

def texts():
    """(nhãn, chuỗi) cho báo cáo và slide. Slide lấy chuỗi trong dấu nháy của build_slides.py."""
    sp = importlib.util.spec_from_file_location("content", os.path.join(HERE, "..", "content.py"))
    c = importlib.util.module_from_spec(sp); sp.loader.exec_module(c)
    out = list(c.SUMMARY)
    for b in c.BODY:
        if b[0] in ("h1", "h2", "h3", "p"): out.append(b[1])
        elif b[0] in ("ul", "ol"): out += b[1]
        elif b[0] == "table": out += [b[1]] + b[2] + [x for r in b[3] for x in r]
        elif b[0] == "fig": out.append(b[2])
    rep = [("báo cáo", s) for s in out]
    sl = os.path.join(HERE, "..", "..", "slide", "build_slides.py")
    if os.path.exists(sl): rep.append(("slide", open(sl, encoding="utf-8").read()))
    return rep

if "--md" in sys.argv:
    L = ["# Từ điển thuật ngữ và theo dõi văn phong", "",
         "Sinh từ `tracking/glossary.py`. Sửa ở đó rồi chạy `python tracking/check_terms.py --md`.", "",
         "## Thuật ngữ thống nhất", "", "| Tránh | Dùng | Ghi chú | Thay tự động |", "|---|---|---|---|"]
    for p, u, n, a in TERMS:
        L.append(f"| `{p.replace('|', '/')}` | {u} | {n} | {'có' if a else 'không, viết lại tay'} |")
    L += ["", "## Dấu hiệu văn slop cần soát", "", "| Mẫu | Vì sao |", "|---|---|"]
    L += [f"| `{p.replace('|', '/')}` | {n} |" for p, n in SLOP]
    open(os.path.join(HERE, "..", "..", "TU-DIEN-THUAT-NGU.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote TU-DIEN-THUAT-NGU.md"); sys.exit()

T = texts()
print(f"{'mẫu':44}{'báo cáo':>9}{'slide':>7}")
for title, rows in (("THUẬT NGỮ", [(p, p) for p, *_ in TERMS]), ("SLOP", [(p, p) for p, _ in SLOP])):
    print("--", title)
    for p, _ in rows:
        rx = re.compile(p, re.M)
        a = sum(len(rx.findall(s)) for k, s in T if k == "báo cáo"); b = sum(len(rx.findall(s)) for k, s in T if k == "slide")
        if a or b: print(f"{p[:42]:44}{a:>9}{b:>7}")
