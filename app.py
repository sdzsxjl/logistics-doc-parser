"""
物流单据智能解析系统 - Streamlit Web界面
支持两种模式：手动上传 ｜ 文件夹监听（自动处理微信接收的PDF）
支持多客户管理：API Key分配 + 用量追踪 + 配额管理
"""
import streamlit as st
import pandas as pd
import os
import io
import threading
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from src.pdf_extractor import extract_text_from_pdf
from src.ai_parser import AIParser
from src.regex_parser import RegexParser
from src.models import ShippingOrder, ParseResult
from src.excel_exporter import ExcelExporter, orders_to_dataframe
from src.customer_manager import get_customer_manager, init_db

# ─── 页面配置 ───────────────────────────────────────────
# 必须是脚本中第一个 Streamlit 命令（Streamlit 1.35+ 严格要求）
st.set_page_config(
    page_title="物流单据智能解析系统",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Streamlit Cloud 适配：secrets → 环境变量 ──────────
# 本地用 .streamlit/secrets.toml，云端在 Dashboard 配置
# 注入为环境变量后，所有 os.getenv() 调用透明兼容
# 注意：直接访问 st.secrets 在无 secrets.toml 时会触发 st.error("No secrets files found")
# 因此先用 load_if_toml_exists() 静默检测，本地仅用 .env 时不会报错
if st.secrets.load_if_toml_exists():
    for _key in ["DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "MODEL_NAME",
                 "WATCH_DIR", "AUTO_EXCEL"]:
        try:
            if _key in st.secrets and _key not in os.environ:
                os.environ[_key] = st.secrets[_key]
        except Exception:
            pass  # 单个 key 缺失不影响整体

st.markdown("""
<style>
    .main-header { font-size: 2rem; font-weight: 700; color: #1F4E79; margin-bottom: 0; }
    .sub-header { color: #666; font-size: 0.9rem; margin-top: 0; }
    .stat-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; text-align: center; }
    .stat-value { font-size: 1.8rem; font-weight: 700; color: #1F4E79; }
    .stat-label { font-size: 0.8rem; color: #64748b; }
    .log-line { font-family: monospace; font-size: 0.8rem; padding: 2px 8px; border-bottom: 1px solid #f1f5f9; }
    .log-info { color: #334155; }
    .log-success { color: #16a34a; }
    .log-error { color: #dc2626; }
    .monitor-on { color: #16a34a; font-weight: 600; }
    .monitor-off { color: #94a3b8; font-weight: 600; }
    .quota-bar { height: 8px; border-radius: 4px; background: #e2e8f0; margin: 4px 0; overflow: hidden; }
    .quota-fill { height: 100%; border-radius: 4px; transition: width 0.5s; }
    .quota-ok { background: #16a34a; }
    .quota-warn { background: #f59e0b; }
    .quota-over { background: #dc2626; }
    .admin-badge { display: inline-block; background: #1F4E79; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }
</style>
""", unsafe_allow_html=True)

# ─── 初始化 ─────────────────────────────────────────────
init_db()
cm = get_customer_manager()
start_btn = False
stop_btn = False

# ─── Session State ─────────────────────────────────────
defaults = {
    "results": [], "processed": False, "uploaded_files": [],
    "watcher": None, "watcher_running": False,
    "monitor_results": [], "monitor_orders": [],
    "admin_authenticated": False,
    "current_customer_id": 0,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ─── 工具函数 ───────────────────────────────────────────
def do_parse_pdf(file_bytes: bytes, filename: str, api_key: str,
                 parse_mode: str, model_name: str) -> ParseResult:
    """解析单个PDF文件"""
    result = ParseResult(filename=filename, success=False)
    use_ai = parse_mode != "仅正则解析" and bool(api_key)

    try:
        full_text, _, _ = extract_text_from_pdf(file_bytes, filename)
        result.raw_text = full_text

        if not full_text.strip():
            result.error_message = "PDF中未检测到文字，可能是扫描件"
            return result

        if use_ai:
            try:
                parser = AIParser(api_key=api_key, model=model_name)
                orders = parser.parse(full_text, filename)
                result.extraction_method = "ai"
            except Exception:
                if parse_mode == "AI优先（推荐）":
                    orders = RegexParser().parse(full_text, filename)
                    result.extraction_method = "regex (AI回退)"
                else:
                    raise
        else:
            orders = RegexParser().parse(full_text, filename)
            result.extraction_method = "regex"

        result.orders = orders
        result.success = True
    except Exception as e:
        result.error_message = str(e)

    return result


def append_to_excel(orders: list, excel_path: str):
    """追加运单到Excel"""
    if not orders:
        return
    new_df = orders_to_dataframe(orders)
    path = Path(excel_path)
    if path.exists():
        try:
            existing = pd.read_excel(path, sheet_name="运单数据", header=3)
            combined = pd.concat([existing, new_df], ignore_index=True)
        except Exception:
            combined = new_df
    else:
        combined = new_df
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        combined.to_excel(writer, sheet_name="运单数据", index=False)
    return path


def check_admin_password(pwd: str) -> bool:
    """验证管理员密码（SHA256哈希）"""
    stored = cm.get_setting("admin_password_hash", "")
    if not stored:
        # 首次使用，设置默认密码 admin123
        default = hashlib.sha256("admin123".encode() + b"logistics_salt_2024").hexdigest()
        cm.set_setting("admin_password_hash", default)
        stored = default
    return hashlib.sha256(pwd.encode() + b"logistics_salt_2024").hexdigest() == stored

# ─── 侧边栏 ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/color/96/package--v1.png", width=48)
    st.markdown("### ⚙️ 配置")

    # 页面导航
    page = st.radio(
        "导航",
        ["📦 运单解析", "🔧 系统管理"],
        index=0,
    )

if page == "🔧 系统管理":
    # ═══════════════════════════════════════════════════════
    # 系统管理页面
    # ═══════════════════════════════════════════════════════
    st.markdown('<p class="main-header">🔧 系统管理</p>', unsafe_allow_html=True)
    st.markdown('<p class="sub-header">客户管理 | API Key分配 | 用量追踪 | 配额监控</p>',
                unsafe_allow_html=True)

    # 管理员登录
    if not st.session_state.admin_authenticated:
        st.divider()
        col_center = st.columns([1, 2, 1])
        with col_center[1]:
            st.markdown("#### 🔐 管理员登录")
            admin_pwd = st.text_input("管理员密码", type="password",
                                       placeholder="输入管理员密码",
                                       key="admin_pwd_input")
            if st.button("登录", type="primary", use_container_width=True):
                if check_admin_password(admin_pwd):
                    st.session_state.admin_authenticated = True
                    st.rerun()
                else:
                    st.error("密码错误")
            st.caption("默认密码: admin123（请登录后修改）")
        st.stop()

    # ── 管理员已登录 ──────────────────────────────────────
    with st.sidebar:
        st.divider()
        if st.button("🚪 退出管理", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.rerun()
        st.markdown('<span class="admin-badge">管理员模式</span>', unsafe_allow_html=True)

        # 修改密码
        with st.expander("🔑 修改管理员密码"):
            new_pwd = st.text_input("新密码", type="password", key="new_admin_pwd")
            if st.button("确认修改", key="change_pwd_btn"):
                if new_pwd and len(new_pwd) >= 6:
                    h = hashlib.sha256(new_pwd.encode() + b"logistics_salt_2024").hexdigest()
                    cm.set_setting("admin_password_hash", h)
                    st.success("✅ 密码已修改")
                else:
                    st.warning("密码至少6位")

    # ── 统计卡片 ──────────────────────────────────────────
    customers = cm.get_all()
    active_customers = [c for c in customers if c["is_active"]]
    inactive_customers = [c for c in customers if not c["is_active"]]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{len(customers)}</div>'
                    f'<div class="stat-label">客户总数</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="stat-card"><div class="stat-value">{len(active_customers)}</div>'
                    f'<div class="stat-label">启用中</div></div>', unsafe_allow_html=True)
    with c3:
        # 统计本月总用量
        total_orders_month = 0
        for c in active_customers:
            usage = cm.get_usage(c["id"], days=30)
            total_orders_month += usage.get("total_orders", 0)
        st.markdown(f'<div class="stat-card"><div class="stat-value">{total_orders_month}</div>'
                    f'<div class="stat-label">近30天解析运单</div></div>', unsafe_allow_html=True)
    with c4:
        # 总API费用
        total_cost = 0
        for c in active_customers:
            usage = cm.get_usage(c["id"], days=30)
            total_cost += usage.get("total_cost", 0)
        st.markdown(f'<div class="stat-card"><div class="stat-value">¥{total_cost:.2f}</div>'
                    f'<div class="stat-label">近30天API费用</div></div>', unsafe_allow_html=True)

    st.divider()

    # ── 两个Tab：客户列表 | 添加客户 ──────────────────────
    tab_list, tab_add = st.tabs(["📋 客户列表", "➕ 添加客户"])

    with tab_add:
        st.markdown("#### 新建客户")
        col_a, col_b = st.columns(2)
        with col_a:
            new_name = st.text_input("登录名（英文/拼音）*", placeholder="zhangsan_logistics",
                                     key="new_name", help="唯一标识，用于客户选择")
            new_display = st.text_input("显示名称*", placeholder="张三物流",
                                        key="new_display")
            new_company = st.text_input("公司名称", placeholder="XX物流有限公司",
                                        key="new_company")
        with col_b:
            new_api_key = st.text_input("DeepSeek API Key",
                                        placeholder="sk-...（留空则使用您的Key）",
                                        key="new_api_key")
            new_model = st.selectbox("AI模型", ["deepseek-chat", "deepseek-reasoner"],
                                     key="new_model")
            new_quota = st.number_input("月配额（运单数）", min_value=100, max_value=100000,
                                        value=5000, step=500, key="new_quota")
        col_a2, col_b2 = st.columns(2)
        with col_a2:
            new_phone = st.text_input("联系电话", placeholder="选填", key="new_phone")
        with col_b2:
            new_email = st.text_input("联系邮箱", placeholder="选填", key="new_email")
        new_notes = st.text_area("备注", placeholder="内部备注...", key="new_notes")
        new_expires = st.text_input("过期日期", placeholder="YYYY-MM-DD，留空=永久有效",
                                    key="new_expires")

        if st.button("✅ 添加客户", type="primary", use_container_width=True):
            if not new_name or not new_display:
                st.error("登录名和显示名称为必填")
            elif not cm.verify_name(new_name):
                st.error(f"登录名 '{new_name}' 已存在")
            else:
                cid = cm.add(
                    name=new_name, display_name=new_display, company=new_company,
                    api_key=new_api_key, model=new_model, monthly_quota=new_quota,
                    contact_phone=new_phone, contact_email=new_email,
                    notes=new_notes, expires_at=new_expires,
                )
                if cid:
                    st.success(f"✅ 客户 '{new_display}' 添加成功 (ID: {cid})")
                    st.rerun()
                else:
                    st.error("添加失败")

    with tab_list:
        if not customers:
            st.info("暂无客户，请在「添加客户」中创建第一个")
        else:
            for customer in customers:
                is_active = customer["is_active"]
                usage = cm.get_usage(customer["id"], days=30)
                quota = customer["monthly_quota"] or 5000
                used = usage.get("monthly_used", 0)
                pct = min(used / max(quota, 1) * 100, 100)

                # 配额颜色
                if pct < 60:
                    bar_class = "quota-ok"
                    status_icon = "🟢"
                elif pct < 90:
                    bar_class = "quota-warn"
                    status_icon = "🟡"
                else:
                    bar_class = "quota-over"
                    status_icon = "🔴"

                expander_title = (
                    f"{status_icon if is_active else '⚫'} "
                    f"{customer['display_name']} "
                    f"({'禁用' if not is_active else '启用'}) | "
                    f"月用量: {used}/{quota} ({pct:.0f}%) | "
                    f"30天费用: ¥{usage.get('total_cost', 0):.2f}"
                )

                with st.expander(expander_title, expanded=False):
                    col_info, col_actions = st.columns([3, 1])

                    with col_info:
                        st.markdown(f"**公司**: {customer['company'] or '—'}")
                        st.markdown(f"**API Key**: {customer['api_key_masked'] or '未配置'}")
                        st.markdown(f"**模型**: {customer['model']}")
                        st.markdown(f"**电话**: {customer['contact_phone'] or '—'} | "
                                    f"**邮箱**: {customer['contact_email'] or '—'}")
                        st.markdown(f"**创建时间**: {customer['created_at']} | "
                                    f"**过期**: {customer['expires_at'] or '永久'}")
                        if customer['notes']:
                            st.caption(f"备注: {customer['notes']}")

                        # 配额进度条
                        st.markdown(
                            f'<div class="quota-bar"><div class="quota-fill {bar_class}" '
                            f'style="width:{pct}%"></div></div>',
                            unsafe_allow_html=True,
                        )
                        st.caption(f"本月用量: {used}/{quota} 单")

                        # 近期用量
                        daily_data = usage.get("daily", [])[:7]
                        if daily_data:
                            daily_df = pd.DataFrame(daily_data)
                            daily_df.columns = ["日期", "请求数", "运单数", "费用(元)"]
                            st.dataframe(daily_df, hide_index=True, use_container_width=True)

                    with col_actions:
                        customer_key = f"cust_{customer['id']}"

                        # 切换启用/禁用
                        btn_label = "⏸️ 禁用" if is_active else "▶️ 启用"
                        if st.button(btn_label, key=f"toggle_{customer_key}",
                                     use_container_width=True):
                            cm.toggle_active(customer["id"])
                            st.rerun()

                        # 编辑操作（tabs 可嵌套在 expander 内，popover/expander 会被拦截）
                        tab_key, tab_quota, tab_del = st.tabs(
                            ["🔑 Key", "📊 配额", "🗑️ 删除"]
                        )
                        with tab_key:
                            edit_key = st.text_input(
                                "新API Key", type="password",
                                placeholder="sk-...",
                                key=f"edit_key_{customer_key}"
                            )
                            if st.button("保存Key", key=f"save_key_{customer_key}"):
                                cm.update(customer["id"], api_key=edit_key)
                                st.success("已更新")
                                st.rerun()

                        with tab_quota:
                            edit_quota = st.number_input(
                                "月配额", value=customer["monthly_quota"],
                                min_value=100, step=500,
                                key=f"edit_quota_{customer_key}"
                            )
                            if st.button("保存配额", key=f"save_quota_{customer_key}"):
                                cm.update(customer["id"], monthly_quota=edit_quota)
                                st.success("已更新")
                                st.rerun()

                        with tab_del:
                            if customer["name"] != "admin":
                                st.warning("⚠️ 删除后不可恢复")
                                if st.button("确认删除", key=f"del_{customer_key}",
                                             use_container_width=True, type="secondary"):
                                    cm.delete(customer["id"])
                                    st.rerun()
                            else:
                                st.caption("内置管理员账号不可删除")

    st.stop()  # 管理页面不显示下面的解析UI

# ═══════════════════════════════════════════════════════════
# 运单解析页面
# ═══════════════════════════════════════════════════════════
with st.sidebar:
    st.divider()

    # ── 客户选择（多租户模式） ─────────────────────────
    active_customers = cm.get_all(active_only=True)
    customer_options = {"无（全局模式）": 0}
    for c in active_customers:
        label = f"{c['display_name']} ({c['api_key_masked'] or '无Key'})"
        customer_options[label] = c["id"]

    selected_customer_label = st.selectbox(
        "当前客户",
        list(customer_options.keys()),
        help="选择客户后将使用该客户的API Key并记录用量\n（单用户部署时保持'全局模式'）",
    )
    current_customer_id = customer_options[selected_customer_label]

    # 从客户记录获取API Key
    if current_customer_id > 0:
        cust = cm.get_by_id(current_customer_id)
        api_key = cust.get("api_key", "") if cust else ""
        default_model = cust.get("model", "deepseek-chat") if cust else "deepseek-chat"
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        default_model = "deepseek-chat"

    st.divider()

    # ── 工作模式 ───────────────────────────────────────
    work_mode = st.radio(
        "工作模式",
        ["📤 手动上传", "👁️ 文件夹监听"],
        index=0,
        help="手动上传：打开网页上传PDF解析\n文件夹监听：自动检测文件夹中的新PDF",
    )

    # ── API Key 输入（覆盖客户Key） ────────────────────
    api_key_override = st.text_input(
        "DeepSeek API Key (覆盖)",
        type="password",
        value=api_key,
        placeholder="sk-...（留空用正则模式）",
    )
    actual_api_key = api_key_override or api_key

    # ── 解析模式 ───────────────────────────────────────
    parse_mode = st.radio(
        "解析模式",
        ["AI优先（推荐）", "仅AI解析", "仅正则解析"],
        index=0,
    )

    if parse_mode != "仅正则解析":
        # 找默认模型的索引
        model_options = ["deepseek-chat", "deepseek-reasoner"]
        try:
            model_idx = model_options.index(default_model)
        except ValueError:
            model_idx = 0
        model_name = st.selectbox(
            "AI模型",
            model_options,
            index=model_idx,
            help="deepseek-chat: 性价比最高 | deepseek-reasoner: 推理更强",
        )
    else:
        model_name = "deepseek-chat"

    st.divider()

    # ── 文件夹监听配置 ─────────────────────────────────
    if work_mode == "👁️ 文件夹监听":
        st.markdown("### 📁 监听设置")

        watch_dir = st.text_input(
            "监听文件夹路径",
            value=os.getenv("WATCH_DIR", str(Path.home() / "Documents" / "WeChat Files")),
            placeholder="D:\\运单待处理",
            help="设置微信文件自动下载目录",
        )

        auto_excel = st.text_input(
            "自动导出Excel路径",
            value=os.getenv("AUTO_EXCEL", str(Path("output/运单汇总.xlsx").resolve())),
            placeholder="output/运单汇总.xlsx",
        )

        col_start, col_stop = st.columns(2)
        with col_start:
            start_btn = st.button("▶️ 启动监听", type="primary",
                                  use_container_width=True,
                                  disabled=st.session_state.watcher_running)
        with col_stop:
            stop_btn = st.button("⏹️ 停止监听", use_container_width=True,
                                 disabled=not st.session_state.watcher_running)

        if st.session_state.watcher_running:
            st.markdown('<span class="monitor-on">🟢 监听运行中</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="monitor-off">⚫ 监听未启动</span>', unsafe_allow_html=True)

    # ── 客户用量提示 ───────────────────────────────────
    if current_customer_id > 0:
        usage_info = cm.get_usage(current_customer_id, days=30)
        quota = usage_info.get("monthly_quota", 5000)
        used = usage_info.get("monthly_used", 0)
        pct = min(used / max(quota, 1) * 100, 100)
        st.caption(
            f"📊 {usage_info.get('customer_name', '')} 本月用量: "
            f"{used}/{quota} ({pct:.0f}%) | "
            f"30天费用: ¥{usage_info.get('total_cost', 0):.4f}"
        )

    # ── 使用说明 ───────────────────────────────────────
    with st.expander("💡 使用说明"):
        st.markdown("""
        **手动上传模式**
        1. 上传PDF文件（支持批量）
        2. 点击"开始解析"
        3. 查看结果 → 下载Excel

        **文件夹监听模式**
        1. 设置微信自动下载目录
        2. 启动监听
        3. 微信收到PDF → 自动解析 → 自动写Excel
        4. 完全无需手动操作！

        > 微信设置：设置 → 文件管理 → 开启自动下载
        """)

    if not actual_api_key and parse_mode != "仅正则解析":
        st.warning("⚠️ 未配置API Key，将自动使用正则解析模式")

# ─── 主页面：运单解析 ─────────────────────────────────
st.markdown('<p class="main-header">📦 物流单据智能解析系统</p>', unsafe_allow_html=True)
if work_mode == "👁️ 文件夹监听":
    st.markdown('<p class="sub-header">自动检测文件夹中的新PDF，解析后自动写入Excel — '
                '配合微信自动下载实现全自动化</p>', unsafe_allow_html=True)
else:
    st.markdown('<p class="sub-header">上传PDF运单，AI自动提取单号、收发地址等关键信息，'
                '一键导出Excel</p>', unsafe_allow_html=True)

st.divider()

# ═══════════════════════════════════════════════════════════
# 模式一：手动上传
# ═══════════════════════════════════════════════════════════
if work_mode == "📤 手动上传":
    st.markdown("### 📁 上传PDF文件")
    uploaded_files = st.file_uploader(
        "支持拖拽上传，可一次性上传多个PDF文件（单个不超过50MB）",
        type=["pdf"], accept_multiple_files=True, key="pdf_uploader",
    )

    col1, col2, col3 = st.columns([2, 1, 2])
    with col1:
        process_btn = st.button("🚀 开始解析", type="primary",
                                use_container_width=True, disabled=not uploaded_files)

    st.divider()

    if process_btn and uploaded_files:
        st.session_state.results = []
        st.session_state.processed = False

        progress_bar = st.progress(0)
        status_text = st.empty()
        total = len(uploaded_files)
        st.session_state.uploaded_files = [f.name for f in uploaded_files]

        for i, f in enumerate(uploaded_files):
            status_text.text(f"正在处理: {f.name} ({i+1}/{total})")
            progress_bar.progress((i + 1) / total)
            result = do_parse_pdf(f.read(), f.name, actual_api_key, parse_mode, model_name)
            st.session_state.results.append(result)

            # 记录用量
            if current_customer_id > 0 and result.success:
                cm.log_usage(
                    customer_id=current_customer_id,
                    pdf_filename=f.name,
                    order_count=len(result.orders),
                    parse_method=result.extraction_method,
                    success=result.success,
                )

        progress_bar.progress(100)
        status_text.text(f"✅ 解析完成！共处理 {total} 个文件")
        st.session_state.processed = True

# ═══════════════════════════════════════════════════════════
# 模式二：文件夹监听
# ═══════════════════════════════════════════════════════════
else:
    if start_btn and not st.session_state.watcher_running:
        watch_path = Path(watch_dir)
        if not watch_path.exists():
            st.error(f"文件夹不存在: {watch_dir}")
        else:
            from src.folder_watcher import FolderWatcher

            def on_new_pdf(filepath: str):
                try:
                    with open(filepath, "rb") as fh:
                        fb = fh.read()
                    filename = os.path.basename(filepath)
                    result = do_parse_pdf(fb, filename, actual_api_key, parse_mode, model_name)

                    with threading.Lock():
                        st.session_state.monitor_results.append(result)
                        for order in result.orders:
                            st.session_state.monitor_orders.append(order)
                        if result.success and result.orders:
                            excel_path = auto_excel or "output/运单汇总.xlsx"
                            append_to_excel(result.orders, excel_path)

                    # 记录用量
                    if current_customer_id > 0 and result.success:
                        cm.log_usage(
                            customer_id=current_customer_id,
                            pdf_filename=filename,
                            order_count=len(result.orders),
                            parse_method=result.extraction_method,
                            success=result.success,
                        )

                    return {
                        "success": result.success,
                        "order_count": len(result.orders),
                        "method": result.extraction_method,
                        "error": result.error_message if not result.success else None,
                    }
                except Exception as e:
                    return {"success": False, "order_count": 0, "method": "", "error": str(e)}

            watcher = FolderWatcher(
                watch_folder=str(watch_path),
                on_new_file=on_new_pdf,
                output_excel=auto_excel or "output/运单汇总.xlsx",
            )
            watcher.start(scan_existing=True)
            st.session_state.watcher = watcher
            st.session_state.watcher_running = True
            st.rerun()

    if stop_btn and st.session_state.watcher_running:
        if st.session_state.watcher:
            st.session_state.watcher.stop()
        st.session_state.watcher_running = False
        st.rerun()

    # 监听状态面板
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        processed_count = len(st.session_state.monitor_results)
        st.markdown(f'<div class="stat-card"><div class="stat-value">{processed_count}</div>'
                    f'<div class="stat-label">本次已处理文件</div></div>', unsafe_allow_html=True)
    with c2:
        total_orders = len(st.session_state.monitor_orders)
        st.markdown(f'<div class="stat-card"><div class="stat-value">{total_orders}</div>'
                    f'<div class="stat-label">累计提取运单</div></div>', unsafe_allow_html=True)
    with c3:
        success_count = sum(1 for r in st.session_state.monitor_results if r.success)
        st.markdown(f'<div class="stat-card"><div class="stat-value">{success_count}</div>'
                    f'<div class="stat-label">成功解析</div></div>', unsafe_allow_html=True)
    with c4:
        status_text = "🟢 运行中" if st.session_state.watcher_running else "⚫ 已停止"
        st.markdown(f'<div class="stat-card"><div class="stat-value">{status_text}</div>'
                    f'<div class="stat-label">监听状态</div></div>', unsafe_allow_html=True)

    st.divider()

    # 日志
    st.markdown("### 📜 处理日志")
    if st.session_state.watcher and st.session_state.watcher.event_log:
        log_container = st.container(height=200)
        with log_container:
            for entry in reversed(st.session_state.watcher.event_log[-50:]):
                cls = f"log-{entry['level']}"
                st.markdown(
                    f'<div class="log-line {cls}">[{entry["time"]}] {entry["message"]}</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.info("启动监听后，处理日志将显示在这里")

    # 已处理运单表格
    if st.session_state.monitor_orders:
        st.divider()
        st.markdown(f"### 📋 已提取运单 ({len(st.session_state.monitor_orders)}条)")
        df = orders_to_dataframe(st.session_state.monitor_orders)
        st.data_editor(df, use_container_width=True, hide_index=True, num_rows="fixed",
                       column_config={
                           "运单号": st.column_config.TextColumn("运单号", width="medium"),
                           "寄件人姓名": st.column_config.TextColumn("寄件人", width="small"),
                           "寄件人电话": st.column_config.TextColumn("寄件电话", width="small"),
                           "寄件人地址": st.column_config.TextColumn("寄件地址", width="large"),
                           "收件人姓名": st.column_config.TextColumn("收件人", width="small"),
                           "收件人电话": st.column_config.TextColumn("收件电话", width="small"),
                           "收件人地址": st.column_config.TextColumn("收件地址", width="large"),
                           "置信度": st.column_config.ProgressColumn(
                               "置信度", min_value=0, max_value=1, format="%.0f%%", width="small"),
                       }, key="monitor_editor")
        st.caption("💡 新文件到达后自动追加。可在单元格中直接编辑修正。")

        col_d1, col_d2, col_d3 = st.columns([1, 1, 2])
        with col_d1:
            exporter = ExcelExporter()
            st.download_button(
                "📥 下载全部Excel", exporter.export(st.session_state.monitor_orders),
                f"运单汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_d2:
            csv_data = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("📥 下载CSV", csv_data,
                               f"运单汇总_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                               "text/csv", use_container_width=True)
        with col_d3:
            if st.button("🗑️ 清空记录", use_container_width=True):
                st.session_state.monitor_results = []
                st.session_state.monitor_orders = []
                st.rerun()
    else:
        if not st.session_state.watcher_running:
            st.markdown("""
            <div style="text-align:center; padding:60px 20px; color:#94a3b8;">
                <div style="font-size:4rem;">👁️</div>
                <div style="font-size:1.2rem; margin-top:16px;">设置监听文件夹，点击"启动监听"</div>
            </div>
            """, unsafe_allow_html=True)

    if st.session_state.watcher_running:
        st.divider()
        st.caption(f"🔄 每5秒自动刷新 | 监听: {watch_dir} | 导出: {auto_excel}")
        st.markdown("""
        <script>
            if (!window._autoRefreshSet) {
                window._autoRefreshSet = true;
                setTimeout(function() { window.location.reload(); }, 5000);
            }
        </script>
        """, unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════
# 手动上传结果展示
# ═══════════════════════════════════════════════════════════
if work_mode == "📤 手动上传" and st.session_state.processed and st.session_state.results:
    results = st.session_state.results

    st.markdown("### 📊 解析概况")
    success_count = sum(1 for r in results if r.success)
    total_orders = sum(len(r.orders) for r in results if r.success)
    ai_count = sum(1 for r in results if r.success and r.extraction_method.startswith("ai"))

    c1, c2, c3, c4 = st.columns(4)
    for val, label in [
        (len(results), "处理文件数"), (total_orders, "提取运单数"),
        (f"{success_count}/{len(results)}", "成功/失败"), (ai_count, "AI解析数"),
    ]:
        col = [c1, c2, c3, c4][[len(results), total_orders,
                                 f"{success_count}/{len(results)}", ai_count].index(val)]
        st.markdown(f'<div class="stat-card"><div class="stat-value">{val}</div>'
                    f'<div class="stat-label">{label}</div></div>', unsafe_allow_html=True)

    st.divider()

    failures = [r for r in results if not r.success]
    if failures:
        with st.expander(f"⚠️ {len(failures)} 个文件解析失败", expanded=True):
            for f in failures:
                st.error(f"**{f.filename}**: {f.error_message}")

    all_orders = []
    for r in results:
        if r.success:
            all_orders.extend(r.orders)

    if all_orders:
        st.markdown("### 📋 解析结果（点击单元格可编辑）")
        df = orders_to_dataframe(all_orders)
        st.data_editor(df, use_container_width=True, hide_index=True, num_rows="fixed",
                       column_config={
                           "运单号": st.column_config.TextColumn("运单号", width="medium"),
                           "寄件人姓名": st.column_config.TextColumn("寄件人", width="small"),
                           "寄件人电话": st.column_config.TextColumn("寄件电话", width="small"),
                           "寄件人地址": st.column_config.TextColumn("寄件地址", width="large"),
                           "收件人姓名": st.column_config.TextColumn("收件人", width="small"),
                           "收件人电话": st.column_config.TextColumn("收件电话", width="small"),
                           "收件人地址": st.column_config.TextColumn("收件地址", width="large"),
                           "置信度": st.column_config.ProgressColumn(
                               "置信度", min_value=0, max_value=1, format="%.0f%%", width="small"),
                       }, key="result_editor")
        st.caption("💡 如果发现提取有误，可以直接在表格中修改，修改后的数据会包含在下载的Excel中")

        st.divider()
        st.markdown("### 📥 导出结果")
        col_d1, col_d2, col_d3 = st.columns([1, 1, 2])
        with col_d1:
            exporter = ExcelExporter()
            st.download_button("📥 下载Excel", exporter.export(all_orders),
                               f"物流信息_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
        with col_d2:
            st.download_button("📥 下载CSV", df.to_csv(index=False).encode("utf-8-sig"),
                               f"物流信息_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                               "text/csv", use_container_width=True)
        with col_d3:
            if st.button("🔄 重新上传", use_container_width=True):
                st.session_state.results = []
                st.session_state.processed = False
                st.rerun()
    else:
        st.warning("未能提取到有效运单信息。请检查PDF是否为文字版（非扫描件）")

    st.divider()
    st.markdown("### 🔍 各文件详情")
    for i, result in enumerate(results):
        icon = "✅" if result.success else "❌"
        badge = "🤖 AI" if result.extraction_method.startswith("ai") else "📐 正则"
        with st.expander(f"{icon} {result.filename} - {badge} - {result.order_count}个运单"
                         + (f" - ⚠️{result.error_message}" if not result.success else "")):
            if result.raw_text:
                st.text_area("原始文本", result.raw_text[:3000], height=200, disabled=True,
                             key=f"raw_{i}")
            if result.error_message:
                st.error(f"错误: {result.error_message}")

# ─── 页脚 ─────────────────────────────────────────────
st.divider()
st.caption("物流单据智能解析系统 | Powered by DeepSeek AI | 多客户管理 + 用量追踪 | 数据仅在本地处理")
