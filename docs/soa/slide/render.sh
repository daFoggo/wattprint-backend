#!/bin/bash
# dựng pptx, nhúng font, xuất PDF và contact sheet để kiểm
cd "$(dirname "$0")"
PYTHONIOENCODING=utf-8 python build_slides.py build.pptx && python embed_fonts.py build.pptx >/dev/null && rm -f build.pdf && powershell -File export_pdf.ps1 "$(cygpath -w $PWD/build.pptx)" "$(cygpath -w $PWD/build.pdf)" && mkdir -p _png && rm -f _png/* && pdftoppm -r 60 -png build.pdf _png/s && python - <<'PY'
from PIL import Image
import glob
ims=[Image.open(f) for f in sorted(glob.glob('_png/s-*.png'))]
w,h=ims[0].size
for k in range(0,len(ims),4):
    sh=Image.new('RGB',(w*2,h*2),'#888')
    for i,im in enumerate(ims[k:k+4]): sh.paste(im,((i%2)*w,(i//2)*h))
    sh.save(f'_png/sheet{k//4}.png')
PY
