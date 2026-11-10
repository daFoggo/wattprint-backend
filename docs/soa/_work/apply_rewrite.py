"""Áp OVR (ovr1, ovr2) vào content.py theo chỉ số khối. Chạy trong thư mục _work."""
import importlib.util, sys, shutil
sys.path.insert(0, '.')
spec = importlib.util.spec_from_file_location('old', '../draft/content.py')
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
from ovr1 import OVR as A1
from ovr2 import OVR as A2
OVR = {**A1, **A2}
used, body = set(), []
for i, x in enumerate(old.BODY):
    if x[0] == 'p' and str(i) in OVR:
        x = ('p', OVR[str(i)]); used.add(str(i))
    elif x[0] in ('ul', 'ol'):
        items = list(x[1])
        for j in range(len(items)):
            k = f'{i}.{j}'
            if k in OVR:
                items[j] = OVR[k]; used.add(k)
        x = (x[0], items)
    body.append(x)
summary = list(old.SUMMARY)
for j in range(len(summary)):
    if f'S{j}' in OVR:
        summary[j] = OVR[f'S{j}']; used.add(f'S{j}')
print('unused keys', sorted(set(OVR) - used))
src = open('../draft/content.py', encoding='utf-8').read()
shutil.copy('../draft/content.py', 'content.before_rewrite.py')
a = src.index('SUMMARY = ['); b = src.index('KEYWORDS =')
head = src[:a] + 'SUMMARY = ' + repr(summary) + '\n' + src[b:src.index('BODY = []')]
out = head + 'BODY = []\nA = BODY.append\n\n' + ''.join('A(' + repr(x) + ')\n' for x in body)
open('../draft/content.py', 'w', encoding='utf-8').write(out)
print('written', len(body))
