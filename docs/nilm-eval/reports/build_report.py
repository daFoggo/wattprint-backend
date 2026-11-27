# Sinh báo cáo thực nghiệm dạng DOCX rồi xuất PDF bằng LibreOffice.
# Chạy từ thư mục gốc: uv run --with python-docx==1.2.0 python reports/build_report.py
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/processed/REFIT/temporal_7aea0ef86866"
OUTPUT = ROOT / "reports/bao_cao_thuc_nghiem.docx"
sys.path.insert(0, str(ROOT))
from training.model.NILMFormer.NILMFormer import NILMFormer, NILMFormerConfig  # noqa: E402
from training.model.TwoStageNILMFormer.GRUDetector import GRUConfig  # noqa: E402
from training.model.TwoStageNILMFormer.NILMFormerRegressor import NILMFormerConfig as RegressorConfig  # noqa: E402
from training.train_twostage_nilmformer import STUDY_HOUSES, initialize_twostage_nilmformer  # noqa: E402

DEVICES = ["WashingMachine", "Dishwasher", "Kettle", "Microwave"]
DEVICE_VI = {"WashingMachine": "Máy giặt", "Dishwasher": "Máy rửa bát", "Kettle": "Ấm đun nước", "Microwave": "Lò vi sóng"}
# Ngưỡng mức tải theo điện tổng mỗi phút, chốt bằng số tròn trước khi có kết quả mô hình.
LOAD_BINS_W = [0, 300, 1000, 2500, np.inf]
LOAD_LABELS = ["< 300 W", "300–1.000 W", "1.000–2.500 W", "≥ 2.500 W"]

manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
seeds = json.loads((ROOT / "training/configs/seeds.json").read_text(encoding="utf-8"))
house_report = pd.read_csv(DATA_DIR / "house_report.csv", encoding="utf-8-sig")
device_report = pd.read_csv(DATA_DIR / "device_report.csv", encoding="utf-8-sig")
overlap_report = pd.read_csv(DATA_DIR / "overlap_report.csv", encoding="utf-8-sig")
config = manifest["config"]
assert config["targets"] == DEVICES, "Thứ tự thiết bị trong manifest khác thứ tự đã chốt."
assert set(STUDY_HOUSES) <= set(house_report["house"]), "Có hộ nghiên cứu không tồn tại trong dữ liệu tiền xử lý."

# Chỉ đọc điện tổng của phần test để báo số phút trong mỗi tầng tải; không dùng kết quả mô hình.
test_aggregate = pd.concat([pd.read_csv(DATA_DIR / f"test_house_{h:02d}.csv", usecols=["aggregate_w"]) for h in STUDY_HOUSES])["aggregate_w"]
load_minutes = pd.cut(test_aggregate, LOAD_BINS_W, right=False, labels=LOAD_LABELS).value_counts().reindex(LOAD_LABELS)
assert load_minutes.sum() == len(test_aggregate), "Có phút điện tổng nằm ngoài các tầng tải."
overlap_test = overlap_report[overlap_report["house"].isin(STUDY_HOUSES) & (overlap_report["split"] == "test")].groupby("active_target_devices")["minutes"].sum()
train_months = [(pd.Timestamp(s["train_end_exclusive"]) - pd.Timestamp(s["start"])).days / 30.44 for h, s in manifest["time_splits"].items() if int(h) in STUDY_HOUSES]

n_params = lambda model: sum(p.numel() for p in model.parameters())  # noqa: E731
nilmformer = NILMFormer(NILMFormerConfig(c_out=len(DEVICES)))
twostage = initialize_twostage_nilmformer(GRUConfig(c_out=len(DEVICES)), RegressorConfig(c_out=len(DEVICES)), 0)
param_rows = [
    ["NILMFormer", n_params(nilmformer)],
    ["TwoStageNILMFormer", n_params(twostage)],
    ["  – bộ phát hiện GRU", n_params(twostage.Detector)],
    ["  – bộ hồi quy NILMFormer", n_params(twostage.Regressor)],
]

doc = Document()
for section in doc.sections:
    section.top_margin, section.bottom_margin = Cm(2), Cm(2)
    section.left_margin, section.right_margin = Cm(3), Cm(2)
for name in ["Normal", "Title", "Heading 1", "Heading 2", "Caption"]:
    style = doc.styles[name]
    style.font.name = "Times New Roman"
    style.font.color.rgb = RGBColor(0, 0, 0)
    rfonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    # Heading của template mặc định trỏ tới font theme (Calibri); bỏ thuộc tính theme để Times New Roman có hiệu lực.
    for attr in ["asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"]:
        rfonts.attrib.pop(qn(f"w:{attr}"), None)
    rfonts.set(qn("w:eastAsia"), "Times New Roman")
doc.styles["Normal"].font.size = Pt(13)
doc.styles["Title"].font.size = Pt(22)
doc.styles["Heading 1"].font.size = Pt(16)
doc.styles["Heading 2"].font.size = Pt(14)
doc.styles["Caption"].font.size = Pt(11)
doc.styles["Normal"].paragraph_format.space_after = Pt(6)
doc.styles["Normal"].paragraph_format.line_spacing = 1.2
table_counter = 0


def paragraph(text, style=None):
    p = doc.add_paragraph(style=style)
    # Đoạn văn đánh dấu **...** để in đậm một số cụm từ khóa.
    for i, part in enumerate(text.split("**")):
        p.add_run(part).bold = i % 2 == 1
    if style is None:
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    return p


def bullets(items):
    for item in items:
        paragraph(item, "List Bullet")


def table(caption, header, rows, widths=None):
    global table_counter
    table_counter += 1
    cap = doc.add_paragraph(f"Bảng {table_counter}. {caption}", style="Caption")
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=len(header), style="Table Grid")
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, text in zip(t.rows[0].cells, header):
        cell.text = ""
        cell.paragraphs[0].add_run(str(text)).bold = True
    for row in rows:
        for cell, text in zip(t.add_row().cells, row):
            cell.text = str(text)
    if widths:
        t.autofit = False
        for column, width in zip(t.columns, widths):
            column.width = Cm(width)
    # Lặp hàng tiêu đề khi bảng sang trang mới.
    t.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    for r, row in enumerate(t.rows):
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for i, cell in enumerate(row.cells):
            if widths:
                cell.width = Cm(widths[i])
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                # Giữ các hàng dính nhau để bảng ngắn không bị tách qua hai trang.
                p.paragraph_format.keep_with_next = r < len(t.rows) - 1
                for run in p.runs:
                    run.font.size = Pt(11)
    doc.add_paragraph()


def fmt(value, digits=0):
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(part, whole):
    return fmt(100 * part / whole, 2) + "%"


# Trang tiêu đề.
title = doc.add_paragraph("BÁO CÁO THỰC NGHIỆM", style="Title")
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Phân rã phụ tải không xâm nhập (NILM) trên bộ dữ liệu REFIT: NILMFormer và TwoStageNILMFormer")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph(f"Ngày lập: {date.today():%d/%m/%Y}").alignment = WD_ALIGN_PARAGRAPH.CENTER

# ---------------------------------------------------------------- Phần 1
doc.add_heading("1. Thiết kế thực nghiệm", level=1)
n_houses = len(STUDY_HOUSES)

doc.add_heading("1.1. Mục tiêu đánh giá", level=2)
paragraph("Thực nghiệm phục vụ hai mục tiêu. Bảng 1 nêu vấn đề, yêu cầu, cách thiết kế đáp ứng và minh chứng tương ứng với từng mục tiêu.")
table(
    "Mục tiêu đánh giá và cách thiết kế đáp ứng",
    ["Mục tiêu", "Vấn đề và yêu cầu", "Cách đáp ứng trong thiết kế", "Minh chứng"],
    [
        [
            "1. Đánh giá NILM ở hộ/thiết bị mới",
            "Hiệu năng có thể giảm khi nhiều thiết bị chạy đồng thời hoặc gặp thiết bị chưa thấy. Đo sai số điện năng và F1 theo thiết bị, hộ mới, mức tải; "
            "tách tập kiểm tra theo hộ; báo trường hợp bật đồng thời.",
            f"Tập kiểm tra tách riêng từng hộ; ma trận chuyển giao {n_houses} × {n_houses} của phép đánh giá chéo hộ (mục 1.5); phân tầng theo thiết bị, "
            "hộ đã thấy/chưa thấy, mức tải và số thiết bị bật đồng thời (mục 1.9).",
            "Bảng theo thiết bị và hộ; đồ thị điện tổng và điện từng thiết bị; phân tích lỗi (mục 1.11).",
        ],
        [
            "2. Kiểm chứng lợi ích và chi phí triển khai",
            "Chưa rõ đóng góp của cá nhân hóa so với NILM cơ sở và chi phí tính toán cho mỗi hộ. So baseline NILM và bản không cá nhân hóa trên cùng đầu vào; "
            "báo thời gian, thiết bị cảm biến và chi phí ước tính.",
            "Thiết kế giai thừa 2 × 3: kiến trúc (NILMFormer, TwoStageNILMFormer) × chiến lược huấn luyện (gộp, riêng từng hộ, gộp rồi fine-tune theo hộ) (mục 1.5); "
            "đo thời gian huấn luyện, độ trễ suy luận và tài nguyên (mục 1.10).",
            "Bảng đối chứng độ chính xác – độ trễ – chi phí; cấu hình triển khai gọn (mục 1.10, 1.11).",
        ],
    ],
    [3.0, 4.6, 4.6, 3.3],
)
paragraph(
    "**Phạm vi.** Báo cáo này chỉ đánh giá tầng mô hình NILM. Thành phần trợ lý (copilot) thuộc hệ thống Wattprint được đánh giá riêng, "
    "nên phép so sánh phiên bản không có trợ lý không nằm trong báo cáo."
)
paragraph(
    "**Về thiết bị chưa thấy.** Các mô hình có đúng bốn đầu ra cố định, nên không thể dự đoán một loại thiết bị chưa từng được học. "
    "Khía cạnh này được đo theo hai cách: (i) ở hộ chưa thấy, máy giặt, máy rửa bát, ấm và lò vi sóng là các thiết bị cụ thể khác "
    "(hãng, model, chế độ vận hành) so với hộ huấn luyện; (ii) phân tích ảnh hưởng của phần điện tổng không thuộc bốn thiết bị đích, "
    "tức các thiết bị mà mô hình không được giám sát."
)

doc.add_heading("1.2. Dữ liệu, cảm biến và phạm vi", level=2)
paragraph(
    "Nhóm nghiên cứu sử dụng bản đã làm sạch (cleaned) của bộ dữ liệu **REFIT** [1], gồm 20 hộ gia đình tại Vương quốc Anh trong giai đoạn 2013–2015. "
    "Mỗi hộ được lắp một kẹp dòng đo điện tổng và 9 ổ cắm đo từng thiết bị (Individual Appliance Monitor, IAM); dữ liệu chỉ gồm công suất tác dụng (W) "
    "với chu kỳ lấy mẫu khoảng 8 giây. Bốn thiết bị đích được cố định theo thứ tự: " + ", ".join(f"{DEVICE_VI[d]} ({d})" for d in DEVICES) + ". Các mô hình đều có 4 kênh đầu ra theo đúng thứ tự này."
)
paragraph(
    f"Dữ liệu được tiền xử lý cho cả 20 hộ, nhưng thực nghiệm chỉ sử dụng **{n_houses} hộ nghiên cứu: {', '.join(map(str, STUDY_HOUSES))}**, "
    "là các hộ có nhãn hợp lệ cho đủ bốn thiết bị đích. Hộ 15 cũng có đủ bốn kênh nhưng bị loại vì theo mô tả của bộ dữ liệu, kênh được ánh xạ thành ấm đun nước "
    "có thể là thiết bị Hi-Fi. Việc dùng chung một tập hộ đủ nhãn giúp ma trận chuyển giao giữa các hộ không bị khuyết ô theo thiết bị."
)
rows = []
for house in STUDY_HOUSES:
    sub = device_report[(device_report["house"] == house) & (device_report["split"] == "train")].set_index("device")
    rows.append([house] + [sub.loc[d, "source_channel"] for d in DEVICES])
table("Kênh đo của REFIT được ánh xạ cho bốn thiết bị đích ở các hộ nghiên cứu", ["Hộ"] + [DEVICE_VI[d] for d in DEVICES], rows, [1.5, 3.4, 3.4, 3.4, 3.4])

doc.add_heading("1.3. Tiền xử lý dữ liệu", level=2)
paragraph(
    "Quy trình tiền xử lý tín hiệu tuân theo cài đặt công bố của NILMFormer [2] để kết quả có thể đối chiếu với nghiên cứu gốc. "
    "Để tránh **rò rỉ dữ liệu (data leakage)**, chuỗi của mỗi hộ được chia train/test theo thời gian **trước** mọi bước tái lấy mẫu, nội suy và phân đoạn; "
    "hai phần được xử lý độc lập, không nội suy qua ranh giới và không có cửa sổ nằm vắt qua hai tập. Bảng 3 liệt kê các bước theo đúng thứ tự thực hiện."
)
thresholds = manifest["thresholds_w"]
table(
    "Các bước tiền xử lý dữ liệu",
    ["Bước", "Thiết lập"],
    [
        [
            "1. Data cleaning",
            "Loại các thời điểm có tổng công suất các thiết bị đo riêng lớn hơn điện tổng (bản ghi bất thường được REFIT gắn cờ); giá trị vô hạn được coi là khuyết",
        ],
        ["2. Resampling", "Lấy trung bình về lưới thời gian đều 10 giây"],
        [
            "3. Imputation",
            f"Nội suy giữ giá trị trước (forward-fill) tối đa {config['ffill_10s_steps']} bước, tức 90 giây; khoảng khuyết dài hơn được giữ nguyên là khuyết",
        ],
        ["4. Noise floor removal", f"Công suất dưới {fmt(config['small_power_w'])} W được đặt về 0"],
        ["5. Clipping", f"Giới hạn công suất trong đoạn [0; {fmt(config['clip_w'])}] W"],
        [
            "6. State labeling",
            "Ngưỡng hóa theo dải công suất của từng thiết bị tại lưới 10 giây: " + "; ".join(f"{DEVICE_VI[d]} {fmt(thresholds[d][0])}–{fmt(thresholds[d][1])} W" for d in DEVICES),
        ],
        ["7. Downsampling", "Lấy trung bình về chu kỳ 1 phút; một phút được gán nhãn bật nếu có ít nhất một mẫu 10 giây ở trạng thái bật"],
        [
            "8. Windowing",
            f"Cửa sổ dài {config['window_size']} phút, không chồng lấn; loại cửa sổ còn giá trị khuyết ở điện tổng hoặc ở kênh thiết bị có nhãn",
        ],
        [
            "9. Scaling",
            f"Chia công suất cho hệ số cố định {fmt(config['power_scale_w'])}; không ước lượng thống kê từ dữ liệu nên không rò rỉ thông tin từ tập kiểm tra",
        ],
        ["10. Temporal encoding", "8 đặc trưng sin/cos tuần hoàn của phút, giờ, ngày trong tuần và tháng (TimeRPE [2]); đầu vào mô hình có 9 kênh"],
        [
            "11. Label masking",
            "Kênh thiết bị không có cảm biến ở một hộ được đánh dấu bằng mặt nạ; các vị trí bị che không tham gia hàm mất mát và chỉ số đánh giá, thay vì bị coi là trạng thái tắt",
        ],
    ],
    [4.2, 11.0],
)

doc.add_heading("1.4. Chia dữ liệu theo thời gian và theo hộ", level=2)
paragraph(
    f"Mỗi hộ được xét độc lập theo thứ tự thời gian: **{int(config['train_time_fraction'] * 100)}% thời gian đầu dùng để huấn luyện, "
    f"{100 - int(config['train_time_fraction'] * 100)}% cuối dùng để kiểm tra**. Mốc chia tính trên khoảng thời gian lịch và làm tròn lên phút, "
    "nên số cửa sổ còn lại sau bước phân đoạn không nhất thiết đúng tỷ lệ 80/20. Trong phần huấn luyện, 20% thời gian cuối được tách làm **tập kiểm định (validation)** "
    "phục vụ dừng sớm; tỷ lệ xấp xỉ trên toàn kỳ là 64/16/20. Cửa sổ nằm vắt qua mốc huấn luyện/kiểm định bị loại. "
    "Tập kiểm tra luôn được **tách và báo cáo riêng theo từng hộ**; mọi mô hình dùng cùng 20% cuối của mỗi hộ để kết quả so sánh được với nhau."
)
rows = []
for house in STUDY_HOUSES:
    h = house_report[house_report["house"] == house].set_index("split")
    split = manifest["time_splits"][str(house)]
    rows.append([house, split["start"][:10], split["test_start"][:10], split["end_exclusive"][:10], fmt(h.loc["train", "kept_windows"]), fmt(h.loc["test", "kept_windows"])])
total = house_report[house_report["house"].isin(STUDY_HOUSES)].groupby("split")["kept_windows"].sum()
rows.append(["Tổng", "", "", "", fmt(total["train"]), fmt(total["test"])])
table(
    "Mốc chia thời gian và số cửa sổ 128 phút ở các hộ nghiên cứu",
    ["Hộ", "Bắt đầu", "Bắt đầu kiểm tra", "Kết thúc", "Cửa sổ huấn luyện*", "Cửa sổ kiểm tra"],
    rows,
    [1.3, 2.5, 2.9, 2.5, 3.1, 2.6],
)
paragraph("* Số cửa sổ huấn luyện trước khi tách tập kiểm định.", style=None).runs[0].italic = True

doc.add_heading("1.5. Chiến lược huấn luyện và các biến thể so sánh", level=2)
table(
    "Ba chiến lược huấn luyện",
    ["Chiến lược", "Dữ liệu huấn luyện và kiểm định", "Dữ liệu kiểm tra"],
    [
        ["Huấn luyện gộp (pooled training) – không cá nhân hóa", f"Phần huấn luyện của cả {n_houses} hộ", "20% cuối của từng hộ, báo cáo riêng theo hộ"],
        [
            "Huấn luyện riêng từng hộ, đánh giá chéo hộ (cross-house evaluation)",
            "Khởi tạo ngẫu nhiên, chỉ học phần huấn luyện của hộ h; tập kiểm định cũng lấy từ hộ h",
            f"20% cuối của cả {n_houses} hộ: hộ h là hộ đã thấy, các hộ còn lại là hộ chưa thấy",
        ],
        [
            "Gộp rồi fine-tune theo hộ (fine-tuning)",
            "Khởi tạo từ mô hình gộp cùng seed, tiếp tục học trên phần huấn luyện của hộ h; tập kiểm định lấy từ hộ h",
            f"20% cuối của cả {n_houses} hộ: hộ h đo hiệu quả cá nhân hóa, các hộ còn lại đo mức suy giảm trên hộ khác sau fine-tune",
        ],
    ],
    [4.5, 5.0, 5.5],
)
paragraph(
    f"Đánh giá chéo hộ tạo **ma trận chuyển giao {n_houses} × {n_houses}** (hộ huấn luyện × hộ kiểm tra) cho mỗi thiết bị và mỗi seed. "
    "Đường chéo đo khả năng dự đoán giai đoạn tương lai của chính hộ đã học; các ô ngoài đường chéo là **phép đo trên hộ mới** của mục tiêu 1. "
    "Mô hình riêng từng hộ luôn được khởi tạo ngẫu nhiên, không kế thừa trọng số của mô hình gộp; kế thừa trọng số là chiến lược fine-tune và được tách riêng."
)
paragraph(
    "**Fine-tune** cập nhật toàn bộ tham số của mô hình gộp với tốc độ học nhỏ hơn 10 lần (1e-5), tối đa 50 epoch và dừng sớm sau 10 epoch không cải thiện "
    "trên tập kiểm định của hộ h; trọng số lớp dương được tính lại từ nhãn huấn luyện của hộ h. Vì mô hình gộp đã thấy phần huấn luyện của hộ h, "
    "fine-tune ở đây đo lợi ích của việc **chuyên biệt hóa** cho hộ, không phải thích nghi với hộ chưa từng thấy."
)
paragraph("Để trả lời mục tiêu 2, ba chiến lược được áp dụng cho cả hai kiến trúc, tạo sáu biến thể trên cùng đầu vào:")
table(
    "Các biến thể so sánh cho mục tiêu 2",
    ["Biến thể", "Kiến trúc", "Chiến lược huấn luyện", "Vai trò"],
    [
        ["A", "NILMFormer", "Gộp", "Baseline NILM"],
        ["B", "NILMFormer", "Riêng từng hộ", "Baseline, cá nhân hóa bằng huấn luyện riêng"],
        ["C", "NILMFormer", "Gộp rồi fine-tune", "Baseline, cá nhân hóa bằng fine-tune"],
        ["D", "TwoStageNILMFormer", "Gộp", "Không cá nhân hóa"],
        ["E", "TwoStageNILMFormer", "Riêng từng hộ", "Cá nhân hóa bằng huấn luyện riêng"],
        ["F", "TwoStageNILMFormer", "Gộp rồi fine-tune", "Cá nhân hóa bằng fine-tune"],
    ],
    [1.8, 4.7, 3.7, 4.8],
)
bullets(
    [
        "**Cùng đầu vào:** mọi biến thể nhận điện tổng (1 kênh) và 8 kênh mã hóa thời gian, cùng tập cửa sổ, cùng mặt nạ nhãn và cùng tập kiểm tra.",
        "**Lợi ích của cá nhân hóa** so với không cá nhân hóa: E − D và F − D (tương ứng B − A và C − A trên kiến trúc cơ sở), "
        "so sánh ghép cặp theo hộ kiểm tra và seed trên chính hộ được cá nhân hóa.",
        "**So sánh hai cách cá nhân hóa:** F − E và C − B, cho biết kế thừa tri thức từ nhiều hộ có tốt hơn học từ đầu trên một hộ hay không.",
        "**Lợi ích của kiến trúc hai giai đoạn:** D − A, E − B và F − C, ở cùng chiến lược huấn luyện.",
        "**Cái giá của cá nhân hóa** là dữ liệu đo từng thiết bị tại chính hộ đó, số mô hình phải lưu trữ và thời gian huấn luyện thêm, được định lượng ở mục 1.10.",
    ]
)

doc.add_heading("1.6. Mô hình", level=2)
bullets(
    [
        "**NILMFormer** [2] (mô hình cơ sở): khối tích chập giãn nở (dilation 1, 2, 4, 8) tạo embedding, 3 lớp encoder Transformer (d_model = 96, 8 head, dropout 0,2) "
        "và token thống kê của chuỗi đầu vào; đầu ra trực tiếp là công suất của 4 thiết bị.",
        "**TwoStageNILMFormer**: bộ phát hiện GRU (tích chập 64 kênh, kernel 5, GRU 2 lớp 64 đơn vị) dự đoán xác suất bật của từng thiết bị; "
        "bộ hồi quy NILMFormer cùng cấu hình như trên, qua hàm softplus để công suất không âm. Công suất cuối = công suất hồi quy × mặt nạ bật/tắt "
        "(ngưỡng xác suất 0,5). Khi huấn luyện, mặt nạ dùng bộ ước lượng straight-through để gradient từ hàm mất mát công suất truyền được về bộ phát hiện.",
    ]
)
paragraph(
    "Hàm mất mát của TwoStageNILMFormer gồm ba thành phần trên các điểm có nhãn hợp lệ: MSE của công suất sau mặt nạ, BCE có trọng số lớp dương cho bộ phát hiện, "
    "và MSE phụ (trọng số 0,1) của công suất trước mặt nạ tại các điểm thực sự bật, giúp bộ hồi quy vẫn học được khi mặt nạ tắt nhầm."
)

doc.add_heading("1.7. Huấn luyện và lựa chọn mô hình", level=2)
table(
    "Thiết lập huấn luyện",
    ["Tham số", "Giá trị"],
    [
        ["Bộ tối ưu", "AdamW, tốc độ học 1e-4, weight decay 0, gradient clipping theo chuẩn 1,0"],
        ["Kích thước batch", "64 cửa sổ"],
        ["Số epoch", "Tối đa 50; dừng sớm (early stopping) khi hàm mất mát trên tập kiểm định không cải thiện sau 10 epoch"],
        ["Lựa chọn mô hình", "Trọng số có hàm mất mát kiểm định thấp nhất được dùng để đánh giá trên tập kiểm tra"],
        ["Trọng số lớp dương (BCE)", "(số mẫu tắt + 1) / (số mẫu bật + 1), tính riêng từng thiết bị chỉ trên tập huấn luyện, giới hạn trong [0,01; 100]"],
        ["Phần cứng", "GPU NVIDIA L40S"],
    ],
    [4.5, 10.5],
)
paragraph(
    "Tập kiểm tra không tham gia vào việc chọn epoch, chọn siêu tham số hay tính trọng số lớp. Mô hình gộp thấy nhiều mẫu hơn mỗi mô hình riêng, "
    "nên cùng số epoch không đồng nghĩa cùng chi phí; báo cáo kèm số mẫu, số bước cập nhật và thời gian huấn luyện của từng biến thể."
)

doc.add_heading("1.8. Seed và khả năng tái lập", level=2)
n_seeds = len(seeds["model_seeds"])
n_runs = (1 + 2 * n_houses) * n_seeds
paragraph(
    f"Seed gốc **{seeds['base_seed']}** cố định việc chia dữ liệu, thứ tự batch và các yếu tố ngẫu nhiên trong huấn luyện. "
    f"**{n_seeds} seed khởi tạo** ({', '.join(map(str, seeds['model_seeds']))}) chỉ dùng để tạo các bộ trọng số ban đầu khác nhau; "
    "mô hình fine-tune kế thừa trọng số của mô hình gộp cùng seed. "
    f"Mỗi kiến trúc có (1 mô hình gộp + {n_houses} mô hình riêng + {n_houses} mô hình fine-tune) × {n_seeds} seed = **{n_runs} lượt huấn luyện**, "
    f"hai kiến trúc tổng cộng {2 * n_runs} lượt. "
    "Các phép tính được đặt ở chế độ tất định (deterministic); tính tái lập chỉ được bảo đảm trong cùng môi trường thư viện và phần cứng."
)

doc.add_heading("1.9. Chỉ số đánh giá và phân tầng", level=2)
table(
    "Các nhóm chỉ số",
    ["Nhóm", "Chỉ số", "Ghi chú"],
    [
        ["Điện năng", "Sai số điện năng tuyệt đối (kWh) và tương đối", "Chỉ số chính của mục tiêu 1; chỉ tính trên các phút có nhãn hợp lệ"],
        ["Bật/tắt", "F1, precision, recall, tỷ lệ âm tính giả", "Chỉ số chính của mục tiêu 1; trạng thái suy ra từ công suất cuối theo ngưỡng thiết bị, tính theo từng phút"],
        ["Công suất", "MAE, RMSE (W); NDE, SAE, MR", "Tính trên công suất đã hoàn nguyên về W"],
        ["Bộ phát hiện", "F1 của bộ phát hiện", "Đánh giá riêng mặt nạ của TwoStageNILMFormer, là phân tích bổ sung"],
    ],
    [3.0, 5.5, 6.5],
)
paragraph("Mỗi chỉ số được báo cáo theo các tầng sau. Tầng được xác định từ nhãn thực tế và điện tổng, không phụ thuộc vào dự đoán của mô hình:")
bullets(
    [
        "**Thiết bị** (4 loại) và **hộ kiểm tra** (7 hộ), tách hộ đã thấy và hộ chưa thấy.",
        "**Mức tải**: điện tổng mỗi phút chia thành bốn khoảng " + ", ".join(LOAD_LABELS) + f" (Bảng {table_counter + 2}).",
        f"**Số thiết bị đích bật đồng thời** (Bảng {table_counter + 1}): 0, 1 và từ 2 trở lên. Tầng 0 không có mẫu bật nên F1 không xác định; ở tầng này báo tỷ lệ bật nhầm và điện năng dự đoán thừa.",
        "**Tỷ trọng tải ngoài thiết bị đích**: (điện tổng − tổng bốn thiết bị đích) / điện tổng, để đo ảnh hưởng của các thiết bị mà mô hình không được giám sát.",
    ]
)
total_test = overlap_test.sum()
table(
    f"Số phút kiểm tra theo số thiết bị đích bật đồng thời ({n_houses} hộ nghiên cứu)",
    ["Số thiết bị bật", "Số phút", "Tỷ lệ"],
    [[k, fmt(v), pct(v, total_test)] for k, v in overlap_test.items()],
    [4.0, 4.0, 4.0],
)
table(
    f"Số phút kiểm tra theo mức tải điện tổng ({n_houses} hộ nghiên cứu)",
    ["Mức tải", "Số phút", "Tỷ lệ"],
    [[k, fmt(v), pct(v, load_minutes.sum())] for k, v in load_minutes.items()],
    [4.0, 4.0, 4.0],
)
paragraph(
    f"Trường hợp bật đồng thời rất hiếm: chỉ {pct(overlap_test[overlap_test.index >= 2].sum(), total_test)} số phút kiểm tra có từ hai thiết bị đích trở lên "
    f"và {fmt(overlap_test[overlap_test.index >= 3].sum())} phút có ba thiết bị. Vì vậy các tầng từ 2 trở lên được gộp, luôn báo kèm số phút, và kết quả ở tầng này "
    "được xem là định tính; khoảng tin cậy được ước lượng bằng bootstrap theo cửa sổ."
)
bullets(
    [
        "Chỉ số được tính một lần trên toàn bộ dự đoán của một tầng (cộng dồn sai số và TP/FP/FN/TN), không lấy trung bình theo batch.",
        "Kết quả theo seed được tổng hợp bằng trung bình và độ lệch chuẩn. Trung bình giữa các hộ là **trung bình macro theo hộ** trong từng seed, để hộ có nhiều dữ liệu không chi phối kết quả.",
        "So sánh giữa các biến thể được ghép cặp theo hộ kiểm tra và seed, vì độ phân tán giữa các hộ thường lớn hơn giữa các seed.",
        "Kênh không có nhãn được ghi nhận là không xác định, không quy về 0.",
    ]
)

doc.add_heading("1.10. Đo chi phí triển khai", level=2)
paragraph(
    "**Cảm biến.** Khi suy luận, cả sáu biến thể chỉ cần **một cảm biến điện tổng** (kẹp dòng) với tần suất tối thiểu một mẫu mỗi phút. "
    "Khác biệt nằm ở giai đoạn huấn luyện: cả hai cách cá nhân hóa (huấn luyện riêng và fine-tune) đều cần ổ cắm đo từng thiết bị (IAM) lắp tại **chính hộ đó** "
    f"trong giai đoạn thu nhãn (trong dữ liệu này, phần huấn luyện của mỗi hộ dài {fmt(min(train_months), 1)}–{fmt(max(train_months), 1)} tháng). "
    "Nếu fine-tune đạt độ chính xác tương đương với ít dữ liệu của hộ hơn, thời gian lắp IAM có thể rút ngắn; đây là phân tích mở rộng sau khi có kết quả chính. "
    "Một mô hình đã huấn luyện ở hộ khác dùng được cho hộ mới mà không cần IAM tại hộ đó; "
    "các ô hộ chưa thấy của ma trận chuyển giao đo cái giá về độ chính xác của trường hợp này."
)
table(
    "Số tham số của các mô hình với 4 thiết bị đầu ra",
    ["Mô hình", "Số tham số", "Kích thước trọng số FP32"],
    [[name, fmt(n), f"{fmt(n * 4 / 1e6, 2)} MB"] for name, n in param_rows],
    [6.0, 4.0, 5.0],
)
paragraph("Các đại lượng chi phí được đo cho từng biến thể A–F:")
bullets(
    [
        "**Huấn luyện:** thời gian GPU (giờ) đến khi dừng sớm, số epoch, số bước cập nhật và bộ nhớ GPU đỉnh; với biến thể cá nhân hóa báo cả thời gian mỗi hộ và tổng. "
        "Chi phí của biến thể fine-tune gồm cả chi phí huấn luyện mô hình gộp ban đầu, vốn được dùng chung cho mọi hộ.",
        "**Suy luận:** độ trễ xử lý một cửa sổ 128 phút với batch 1 và batch 64, trên GPU (NVIDIA L40S) và CPU; bỏ các lần chạy khởi động (warm-up), báo trung vị và phân vị 95 qua nhiều lần lặp.",
        "**Chi phí ước tính:** chi phí huấn luyện = số giờ GPU × đơn giá thuê GPU; chi phí suy luận mỗi hộ mỗi ngày dựa trên "
        f"{fmt(24 * 60 / config['window_size'], 2)} cửa sổ/ngày. Với tải suy luận nhỏ như vậy, giả thuyết cần kiểm chứng là CPU đủ đáp ứng và không cần GPU khi triển khai.",
        "**Cấu hình triển khai gọn:** container Docker chỉ dùng CPU, chứa trọng số mô hình và chương trình suy luận nhận chuỗi điện tổng, trả về công suất bốn thiết bị; "
        "báo kích thước image, RAM đỉnh và độ trễ.",
    ]
)

doc.add_heading("1.11. Minh chứng dự kiến", level=2)
bullets(
    [
        "**Bảng theo thiết bị × hộ kiểm tra**: sai số điện năng, F1 và MAE (trung bình ± độ lệch chuẩn qua 5 seed) cho sáu biến thể, tách hộ đã thấy và hộ chưa thấy.",
        f"**Heatmap ma trận chuyển giao {n_houses} × {n_houses}** cho từng thiết bị (F1 và sai số điện năng tương đối).",
        "**Bảng theo mức tải và theo số thiết bị bật đồng thời**, kèm số phút của mỗi tầng.",
        "**Đồ thị chuỗi thời gian**: điện tổng cùng công suất thực tế và dự đoán của bốn thiết bị trên các cửa sổ đại diện. Cửa sổ được chọn theo quy tắc cố định "
        "(lỗi điện năng ở trung vị, lỗi lớn nhất, có thiết bị bật đồng thời) để tránh chọn lọc chủ quan.",
        "**Phân tích lỗi**: tỷ lệ bỏ sót và bật nhầm theo thiết bị; nhầm lẫn giữa các thiết bị cùng dải công suất (ấm và lò vi sóng); quan hệ giữa lỗi và tỷ trọng tải ngoài thiết bị đích.",
        "**Bảng đối chứng độ chính xác – độ trễ – chi phí** cho sáu biến thể A–F và bản demo cấu hình triển khai gọn.",
    ]
)

doc.add_heading("1.12. Giới hạn của thiết kế", level=2)
bullets(
    [
        "Mỗi mô hình trong đánh giá chéo hộ chỉ học từ một hộ, nên kết quả trên hộ chưa thấy là ước lượng bi quan so với mô hình học từ nhiều hộ.",
        "Mô hình gộp đã thấy phần huấn luyện của mọi hộ nghiên cứu, nên fine-tune chỉ đo lợi ích chuyên biệt hóa; "
        "tình huống cá nhân hóa cho một hộ hoàn toàn mới (mô hình gộp chưa từng thấy hộ đó) không được đo trong thiết kế này.",
        "Trường hợp từ hai thiết bị đích bật đồng thời rất ít, nên kết luận ở tầng này chỉ mang tính định tính.",
        "Phép chia theo thời gian trong từng hộ khác với phép chia theo hộ trong bài báo NILMFormer [2]; kết quả không phải là tái lập nguyên bản nghiên cứu gốc.",
        "Giới hạn nội suy 90 giây theo cài đặt công bố của tác giả, trong khi bài báo [2] ghi 3 phút.",
        "Mốc thời gian lấy theo trường Time của bản cleaned, không quy đổi múi giờ.",
        "Ánh xạ kênh thiết bị dựa trên bảng của tác giả NILMFormer và có chênh lệch với mô tả của REFIT ở một số hộ; nhãn chưa được xác minh độc lập.",
        "Giảm mẫu về 1 phút làm mất thông tin các sự kiện ngắn của ấm đun nước và lò vi sóng.",
        "Thành phần trợ lý (copilot) của hệ thống Wattprint nằm ngoài phạm vi báo cáo này.",
    ]
)

doc.add_heading("Tài liệu tham khảo", level=1)
for ref in [
    "[1] D. Murray, L. Stankovic, V. Stankovic, “An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study,” Scientific Data, vol. 4, 160122, 2017.",
    "[2] A. Petralia, P. Charpentier, Y. Kadhi, T. Palpanas, “NILMFormer: Non-Intrusive Load Monitoring that Accounts for Non-Stationarity,” arXiv:2506.05880, 2025.",
]:
    paragraph(ref)

doc.save(OUTPUT)
subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(OUTPUT.parent), str(OUTPUT)], check=True, capture_output=True)
print(f"Đã ghi {OUTPUT} và {OUTPUT.with_suffix('.pdf')}")
