"""
生成 3 种不同格式的运单 PDF + 标注数据，用于跑测评演示
全部使用英文/ASCII，无需中文字体
"""
import json
from pathlib import Path
from fpdf import FPDF


TEST_PDFS_DIR = Path(__file__).parent.parent / "sample_pdfs"
LABELS_PATH = Path(__file__).parent.parent / "data" / "labels.json"


class WaybillPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_page()
        self.set_auto_page_break(auto=True, margin=15)

    def add_t(self, text, size=16):
        self.set_font("Helvetica", "B", size)
        self.cell(0, 10, text, new_x="LMARGIN", new_y="NEXT", align="C")
        self.ln(5)

    def section(self, title):
        self.set_font("Helvetica", "B", 12)
        self.set_fill_color(230, 230, 230)
        self.cell(0, 8, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
        self.ln(2)

    def field(self, label, value, w1=50, w2=140):
        self.set_font("Helvetica", "B", 10)
        self.cell(w1, 7, f"{label}:", border=0)
        self.set_font("Helvetica", "", 10)
        self.cell(w2, 7, value, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def h_line(self):
        self.set_draw_color(180, 180, 180)
        FPDF.line(self, 10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def rect_box(self, items, y_start=None):
        """画表格框并填充字段"""
        if y_start:
            self.set_y(y_start)
        y0 = self.get_y()
        row_h = 9
        n = len(items)
        self.set_draw_color(0, 0, 0)
        self.rect(10, y0, 190, n * row_h + 4)
        for i, (label, value) in enumerate(items):
            self.set_xy(12, y0 + 2 + i * row_h)
            self.set_font("Helvetica", "B", 9)
            self.cell(35, 7, label)
            self.set_font("Helvetica", "", 9)
            self.cell(150, 7, value)
        self.set_y(y0 + n * row_h + 6)


def make_sf_pdf():
    """格式1: 顺丰风格 - 区块式布局"""
    p = WaybillPDF()
    p.add_t("SF EXPRESS - Electronic Waybill")
    p.set_font("Helvetica", "", 9)
    p.cell(0, 6, "Shipper: SF Express Co., Ltd.", new_x="LMARGIN", new_y="NEXT", align="C")
    p.ln(8)

    p.section("Tracking Information")
    p.field("Tracking No.", "SF1234567890123")
    p.field("Order No.", "ORD20240715001")
    p.field("Shipping Date", "2024-07-15")
    p.field("Service Type", "Standard Express")
    p.field("Payment Method", "Prepaid")
    p.h_line()

    p.section("Sender (Shipper)")
    p.field("Name", "Zhang Wei")
    p.field("Company", "Shenzhen Tech Co., Ltd.")
    p.field("Phone", "13800138001")
    p.field("Address", "Room 2808, Bldg A, Science Park, Nanshan District")
    p.field("City / Province", "Shenzhen, Guangdong")
    p.h_line()

    p.section("Recipient (Consignee)")
    p.field("Name", "Li Ming")
    p.field("Company", "Beijing Trading Corp.")
    p.field("Phone", "13900139002")
    p.field("Address", "No.66 Jianguo Road, Chaoyang District")
    p.field("City / Province", "Beijing")
    p.h_line()

    p.section("Shipment Details")
    p.field("Weight", "2.50 kg")
    p.field("Pieces", "1")
    p.field("Declared Value", "CNY 500.00")
    p.field("Estimated Delivery", "2024-07-17")
    p.field("Remarks", "Fragile - Handle with care")
    p.h_line()

    p.ln(5)
    p.set_font("Courier", "", 8)
    p.cell(0, 6, "||| |||||| ||||| ||| || |||||| ||||| |||||| |||", new_x="LMARGIN", new_y="NEXT", align="C")
    p.cell(0, 6, "SF1234567890123", new_x="LMARGIN", new_y="NEXT", align="C")

    path = str(TEST_PDFS_DIR / "test_sf_waybill.pdf")
    p.output(path)
    return path


def make_zhongtong_pdf():
    """格式2: 中通风格 - 表格式布局"""
    p = WaybillPDF()
    p.add_t("LOGISTICS CONSIGNMENT NOTE")
    p.add_t("ZTO Express (Zhongtong)", 12)
    p.ln(3)

    items = [
        ("Waybill No.", "ZT2024071500888                      Order No.    PO-2024-0715-5566"),
        ("Date", "2024-07-15                                    Carrier      ZTO Express"),
        ("Sender", "Wang Fang                                    Phone        13600136003"),
        ("From", "No.88 Zhongshan Rd, Gulou Dist, Nanjing, Jiangsu"),
        ("Recipient", "Chen Xiao                                    Phone        13700137004"),
        ("To", "Bldg 3, Tianhe Software Park, Tianhe Dist, Guangzhou, Guangdong"),
        ("Weight", "3.8kg        Qty    2        Declared Value    CNY 1200"),
        ("Payment", "COD (Cash on Delivery)                Est.Delivery   2024-07-18"),
    ]
    p.rect_box(items)

    path = str(TEST_PDFS_DIR / "test_zhongtong_waybill.pdf")
    p.output(path)
    return path


def make_yuantong_pdf():
    """格式3: 圆通风格 - 无框自由格式（最难）"""
    p = WaybillPDF()
    p.add_t("Express Delivery Note")
    p.ln(5)

    p.set_font("Helvetica", "B", 11)
    p.cell(40, 7, "Waybill #:")
    p.set_font("Helvetica", "", 11)
    p.cell(0, 7, "YT998877665544332211", new_x="LMARGIN", new_y="NEXT")
    p.ln(4)

    p.set_font("Helvetica", "B", 10)
    p.cell(0, 7, "From:", new_x="LMARGIN", new_y="NEXT")
    p.set_font("Helvetica", "", 10)
    p.cell(0, 7, "  Zhao Qiang", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  15000150005", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  Floor 12, Wanda Plaza, Jinjiang District", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  Chengdu, Sichuan", new_x="LMARGIN", new_y="NEXT")
    p.ln(4)

    p.set_font("Helvetica", "B", 10)
    p.cell(0, 7, "To:", new_x="LMARGIN", new_y="NEXT")
    p.set_font("Helvetica", "", 10)
    p.cell(0, 7, "  Sun Li", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  15200152006", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  Room 501, No.18 Hubin Road, Siming District", new_x="LMARGIN", new_y="NEXT")
    p.cell(0, 7, "  Xiamen, Fujian", new_x="LMARGIN", new_y="NEXT")
    p.ln(4)

    p.h_line()
    p.field("Date", "2024/07/15")
    p.field("Weight", "1.2kg")
    p.field("Carrier", "YTO Express (Yuantong)")
    p.field("Payment", "Sender Pay")
    p.field("Note", "Clothing samples - No commercial value")

    path = str(TEST_PDFS_DIR / "test_yuantong_waybill.pdf")
    p.output(path)
    return path


def create_labels():
    """Ground Truth"""
    return {
        "_说明": "标注数据 - 每个PDF的正确答案。字段留空=PDF中不存在该信息",
        "test_cases": [
            {
                "pdf_file": "sample_pdfs/test_sf_waybill.pdf",
                "ground_truth": [{
                    "tracking_number": "SF1234567890123",
                    "order_number": "ORD20240715001",
                    "sender": {
                        "name": "Zhang Wei",
                        "phone": "13800138001",
                        "address": "Room 2808, Bldg A, Science Park, Nanshan District",
                        "province": "Guangdong",
                        "city": "Shenzhen",
                        "district": "Nanshan District"
                    },
                    "recipient": {
                        "name": "Li Ming",
                        "phone": "13900139002",
                        "address": "No.66 Jianguo Road, Chaoyang District",
                        "province": "Beijing",
                        "city": "Beijing",
                        "district": "Chaoyang District"
                    },
                    "shipping_date": "2024-07-15",
                    "weight": "2.50 kg",
                    "quantity": "1",
                    "shipping_method": "Standard Express",
                    "carrier": "SF Express",
                    "declared_value": "CNY 500.00",
                    "payment_method": "Prepaid",
                    "delivery_date": "2024-07-17",
                    "remarks": "Fragile - Handle with care"
                }]
            },
            {
                "pdf_file": "sample_pdfs/test_zhongtong_waybill.pdf",
                "ground_truth": [{
                    "tracking_number": "ZT2024071500888",
                    "order_number": "PO-2024-0715-5566",
                    "sender": {
                        "name": "Wang Fang",
                        "phone": "13600136003",
                        "address": "No.88 Zhongshan Rd, Gulou Dist, Nanjing, Jiangsu",
                        "province": "Jiangsu",
                        "city": "Nanjing",
                        "district": "Gulou Dist"
                    },
                    "recipient": {
                        "name": "Chen Xiao",
                        "phone": "13700137004",
                        "address": "Bldg 3, Tianhe Software Park, Tianhe Dist, Guangzhou, Guangdong",
                        "province": "Guangdong",
                        "city": "Guangzhou",
                        "district": "Tianhe Dist"
                    },
                    "shipping_date": "2024-07-15",
                    "weight": "3.8kg",
                    "quantity": "2",
                    "shipping_method": "",
                    "carrier": "ZTO Express",
                    "declared_value": "CNY 1200",
                    "payment_method": "COD",
                    "delivery_date": "2024-07-18",
                    "remarks": ""
                }]
            },
            {
                "pdf_file": "sample_pdfs/test_yuantong_waybill.pdf",
                "ground_truth": [{
                    "tracking_number": "YT998877665544332211",
                    "order_number": "",
                    "sender": {
                        "name": "Zhao Qiang",
                        "phone": "15000150005",
                        "address": "Floor 12, Wanda Plaza, Jinjiang District",
                        "province": "Sichuan",
                        "city": "Chengdu",
                        "district": "Jinjiang District"
                    },
                    "recipient": {
                        "name": "Sun Li",
                        "phone": "15200152006",
                        "address": "Room 501, No.18 Hubin Road, Siming District",
                        "province": "Fujian",
                        "city": "Xiamen",
                        "district": "Siming District"
                    },
                    "shipping_date": "2024-07-15",
                    "weight": "1.2kg",
                    "quantity": "",
                    "shipping_method": "",
                    "carrier": "YTO Express",
                    "declared_value": "",
                    "payment_method": "Sender Pay",
                    "delivery_date": "",
                    "remarks": "Clothing samples - No commercial value"
                }]
            }
        ]
    }


if __name__ == "__main__":
    TEST_PDFS_DIR.mkdir(parents=True, exist_ok=True)
    LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)

    print("Generating test PDFs...")
    print(f"  1. SF Express style  -> {make_sf_pdf()}")
    print(f"  2. ZTO table style   -> {make_zhongtong_pdf()}")
    print(f"  3. YTO free style    -> {make_yuantong_pdf()}")

    labels = create_labels()
    LABELS_PATH.write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nLabels -> {LABELS_PATH}")
    print(f"3 PDFs + labels ready.")
    print(f"\nRun: python scripts/evaluate.py --data data/labels.json --pdf-dir . --mode compare")
