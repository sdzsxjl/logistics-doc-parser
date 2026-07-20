"""
数据模型定义 - 物流运单字段定义
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class ContactInfo(BaseModel):
    """寄件人或收件人信息"""
    name: str = Field(default="", description="姓名/公司名")
    phone: str = Field(default="", description="联系电话")
    address: str = Field(default="", description="详细地址")
    province: str = Field(default="", description="省份")
    city: str = Field(default="", description="城市")
    district: str = Field(default="", description="区/县")

    def full_address(self) -> str:
        parts = [self.province, self.city, self.district, self.address]
        return "".join(p for p in parts if p)

    def to_flat_dict(self, prefix: str) -> dict:
        """展开为扁平字典，键名加前缀"""
        return {
            f"{prefix}姓名": self.name,
            f"{prefix}电话": self.phone,
            f"{prefix}地址": self.full_address(),
            f"{prefix}详细地址": self.address,
            f"{prefix}省份": self.province,
            f"{prefix}城市": self.city,
            f"{prefix}区县": self.district,
        }


class ShippingOrder(BaseModel):
    """物流运单信息"""
    # 核心标识
    tracking_number: str = Field(default="", description="运单号/快递单号")
    order_number: str = Field(default="", description="订单号/参考号")

    # 收发人信息
    sender: ContactInfo = Field(default_factory=ContactInfo, description="寄件人")
    recipient: ContactInfo = Field(default_factory=ContactInfo, description="收件人")

    # 运输信息
    shipping_date: str = Field(default="", description="发货日期")
    weight: str = Field(default="", description="重量(含单位)")
    quantity: str = Field(default="", description="件数")
    shipping_method: str = Field(default="", description="运输方式/服务类型")
    carrier: str = Field(default="", description="承运商/快递公司")

    # 费用信息
    declared_value: str = Field(default="", description="申报价值")
    payment_method: str = Field(default="", description="付款方式(寄付/到付/月结)")

    # 其他
    remarks: str = Field(default="", description="备注")
    delivery_date: str = Field(default="", description="预计送达日期")

    # 元数据
    pdf_filename: str = Field(default="", description="来源PDF文件名")
    extraction_confidence: float = Field(default=0.0, description="提取置信度 0.0~1.0")
    extraction_method: str = Field(default="", description="提取方式: ai / regex / merged")

    def to_flat_dict(self) -> dict:
        """转为扁平字典，适合导出Excel"""
        result = {
            "运单号": self.tracking_number,
            "订单号": self.order_number,
            "发货日期": self.shipping_date,
            "重量": self.weight,
            "件数": self.quantity,
            "运输方式": self.shipping_method,
            "承运商": self.carrier,
            "申报价值": self.declared_value,
            "付款方式": self.payment_method,
            "预计送达": self.delivery_date,
            "备注": self.remarks,
            "置信度": self.extraction_confidence,
            "来源文件": self.pdf_filename,
        }
        result.update(self.sender.to_flat_dict("寄件人"))
        result.update(self.recipient.to_flat_dict("收件人"))
        return result

    def is_valid(self) -> bool:
        """检查是否至少提取到了一些有效信息"""
        return bool(
            self.tracking_number
            or self.sender.name
            or self.recipient.name
            or self.sender.phone
            or self.recipient.phone
        )


class ParseResult(BaseModel):
    """单个PDF的解析结果"""
    filename: str = ""
    success: bool = False
    orders: List[ShippingOrder] = Field(default_factory=list)
    raw_text: str = Field(default="", description="提取的原始文本")
    error_message: str = Field(default="")
    extraction_method: str = Field(default="")

    @property
    def order_count(self) -> int:
        return len(self.orders)
