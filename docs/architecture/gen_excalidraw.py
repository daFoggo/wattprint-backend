"""Generate WattPrint C4 diagrams as .excalidraw files.

Usage: python -I gen_excalidraw.py <out_dir> [--all]
"""
import json
import random
import sys
from pathlib import Path

random.seed(7)
FONT = 2  # Helvetica: has Vietnamese glyphs via system fallback
CW = 0.56  # approx char width / font size

# pastel fill + dark text (light enough to print, readable when scaled down)
STYLE = {
    "person":   dict(bg="#dbe4ff", stroke="#4263eb", fg="#1e1e1e", sub="#495057"),
    "system":   dict(bg="#a5d8ff", stroke="#1971c2", fg="#1e1e1e", sub="#495057"),
    "team":     dict(bg="#b2f2bb", stroke="#2f9e44", fg="#1e1e1e", sub="#495057"),
    "comp":     dict(bg="#d3f9d8", stroke="#2f9e44", fg="#1e1e1e", sub="#495057"),
    "offshelf": dict(bg="#d0bfff", stroke="#7048e8", fg="#1e1e1e", sub="#495057"),
    "db":       dict(bg="#c3fae8", stroke="#0c8599", fg="#1e1e1e", sub="#495057"),
    "external": dict(bg="#ffd8a8", stroke="#e8590c", fg="#1e1e1e", sub="#495057"),
    "queue":    dict(bg="#fff3bf", stroke="#f08c00", fg="#1e1e1e", sub="#495057"),
}
ARROW = {
    "sync":  dict(color="#2b2b2b", style="solid"),
    "reply": dict(color="#5a5a5a", style="dotted"),
    "async": dict(color="#c05600", style="dashed"),
}


def rid():
    return random.randint(1, 2**31 - 1)


def base(i, t, x, y, w, h, **kw):
    d = dict(id=i, type=t, x=x, y=y, width=w, height=h, angle=0, strokeColor="#1e1e1e",
             backgroundColor="transparent", fillStyle="solid", strokeWidth=2, strokeStyle="solid",
             roughness=0, opacity=100, groupIds=[], frameId=None, roundness=None, seed=rid(),
             version=1, versionNonce=rid(), isDeleted=False, boundElements=[], updated=1,
             link=None, locked=False)
    d.update(kw)
    return d


def wrap(s, width_px, fs):
    maxc = max(8, int(width_px / (fs * CW)))
    out = []
    for para in s.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = (line + " " + word).strip()
            if len(cand) > maxc and line:
                out.append(line)
                line = word
            else:
                line = cand
        out.append(line)
    return out


def text(i, x, y, s, fs=16, color="#1e1e1e", align="left", container=None, group=None, width=None):
    lines = s.split("\n")
    w = width if width is not None else max(len(l) for l in lines) * fs * CW
    h = len(lines) * fs * 1.25
    return base(i, "text", x, y, w, h, strokeColor=color, text=s, originalText=s, fontSize=fs,
                fontFamily=FONT, textAlign=align, verticalAlign="middle" if container else "top",
                containerId=container, autoResize=True, lineHeight=1.25,
                groupIds=[group] if group else [], strokeWidth=1)


class Diagram:
    def __init__(self):
        self.els = []
        self.boxes = {}

    def add(self, *els):
        self.els.extend(els)

    # ---------- shapes ----------
    def box(self, i, x, y, w, h, kind, name, tech="", desc="", name_fs=22, desc_fs=16):
        st = STYLE[kind]
        g = "g_" + i
        rnd = {"type": 3}
        rect = base(i, "rectangle", x, y, w, h, strokeColor=st["stroke"], backgroundColor=st["bg"],
                    strokeWidth=st.get("sw", 2), roundness=rnd, groupIds=[g])
        parts = [(name, name_fs, st["fg"])]
        if tech:
            parts.append((tech, 16, st["sub"]))
        if desc:
            parts.append((desc, desc_fs, st["fg"]))
        blocks, total = [], 0
        for k, (s, fs, col) in enumerate(parts):
            lines = wrap(s, w - 28, fs)
            hh = len(lines) * fs * 1.25
            gap = 8 if k else 0
            blocks.append((lines, fs, col, gap))
            total += hh + gap
        yy = y + (h - total) / 2
        out = [rect]
        for k, (lines, fs, col, gap) in enumerate(blocks):
            yy += gap
            s = "\n".join(lines)
            tw = max(len(l) for l in lines) * fs * CW
            out.append(text(f"{i}_t{k}", x + (w - tw) / 2, yy, s, fs, col, "center", group=g, width=tw))
            yy += len(lines) * fs * 1.25
        self.boxes[i] = rect
        self.add(*out)
        return rect

    def boundary(self, i, x, y, w, h, label, dashed=True, color="#666666", fs=18):
        r = base(i, "rectangle", x, y, w, h, strokeColor=color, strokeStyle="dashed" if dashed else "solid",
                 roundness={"type": 3}, strokeWidth=2)
        self.add(r, text(i + "_lbl", x + 16, y + 10, label, fs, color))
        return r

    def label(self, i, x, y, s, fs=16, color="#1e1e1e", align="left"):
        self.add(text(i, x, y, s, fs, color, align))

    # ---------- arrows ----------
    @staticmethod
    def _clip(r, tx, ty, gap=6):
        cx, cy = r["x"] + r["width"] / 2, r["y"] + r["height"] / 2
        dx, dy = tx - cx, ty - cy
        ts = []
        if dx:
            ts.append((r["width"] / 2) / abs(dx))
        if dy:
            ts.append((r["height"] / 2) / abs(dy))
        t = min(ts)
        L = (dx * dx + dy * dy) ** 0.5
        k = t + gap / L
        return cx + dx * k, cy + dy * k

    def arrow(self, i, src, dst, lbl="", kind="sync", pts=None, lbl_seg=None, lbl_w=230, head="arrow"):
        st = ARROW[kind]
        if pts is None:
            a, b = self.boxes[src], self.boxes[dst]
            bc = (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
            ac = (a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
            pts = [self._clip(a, *bc), self._clip(b, *ac)]
        x0, y0 = pts[0]
        rel = [[px - x0, py - y0] for px, py in pts]
        xs = [p[0] for p in rel]
        ys = [p[1] for p in rel]
        el = base(i, "arrow", x0, y0, max(xs) - min(xs), max(ys) - min(ys), strokeColor=st["color"],
                  strokeStyle=st["style"], points=rel, lastCommittedPoint=None,
                  startBinding={"elementId": src, "focus": 0, "gap": 6} if src in self.boxes else None,
                  endBinding={"elementId": dst, "focus": 0, "gap": 6} if dst in self.boxes else None,
                  startArrowhead=None, endArrowhead=head, elbowed=False)
        for k in (src, dst):
            if k in self.boxes:
                self.boxes[k]["boundElements"].append({"id": i, "type": "arrow"})
        self.add(el)
        if lbl:
            if lbl_seg is None:
                segs = list(zip(pts, pts[1:]))
                lbl_seg = max(range(len(segs)), key=lambda n: abs(segs[n][1][0] - segs[n][0][0]) + abs(segs[n][1][1] - segs[n][0][1]))
            (ax, ay), (bx, by) = pts[lbl_seg], pts[lbl_seg + 1]
            mx, my = (ax + bx) / 2, (ay + by) / 2
            lines = wrap(lbl, lbl_w, 16)
            s = "\n".join(lines)
            tw = max(len(l) for l in lines) * 16 * CW
            th = len(lines) * 16 * 1.25
            t = text(i + "_lbl", mx - tw / 2, my - th / 2, s, 16, st["color"], "center", container=i, width=tw)
            el["boundElements"].append({"id": i + "_lbl", "type": "text"})
            self.add(t)
        return el

    def line(self, i, x, y, pts, color="#9a9a9a", style="dashed", sw=1):
        rel = [[px - x, py - y] for px, py in pts]
        xs = [p[0] for p in rel]
        ys = [p[1] for p in rel]
        self.add(base(i, "line", x, y, max(xs) - min(xs), max(ys) - min(ys), strokeColor=color,
                      strokeStyle=style, strokeWidth=sw, points=rel, lastCommittedPoint=None,
                      startBinding=None, endBinding=None, startArrowhead=None, endArrowhead=None))

    # ---------- legend ----------
    def legend(self, x, y, kinds, arrows, w=430):
        rows = len(kinds) + len(arrows)
        h = 70 + rows * 52
        self.add(base("legend", "rectangle", x, y, w, h, strokeColor="#9a9a9a", backgroundColor="#fafafa",
                      roundness={"type": 3}, strokeWidth=1))
        self.label("legend_title", x + 20, y + 16, "Chú giải", 18, "#333333")
        yy = y + 58
        names = {
            "person": "Người dùng (Person)",
            "system": "Hệ thống phần mềm (Software system)",
            "team": "Container do nhóm viết",
            "offshelf": "Container phần mềm có sẵn",
            "db": "Kho dữ liệu (database, volume)",
            "external": "Hệ thống bên ngoài",
            "queue": "Queue RabbitMQ",
            "comp": "Component (module trong service)",
        }
        for k in kinds:
            st = STYLE[k]
            self.add(base(f"lg_{k}", "rectangle", x + 20, yy, 70, 34, strokeColor=st["stroke"],
                          backgroundColor=st["bg"], strokeWidth=st.get("sw", 2), roundness={"type": 3}))
            self.label(f"lg_{k}_t", x + 106, yy + 7, names[k], 16, "#333333")
            yy += 52
        an = {
            "sync": "Gọi đồng bộ (request)",
            "reply": "Phản hồi của lời gọi",
            "async": "Sự kiện bất đồng bộ qua RabbitMQ",
        }
        for k in arrows:
            st = ARROW[k]
            self.add(base(f"lga_{k}", "arrow", x + 20, yy + 17, 70, 0, strokeColor=st["color"],
                          strokeStyle=st["style"], points=[[0, 0], [70, 0]], lastCommittedPoint=None,
                          startBinding=None, endBinding=None, startArrowhead=None, endArrowhead="arrow",
                          elbowed=False))
            self.label(f"lga_{k}_t", x + 106, yy + 7, an[k], 16, "#333333")
            yy += 52

    def title(self, x, y, t, sub):
        self.label("title", x, y, t, 30, "#0b2e4f")
        self.label("subtitle", x, y + 46, sub, 17, "#555555")

    def dump(self, path):
        doc = {"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
               "elements": self.els,
               "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
               "files": {}}
        Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


# =====================================================================
# 00 Overview: one readable page, few words, big text
# =====================================================================
def overview():
    d = Diagram()
    d.label("title", 0, -120, "WattPrint · kiến trúc tổng quan", 34, "#0b2e4f")
    d.label("subtitle", 0, -70, "Một trang, đủ để trình bày. Chi tiết ở sơ đồ 01 (Context), 02 (Container), 03–06 (Component).", 18, "#555555")
    big = dict(name_fs=26, desc_fs=18)
    d.box("app", 300, 0, 260, 90, "team", "App Expo", **big)
    d.box("web", 680, 0, 260, 90, "team", "Web Next.js", **big)
    d.box("sensor", 1060, 0, 260, 90, "external", "REFIT replayer", desc="public dataset REFIT", **big)
    d.label("sensor_note", 1340, 10, "Thay cho cảm biến CT ở aptomat\n(Shelly EM, ESP32 + ESPHome)\nvì đồ án không có thiết bị", 16, "#495057")
    d.box("kc", 1800, 190, 260, 90, "offshelf", "Keycloak", desc="đăng nhập · JWT", **big)
    d.box("gw", 300, 190, 1400, 90, "offshelf", "API Gateway · Envoy",
          desc="kiểm JWT · định tuyến · rate limit · không chứa nghiệp vụ", **big)
    for k in ("app", "web", "sensor"):
        cx = d.boxes[k]["x"] + 130
        d.arrow("in_" + k, k, "gw", pts=[(cx, 96), (cx, 184)])
    d.arrow("jwks", "gw", "kc", "JWKS", pts=[(1706, 235), (1794, 235)], lbl_w=80)

    svc = [("cop", "copilot", "hỏi đáp · gợi ý · RAG", ("copilot_db", "pgvector")),
           ("ins", "insight", "bất thường · dự báo", ("insight_db", "TimescaleDB")),
           ("core", "core", "nhà · số đo · hóa đơn", ("core_db", "TimescaleDB")),
           ("nilm", "nilm", "tách điện từng thiết bị", ("nilm_db", "PostgreSQL"))]
    xs = [300, 680, 1060, 1440]
    for (i, n, desc, (db, dbt)), x in zip(svc, xs):
        d.box(i, x, 380, 260, 130, "team", n, desc=desc, name_fs=28, desc_fs=18)
        d.arrow("r_" + i, "gw", i, pts=[(x + 130, 286), (x + 130, 374)])
        d.box(i + "_db", x + 30, 600, 200, 80, "db", db, desc=dbt, name_fs=20, desc_fs=16)
        d.arrow("d_" + i, i, i + "_db", pts=[(x + 130, 516), (x + 130, 594)])
    for (a, _, _, _), (b, _, _, _), x in zip(svc, svc[1:], xs):
        d.arrow(f"s_{a}", a, b, "gọi", pts=[(x + 266, 415), (x + 374, 415)], lbl_w=80)
        d.arrow(f"e_{a}", b, a, "sự kiện", "async", pts=[(x + 374, 475), (x + 266, 475)], lbl_w=90)
    d.box("llm", 0, 380, 220, 130, "external", "LLM", desc="API ngoài", **big)
    d.arrow("llm_a", "cop", "llm", pts=[(294, 445), (226, 445)])
    d.box("infra", 300, 750, 1400, 80, "offshelf", "Hạ tầng chung",
          desc="PostgreSQL 18 + TimescaleDB + pgvector (một server, mỗi service và Keycloak một DB) · "
               "RabbitMQ: exchange → queue → DLQ", name_fs=22, desc_fs=18)
    d.legend(1800, 380, ["team", "offshelf", "db", "external"], ["sync", "async"], w=420)
    return d


# =====================================================================
# 01 System context
# =====================================================================
def context():
    d = Diagram()
    d.title(0, -170, "[System Context] WattPrint",
            "Phạm vi: WattPrint và những người, hệ thống bên ngoài mà nó tương tác. Chi tiết bên trong ở sơ đồ Container.")
    d.box("hh", 420, 0, 360, 170, "person", "Thành viên hộ gia đình", "[Person]",
          "Xem điện từng thiết bị, hóa đơn, cảnh báo; hỏi Energy Copilot")
    d.box("op", 1180, 0, 360, 170, "person", "Nhóm vận hành", "[Person]",
          "Quản trị nhà, công tơ, model; nhận phản hồi người dùng")
    d.box("sys", 660, 400, 640, 250, "system", "WattPrint", "[Software system]",
          "Tách điện từng thiết bị từ một cảm biến ở aptomat (NILM), tính tiền theo biểu giá 5 bậc, "
          "phát hiện bất thường, dự báo hóa đơn, trợ lý năng lượng hai chiều", name_fs=26)
    d.box("meter", 0, 430, 420, 190, "external", "REFIT replayer", "[Công cụ demo: Python]",
          "Phát lại public dataset REFIT, gửi batch số đo qua gateway giống hệt cảm biến thật")
    d.label("meter_note", 0, 640, "Ghi chú: ngoài đời là cảm biến CT ở aptomat\n(Shelly EM, ESP32 + ESPHome); đồ án dùng\npublic dataset REFIT vì không có thiết bị.", 16, "#495057")
    d.box("llm", 1600, 140, 420, 170, "external", "Nhà cung cấp LLM", "[External system]",
          "API tương thích OpenAI: chat, tool calling, embedding")
    d.box("wx", 1600, 440, 420, 170, "external", "Open-Meteo", "[External system]",
          "Nhiệt độ, độ ẩm theo giờ")
    d.box("push", 1600, 740, 420, 170, "external", "Expo Push", "[External system]",
          "Chuyển thông báo đẩy tới điện thoại người dùng")
    d.box("tg", 1080, 860, 400, 170, "external", "Telegram Bot API", "[External system]",
          "Kênh nhận phản hồi, sự cố của nhóm vận hành")
    d.box("gg", 480, 860, 400, 170, "external", "Google Identity", "[External system]",
          "Đăng nhập bằng tài khoản Google (liên kết qua Keycloak)")
    d.arrow("a1", "hh", "sys", "Xem số liệu, hỏi Copilot [app Expo, web Next.js]")
    d.arrow("a2", "op", "sys", "Quản trị, xem log và queue [web, RabbitMQ UI]")
    d.arrow("a3", "meter", "sys", "Gửi batch số đo công suất [HTTPS/JSON]", lbl_w=200)
    d.arrow("a4", "sys", "llm", "Gửi prompt đã ẩn PII [HTTPS]", lbl_w=200)
    d.arrow("a5", "sys", "wx", "Lấy thời tiết theo giờ [HTTPS]", lbl_w=200)
    d.arrow("a6", "sys", "push", "Gửi gợi ý, cảnh báo [HTTPS]", lbl_w=200)
    d.arrow("a7", "sys", "tg", "Chuyển phản hồi, sự cố [HTTPS]", lbl_w=200)
    d.arrow("a8", "sys", "gg", "Đăng nhập liên kết [OIDC]", lbl_w=200)
    d.legend(0, 820, ["person", "system", "external"], ["sync"])
    return d


# =====================================================================
# 02 Container
# =====================================================================
def container():
    d = Diagram()
    d.title(0, -220, "[Container] WattPrint",
            "Phạm vi: các khối chạy độc lập bên trong WattPrint. Mỗi service nghiệp vụ có mã nguồn, database và OpenAPI riêng.")
    d.boundary("b_sys", 20, 250, 2800, 1480, "WattPrint [Software system]", color="#1168bd", fs=20)

    d.box("hh", 1150, -100, 360, 160, "person", "Thành viên hộ gia đình", "[Person]")
    d.box("op", 1800, -100, 360, 160, "person", "Nhóm vận hành", "[Person]")

    d.box("kc", 60, 320, 420, 190, "offshelf", "Identity provider", "[Container: Keycloak 26]",
          "Đăng nhập, user, role; cấp JWT; liên kết Google")
    d.box("mob", 760, 320, 380, 190, "team", "Ứng dụng di động", "[Container: Expo, React Native]",
          "Màn hình tiêu thụ, hóa đơn, cảnh báo, chat Copilot")
    d.box("web", 1380, 320, 380, 190, "team", "Web dashboard", "[Container: Next.js 16]",
          "Dashboard hộ và trang quản trị")
    d.box("meter", 2300, -100, 420, 160, "external", "REFIT replayer", "[Công cụ demo: Python]",
          "Phát lại public dataset REFIT")
    d.label("meter_note", 2760, -90, "Thay cho cảm biến CT ở aptomat\n(Shelly EM, ESP32 + ESPHome)", 16, "#495057")

    d.box("gw", 500, 620, 2280, 120, "offshelf", "API Gateway", "[Container: Envoy 1.40, bộ lọc jwt_authn]",
          "Điểm vào duy nhất, HTTPS: kiểm JWT (RS256, iss, aud), định tuyến theo prefix, rate limit, x-request-id, timeout và retry. Không chứa luật nghiệp vụ.")

    sx = {"cop": 500, "ins": 1120, "core": 1740, "nilm": 2360}
    SY, SW, SH = 920, 420, 240
    d.box("cop", sx["cop"], SY, SW, SH, "team", "copilot", "[Container: Python, FastAPI, FastStream]",
          "Trợ lý hai chiều: hỏi đáp, gợi ý chủ động, guardrail PII/injection, verifier, RAG, thông báo")
    d.box("ins", sx["ins"], SY, SW, SH, "team", "insight", "[Container: Python, FastAPI, FastStream]",
          "Read model tiêu thụ; bất thường, chạy ngầm, dự báo hóa đơn, so sánh nhóm, what-if, M&V; truy vấn an toàn")
    d.box("core", sx["core"], SY, SW, SH, "team", "core", "[Container: Python, FastAPI, FastStream]",
          "Nhà, công tơ, thiết bị, nhận số đo, biểu giá 5 bậc, hóa đơn. Nguồn sự thật")
    d.box("nilm", sx["nilm"], SY, SW, SH, "team", "nilm", "[Container: Python, FastAPI, PyTorch]",
          "Suy luận NILMFormer, hiệu chỉnh theo hộ, quản lý phiên bản model")

    DY, DH = 1320, 160
    d.box("cop_db", 500, DY, 200, DH, "db", "copilot_db", "[PostgreSQL + pgvector]", name_fs=17)
    d.box("llm", 720, DY, 200, DH, "external", "LLM provider", "[External]", "Chat, embedding", name_fs=17)
    d.box("ins_db", 1120, DY, 200, DH, "db", "insight_db", "[PostgreSQL + TimescaleDB]", name_fs=17)
    d.box("wx", 1340, DY, 200, DH, "external", "Open-Meteo", "[External]", "Thời tiết theo giờ", name_fs=17)
    d.box("core_db", 1740, DY, 200, DH, "db", "core_db", "[PostgreSQL + TimescaleDB]", name_fs=17)
    d.box("nilm_db", 2360, DY, 200, DH, "db", "nilm_db", "[PostgreSQL]", "Model, hiệu chỉnh, lần chạy", name_fs=17)
    d.box("models", 2580, DY, 200, DH, "db", "Kho model", "[Docker volume, chỉ đọc]", name_fs=17)
    d.box("notify", 40, 960, 340, 170, "external", "Expo Push, Telegram", "[External system]",
          "Thông báo tới điện thoại; phản hồi tới nhóm vận hành")
    # C4: each queue is a container (data store); the broker itself is only a deployment concern
    QY, QH = 1560, 140
    d.box("q_cop_dlq", 500, QY, 280, QH, "queue", "copilot.alerts.dlq", "[Queue: RabbitMQ]", "Message lỗi quá 3 lần")
    d.box("q_cop", 900, QY, 360, QH, "queue", "copilot.alerts", "[Queue: RabbitMQ quorum]", "insight.alert.created")
    d.box("q_ins", 1600, QY, 480, QH, "queue", "insight.usage", "[Queue: RabbitMQ quorum]",
          "energy.usage.updated, core.device.changed")
    d.box("q_ins_dlq", 2200, QY, 400, QH, "queue", "insight.usage.dlq", "[Queue: RabbitMQ]", "Message lỗi quá 3 lần")

    d.arrow("p1", "hh", "mob", "Dùng hằng ngày", lbl_w=150)
    d.arrow("p2", "hh", "web", "Xem dashboard", lbl_w=150)
    d.arrow("p3", "op", "web", "Quản trị", lbl_w=120)
    d.arrow("k1", "mob", "kc", "Đăng nhập [OIDC + PKCE]", lbl_w=180)
    d.arrow("k2", "web", "kc", "Đăng nhập [OIDC]", pts=[(1420, 314), (1420, 296), (270, 296), (270, 314)], lbl_seg=1)
    d.arrow("g1", "mob", "gw", "Gọi API [HTTPS/JSON, JWT]", pts=[(950, 516), (950, 614)], lbl_w=210)
    d.arrow("g2", "web", "gw", "Gọi API [HTTPS/JSON, JWT]", pts=[(1570, 516), (1570, 614)], lbl_w=210)
    d.arrow("g3", "meter", "gw", "Gửi batch số đo [HTTPS, API key thiết bị]", pts=[(2510, 66), (2510, 614)], lbl_w=230)
    d.arrow("g4", "gw", "kc", "Lấy khóa công khai kiểm JWT [JWKS, HTTPS]", pts=[(494, 680), (270, 680), (270, 516)], lbl_seg=1, lbl_w=200)
    for k, path in (("cop", "/api/copilot/*"), ("ins", "/api/insight/*"), ("core", "/api/core/*"), ("nilm", "/api/nilm/* (admin)")):
        cx = sx[k] + SW / 2
        d.arrow("r_" + k, "gw", k, f"Định tuyến {path} [HTTP]", pts=[(cx, 746), (cx, SY - 6)], lbl_w=200)
    # sync chain (top band) and events (bottom band)
    d.arrow("s1", "cop", "ins", "Gọi tool: truy vấn an toàn, dự báo, what-if [REST]", pts=[(926, 980), (1114, 980)], lbl_w=170)
    d.arrow("s2", "ins", "core", "Lấy biểu giá, danh sách thiết bị [REST]", pts=[(1546, 980), (1734, 980)], lbl_w=170)
    d.arrow("s3", "core", "nilm", "Yêu cầu suy luận [REST, timeout 3s]", pts=[(2166, 980), (2354, 980)], lbl_w=170)
    d.arrow("e1", "core", "q_ins", "gửi [AMQP]", "async", pts=[(2050, 1166), (2050, QY - 6)], lbl_w=100)
    d.arrow("e2", "q_ins", "ins", "nhận [AMQP]", "async", pts=[(1640, QY - 6), (1640, 1100), (1546, 1100)], lbl_seg=0, lbl_w=100)
    d.arrow("e3", "ins", "q_cop", "gửi [AMQP]", "async", pts=[(1114, 1100), (1070, 1100), (1070, QY - 6)], lbl_seg=1, lbl_w=100)
    d.arrow("e4", "q_cop", "cop", "nhận [AMQP]", "async", pts=[(990, QY - 6), (990, 1040), (926, 1040)], lbl_seg=0, lbl_w=100)
    d.arrow("e5", "q_cop", "q_cop_dlq", "quá 3 lần", "async", pts=[(894, QY + 70), (786, QY + 70)], lbl_w=100)
    d.arrow("e6", "q_ins", "q_ins_dlq", "quá 3 lần", "async", pts=[(2086, QY + 70), (2194, QY + 70)], lbl_w=100)
    d.arrow("n1", "cop", "notify", "Gửi thông báo, phản hồi [HTTPS]", pts=[(494, 1045), (386, 1045)], lbl_w=100)
    # data and externals
    d.arrow("d1", "cop", "cop_db", "Đọc/ghi [SQL]", pts=[(600, SY + SH + 6), (600, DY - 6)], lbl_w=110)
    d.arrow("d2", "cop", "llm", "Prompt đã ẩn PII [HTTPS]", pts=[(820, SY + SH + 6), (820, DY - 6)], lbl_w=110)
    d.arrow("d3", "ins", "ins_db", "Đọc/ghi [SQL]", pts=[(1220, SY + SH + 6), (1220, DY - 6)], lbl_w=110)
    d.arrow("d4", "ins", "wx", "Lấy thời tiết [HTTPS]", pts=[(1440, SY + SH + 6), (1440, DY - 6)], lbl_w=110)
    d.arrow("d5", "core", "core_db", "Đọc/ghi [SQL]", pts=[(1840, SY + SH + 6), (1840, DY - 6)], lbl_w=110)
    d.arrow("d6", "nilm", "nilm_db", "Đọc/ghi [SQL]", pts=[(2460, SY + SH + 6), (2460, DY - 6)], lbl_w=110)
    d.arrow("d7", "nilm", "models", "Nạp trọng số [file]", pts=[(2680, SY + SH + 6), (2680, DY - 6)], lbl_w=110)
    d.legend(40, 1790, ["person", "team", "offshelf", "db", "queue", "external"], ["sync", "async"], w=460)
    d.label("note", 580, 1790,
            "Ghi chú\n"
            "• Nét đứt là message AMQP. Service gửi lên exchange wattprint.events, exchange chép vào queue theo routing key (README mục 3).\n"
            "• Theo C4, mỗi queue là một container lưu message; RabbitMQ chỉ xuất hiện ở sơ đồ Deployment.\n"
            "• Một PostgreSQL server, mỗi service (và Keycloak) một database, một role; không service nào đọc database của service khác.\n"
            "• Lời gọi đồng bộ chỉ đi một chiều copilot → insight → core → nilm. Thông tin đi ngược lên chỉ bằng sự kiện.\n"
            "• Mọi lời gọi giữa service có timeout, retry có giới hạn, circuit breaker; địa chỉ lấy từ biến môi trường.\n"
            "• Mỗi service là một container: API, consumer và outbox relay chạy chung process; có /health và /ready.", 16, "#333333")
    return d


# =====================================================================
# 03 Deployment
# =====================================================================
def deployment():
    d = Diagram()
    d.title(0, -170, "[Deployment] WattPrint, môi trường demo",
            "Phạm vi: một máy chạy Docker Compose, khởi động toàn bộ bằng `docker compose up`. Cổng theo dải 1109x của dự án.")
    d.box("client", 900, -40, 640, 130, "person", "Điện thoại, trình duyệt, Postman/Newman, REFIT replayer", "[Client]")
    d.boundary("host", 20, 160, 2700, 1060,
               "Máy demo / server lab  [Deployment node: Ubuntu 24.04, Docker Engine + Compose v2, ≥ 16 GB RAM]",
               dashed=False, color="#333333")

    d.boundary("n_edge", 60, 230, 2620, 250, "Cổng vào  [network: edge, có publish port]", color="#5b8fc7")
    d.box("kong", 100, 290, 820, 160, "offshelf", "gateway", "[envoyproxy/envoy:v1.40 · :11093 (lab), :443 (server) · 256 MB]",
          "Proxy duy nhất ra ngoài; jwt_authn kiểm JWT, local rate limit, x-request-id, timeout, retry")
    d.box("kc", 960, 290, 820, 160, "offshelf", "keycloak", "[keycloak:26 · :11095 · 1 GB]",
          "Realm wattprint import khi khởi động; dữ liệu nằm ở keycloak_db trên postgres")
    d.box("mqui", 1820, 290, 820, 160, "offshelf", "RabbitMQ management", "[:11099, chỉ 127.0.0.1]",
          "Xem queue, DLQ, đẩy lại message")

    d.boundary("n_app", 60, 530, 2620, 260, "Service ứng dụng  [network: internal, không publish port]", color="#2e6295")
    cols = [100, 740, 1380, 2020]
    api = [("copilot", "512 MB · 1 CPU"), ("insight", "512 MB · 1 CPU"), ("core", "512 MB · 1 CPU"), ("nilm", "2 GB · 2 CPU, PyTorch CPU")]
    for c, (n, lim) in zip(cols, api):
        d.box("api_" + n, c, 590, 600, 160, "team", n, f"[Container · {lim}]", "uvicorn: API + consumer + outbox relay · /health · /ready")

    d.boundary("n_data", 60, 840, 2620, 300, "Dữ liệu và messaging  [network: internal]", color="#2e6295")
    d.box("pg", 100, 900, 920, 200, "db", "postgres",
          "[timescale/timescaledb:2.31.0-pg18 · 1.5 GB · volume pgdata]",
          "5 database: core_db, insight_db (TimescaleDB: hypertable, continuous aggregate), copilot_db (pgvector), nilm_db, keycloak_db")
    d.box("mq", 1060, 900, 760, 200, "offshelf", "rabbitmq", "[rabbitmq:4-management · 512 MB · volume mqdata]",
          "Exchange wattprint.events, quorum queue theo consumer, delivery-limit 3 → DLQ")
    d.box("vol", 1860, 900, 780, 200, "db", "models", "[Docker volume, mount chỉ đọc vào nilm]",
          "Trọng số NILMFormer theo phiên bản, ví dụ nilmformer-refit-v3.pt")

    d.label("o_note", 100, 1160,
            "Log: mọi container ghi JSON ra stdout có request_id, xem bằng docker compose logs.  "
            "Tổng giới hạn bộ nhớ toàn hệ thống ≈ 7 GB, 8 container.", 16, "#333333")

    d.box("saas", 2860, 560, 520, 400, "external", "Dịch vụ bên ngoài", "[Internet, HTTPS]",
          "LLM provider (server, key của thầy Cường)\nOpen-Meteo\nExpo Push\nTelegram Bot API")
    d.box("gha", 2860, 1000, 520, 240, "external", "GitHub Actions", "[CI runner]",
          "ruff + pytest từng service, build image, compose up, Newman chạy Postman collection, kiểm OpenAPI")

    d.arrow("c1", "client", "kong", "HTTPS :11093", pts=[(1000, 96), (1000, 212), (660, 212), (660, 284)], lbl_seg=1, lbl_w=160)
    d.arrow("c2", "kong", "", "HTTP nội bộ tới 4 API, theo route", pts=[(660, 456), (660, 584)], lbl_w=170)
    d.arrow("c3", "", "saas", "copilot, insight gọi API ngoài [HTTPS]", pts=[(2686, 760), (2854, 760)], lbl_w=150)
    d.legend(2860, 1290, ["team", "offshelf", "db", "external"], ["sync"], w=460)
    return d


# =====================================================================
# Sequence-style dynamic diagrams
# =====================================================================
def sequence(title, sub, parts, steps, frames=(), col=330, bw=280, row=78, top=0):
    """parts: [(id, kind, name, tech)], steps: [(src, dst, label, kind)] src==dst = self note.
    frames: [(first_step_idx, last_step_idx, label)]"""
    d = Diagram()
    d.title(0, top - 170, title, sub)
    xs = {}
    for n, (pid, kind, name, tech) in enumerate(parts):
        x = n * col
        xs[pid] = x + bw / 2
        d.box(pid, x, top, bw, 110, kind, name, tech, name_fs=18)
    FS = 16
    order = list(xs)

    def lbl_lines(k, st):
        s = f"{k + 1}. {st[2]}"
        if st[0] == st[1]:
            return wrap(s, 400, FS)
        span = col * abs(order.index(st[1]) - order.index(st[0])) - 30
        return wrap(s, max(span, 2 * col - 30), FS)

    y = top + 170
    ys = []
    for k, st in enumerate(steps):
        n = len(lbl_lines(k, st))
        h = max(row, 34 + n * FS * 1.25 + 22) if st[0] != st[1] else max(row, 24 + n * FS * 1.25)
        ys.append((y, h))
        y += h
    end = y + 30
    for pid in xs:
        d.line("ll_" + pid, xs[pid], top + 110, [(xs[pid], top + 116), (xs[pid], end)])
    for k, (a, b, lbl, kind) in enumerate(steps):
        yy, h = ys[k]
        lines = lbl_lines(k, (a, b, lbl, kind))
        th = len(lines) * FS * 1.25
        col_c = ARROW[kind]["color"]
        if a == b:
            x = xs[a]
            cy = yy + h / 2
            d.arrow(f"st{k}", "", "", "", kind, pts=[(x + 4, cy - 14), (x + 46, cy - 14), (x + 46, cy + 14), (x + 6, cy + 14)])
            d.label(f"st{k}_t", x + 58, cy - th / 2, "\n".join(lines), FS, col_c)
        else:
            x1, x2 = xs[a], xs[b]
            dirn = 1 if x2 > x1 else -1
            ay = yy + 14 + th + 10
            d.arrow(f"st{k}", "", "", "", kind, pts=[(x1 + dirn * 6, ay), (x2 - dirn * 6, ay)])
            lx = min(x1, x2) + 16
            d.label(f"st{k}_t", lx, yy + 14, "\n".join(lines), FS, col_c)
    for n, (i0, i1, lbl) in enumerate(frames):
        fy0 = ys[i0][0] - 6
        fy1 = ys[i1][0] + ys[i1][1] + 4
        fx0 = min(xs.values()) - bw / 2 - 20
        fx1 = max(xs.values()) + bw / 2 + 20
        d.add(base(f"fr{n}", "rectangle", fx0, fy0, fx1 - fx0, fy1 - fy0, strokeColor="#7a5c99",
                   strokeStyle="dashed", strokeWidth=1, roundness=None))
        d.label(f"fr{n}_t", fx0 + 8, fy0 + 4, lbl, 14, "#7a5c99")
    total_w = len(parts) * col
    kinds = []
    for _, k, _, _ in parts:
        if k not in kinds:
            kinds.append(k)
    arrows = [k for k in ("sync", "reply", "async") if any(s[3] == k for s in steps)]
    d.legend(total_w + 40, top, kinds, arrows)
    return d


def ingest():
    parts = [("meter", "external", "REFIT replayer", "[thay cảm biến CT]"),
             ("gw", "offshelf", "API Gateway", "[Envoy]"),
             ("core", "team", "core", "[FastAPI]"),
             ("cdb", "db", "core_db", "[TimescaleDB]"),
             ("nilm", "team", "nilm", "[FastAPI, PyTorch]"),
             ("wk", "team", "core: outbox relay", "[background task]"),
             ("mq", "offshelf", "RabbitMQ", "[broker]"),
             ("ins", "team", "insight: consumer", "[FastStream]")]
    steps = [
        ("meter", "gw", "POST /api/core/ingest/batches, Idempotency-Key = batch_id", "sync"),
        ("gw", "core", "Rate limit, gắn x-request-id, chuyển tiếp (route ingest dùng API key, không cần JWT)", "sync"),
        ("core", "cdb", "Kiểm API key và công tơ thuộc nhà (401/403); batch_id chưa xử lý, số đo liên tục, đủ cửa sổ (409/422)", "sync"),
        ("core", "cdb", "Lưu readings, batch = RECEIVED (một transaction)", "sync"),
        ("core", "nilm", "POST /inferences: cửa sổ công suất tổng. Timeout 3s, retry 2 lần, circuit breaker", "sync"),
        ("nilm", "core", "200: công suất từng thiết bị, confidence, model_version", "reply"),
        ("core", "cdb", "Lưu device_estimate, batch = DONE, ghi outbox event (cùng transaction)", "sync"),
        ("core", "meter", "201 Created {status: DONE} (đi qua gateway)", "reply"),
        ("core", "cdb", "batch = PENDING_INFERENCE (dữ liệu không mất)", "sync"),
        ("core", "meter", "202 Accepted {status: PENDING_INFERENCE}", "reply"),
        ("wk", "nilm", "Thử lại theo backoff 1, 2, 4 phút; quá 5 lần → FAILED và cảnh báo vận hành", "sync"),
        ("wk", "cdb", "Đọc outbox chưa gửi", "sync"),
        ("wk", "mq", "Publish energy.usage.updated (kèm tổng theo giờ từng thiết bị)", "async"),
        ("mq", "ins", "Giao message; insight xử lý idempotent theo message_id", "async"),
    ]
    frames = [(5, 7, "[alt] nilm trả lời kịp"), (8, 10, "[alt] nilm timeout, lỗi 5xx hoặc breaker đang mở")]
    return sequence("[Dynamic] Nhận số đo và suy luận NILM",
                    "Luồng nghiệp vụ bắt buộc qua nhiều service: core → nilm, có trạng thái PENDING khi không biết kết quả.",
                    parts, steps, frames)


def proactive():
    parts = [("mq", "offshelf", "RabbitMQ", "[broker]"),
             ("iw", "team", "insight: consumer", "[FastStream]"),
             ("idb", "db", "insight_db", "[TimescaleDB]"),
             ("ia", "team", "insight", "[FastAPI]"),
             ("cw", "team", "copilot: consumer", "[FastStream]"),
             ("cdb", "db", "copilot_db", "[PostgreSQL]"),
             ("push", "external", "Expo Push", "[External system]")]
    steps = [
        ("mq", "iw", "energy.usage.updated (queue insight.usage)", "async"),
        ("iw", "idb", "Inbox: message_id đã xử lý thì bỏ qua; chưa thì cập nhật read model theo giờ", "sync"),
        ("iw", "iw", "Chạy detector: chạy ngầm, chạy lâu bất thường, dự báo chạm bậc giá, vượt ngân sách", "sync"),
        ("iw", "idb", "Lưu alert và outbox (cùng transaction)", "sync"),
        ("iw", "mq", "Publish insight.alert.created", "async"),
        ("mq", "cw", "Giao message (queue copilot.alerts)", "async"),
        ("cw", "ia", "POST /what-if: kWh và VND tiết kiệm của từng hành động", "sync"),
        ("ia", "cw", "200: danh sách hành động kèm ΔE, ΔVND", "reply"),
        ("cw", "cw", "Xếp hạng: min ΔE − λ·log p̂(người dùng chấp nhận); bỏ giờ yên tĩnh, bỏ gợi ý trùng 7 ngày", "sync"),
        ("cw", "cdb", "Lưu suggestion, nhãn AI tạo, inbox (cùng transaction)", "sync"),
        ("cw", "push", "Gửi thông báo đẩy", "sync"),
        ("cw", "mq", "Lỗi xử lý → nack; quorum queue giao lại, quá delivery-limit 3 → copilot.alerts.dlq", "async"),
    ]
    frames = [(11, 11, "[alt] xử lý thất bại")]
    return sequence("[Dynamic] Gợi ý chủ động (vòng push)",
                    "Luồng phụ bất đồng bộ: consumer idempotent, retry và hàng đợi lỗi (DLQ).",
                    parts, steps, frames)


def qa():
    parts = [("user", "person", "Người dùng", "[app Expo / web]"),
             ("gw", "offshelf", "API Gateway", "[Envoy]"),
             ("gr", "team", "copilot: Guardrail", "[component]"),
             ("orch", "team", "copilot: Orchestrator", "[component]"),
             ("ver", "team", "copilot: Verifier", "[component]"),
             ("cdb", "db", "copilot_db", "[pgvector]"),
             ("ia", "team", "insight", "[FastAPI]"),
             ("llm", "external", "LLM provider", "[External system]")]
    steps = [
        ("user", "gw", "POST /api/copilot/conversations/{id}/messages: \"Tại sao tháng này tiền điện cao?\"", "sync"),
        ("gw", "gr", "JWT hợp lệ, rate limit 20 tin/phút, chuyển tiếp", "sync"),
        ("gr", "gr", "Tìm PII (regex SĐT, CCCD, email + NER) → thay placeholder; kiểm prompt injection; kiểm gói Pro (403)", "sync"),
        ("gr", "user", "409 pii_confirmation_required: hỏi người dùng có thật sự muốn gửi", "reply"),
        ("gr", "orch", "Câu hỏi đã làm sạch và ngữ cảnh hộ", "sync"),
        ("orch", "llm", "Prompt và danh sách tool (function calling). Timeout 20s, circuit breaker", "sync"),
        ("llm", "orch", "Tool calls: so sánh tháng, tiêu thụ theo thiết bị, thời tiết", "reply"),
        ("orch", "ia", "POST /queries (SQL do LLM sinh) và GET /forecast", "sync"),
        ("ia", "ia", "Chỉ cho SELECT trên view được phép, ép home_id, timeout 2s; sai → 400", "sync"),
        ("ia", "orch", "Số liệu và nguồn", "reply"),
        ("orch", "cdb", "Tìm tri thức liên quan (pgvector) để giải thích và trích dẫn", "sync"),
        ("orch", "llm", "Kết quả tool → soạn câu trả lời", "sync"),
        ("llm", "orch", "Bản nháp", "reply"),
        ("orch", "ver", "Gửi bản nháp và kết quả tool", "sync"),
        ("ver", "ver", "Mọi con số khớp kết quả tool, đúng đơn vị kWh/VND, có trích dẫn; gắn nhãn AI tạo và độ tin cậy", "sync"),
        ("ver", "cdb", "Lưu message, tool_call, số token", "sync"),
        ("ver", "user", "200: câu trả lời, trích dẫn, nhãn AI tạo, độ tin cậy", "reply"),
        ("orch", "user", "503 + số liệu thô từ tool (không diễn giải), Retry-After", "reply"),
    ]
    frames = [(3, 3, "[alt] có PII chưa xác nhận"), (17, 17, "[alt] LLM timeout hoặc breaker đang mở")]
    return sequence("[Dynamic] Hỏi đáp với Energy Copilot (vòng pull)",
                    "Nguyên tắc tools first, language second: số liệu do tool tính, LLM chỉ lập kế hoạch và diễn giải.",
                    parts, steps, frames)


def saga():
    parts = [("user", "person", "Người dùng", "[app Expo]"),
             ("cop", "team", "copilot", "[saga orchestrator]"),
             ("cdb", "db", "copilot_db", "[PostgreSQL]"),
             ("ia", "team", "insight", "[FastAPI]"),
             ("cw", "team", "copilot: reconciler", "[background task]")]
    steps = [
        ("user", "cop", "POST /api/copilot/plans {suggestion_id}, Idempotency-Key", "sync"),
        ("cop", "cdb", "plan = PENDING, lưu các bước của saga", "sync"),
        ("cop", "ia", "Bước 1: POST /savings-measures (baseline M&V, cần ≥ 14 ngày dữ liệu, thiếu → 422)", "sync"),
        ("ia", "cop", "201 measure_id", "reply"),
        ("cop", "ia", "Bước 2: PUT /homes/{id}/budget (ngân sách tháng theo kế hoạch)", "sync"),
        ("ia", "cop", "200", "reply"),
        ("cop", "cdb", "plan = ACTIVE, tạo lịch nhắc", "sync"),
        ("cop", "user", "201 {status: ACTIVE}", "reply"),
        ("ia", "cop", "422 ngân sách thấp hơn mức tối thiểu", "reply"),
        ("cop", "ia", "Bù trừ bước 1: DELETE /savings-measures/{id}", "sync"),
        ("cop", "cdb", "plan = CANCELLED, lưu lý do", "sync"),
        ("cop", "user", "422 kèm lý do", "reply"),
        ("cop", "cdb", "Bước 2 timeout: không biết insight đã ghi chưa → plan giữ PENDING", "sync"),
        ("cop", "user", "202 {status: PENDING}", "reply"),
        ("cw", "ia", "Reconciler: GET /homes/{id}/budget → đã đổi thì hoàn tất ACTIVE, chưa thì bù trừ bước 1", "sync"),
    ]
    frames = [(5, 7, "[alt] bước 2 thành công"), (8, 11, "[alt] bước 2 bị từ chối (4xx): hoàn tác theo thứ tự ngược"),
              (12, 14, "[alt] bước 2 timeout (lỗi hạ tầng 504)")]
    return sequence("[Dynamic] Kích hoạt kế hoạch tiết kiệm (saga)",
                    "Saga do copilot điều phối qua copilot và insight: hoàn tác theo thứ tự ngược, PENDING khi không biết kết quả.",
                    parts, steps, frames, col=380, bw=300)


# =====================================================================
# 08 Messaging: one event end to end, RabbitMQ tutorial order (producer → exchange → queue → consumer)
# =====================================================================
def messaging():
    d = Diagram()
    d.title(0, -170, "[Dynamic] Một sự kiện đi qua RabbitMQ: outbox → exchange → queue → consumer → DLQ",
            "Ví dụ energy.usage.updated từ core tới insight. Số trên mũi tên khớp với danh sách bước bên dưới.")
    W, H, G = 240, 130, 150
    row = [("core", "team", "core", "[FastAPI]", "Lưu kết quả NILM"),
           ("cdb", "db", "core_db", "[bảng outbox]", ""),
           ("relay", "team", "outbox relay", "[background task trong core]", ""),
           ("ex", "queue", "wattprint.events", "[Exchange: topic]", ""),
           ("q", "queue", "insight.usage", "[Queue: quorum, delivery-limit 3]", ""),
           ("ic", "team", "insight consumer", "[FastStream]", ""),
           ("idb", "db", "insight_db", "[bảng inbox + read model]", "")]
    xs = {}
    for n, (i, kind, name, tech, desc) in enumerate(row):
        xs[i] = n * (W + G)
        d.box(i, xs[i], 0, W, H, kind, name, tech, desc, name_fs=20)
    links = [("core", "cdb", "1", "sync"), ("cdb", "relay", "2", "sync"), ("relay", "ex", "3", "async"),
             ("ex", "q", "4", "async"), ("q", "ic", "5", "async"), ("ic", "idb", "6", "sync")]
    for a, b, n, kind in links:
        y = 40 if (a, b) == ("q", "ic") else 65
        d.arrow(f"m{n}", a, b, n, kind, pts=[(xs[a] + W + 6, y), (xs[b] - 6, y)], lbl_w=40)
    d.arrow("nack", "ic", "q", "nack", "async", pts=[(xs["ic"] - 6, 95), (xs["q"] + W + 6, 95)], lbl_w=60)

    FY = 330
    d.box("dlx", xs["q"], FY, W, H, "queue", "wattprint.dlx", "[Exchange: dead-letter]")
    d.box("dlq", xs["ic"], FY, W, H, "queue", "insight.usage.dlq", "[Queue]", "Message nằm chờ, không mất")
    d.box("op", xs["idb"], FY, W, H, "person", "Nhóm vận hành", "[RabbitMQ UI :11099]")
    cx = xs["q"] + W / 2
    d.arrow("m7", "q", "dlx", "7", "async", pts=[(cx, H + 6), (cx, FY - 6)], lbl_w=40)
    d.arrow("m8", "dlx", "dlq", "8", "async", pts=[(xs["q"] + W + 6, FY + 65), (xs["ic"] - 6, FY + 65)], lbl_w=40)
    d.arrow("m9", "dlq", "op", "9", "sync", pts=[(xs["ic"] + W + 6, FY + 65), (xs["idb"] - 6, FY + 65)], lbl_w=40)

    d.label("json_t", 0, FY - 4, "Ví dụ message (routing key energy.usage.updated, body JSON)", 16, "#333333")
    js = ('{\n'
          '  "message_id": "6f1c2b9e-0d4a-4c1e-9a77-2f5e8b1d3c40",\n'
          '  "type": "energy.usage.updated",\n'
          '  "occurred_at": "2026-11-10T08:00:05Z",\n'
          '  "home_id": 42,\n'
          '  "hour": "2026-11-10T07:00:00Z",\n'
          '  "kwh_by_device": {"fridge": 0.12, "washing_machine": 0.85, "standby": 0.05}\n'
          '}')
    d.add(base("json_bg", "rectangle", 0, FY + 26, 1400, 230, strokeColor="#1e1e2e", backgroundColor="#1e1e2e",
               roundness={"type": 3}))
    t = text("json", 24, FY + 44, js, 17, "#e5e5e5")
    t["fontFamily"] = 3
    d.add(t)

    d.label("steps", 0, 640,
            "Các bước\n"
            "1. core lưu kết quả NILM và một dòng vào bảng outbox trong cùng một transaction: lưu được cả hai hoặc không gì cả.\n"
            "2. Outbox relay (vòng lặp nền trong core) đọc các dòng chưa gửi bằng SELECT … FOR UPDATE SKIP LOCKED.\n"
            "3. Relay publish lên exchange wattprint.events với routing key energy.usage.updated, đợi broker xác nhận rồi mới đánh dấu đã gửi.\n"
            "4. Exchange kiểu topic chép message vào mọi queue có binding khớp. insight.usage bind energy.usage.* và core.device.*.\n"
            "5. RabbitMQ giao message cho consumer của insight. Consumer lỗi thì nack, RabbitMQ giao lại.\n"
            "6. Consumer tra message_id trong bảng inbox: đã có thì bỏ qua; chưa có thì cập nhật read model và ghi inbox cùng một transaction, rồi ack.\n"
            "7. Giao quá 3 lần vẫn lỗi: queue chuyển message sang dead-letter exchange wattprint.dlx.\n"
            "8. wattprint.dlx chép message vào insight.usage.dlq.\n"
            "9. Nhóm vận hành xem DLQ trên RabbitMQ UI, sửa lỗi, rồi chuyển message về insight.usage để chạy lại.", 18, "#1e1e1e")
    d.label("why", 0, 920,
            "Vì sao cần outbox: nếu lưu DB xong mà publish lỗi (hoặc publish xong mà transaction rollback), insight sẽ thiếu hoặc thừa dữ liệu.\n"
            "Vì sao cần inbox: RabbitMQ bảo đảm giao ít nhất một lần, nên cùng một message có thể đến hai lần; inbox làm consumer idempotent.\n"
            "Luồng insight → copilot (insight.alert.created → copilot.alerts → copilot.alerts.dlq) đi đúng các bước như trên.", 17, "#555555")
    d.legend(xs["idb"] + W + 60, 0, ["team", "db", "queue", "person"], ["sync", "async"], w=440)
    return d


# =====================================================================
# 03-06 Component (C4 level 3): one diagram per business service
# =====================================================================
CP, CBW, CBH, RG = 420, 340, 150, 110  # column pitch, box size, gap between rows


def component(title, sub, cname, ctech, above, rows, below, links, note=""):
    """above/below: [(col, id, kind, name, tech)] outside the boundary; rows: [[(col, id, name, tech, desc)]]
    links: [(src, dst, label, kind)]; empty label = internal call."""
    d = Diagram()
    d.title(0, -190, title, sub)
    cx = lambda c: 40 + c * CP
    for c, i, kind, name, tech in above:
        d.box(i, cx(c), 0, CBW, 110, kind, name, tech, name_fs=20)
    top = 110 + RG
    ncol = max(c for r in rows for c, *_ in r) + 1
    bh = 70 + len(rows) * (CBH + RG) - RG + 50
    d.boundary("b", 0, top, ncol * CP + 40, bh, f"{cname}  {ctech}", color="#1971c2", fs=20)
    for r, row in enumerate(rows):
        for c, i, name, tech, desc in row:
            d.box(i, cx(c), top + 70 + r * (CBH + RG), CBW, CBH, "comp", name, tech, desc, name_fs=20)
    by = top + bh + RG
    for c, i, kind, name, tech in below:
        d.box(i, cx(c), by, CBW, 110, kind, name, tech, name_fs=20)
    for src, dst, lbl, kind, *route in links:
        # route "under": go below the bottom row, so a long link does not cross the other labels
        pts = None
        if route == ["under"]:
            a, b = d.boxes[src], d.boxes[dst]
            ax, bx, uy = a["x"] + CBW / 2, b["x"] + CBW / 2, by + 150
            pts = [(ax, a["y"] + a["height"] + 6), (ax, uy), (bx, uy), (bx, by + 116)]
        d.arrow(f"l_{src}_{dst}", src, dst, lbl, kind, pts=pts, lbl_w=170)
    kinds = []
    for k in [a[2] for a in above + below] + ["comp"]:
        if k not in kinds:
            kinds.append(k)
    arrows = [k for k in ("sync", "async") if any(l[3] == k for l in links)]
    d.legend(ncol * CP + 100, top, kinds, arrows, w=420)
    d.label("note", 0, by + 210, "Mũi tên không ghi nhãn: gọi hàm trong cùng process. " + note, 17, "#495057")
    return d


def comp_core():
    return component(
        "[Component] core", "Phạm vi: bên trong container core. Nguồn sự thật: nhà, công tơ, thiết bị, số đo, hóa đơn.",
        "core", "[Container: Python, FastAPI, FastStream]",
        above=[(1, "gw", "offshelf", "API Gateway", "[Envoy]"), (3, "ins", "team", "insight", "[Container]")],
        rows=[
            [(0, "home_api", "Homes & devices API", "[FastAPI router]", "Nhà, mã mời, công tơ, thiết bị"),
             (1, "ingest_api", "Ingest API", "[FastAPI router]", "Nhận batch, kiểm API key thiết bị"),
             (2, "bill_api", "Billing API", "[FastAPI router]", "Hóa đơn, biểu giá 5 bậc")],
            [(0, "home_svc", "HomeService", "[Python]", "Mỗi tài khoản một nhà; mã mời dùng một lần"),
             (1, "ingest_svc", "IngestService", "[Python]", "Batch idempotent, liên tục; PENDING khi nilm lỗi"),
             (2, "bill_svc", "BillingService", "[Python]", "Tính tiền theo đúng phiên bản biểu giá"),
             (3, "retrier", "PendingRetrier", "[background task]", "Gửi lại batch PENDING, backoff 1-2-4 phút")],
            [(0, "repo", "Repositories", "[SQLAlchemy async]", "Bảng nghiệp vụ + outbox"),
             (1, "relay", "OutboxRelay", "[background task]", "Đọc outbox, publish có xác nhận"),
             (2, "nilm_cli", "NilmClient", "[httpx, tenacity, breaker]", "Timeout 3s, retry 2, circuit breaker")],
        ],
        below=[(0, "db", "db", "core_db", "[PostgreSQL + TimescaleDB]"), (1, "q", "queue", "insight.usage", "[Queue: RabbitMQ]"),
               (2, "nilm", "team", "nilm", "[Container]")],
        links=[("gw", "home_api", "REST", "sync"), ("gw", "ingest_api", "REST", "sync"), ("gw", "bill_api", "REST", "sync"),
               ("ins", "bill_api", "Lấy biểu giá [REST]", "sync"),
               ("home_api", "home_svc", "", "sync"), ("ingest_api", "ingest_svc", "", "sync"), ("bill_api", "bill_svc", "", "sync"),
               ("home_svc", "repo", "", "sync"), ("ingest_svc", "nilm_cli", "", "sync"), ("bill_svc", "repo", "", "sync"),
               ("retrier", "nilm_cli", "", "sync"),
               ("repo", "db", "SQL", "sync"), ("nilm_cli", "nilm", "POST /inferences [REST]", "sync"),
               ("relay", "db", "Đọc outbox [SQL]", "sync"), ("relay", "q", "energy.usage.updated [AMQP]", "async")],
        note="IngestService ghi số đo và outbox qua Repositories trong cùng một transaction.")


def comp_nilm():
    return component(
        "[Component] nilm", "Phạm vi: bên trong container nilm. Tách công suất tổng thành công suất từng thiết bị.",
        "nilm", "[Container: Python, FastAPI, PyTorch]",
        above=[(0, "gw", "offshelf", "API Gateway", "[Envoy, chỉ admin]"), (1, "core", "team", "core", "[Container]")],
        rows=[
            [(0, "admin_api", "Model admin API", "[FastAPI router]", "Đăng ký, kích hoạt phiên bản"),
             (1, "inf_api", "Inference API", "[FastAPI router]", "POST /inferences; giới hạn đồng thời (bulkhead)")],
            [(0, "registry", "ModelRegistry", "[Python]", "Phiên bản đang dùng, metadata"),
             (1, "engine", "InferenceEngine", "[PyTorch, NILMFormer]", "Công suất từng thiết bị + confidence"),
             (2, "calib", "Calibrator", "[Python]", "Hiệu chỉnh theo từng hộ")],
            [(0, "repo", "Repositories", "[SQLAlchemy async]", "Model, hiệu chỉnh, lần chạy"),
             (1, "loader", "ModelLoader", "[torch.load, cache]", "Nạp trọng số một lần, giữ trong RAM")],
        ],
        below=[(0, "db", "db", "nilm_db", "[PostgreSQL]"), (1, "vol", "db", "Kho model", "[Docker volume, chỉ đọc]")],
        links=[("gw", "admin_api", "REST", "sync"), ("core", "inf_api", "Yêu cầu suy luận [REST]", "sync"),
               ("admin_api", "registry", "", "sync"), ("inf_api", "engine", "", "sync"), ("engine", "calib", "", "sync"),
               ("registry", "repo", "", "sync"), ("engine", "loader", "", "sync"), ("calib", "repo", "", "sync"),
               ("repo", "db", "SQL", "sync"), ("loader", "vol", "Đọc file .pt", "sync")])


def comp_insight():
    return component(
        "[Component] insight", "Phạm vi: bên trong container insight. Read model tiêu thụ (CQRS) và các phân tích.",
        "insight", "[Container: Python, FastAPI, FastStream]",
        above=[(0, "gw", "offshelf", "API Gateway", "[Envoy]"), (1, "cop", "team", "copilot", "[Container]"),
               (3, "q_in", "queue", "insight.usage", "[Queue: RabbitMQ]")],
        rows=[
            [(0, "an_api", "Analytics API", "[FastAPI router]", "Tiêu thụ, dự báo, ngân sách, what-if, M&V"),
             (1, "q_api", "Safe query API", "[FastAPI router]", "POST /queries cho Text-to-SQL"),
             (3, "consumer", "Usage consumer", "[FastStream]", "Inbox: bỏ qua message_id đã xử lý")],
            [(0, "forecast", "Forecast & what-if", "[Python]", "Cần ≥ 7 ngày dữ liệu; M&V cần ≥ 14 ngày"),
             (1, "guard", "SQL guard", "[Python]", "Chỉ SELECT trên view cho phép, ép home_id, timeout 2s"),
             (2, "detect", "Detectors", "[Python]", "Bất thường, chạy ngầm, chạm bậc, vượt ngân sách"),
             (3, "rm", "ReadModel updater", "[Python]", "Tổng theo giờ từng thiết bị")],
            [(0, "repo", "Repositories", "[SQLAlchemy, TimescaleDB]", "Read model, alert, outbox"),
             (1, "core_cli", "CoreClient", "[httpx, tenacity]", "Biểu giá, danh sách thiết bị"),
             (2, "wx_cli", "WeatherClient", "[httpx]", "Nhiệt độ theo giờ"),
             (3, "relay", "OutboxRelay", "[background task]", "Publish alert")],
        ],
        below=[(0, "db", "db", "insight_db", "[PostgreSQL + TimescaleDB]"), (1, "core", "team", "core", "[Container]"),
               (2, "wx", "external", "Open-Meteo", "[External system]"), (3, "q_out", "queue", "copilot.alerts", "[Queue: RabbitMQ]")],
        links=[("gw", "an_api", "REST", "sync"), ("cop", "q_api", "Gọi tool [REST]", "sync"),
               ("q_in", "consumer", "Nhận [AMQP]", "async"),
               ("an_api", "forecast", "", "sync"), ("q_api", "guard", "", "sync"), ("consumer", "rm", "", "sync"),
               ("rm", "detect", "", "sync"),
               ("forecast", "repo", "", "sync"), ("forecast", "core_cli", "", "sync"), ("guard", "repo", "", "sync"),
               ("detect", "wx_cli", "", "sync"), ("detect", "relay", "", "sync"), ("rm", "repo", "", "sync"),
               ("repo", "db", "SQL", "sync"), ("core_cli", "core", "REST", "sync"), ("wx_cli", "wx", "HTTPS", "sync"),
               ("relay", "q_out", "insight.alert.created [AMQP]", "async")])


def comp_copilot():
    return component(
        "[Component] copilot", "Phạm vi: bên trong container copilot. Trợ lý hai chiều: hỏi đáp (pull) và gợi ý chủ động (push).",
        "copilot", "[Container: Python, FastAPI, FastStream]",
        above=[(1, "gw", "offshelf", "API Gateway", "[Envoy]"), (3, "q_in", "queue", "copilot.alerts", "[Queue: RabbitMQ]")],
        rows=[
            [(0, "chat_api", "Chat API", "[FastAPI router]", "Hội thoại, tin nhắn, phản hồi"),
             (1, "plan_api", "Plans API", "[FastAPI router]", "Kích hoạt kế hoạch tiết kiệm"),
             (3, "consumer", "Alert consumer", "[FastStream]", "Inbox chống trùng")],
            [(0, "guard", "Guardrail", "[Python, regex + NER]", "Ẩn PII, chặn prompt injection, kiểm gói Pro"),
             (1, "orch", "Orchestrator", "[LLM tool calling]", "Tools first: số liệu do tool tính"),
             (2, "saga", "Saga orchestrator", "[Python]", "PENDING, bù trừ ngược, reconciler"),
             (3, "rank", "Ranker", "[Python]", "Xếp hạng theo phản hồi, giờ yên tĩnh, chống trùng")],
            [(0, "verify", "Verifier", "[Python]", "Số khớp tool, đúng đơn vị, có trích dẫn"),
             (1, "llm_cli", "LLMClient", "[httpx, breaker]", "Timeout 20s, circuit breaker"),
             (2, "ins_cli", "InsightClient", "[httpx, tenacity, breaker]", "Truy vấn an toàn, dự báo, what-if"),
             (3, "notify", "Notifier", "[httpx]", "Expo Push, Telegram"),
             (4, "rag", "RAG retriever", "[pgvector]", "Tìm tri thức để trích dẫn")],
        ],
        below=[(0, "db", "db", "copilot_db", "[PostgreSQL + pgvector]"), (1, "llm", "external", "LLM provider", "[External system]"),
               (2, "ins", "team", "insight", "[Container]"), (3, "push", "external", "Expo Push, Telegram", "[External system]")],
        links=[("gw", "chat_api", "REST", "sync"), ("gw", "plan_api", "REST", "sync"), ("q_in", "consumer", "Nhận [AMQP]", "async"),
               ("chat_api", "guard", "", "sync"), ("guard", "orch", "", "sync"), ("plan_api", "saga", "", "sync"),
               ("consumer", "rank", "", "sync"),
               ("orch", "verify", "", "sync"), ("orch", "llm_cli", "", "sync"), ("orch", "ins_cli", "", "sync"),
               ("orch", "rag", "", "sync"), ("saga", "ins_cli", "", "sync"), ("rank", "ins_cli", "", "sync"),
               ("rank", "notify", "", "sync"),
               ("verify", "db", "Lưu tin nhắn, token [SQL]", "sync"), ("llm_cli", "llm", "Prompt đã ẩn PII [HTTPS]", "sync"),
               ("ins_cli", "ins", "REST", "sync"), ("notify", "push", "HTTPS", "sync"), ("rag", "db", "Tìm vector [SQL]", "sync", "under")])


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    diagrams = [("00-overview", overview), ("01-system-context", context), ("02-container", container),
                ("03-component-core", comp_core), ("04-component-nilm", comp_nilm),
                ("05-component-insight", comp_insight), ("06-component-copilot", comp_copilot)]
    if "--all" in sys.argv:  # deployment and dynamic views: kept for later, not part of the current deliverable
        diagrams += [("x1-deployment", deployment), ("x2-dynamic-ingest-nilm", ingest),
                     ("x3-dynamic-proactive-suggestion", proactive), ("x4-dynamic-copilot-qa", qa),
                     ("x5-dynamic-saving-plan-saga", saga), ("x6-dynamic-messaging-rabbitmq", messaging)]
    for name, fn in diagrams:
        random.seed(name)
        fn().dump(out / f"{name}.excalidraw")
        print("wrote", name)
