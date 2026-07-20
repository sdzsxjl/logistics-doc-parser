# 物流单据智能解析系统

📦 基于 AI 的物流运单 PDF 智能解析系统。上传运单 PDF → 自动提取运单号、收发件人、地址、电话等关键信息 → 导出 Excel。

## 技术栈

- **前端**: Streamlit
- **AI**: DeepSeek API（兼容 OpenAI 接口）
- **PDF 解析**: pdfplumber + PyMuPDF
- **数据**: SQLite + Pandas + openpyxl

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

**本地开发**：复制并编辑 secrets 文件

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# 编辑 .streamlit/secrets.toml，填入你的 DeepSeek API Key
```

或使用传统 `.env` 文件：

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

### 3. 启动

```bash
streamlit run app.py
```

浏览器自动打开 http://localhost:8501

## 部署到 Streamlit Community Cloud（免费）

### 1. 推送代码到 GitHub

将本项目推送到一个 **公开** 或 **私有** GitHub 仓库。

### 2. 连接 Streamlit Cloud

1. 访问 [streamlit.io/cloud](https://streamlit.io/cloud)
2. 点击 "New app" → 选择你的 GitHub 仓库
3. Main file path 填 `app.py`
4. 点击 "Advanced settings" → Secrets 中填入：

```toml
DEEPSEEK_API_KEY = "sk-你的deepseek-api-key"
```

5. 点击 Deploy，等待 1-2 分钟即可上线

### 3. 分享给客户

部署完成后会得到一个 `https://xxx.streamlit.app` 的网址，客户浏览器打开即用。

## 项目结构

```
├── app.py                  # Streamlit 主界面
├── run.py                  # 桌面启动器（exe打包用）
├── requirements.txt        # Python 依赖
├── src/
│   ├── ai_parser.py        # DeepSeek AI 解析模块
│   ├── regex_parser.py     # 正则兜底解析
│   ├── pdf_extractor.py    # PDF 文本提取
│   ├── models.py           # 数据模型
│   ├── excel_exporter.py   # Excel 导出
│   ├── customer_manager.py # 多客户管理
│   ├── folder_watcher.py   # 文件夹监听
│   └── evaluator.py        # AI 效果测评
├── data/                   # 运行时数据（不提交）
├── output/                 # 导出文件（不提交）
└── sample_pdfs/            # 测试用 PDF
```

## 默认管理员密码

```
admin123
```
登录后在「系统管理」页面修改。
