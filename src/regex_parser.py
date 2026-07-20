"""
正则规则兜底解析模块 - 当AI不可用或解析失败时的备用方案
使用正则表达式和关键词匹配提取物流运单信息
"""
import re
from typing import List, Optional, Tuple
from .models import ShippingOrder, ContactInfo


class RegexParser:
    """基于正则规则的解析器"""

    # 运单号常见模式
    TRACKING_PATTERNS = [
        # 顺丰：SF开头 + 12位数字
        (r'SF\d{12,15}', 0.95, '顺丰'),
        # 京东：JD开头 + 数字
        (r'JD[VX]?\d{10,16}', 0.95, '京东'),
        # EMS：字母数字组合
        (r'[A-Z]{2}\d{9}[A-Z]{2}', 0.9, 'EMS'),
        # 中通/圆通/韵达等：通常为纯数字
        (r'YT\d{13,16}', 0.9, '圆通'),
        (r'ZT\d{10,16}', 0.9, '中通'),
        # DHL: 10位数字
        (r'\b\d{10}\b', 0.7, None),
        # UPS: 1Z开头
        (r'1Z[A-Z0-9]{16}', 0.95, 'UPS'),
        # FedEx: 12/15位数字
        (r'\b\d{12}\b', 0.7, None),
        (r'\b\d{14,20}\b', 0.65, None),
        # 常见的"YT"/"JD"/"SF"等前缀+长数字
        (r'[A-Z]{2,3}\d{10,18}', 0.8, None),
    ]

    # 手机号（中国）
    PHONE_PATTERNS = [
        (r'1[3-9]\d{9}', 0.95),
        (r'\+86[\s-]?1[3-9]\d{9}', 0.95),
        (r'(\d{3,4}[-\s]?\d{7,8})', 0.7),  # 座机号
    ]

    # 日期格式
    DATE_PATTERNS = [
        (r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})[日号]?', 0.9),
        (r'(\d{4}-\d{2}-\d{2})', 0.95),
        (r'(\d{4}/\d{2}/\d{2})', 0.9),
    ]

    # 地址中的省市区关键词
    PROVINCES = [
        '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江',
        '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南',
        '广东', '海南', '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾',
        '内蒙古', '广西', '西藏', '宁夏', '新疆', '香港', '澳门',
    ]

    # 寄件人关键词标签
    SENDER_LABELS = [
        '寄件人', '寄件方', '发货人', '发货方', '发件人', '发件方',
        'Shipper', 'Sender', 'From', '寄件', '发货',
        '寄件人姓名', '寄件公司', '发件人姓名',
    ]

    # 收件人关键词标签
    RECIPIENT_LABELS = [
        '收件人', '收件方', '收货人', '收货方', '收件', '收货',
        'Consignee', 'Recipient', 'To', 'Ship To', 'Deliver To',
        '收件人姓名', '收件公司', '收货人姓名', '收货地址',
    ]

    # 运单号关键词标签
    TRACKING_LABELS = [
        '运单号', '快递单号', '运单编号', '单号', '快递号',
        'Tracking No', 'Tracking Number', 'Waybill No', 'AWB No',
        '快件单号', '物流单号',
    ]

    # 承运商关键词
    CARRIER_KEYWORDS = {
        '顺丰': '顺丰速运',
        'SF': '顺丰速运',
        '中通': '中通快递',
        '圆通': '圆通速递',
        '韵达': '韵达快递',
        '申通': '申通快递',
        '百世': '百世快递',
        '极兔': '极兔速递',
        '京东': '京东物流',
        'EMS': 'EMS',
        '邮政': '中国邮政',
        'DHL': 'DHL',
        'FedEx': 'FedEx',
        'UPS': 'UPS',
        'TNT': 'TNT',
    }

    # 付款方式
    PAYMENT_KEYWORDS = {
        '寄付': '寄付',
        '到付': '到付',
        '月结': '月结',
        '预付': '预付',
        'Prepaid': '寄付',
        'Collect': '到付',
        'COD': '货到付款',
    }

    def parse(self, pdf_text: str, filename: str = "") -> List[ShippingOrder]:
        """
        使用正则规则解析PDF文本

        Args:
            pdf_text: PDF提取的原始文本
            filename: PDF文件名

        Returns:
            提取到的运单列表
        """
        if not pdf_text.strip():
            return []

        # 清理文本
        text = self._clean_text(pdf_text)

        # 检测是否包含多个运单
        orders = self._extract_orders(text, filename)

        return orders

    def _clean_text(self, text: str) -> str:
        """清理文本：统一空白符、标点等"""
        # 替换多个空白为单个空格
        text = re.sub(r'\s+', ' ', text)
        # 替换中文冒号等
        text = text.replace('：', ':')
        text = text.replace('，', ',')
        text = text.replace('。', '.')
        return text.strip()

    def _extract_orders(self, text: str, filename: str) -> List[ShippingOrder]:
        """从文本中提取运单信息"""

        # 尝试按分隔符拆分为多个运单
        # 常见分隔：多个"运单号"标签、分页符、分隔线等
        segments = self._split_by_tracking_label(text)

        orders = []
        for segment in segments:
            order = self._extract_single_order(segment, filename)
            if order.is_valid():
                orders.append(order)

        # 如果没有拆分出多个，至少尝试提取一个
        if not orders:
            order = self._extract_single_order(text, filename)
            if order.is_valid():
                orders.append(order)

        return orders

    # 仅用于分割多运单的标签（不能与订单号等重叠）
    SPLIT_LABELS = [
        '运单号', '快递单号', '运单编号', '快递号',
        'Tracking No', 'Tracking Number', 'Waybill No', 'AWB No',
        '快件单号', '物流单号',
    ]

    def _split_by_tracking_label(self, text: str) -> List[str]:
        """按运单号标签拆分多运单文本"""
        pattern = '|'.join(re.escape(label) for label in self.SPLIT_LABELS)

        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if len(matches) <= 1:
            return [text]

        segments = []
        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment = text[start:end].strip()
            if segment:
                segments.append(segment)

        return segments if segments else [text]

    def _extract_single_order(self, text: str, filename: str) -> ShippingOrder:
        """从单段文本中提取一个运单"""
        tracking_number = self._find_tracking_number(text)
        order_number = self._find_order_number(text)
        phone_numbers = self._find_phone_numbers(text)
        send_date = self._find_date(text)

        # 分配手机号：寄件人和收件人各取不同的号码
        sender_phones = phone_numbers[:1] if phone_numbers else []
        recipient_phones = phone_numbers[1:2] if len(phone_numbers) > 1 else phone_numbers[:1] if phone_numbers else []

        # 提取寄件人和收件人
        sender = self._extract_contact(text, sender_phones, is_sender=True)
        recipient = self._extract_contact(text, recipient_phones, is_sender=False)

        # 提取其他字段
        weight = self._find_weight(text)
        quantity = self._find_quantity(text)
        carrier = self._find_carrier(text)
        shipping_method = self._find_shipping_method(text)
        payment_method = self._find_payment_method(text)
        declared_value = self._find_declared_value(text)

        return ShippingOrder(
            tracking_number=tracking_number,
            order_number=order_number,
            sender=sender,
            recipient=recipient,
            shipping_date=send_date,
            weight=weight,
            quantity=quantity,
            shipping_method=shipping_method,
            carrier=carrier or shipping_method,
            declared_value=declared_value,
            payment_method=payment_method,
            pdf_filename=filename,
            extraction_confidence=0.6,
            extraction_method="regex",
        )

    def _find_tracking_number(self, text: str) -> str:
        """查找运单号"""
        best_match = ""
        best_conf = 0

        for pattern, conf, _ in self.TRACKING_PATTERNS:
            matches = re.findall(pattern, text)
            if matches and conf > best_conf:
                # 去重，选第一个
                best_match = matches[0]
                best_conf = conf

        # 如果没匹配到，尝试按标签查找
        if not best_match:
            for label in self.TRACKING_LABELS:
                idx = text.find(label)
                if idx != -1:
                    # 取标签后的文本（约30字符）
                    after = text[idx + len(label): idx + len(label) + 50]
                    # 尝试匹配数字字母串
                    m = re.search(r'[A-Za-z0-9]{8,30}', after)
                    if m:
                        return m.group(0).strip()

        return best_match

    def _find_order_number(self, text: str) -> str:
        """查找订单号"""
        labels = ['订单号', '订单编号', 'Order No', 'Order Number', '参考号', 'Reference']
        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 30]
                m = re.search(r'[A-Za-z0-9\-]{6,30}', after)
                if m:
                    return m.group(0).strip()
        return ""

    def _find_phone_numbers(self, text: str) -> List[Tuple[str, float]]:
        """查找所有电话号码，返回 (号码, 置信度)"""
        phones = []
        for pattern, conf in self.PHONE_PATTERNS:
            for m in re.finditer(pattern, text):
                phones.append((m.group(0).strip(), conf))
        return phones

    def _find_date(self, text: str) -> str:
        """查找日期"""
        labels = ['日期', '发货日期', '寄件日期', 'Date', 'Shipping Date']

        # 先按标签查找
        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 20]
                for pattern, _ in self.DATE_PATTERNS:
                    m = re.search(pattern, after)
                    if m:
                        return self._normalize_date(m.group(0))

        # 全局查找
        for pattern, _ in self.DATE_PATTERNS:
            m = re.search(pattern, text)
            if m:
                return self._normalize_date(m.group(0))

        return ""

    def _normalize_date(self, date_str: str) -> str:
        """标准化日期格式为YYYY-MM-DD"""
        # 移除尾部"日"或"号"
        date_str = re.sub(r'[日号]$', '', date_str)

        # 中文日期格式
        m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})', date_str)
        if m:
            return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

        # 数字格式
        date_str = date_str.replace('/', '-')

        return date_str.strip()

    def _extract_contact(
        self, text: str, phone_numbers: List[Tuple[str, float]], is_sender: bool
    ) -> ContactInfo:
        """提取联系人信息"""
        labels = self.SENDER_LABELS if is_sender else self.RECIPIENT_LABELS
        counterpart_labels = self.RECIPIENT_LABELS if is_sender else self.SENDER_LABELS

        # 找标签位置（优先匹配更长的标签）
        label_positions = []
        for label in labels:
            idx = 0
            while True:
                idx = text.find(label, idx)
                if idx == -1:
                    break
                label_positions.append((idx, label))
                idx += 1

        if not label_positions:
            # 没有找到对应标签，可能是无标签格式
            return ContactInfo(
                name=self._find_name_near_phone(text, phone_numbers, is_sender),
                phone=phone_numbers[0][0] if phone_numbers else "",
                address=self._find_address(text),
                province=self._find_province(text),
                city=self._find_city(text),
                district=self._find_district(text),
            )

        # 按位置排序，同位置优先选更长的标签
        label_positions.sort(key=lambda x: (x[0], -len(x[1])))
        label_idx, label_name = label_positions[0]

        # 找到对方标签的位置作为区域边界（避免串区）
        boundary = len(text)
        for cp_label in counterpart_labels:
            cp_idx = text.find(cp_label, label_idx + len(label_name))
            if cp_idx != -1 and cp_idx < boundary:
                boundary = cp_idx

        # 取该联系人区域（标签后到对方标签前，最多300字符）
        region = text[label_idx + len(label_name): min(boundary, label_idx + len(label_name) + 300)]

        name = self._find_name(region)
        phone = self._find_best_phone(region, phone_numbers)
        address = self._find_address(region) or self._find_address(text)
        province = self._find_province(region) or self._find_province(text)
        city = self._find_city(region) or self._find_city(text)
        district = self._find_district(region)

        return ContactInfo(
            name=name,
            phone=phone,
            address=address,
            province=province,
            city=city,
            district=district,
        )

    # 需要排除的非人名词汇（标签关键词）
    EXCLUDED_NAME_WORDS = set([
        '运单号', '订单号', '快递单', '寄件人', '收件人', '电话', '地址',
        '日期', '重量', '件数', '备注', '发货', '签收', '付款',
        'Tracking', 'Waybill', 'Order', 'Phone', 'Address', 'Date',
        'Weight', 'Qty', 'From', 'To', 'Ship',
        '寄付', '到付', '月结', '预付',
    ])

    def _find_name(self, text: str) -> str:
        """查找中文姓名（2-4个汉字）或公司名"""
        # 先尝试找公司名（通常有"公司"、"有限公司"等后缀）
        m = re.search(r'([一-龥a-zA-Z]{2,30}(?:公司|有限公司|集团|工厂|企业|物流|快递))', text)
        if m:
            name = m.group(1)
            if name not in self.EXCLUDED_NAME_WORDS:
                return name

        # 尝试找带标签的个人姓名
        for label in ['姓名', '联系人', 'Name', 'Contact', '寄件人', '收件人',
                       '发货人', '收货人', '寄件方', '收件方']:
            idx = text.find(label)
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 15]
                # 移除冒号等分隔符
                after = re.sub(r'^[:\s：]+', '', after)
                # 匹配中文姓名（2-4个汉字）或英文名
                m = re.search(r'([一-龥]{2,4}|[a-zA-Z]+\s+[a-zA-Z]+)', after)
                if m:
                    name = m.group(1).strip()
                    if name not in self.EXCLUDED_NAME_WORDS and len(name) >= 2:
                        return name

        # 兜底：在文本开头（标签后的第一行）查找中文名或公司名
        # 去掉开头空白和冒号
        clean_start = re.sub(r'^[:\s：]+', '', text)
        m = re.match(r'([一-龥]{2,4}|[a-zA-Z]{2,30}(?:\s+[a-zA-Z]{2,30})?)', clean_start)
        if m:
            name = m.group(1).strip()
            if name not in self.EXCLUDED_NAME_WORDS and len(name) >= 2:
                return name

        return ""

    def _find_name_near_phone(
        self, text: str, phone_numbers: List[Tuple[str, float]], is_sender: bool
    ) -> str:
        """根据手机号位置找附近的姓名"""
        if not phone_numbers:
            return ""

        phone = phone_numbers[0][0]
        phone_idx = text.find(phone)
        if phone_idx == -1:
            return ""

        # 在手机号前30个字符内查找姓名（排除标签关键词）
        before = text[max(0, phone_idx - 40): phone_idx]
        # 优先匹配英文名+空格或中文名
        matches = list(re.finditer(r'([一-龥]{2,4}|[a-zA-Z]+\s+[a-zA-Z]+)', before))
        for m in reversed(matches):
            name = m.group(1).strip()
            if name not in self.EXCLUDED_NAME_WORDS and len(name) >= 2:
                return name

        return ""

    def _find_best_phone(
        self, region: str, all_phones: List[Tuple[str, float]]
    ) -> str:
        """在区域内找到最佳的电话号码"""
        # 先在区域内查找
        for phone, conf in all_phones:
            if phone in region:
                return phone

        # 查找座机号
        m = re.search(r'\d{3,4}[-\s]?\d{7,8}', region)
        if m:
            return m.group(0)

        # 回退到第一个号码
        return all_phones[0][0] if all_phones else ""

    def _find_address(self, text: str) -> str:
        """查找详细地址"""
        labels = ['地址', '详细地址', 'Address', 'Addr', '联系地址', '公司地址']

        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 100]
                # 去除开头的冒号/空格
                after = re.sub(r'^[:\s]+', '', after)
                # 取到换行或句号
                m = re.match(r'(.+?)(?:\.|。|\n|，|,|电话|手机|联系人)', after)
                if m:
                    return m.group(1).strip()
                # 如果没有分隔符，取前80字符
                return after[:80].strip()

        # 尝试找含省市区关键词的行
        for prov in self.PROVINCES:
            idx = text.find(prov)
            if idx != -1:
                # 取这一行
                line_start = text.rfind('\n', 0, idx)
                line_end = text.find('\n', idx)
                if line_end == -1:
                    line_end = len(text)
                line = text[line_start + 1: line_end].strip()
                if len(line) > 5:
                    return line

        return ""

    def _find_province(self, text: str) -> str:
        """查找省份"""
        for prov in sorted(self.PROVINCES, key=len, reverse=True):
            if prov in text:
                return prov
        return ""

    def _find_city(self, text: str) -> str:
        """查找城市"""
        # 四级城市：XX市
        m = re.search(r'([一-龥]{2,4}(?:市|地区|自治州|盟))', text)
        if m:
            return m.group(1)
        return ""

    def _find_district(self, text: str) -> str:
        """查找区县"""
        m = re.search(r'([一-龥]{2,6}(?:区|县|镇|街道))', text)
        if m:
            return m.group(1)
        return ""

    def _find_weight(self, text: str) -> str:
        """查找重量"""
        patterns = [
            r'(\d+\.?\d*)\s*(kg|KG|公斤|千克|KGS?)',
            r'(\d+\.?\d*)\s*(g|克|G)',
            r'重量[:\s]*(\d+\.?\d*)\s*(kg|KG|公斤)?',
            r'Weight[:\s]*(\d+\.?\d*)\s*(kg|KG|lbs?)?',
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                if m.lastindex and m.lastindex >= 2:
                    return f"{m.group(1)}{m.group(2)}"
                return m.group(1)

        return ""

    def _find_quantity(self, text: str) -> str:
        """查找件数"""
        labels = ['件数', '数量', 'Pieces', 'Qty', 'Quantity', '包装件数']
        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 10]
                m = re.search(r'\d+', after)
                if m:
                    return m.group(0)
        return ""

    def _find_shipping_method(self, text: str) -> str:
        """查找运输方式/服务类型"""
        labels = ['运输方式', '服务类型', 'Service', '产品类型', '快递类型']
        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 30]
                # 提取中文或英文词
                m = re.search(r'[一-龥a-zA-Z\s]{2,20}', after)
                if m:
                    return m.group(0).strip()
        return ""

    def _find_carrier(self, text: str) -> str:
        """查找承运商"""
        for keyword, full_name in self.CARRIER_KEYWORDS.items():
            if keyword.lower() in text.lower():
                return full_name
        return ""

    def _find_payment_method(self, text: str) -> str:
        """查找付款方式"""
        for keyword, method in self.PAYMENT_KEYWORDS.items():
            if keyword.lower() in text.lower():
                return method
        return ""

    def _find_declared_value(self, text: str) -> str:
        """查找申报价值"""
        labels = ['申报价值', '声明价值', 'Declared Value', '保价金额', '保价']
        for label in labels:
            idx = text.lower().find(label.lower())
            if idx != -1:
                after = text[idx + len(label): idx + len(label) + 20]
                m = re.search(r'[\d,.]+', after)
                if m:
                    return m.group(0)
        return ""


def parse_with_regex(pdf_text: str, filename: str = "") -> List[ShippingOrder]:
    """便捷函数：使用正则规则解析"""
    parser = RegexParser()
    return parser.parse(pdf_text, filename)
