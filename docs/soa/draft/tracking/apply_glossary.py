"""Thay các thuật ngữ auto trong glossary.py vào content.py và slide/build_slides.py (có backup .bak).
Chạy trong thư mục draft: python tracking/apply_glossary.py"""
import re, os, shutil, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from glossary import TERMS
for f in (os.path.join(HERE, "..", "content.py"), os.path.join(HERE, "..", "..", "slide", "build_slides.py")):
    s = open(f, encoding="utf-8").read(); shutil.copy(f, f + ".bak"); n = 0
    for p, u, _, auto in TERMS:
        if auto: s, k = re.subn(p, u.replace("\\", "\\\\"), s); n += k
    open(f, "w", encoding="utf-8").write(s); print(os.path.basename(f), n, "thay")
