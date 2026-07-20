"""
AI智能解析模块 - 使用DeepSeek API智能提取物流运单信息
DeepSeek API兼容OpenAI接口格式，使用openai库调用
"""
import json
import os
from typing import List, Optional
from dotenv import load_dotenv
from openai import OpenAI

from .models import ShippingOrder, ContactInfo


load_dotenv()

# DeepSeek API默认地址
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# AI解析的System Prompt
SYSTEM_PROMPT = """你是一个物流单据信息提取专家。你的任务是从PDF提取的文本中，精确提取出物流运单的关键信息。

## 提取规则

1. **运单号/快递单号**: 通常是一串数字或字母数字组合，如"SF1234567890"、"1Z999AA10123456784"、"JD0012345678901"等。可能有"运单号"、"快递单号"、"Tracking No."、"Waybill No."等标签。

2. **订单号**: 电商订单号、客户参考号等。标签可能是"订单号"、"Order No."、"Reference No."等。

3. **寄件人（Sender/Shipper）**:
   - 姓名或公司名
   - 电话号码（手机号1开头11位，或座机号）
   - 详细地址（包含省/市/区）

4. **收件人（Recipient/Consignee）**:
   - 姓名或公司名
   - 电话号码
   - 详细地址

5. **发货日期**: 格式统一为YYYY-MM-DD

6. **重量**: 保留原始值和单位

7. **件数**: 包裹数量

8. **运输方式/承运商**: 如"顺丰"、"中通"、"圆通"、"韵达"、"EMS"、"DHL"、"FedEx"等

9. **付款方式**: 寄付/到付/月结

## 注意事项
- 如果某个字段在文本中找不到，对应值设为空字符串""
- 不要猜测或编造任何信息
- 手机号必须是11位数字（以1开头）
- 地址信息尽量完整，包括省市区
- 同一个PDF可能包含多个运单，请全部提取出来，放在orders数组中

## 输出格式
严格按照以下JSON格式输出，不要输出任何其他内容：
{
  "orders": [
    {
      "tracking_number": "运单号",
      "order_number": "订单号",
      "sender": {
        "name": "寄件人姓名",
        "phone": "联系电话",
        "address": "详细地址",
        "province": "省",
        "city": "市",
        "district": "区"
      },
      "recipient": {
        "name": "收件人姓名",
        "phone": "联系电话",
        "address": "详细地址",
        "province": "省",
        "city": "市",
        "district": "区"
      },
      "shipping_date": "YYYY-MM-DD或空",
      "weight": "重量（含单位）",
      "quantity": "件数",
      "shipping_method": "运输方式",
      "carrier": "承运商",
      "declared_value": "申报价值",
      "payment_method": "付款方式",
      "delivery_date": "预计送达日期",
      "remarks": "备注"
    }
  ],
  "confidence": 0.85
}"""


class AIParser:
    """使用DeepSeek API进行智能解析"""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.model = model or os.getenv("MODEL_NAME", "deepseek-chat")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL)

    def parse(self, pdf_text: str, filename: str = "") -> List[ShippingOrder]:
        """
        使用AI解析PDF文本，提取运单信息

        Args:
            pdf_text: 从PDF提取的原始文本
            filename: PDF文件名

        Returns:
            提取到的运单列表
        """
        if not self.api_key:
            raise ValueError("未配置API Key，请设置DEEPSEEK_API_KEY环境变量或在界面中输入")

        if not pdf_text.strip():
            return []

        # 截断过长文本（保留前8000字符，大多数运单足够）
        truncated_text = pdf_text[:8000]

        try:
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)

            response = client.chat.completions.create(
                model=self.model,
                max_tokens=4096,
                temperature=0,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"请从以下PDF文本中提取物流运单信息：\n\n{truncated_text}"},
                ],
            )

            # 解析返回的JSON
            content = response.choices[0].message.content if response.choices else ""

            # 提取JSON部分（防止markdown代码块包裹）
            json_str = self._extract_json(content)
            data = json.loads(json_str)

            return self._build_orders(data, filename)

        except ImportError:
            raise ImportError(
                "请安装openai库: pip install openai"
            )
        except json.JSONDecodeError as e:
            # JSON解析失败，返回空列表
            print(f"AI返回的JSON解析失败: {e}")
            print(f"原始返回: {content[:500]}...")
            return []
        except Exception as e:
            raise RuntimeError(f"AI解析失败: {str(e)}")

    def _extract_json(self, text: str) -> str:
        """从AI返回的文本中提取JSON部分"""
        text = text.strip()

        # 移除markdown代码块标记
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]

        if text.endswith("```"):
            text = text[:-3]

        # 找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")

        if start != -1 and end != -1:
            return text[start : end + 1]

        return text

    def _build_orders(self, data: dict, filename: str) -> List[ShippingOrder]:
        """将API返回的JSON数据构建为ShippingOrder对象"""
        confidence = data.get("confidence", 0.5)
        orders_data = data.get("orders", [])

        if not orders_data:
            return []

        orders = []
        for item in orders_data:
            sender = ContactInfo(
                name=item.get("sender", {}).get("name", ""),
                phone=item.get("sender", {}).get("phone", ""),
                address=item.get("sender", {}).get("address", ""),
                province=item.get("sender", {}).get("province", ""),
                city=item.get("sender", {}).get("city", ""),
                district=item.get("sender", {}).get("district", ""),
            )

            recipient = ContactInfo(
                name=item.get("recipient", {}).get("name", ""),
                phone=item.get("recipient", {}).get("phone", ""),
                address=item.get("recipient", {}).get("address", ""),
                province=item.get("recipient", {}).get("province", ""),
                city=item.get("recipient", {}).get("city", ""),
                district=item.get("recipient", {}).get("district", ""),
            )

            order = ShippingOrder(
                tracking_number=item.get("tracking_number", ""),
                order_number=item.get("order_number", ""),
                sender=sender,
                recipient=recipient,
                shipping_date=item.get("shipping_date", ""),
                weight=item.get("weight", ""),
                quantity=str(item.get("quantity", "")),
                shipping_method=item.get("shipping_method", ""),
                carrier=item.get("carrier", ""),
                declared_value=item.get("declared_value", ""),
                payment_method=item.get("payment_method", ""),
                delivery_date=item.get("delivery_date", ""),
                remarks=item.get("remarks", ""),
                pdf_filename=filename,
                extraction_confidence=confidence,
                extraction_method="ai",
            )

            orders.append(order)

        return orders


def parse_with_ai(
    pdf_text: str, filename: str = "", api_key: Optional[str] = None
) -> List[ShippingOrder]:
    """便捷函数：使用AI解析PDF文本"""
    parser = AIParser(api_key=api_key)
    return parser.parse(pdf_text, filename)
