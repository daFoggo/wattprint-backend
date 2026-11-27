# Sơ đồ kiến trúc TwoStageNILMFormer dạng HTML/SVG, xuất kèm PNG: nhánh detector vẽ mới, nhánh regressor dùng nguyên panel (a) hình NILMFormer gốc.
# Chạy từ thư mục gốc: uv run --with cairosvg --with pillow python reports/ve_kien_truc_2stage.py
import base64
import io
from pathlib import Path

import cairosvg
import numpy as np
from PIL import Image

FIG = Path(__file__).resolve().parent / "figures"
HTML, PNG = FIG / "hinh_kien_truc_2stage.html", FIG / "hinh_kien_truc_2stage.png"
# Bảng màu lấy từ hình kiến trúc NILMFormer gốc.
LINEAR, HEAD, GRU, GROUP = "#b7d5ec", "#fde4d2", "#e2d8f0", "#fdf2ec"
INK, SOFT, ORANGE = "#222222", "#5a6580", "#f0a050"
FONT = "'DejaVu Sans', sans-serif"
# Khung cắt panel (a) của hình NILMFormer gốc (pixel), bỏ chú thích "(a) NILMFormer architecture".
CROP = (50, 0, 912, 1188)


def node(cx, cy, w, h, name, fill, sub=None, stroke=None):
    x, y = cx - w / 2, cy - h / 2
    border = f' stroke="{stroke}" stroke-width="1.2"' if stroke else ""
    out = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" fill="{fill}"{border}/>'
    if sub:
        out += f'<text x="{cx}" y="{cy - 2}" text-anchor="middle" font-size="15" fill="{INK}">{name}</text>'
        out += f'<text x="{cx}" y="{cy + 14}" text-anchor="middle" font-size="10" letter-spacing="0.12em" fill="{SOFT}">{sub}</text>'
    else:
        out += f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="15" fill="{INK}">{name}</text>'
    return out


def path(d, width=2):
    return f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{width}" marker-end="url(#arrow)"/>'


def label(x, y, text, size=12, anchor="middle", mask=True, weight="normal", fill=INK):
    w = len(text) * size * 0.58 + 10
    left = {"middle": x - w / 2, "start": x - 5, "end": x - w + 5}[anchor]
    back = f'<rect x="{left}" y="{y - size}" width="{w}" height="{size + 6}" fill="#ffffff"/>' if mask else ""
    return back + f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{fill}">{text}</text>'


def spark(x0, base, w, h, values, color, fill=None):
    # Đồ thị chuỗi nhỏ kèm hai trục, như các đồ thị minh họa trong hình gốc.
    xs = np.linspace(x0, x0 + w, len(values))
    ys = base - h * values / values.max()
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(xs, ys, strict=True))
    out = f'<polygon points="{x0},{base} {pts} {x0 + w},{base}" fill="{fill}"/>' if fill else ""
    out += f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/>'
    out += f'<line x1="{x0}" y1="{base}" x2="{x0 + w + 10}" y2="{base}" stroke="{INK}" stroke-width="1" marker-end="url(#arrow-s)"/>'
    out += f'<line x1="{x0}" y1="{base}" x2="{x0}" y2="{base - h - 10}" stroke="{INK}" stroke-width="1" marker-end="url(#arrow-s)"/>'
    return out


def main() -> None:
    rng = np.random.default_rng(3)
    mask = np.zeros(128)
    mask[30:46], mask[70:76] = 1, 1
    app = np.zeros(128)
    app[30:46], app[70:76] = 0.8 + 0.05 * rng.random(16), 0.95

    # Nhánh giai đoạn 2 dùng nguyên panel (a) của hình NILMFormer gốc, đặt tại (X0, Y0) với tỷ lệ SCALE.
    crop = Image.open(FIG / "hinh_kien_truc_nilmformer.png").convert("RGB").crop(CROP)
    buffer = io.BytesIO()
    crop.save(buffer, format="PNG")
    width = 600
    scale = width / crop.width
    height = crop.height * scale
    X0, Y0 = 370, 190

    def at(cx, cy):
        # Đổi tọa độ pixel trong hình gốc sang tọa độ SVG.
        return X0 + (cx - CROP[0]) * scale, Y0 + (cy - CROP[1]) * scale

    in_x, in_y = at(370, 1105)  # mép trái đồ thị điện tổng đầu vào của hình gốc
    out_x, _ = at(500, 0)  # tâm đồ thị công suất đầu ra của hình gốc
    image = (
        f'<rect x="{X0 - 10}" y="{Y0 - 10}" width="{width + 20}" height="{height + 20}" rx="10" fill="#ffffff" stroke="#dddddd"/>'
        f'<image x="{X0}" y="{Y0}" width="{width}" height="{height:.1f}" href="data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"/>'
    )
    zones = (
        f'<rect x="40" y="420" width="280" height="440" rx="10" fill="{GROUP}"/>'
        + label(56, 444, "GIAI ĐOẠN 1", 12, anchor="start", mask=False, weight="bold", fill=SOFT)
        + label(56, 460, "DETECTOR", 12, anchor="start", mask=False, weight="bold", fill=SOFT)
        + label(X0 + 4, Y0 + 16, "GIAI ĐOẠN 2 · REGRESSOR", 12, anchor="start", mask=False, weight="bold", fill=SOFT)
        + label(X0 + 4, Y0 + 32, "NILMFormer gốc [3]", 12, anchor="start", mask=False, weight="bold", fill=SOFT)
    )
    arrows = "".join(
        [
            # Cùng cửa sổ điện tổng đầu vào của hình gốc → Detector.
            path(f"M{in_x - 6:.0f},{in_y:.0f} H188 Q180,{in_y:.0f} 180,{in_y - 8:.0f} V838"),
            # Detector.
            path("M180,796 V768"),
            path("M180,726 V698"),
            path("M180,656 V628"),
            path("M180,586 V556"),
            path("M180,506 V402"),
            # Regressor → Softplus → phép nhân với mask.
            path(f"M{out_x:.0f},{Y0 - 10} V170"),
            path(f"M{out_x - 100:.0f},150 H440"),
            path("M282,370 H322 Q330,370 330,362 V158 Q330,150 338,150 H400"),
            path("M420,132 V100"),
        ]
    )
    nodes = "".join(
        [
            node(180, 816, 220, 40, "Conv1D (k = 5) + ReLU", LINEAR),
            node(180, 746, 220, 40, "Bi-GRU (2 lớp)", GRU),
            node(180, 676, 220, 40, "Linear (2h × 4)", LINEAR),
            node(180, 606, 220, 40, "Sigmoid → p", HEAD),
            node(180, 530, 220, 48, "m = 1[p ≥ 0,5]", "#ffffff", stroke=INK),
            node(out_x, 150, 200, 40, "Softplus → P ≥ 0", HEAD),
            f'<circle cx="420" cy="150" r="18" fill="#ffffff" stroke="{INK}" stroke-width="2"/>',
            f'<text x="420" y="157" text-anchor="middle" font-size="22" fill="{INK}">×</text>',
            spark(90, 390, 180, 40, mask, INK),
            spark(350, 92, 140, 48, app, ORANGE),
        ]
    )
    texts = "".join(
        [
            label(380, in_y - 8, "chỉ kênh điện tổng", 11),
            label(180, 342, "Mask bật/tắt từng thiết bị", 12, mask=False),
            label(338, 180, "m", 15, anchor="start"),
            label(500, 142, "P", 15, anchor="start", mask=False),
            label(510, 50, "Công suất dự đoán từng thiết bị", 14, anchor="start", mask=False),
            label(510, 72, "ŷ = P ⊙ m", 14, anchor="start", mask=False),
        ]
    )
    svg = f"""<svg viewBox="0 0 1000 1040" xmlns="http://www.w3.org/2000/svg" role="img" font-family="{FONT}"
  aria-labelledby="kien-truc-2stage-title kien-truc-2stage-desc">
  <title id="kien-truc-2stage-title">Kiến trúc TwoStageNILMFormer</title>
  <desc id="kien-truc-2stage-desc">Bộ phát hiện GRU dự đoán mask bật/tắt, bộ hồi quy NILMFormer dự đoán công suất, đầu ra là tích của hai nhánh.</desc>
  <defs>
    <marker id="arrow" markerWidth="8" markerHeight="7" refX="7" refY="3.5" orient="auto"><polygon points="0 0, 8 3.5, 0 7" fill="{INK}"/></marker>
    <marker id="arrow-s" markerWidth="6" markerHeight="5" refX="5" refY="2.5" orient="auto"><polygon points="0 0, 6 2.5, 0 5" fill="{INK}"/></marker>
  </defs>
  <rect width="100%" height="100%" fill="#ffffff"/>
  {image}{zones}{arrows}{nodes}{texts}
</svg>"""
    HTML.write_text(
        f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Kiến trúc TwoStageNILMFormer</title>
<style>body{{margin:0;padding:2rem;background:#fff;display:flex;justify-content:center}}
.diagram-container{{width:100%;max-width:1000px;overflow-x:auto}} svg{{width:100%;min-width:1000px;display:block}}</style></head>
<body><div class="diagram-container">{svg}</div></body></html>
""",
        encoding="utf-8",
    )
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(PNG), output_width=2000)
    print("Đã ghi", HTML, "và", PNG)


if __name__ == "__main__":
    main()
