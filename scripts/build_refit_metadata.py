"""Build app/seed/refit_metadata.json from dataset/MetaData_Tables.xlsx (stdlib only).

Usage (host): python scripts/build_refit_metadata.py [XLSX] [OUT_JSON]
"""

import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XLSX = ROOT / "dataset" / "MetaData_Tables.xlsx"
DEFAULT_OUT = ROOT / "app" / "seed" / "refit_metadata.json"
NOTE_RE = re.compile(r"\(([^()]*)\)\s*$")


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\t", " ")).strip()


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{{{NS['m']}}}t"))


def read_sheets(path: Path) -> dict[str, list[list[str]]]:
    """Return {sheet name: rows}, each row a list of cell strings (column order kept)."""
    with zipfile.ZipFile(path) as z:
        shared = []
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        rel_root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rels = {r.get("Id"): r.get("Target") for r in rel_root.findall("rel:Relationship", NS)}
        out = {}
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        for sh in wb.find("m:sheets", NS):
            target = rels[sh.get(f"{{{NS['r']}}}id")].lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).iter(f"{{{NS['m']}}}row"):
                cells: dict[int, str] = {}
                for c in row.findall("m:c", NS):
                    col = 0
                    for ch in re.match(r"[A-Z]+", c.get("r")).group():
                        col = col * 26 + ord(ch) - 64
                    v = c.find("m:v", NS)
                    if v is None:
                        is_ = c.find("m:is", NS)
                        val = _text(is_) if is_ is not None else ""
                    elif c.get("t") == "s":
                        val = shared[int(v.text)]
                    else:
                        val = v.text or ""
                    cells[col] = val
                if cells:
                    rows.append([cells.get(i, "") for i in range(1, max(cells) + 1)])
            out[sh.get("name")] = rows
    return out


def parse_int(s: str) -> int | None:
    m = re.search(r"\d+", s)
    return int(m.group()) if m else None


def household(rows: list[list[str]]) -> dict[int, dict]:
    info = {}
    for row in rows:
        cells = [clean(c) for c in row]
        if not cells or not cells[0].isdigit():
            continue
        cells += [""] * (6 - len(cells))
        occ = parse_int(cells[1])
        construction = cells[2] if cells[2] not in ("", "-", "?", "???") else None
        info[int(cells[0])] = {
            "occupancy": occ,
            "construction": construction,
            "appliances_owned": parse_int(cells[3]),
            "type": cells[4],
            "size": cells[5],
        }
    return info


def appliance(cells: list[str]) -> dict:
    cells = [clean(c) for c in cells]
    name = cells[1] if len(cells) > 1 else ""
    brand = cells[2] if len(cells) > 2 else ""
    model_parts = [c for c in cells[3:] if c]
    note = None
    if model_parts:
        m = NOTE_RE.search(model_parts[-1])
        if m:
            note = m.group(1).strip()
            model_parts[-1] = NOTE_RE.sub("", model_parts[-1]).strip()
            model_parts = [p for p in model_parts if p]
    elif (m := NOTE_RE.search(brand)):
        note = m.group(1).strip()
        brand = NOTE_RE.sub("", brand).strip()
    m = NOTE_RE.search(name)
    if m:
        note = m.group(1).strip() if note is None else f"{m.group(1).strip()}; {note}"
        name = NOTE_RE.sub("", name).strip()
    model = " ".join(model_parts)
    if name in ("???", ""):
        name = "unknown"
    return {
        "name": name,
        "brand": None if brand.lower() in ("", "unknown", "???") else brand,
        "model": None if model.lower() in ("", "unknown", "???") else model,
        "note": note,
    }


def build(xlsx: Path) -> dict:
    sheets = read_sheets(xlsx)
    info = household(sheets["Sheet1"])
    result = {}
    for name, rows in sheets.items():
        m = re.fullmatch(r"House (\d+)", name)
        if not m:
            continue
        house = int(m.group(1))
        channels = {"Aggregate": {"name": "Aggregate"}}
        for row in rows:
            cells = [clean(c) for c in row]
            if cells and cells[0].isdigit() and 1 <= int(cells[0]) <= 9:
                channels[f"Appliance{int(cells[0])}"] = appliance(cells)
        h = info[house]
        result[str(house)] = {**h, "channels": channels}
    return dict(sorted(result.items(), key=lambda kv: int(kv[0])))


def main(argv: list[str]) -> int:
    xlsx = Path(argv[0]) if argv else DEFAULT_XLSX
    out = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUT
    data = build(xlsx)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(data)} houses)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
