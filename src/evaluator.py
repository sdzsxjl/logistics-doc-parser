"""
测评模块 - 对比AI/正则解析结果与人工标注，量化准确率
输出：字段级 Precision/Recall/F1 + 端到端指标
"""
import json
import os
import time
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

from .models import ShippingOrder, ContactInfo
from .pdf_extractor import extract_text_from_pdf
from .ai_parser import AIParser
from .regex_parser import RegexParser


# ═══════════════════════════════════════════════════════════
# 标注数据格式
# ═══════════════════════════════════════════════════════════

@dataclass
class FieldScore:
    """单个字段的评分"""
    tp: int = 0      # 正确提取
    fp: int = 0      # 错误提取（提取了但不对）
    fn: int = 0      # 漏提取（该提没提）

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "正确": self.tp,
            "错误": self.fp,
            "遗漏": self.fn,
            "精确率": round(self.precision * 100, 1),
            "召回率": round(self.recall * 100, 1),
            "F1": round(self.f1 * 100, 1),
        }


@dataclass
class EvalResult:
    """单个PDF的测评结果"""
    filename: str = ""
    total_fields: int = 0
    matched_orders: int = 0
    missing_orders: int = 0
    extra_orders: int = 0
    parse_time_ms: float = 0
    parse_method: str = ""
    success: bool = False
    error: str = ""
    fields: Dict[str, FieldScore] = field(default_factory=dict)
    details: List[Dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 核心字段定义（分权重）
# ═══════════════════════════════════════════════════════════

# 关键字段：必须完全匹配
CRITICAL_FIELDS = [
    "tracking_number",   # 运单号
    "sender.phone",      # 寄件人电话
    "recipient.phone",   # 收件人电话
]

# 重要字段：模糊匹配
IMPORTANT_FIELDS = [
    "sender.name",       # 寄件人姓名
    "recipient.name",    # 收件人姓名
    "order_number",      # 订单号
    "shipping_date",     # 发货日期
    "carrier",           # 承运商
]

# 普通字段：非空即算对
NORMAL_FIELDS = [
    "sender.province", "sender.city", "sender.district",
    "recipient.province", "recipient.city", "recipient.district",
    "sender.address", "recipient.address",
    "weight", "quantity", "shipping_method",
    "payment_method", "declared_value",
]

ALL_FIELDS = CRITICAL_FIELDS + IMPORTANT_FIELDS + NORMAL_FIELDS


def get_nested_value(order: ShippingOrder, field_path: str) -> str:
    """从ShippingOrder中按路径取字段值，如 'sender.name'"""
    parts = field_path.split(".")
    obj = order
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        elif isinstance(obj, dict):
            obj = obj.get(part, "")
        else:
            return ""
    return str(obj).strip() if obj else ""


def compare_field(predicted: str, ground_truth: str, field_path: str) -> bool:
    """比较单个字段是否匹配"""
    p = predicted.strip() if predicted else ""
    g = ground_truth.strip() if ground_truth else ""

    if not p and not g:
        return True  # 双方都为空，视为正确
    if not p or not g:
        return False

    if field_path in CRITICAL_FIELDS:
        # 关键字段：完全匹配或清洗后匹配
        p_clean = re.sub(r'[\s\-\(\)（）]+', '', p)
        g_clean = re.sub(r'[\s\-\(\)（）]+', '', g)
        return p_clean.lower() == g_clean.lower()

    elif field_path in IMPORTANT_FIELDS:
        # 重要字段：包含关系或编辑距离近
        if field_path.endswith(".name"):
            # 姓名：允许单字差异（如"张三" vs "张三丰"不算对，但"张叁" vs "张三"难判断）
            return p == g or (len(p) >= 2 and len(g) >= 2 and
                              (p in g or g in p))
        if field_path.endswith("date"):
            # 日期：标准化后比较
            p_date = re.sub(r'[-/年月日]', '', p)
            g_date = re.sub(r'[-/年月日]', '', g)
            return p_date == g_date
        # 其他重要字段：包含关系
        return p in g or g in p

    else:
        # 普通字段：地址用包含关系，其他用非空检查
        if field_path.endswith("address"):
            # 地址：核心部分重叠即算对
            p_parts = set(re.findall(r'[一-鿿\d]+', p))
            g_parts = set(re.findall(r'[一-鿿\d]+', g))
            if not g_parts:
                return bool(p)
            overlap = len(p_parts & g_parts)
            return overlap >= max(1, len(g_parts) * 0.3)
        # 其他普通字段：非空即算对
        return bool(p) == bool(g)


# ═══════════════════════════════════════════════════════════
# 测评引擎
# ═══════════════════════════════════════════════════════════

class Evaluator:
    """测评引擎"""

    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model
        self.ai_parser = AIParser(api_key=self.api_key, model=self.model) if self.api_key else None
        self.regex_parser = RegexParser()

    def evaluate_file(
        self,
        pdf_path: str,
        ground_truth: List[Dict],
        use_ai: bool = True,
    ) -> EvalResult:
        """测评单个PDF文件"""
        result = EvalResult(filename=os.path.basename(pdf_path))

        try:
            start = time.time()
            # Read file into bytes (extract_text_from_pdf expects bytes)
            with open(pdf_path, "rb") as fh:
                pdf_bytes = fh.read()
            full_text, _, _ = extract_text_from_pdf(pdf_bytes, os.path.basename(pdf_path))
            if not full_text.strip():
                result.error = "PDF无文字"
                return result

            # 解析
            if use_ai and self.ai_parser:
                try:
                    orders = self.ai_parser.parse(full_text, os.path.basename(pdf_path))
                    result.parse_method = "ai"
                except Exception:
                    orders = self.regex_parser.parse(full_text, os.path.basename(pdf_path))
                    result.parse_method = "regex (AI回退)"
            else:
                orders = self.regex_parser.parse(full_text, os.path.basename(pdf_path))
                result.parse_method = "regex"

            result.parse_time_ms = (time.time() - start) * 1000
            result.success = True

            # 逐字段对比
            gt_orders = ground_truth
            result.total_fields = len(gt_orders) * len(ALL_FIELDS)
            result.fields = {f: FieldScore() for f in ALL_FIELDS}

            # 运单匹配：按运单号对齐
            matched_pairs = self._align_orders(orders, gt_orders)
            result.matched_orders = len(matched_pairs)
            result.missing_orders = max(0, len(gt_orders) - len(orders))
            result.extra_orders = max(0, len(orders) - len(gt_orders))

            for pred_order, gt_order in matched_pairs:
                self._compare_order(pred_order, gt_order, result)

        except Exception as e:
            result.error = str(e)

        return result

    def _align_orders(
        self, pred_orders: List[ShippingOrder], gt_orders: List[Dict]
    ) -> List[Tuple[ShippingOrder, Dict]]:
        """按运单号对齐预测和标注"""
        pairs = []
        unmatched_pred = list(pred_orders)
        unmatched_gt = list(gt_orders)

        # 先按运单号精准匹配
        for gt in list(unmatched_gt):
            gt_tn = gt.get("tracking_number", "").strip()
            for pred in list(unmatched_pred):
                pred_tn = pred.tracking_number.strip()
                if gt_tn and pred_tn and re.sub(r'[\s\-]+', '', gt_tn) == re.sub(r'[\s\-]+', '', pred_tn):
                    pairs.append((pred, gt))
                    unmatched_pred.remove(pred)
                    unmatched_gt.remove(gt)
                    break

        # 剩余按顺序强制对齐
        for i, gt in enumerate(unmatched_gt):
            if i < len(unmatched_pred):
                pairs.append((unmatched_pred[i], gt))

        return pairs

    def _compare_order(
        self, pred: ShippingOrder, gt: Dict, result: EvalResult
    ):
        """对比单个运单的每个字段"""
        flat_gt = self._flatten_gt(gt)

        for field_path in ALL_FIELDS:
            pred_val = get_nested_value(pred, field_path)
            gt_val = flat_gt.get(field_path, "")

            if not gt_val:
                continue  # 标注为空的不参与计算

            is_correct = compare_field(pred_val, gt_val, field_path)

            if is_correct:
                result.fields[field_path].tp += 1
            else:
                if pred_val:
                    result.fields[field_path].fp += 1
                else:
                    result.fields[field_path].fn += 1

            result.details.append({
                "字段": field_path,
                "预测值": pred_val[:60],
                "标注值": gt_val[:60],
                "正确": is_correct,
            })

    def _flatten_gt(self, gt: Dict) -> Dict[str, str]:
        """将嵌套标注数据展平为点分路径"""
        flat = {}
        for key in ["tracking_number", "order_number", "shipping_date",
                     "weight", "quantity", "shipping_method", "carrier",
                     "declared_value", "payment_method", "delivery_date", "remarks"]:
            if key in gt:
                flat[key] = str(gt[key])

        for role in ["sender", "recipient"]:
            if role in gt:
                for sub in ["name", "phone", "address", "province", "city", "district"]:
                    flat[f"{role}.{sub}"] = str(gt[role].get(sub, ""))

        return flat

    def evaluate_batch(
        self,
        test_cases: List[Dict],
        pdf_dir: str = ".",
        use_ai: bool = True,
        verbose: bool = True,
    ) -> Dict:
        """批量测评"""
        results: List[EvalResult] = []
        total_start = time.time()

        for i, case in enumerate(test_cases):
            pdf_file = case.get("pdf_file", "")
            pdf_path = os.path.join(pdf_dir, pdf_file) if not os.path.isabs(pdf_file) else pdf_file
            ground_truth = case.get("ground_truth", [])

            if not os.path.exists(pdf_path):
                if verbose:
                    print(f"  [WARN]  [{i+1}/{len(test_cases)}] {pdf_file} → 文件不存在，跳过")
                continue

            if verbose:
                print(f"  [ [{i+1}/{len(test_cases)}] {pdf_file}...", end=" ")

            result = self.evaluate_file(pdf_path, ground_truth, use_ai=use_ai)
            results.append(result)

            if verbose:
                if result.success:
                    print(f"[OK] {result.matched_orders}单 | {result.parse_method} | {result.parse_time_ms:.0f}ms")
                else:
                    print(f"[FAIL] {result.error}")

        total_time = (time.time() - total_start) * 1000

        return self._summarize(results, total_time)

    def _summarize(self, results: List[EvalResult], total_time_ms: float) -> Dict:
        """汇总所有测评结果"""
        success_results = [r for r in results if r.success]
        failed_results = [r for r in results if not r.success]

        # 汇总字段评分
        global_scores: Dict[str, FieldScore] = {}
        for field in ALL_FIELDS:
            global_scores[field] = FieldScore()

        for r in success_results:
            for field in ALL_FIELDS:
                if field in r.fields:
                    global_scores[field].tp += r.fields[field].tp
                    global_scores[field].fp += r.fields[field].fp
                    global_scores[field].fn += r.fields[field].fn

        # 计算加权总分
        weights = {}
        for f in CRITICAL_FIELDS:
            weights[f] = 3
        for f in IMPORTANT_FIELDS:
            weights[f] = 2
        for f in NORMAL_FIELDS:
            weights[f] = 1

        weighted_f1 = 0.0
        total_weight = sum(weights.values())
        for field in ALL_FIELDS:
            weighted_f1 += global_scores[field].f1 * weights[field] / total_weight

        # 端到端指标
        total_orders = sum(r.matched_orders + r.missing_orders for r in success_results)
        matched = sum(r.matched_orders for r in success_results)

        return {
            "测试概况": {
                "总文件数": len(results),
                "成功": len(success_results),
                "失败": len(failed_results),
                "成功率": f"{len(success_results)/len(results)*100:.1f}%" if results else "N/A",
                "总耗时_ms": round(total_time_ms),
                "AI解析数": sum(1 for r in success_results if r.parse_method.startswith("ai")),
                "正则解析数": sum(1 for r in success_results if r.parse_method == "regex"),
            },
            "运单识别": {
                "应识别运单数": total_orders,
                "正确匹配": matched,
                "运单召回率": f"{matched/total_orders*100:.1f}%" if total_orders else "N/A",
                "漏识别": sum(r.missing_orders for r in success_results),
                "多识别": sum(r.extra_orders for r in success_results),
            },
            "加权总分": round(weighted_f1 * 100, 1),
            "字段评分": {f: global_scores[f].to_dict() for f in ALL_FIELDS},
            "按重要度": {
                "关键字段(权重3)": self._aggregate_category(global_scores, CRITICAL_FIELDS),
                "重要字段(权重2)": self._aggregate_category(global_scores, IMPORTANT_FIELDS),
                "普通字段(权重1)": self._aggregate_category(global_scores, NORMAL_FIELDS),
            },
            "处理速度": {
                "平均每文件_ms": round(total_time_ms / len(results), 0) if results else 0,
                "平均每单_ms": round(total_time_ms / max(total_orders, 1), 0),
            },
            "失败列表": [
                {"文件": r.filename, "错误": r.error} for r in failed_results
            ],
            "明细": [
                {
                    "文件": r.filename,
                    "方法": r.parse_method,
                    "匹配单数": r.matched_orders,
                    "耗时_ms": round(r.parse_time_ms),
                    "错误字段": [d["字段"] for d in r.details if not d["正确"]],
                }
                for r in success_results
            ],
        }

    def _aggregate_category(self, scores: Dict[str, FieldScore], fields: List[str]) -> Dict:
        """汇总某一类字段的评分"""
        tp = sum(scores[f].tp for f in fields)
        fp = sum(scores[f].fp for f in fields)
        fn = sum(scores[f].fn for f in fields)
        total = tp + fp + fn
        p = tp / (tp + fp) if (tp + fp) > 0 else 0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
        return {
            "样本数": total,
            "精确率": round(p * 100, 1),
            "召回率": round(r * 100, 1),
            "F1": round(f1 * 100, 1),
        }

    def run_comparison(
        self,
        test_cases: List[Dict],
        pdf_dir: str = ".",
    ) -> Dict:
        """对比 AI 和 正则 两种模式"""
        print("\n" + "=" * 60)
        print("[AI] AI 模式测评")
        print("=" * 60)
        ai_result = self.evaluate_batch(test_cases, pdf_dir, use_ai=True, verbose=True)

        print("\n" + "=" * 60)
        print("[:] 正则模式测评")
        print("=" * 60)
        regex_result = self.evaluate_batch(test_cases, pdf_dir, use_ai=False, verbose=True)

        return {
            "AI模式": ai_result,
            "正则模式": regex_result,
            "对比": {
                "AI加权F1": ai_result["加权总分"],
                "正则加权F1": regex_result["加权总分"],
                "AI提升幅度": f"{(ai_result['加权总分'] - regex_result['加权总分']):.1f} 分",
            },
        }

    def print_report(self, summary: Dict):
        """美化打印测评报告"""
        print("\n" + "=" * 70)
        print("  [ 物流运单AI解析 - 测评报告")
        print("=" * 70)

        overview = summary.get("测试概况", {})
        print(f"\n  [ 测试概况")
        print(f"     文件: {overview.get('总文件数', 0)} | "
              f"成功: {overview.get('成功', 0)} | "
              f"失败: {overview.get('失败', 0)} | "
              f"成功率: {overview.get('成功率', 'N/A')}")

        tracking = summary.get("运单识别", {})
        print(f"\n  [ 运单识别")
        print(f"     应识别: {tracking.get('应识别运单数', 0)} | "
              f"已匹配: {tracking.get('正确匹配', 0)} | "
              f"漏识别: {tracking.get('漏识别', 0)} | "
              f"多识别: {tracking.get('多识别', 0)}")

        print(f"\n  [*] 加权总分: {summary.get('加权总分', 'N/A')} / 100")

        print(f"\n    字段评分")
        print(f"     {'字段':<22} {'精确率':>6} {'召回率':>6} {'F1':>6} {'样本':>5}")
        print(f"     {'─'*45}")
        field_scores = summary.get("字段评分", {})
        for field, score in field_scores.items():
            if score["正确"] + score["错误"] + score["遗漏"] == 0:
                continue
            print(f"     {field:<22} {score['精确率']:>5}% {score['召回率']:>5}% {score['F1']:>5}% {score['正确']+score['错误']+score['遗漏']:>4}")

        print(f"\n  [ 按重要度汇总")
        for cat, score in summary.get("按重要度", {}).items():
            print(f"     {cat}: F1={score['F1']}% (精确率={score['精确率']}% 召回率={score['召回率']}%)")

        speed = summary.get("处理速度", {})
        print(f"\n  [ 处理速度")
        print(f"     平均每文件: {speed.get('平均每文件_ms', 0):.0f}ms | "
              f"平均每单: {speed.get('平均每单_ms', 0):.0f}ms")

        failures = summary.get("失败列表", [])
        if failures:
            print(f"\n  [FAIL] 失败详情")
            for f in failures:
                print(f"     {f['文件']}: {f['错误']}")

        print("\n" + "=" * 70 + "\n")
