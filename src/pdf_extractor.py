"""
PDF文本提取模块 - 使用pdfplumber提取PDF中的文本内容
"""
import pdfplumber
from typing import List, Dict, Optional, Tuple
import io


class PDFExtractor:
    """PDF文本提取器"""

    def __init__(self):
        self.text_blocks: List[Dict] = []
        self.tables: List[List[List[str]]] = []
        self.full_text: str = ""
        self.page_count: int = 0

    def extract(self, file_bytes: bytes, filename: str = "") -> str:
        """
        从PDF字节数据中提取文本

        Args:
            file_bytes: PDF文件的字节数据
            filename: 文件名（用于日志）

        Returns:
            提取到的完整文本
        """
        self.text_blocks = []
        self.tables = []
        self.full_text = ""
        self.page_count = 0

        try:
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                self.page_count = len(pdf.pages)
                all_texts = []

                for i, page in enumerate(pdf.pages):
                    # 提取文本
                    page_text = page.extract_text()
                    if page_text:
                        all_texts.append(f"--- 第{i+1}页 ---\n{page_text}")

                    # 提取文本块（带坐标）
                    words = page.extract_words()
                    for w in words:
                        self.text_blocks.append({
                            "page": i + 1,
                            "text": w.get("text", ""),
                            "x0": w.get("x0", 0),
                            "y0": w.get("top", 0),
                            "x1": w.get("x1", 0),
                            "y1": w.get("bottom", 0),
                        })

                    # 提取表格
                    tables = page.extract_tables()
                    for table in tables:
                        if table:
                            self.tables.append(table)
                            # 也将表格转为文本
                            for row in table:
                                row_text = " | ".join(
                                    str(cell).strip() if cell else ""
                                    for cell in row
                                )
                                all_texts.append(row_text)

                self.full_text = "\n".join(all_texts)

        except Exception as e:
            raise ValueError(f"PDF解析失败 ({filename}): {str(e)}")

        return self.full_text

    def get_text_blocks_by_region(
        self, top: float = 0, bottom: float = float("inf")
    ) -> List[Dict]:
        """按区域筛选文本块"""
        return [
            b
            for b in self.text_blocks
            if b["y0"] >= top and b["y1"] <= bottom
        ]

    def extract_fields_from_patterns(self) -> Dict[str, str]:
        """
        基于文本块的坐标关系提取常见字段
        例如：标签在左，值在右
        """
        results = {}
        for i, block in enumerate(self.text_blocks):
            text = block["text"]
            # 找相邻的水平文本对（标签:值 模式）
            for j, other in enumerate(self.text_blocks):
                if i == j:
                    continue
                # 同一行（y坐标相近），且相邻
                if (
                    abs(block["y0"] - other["y0"]) < 5
                    and other["x0"] > block["x1"]
                    and other["x0"] - block["x1"] < 50
                ):
                    # 可能是一对标签-值
                    pass

        return results


def extract_text_from_pdf(file_bytes: bytes, filename: str = "") -> Tuple[str, List, List]:
    """
    便捷函数：从PDF中提取文本、文本块和表格

    Returns:
        (full_text, text_blocks, tables)
    """
    extractor = PDFExtractor()
    full_text = extractor.extract(file_bytes, filename)
    return full_text, extractor.text_blocks, extractor.tables
