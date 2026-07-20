"""
物流单据智能解析系统 - 桌面启动器
双击运行 → 自动启动服务 + 打开浏览器
兼容 exe 打包和源码运行两种模式
"""
import sys
import os
import time
import threading
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).parent.resolve()
APP_PORT = 8501


def open_browser():
    """等待服务启动后打开浏览器"""
    time.sleep(2)
    webbrowser.open(f"http://localhost:{APP_PORT}")


def is_frozen():
    """判断是否在 PyInstaller 打包环境中运行"""
    return getattr(sys, "frozen", False)


def main():
    # 确保工作目录正确
    if is_frozen():
        # exe 打包模式：工作目录设为 exe 所在目录
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(str(APP_DIR))

    if str(APP_DIR) not in sys.path:
        sys.path.insert(0, str(APP_DIR))

    print("=" * 60)
    print("  物流单据智能解析系统 v1.0")
    print("  Powered by DeepSeek AI")
    print("=" * 60)
    print()
    print(f"  服务启动中... 浏览器将自动打开 http://localhost:{APP_PORT}")
    print("  关闭此窗口即停止服务")
    print()

    # 延迟打开浏览器（等 Streamlit 启动完成）
    threading.Thread(target=open_browser, daemon=True).start()

    # ─── 核心：不通过 subprocess，直接在同一进程中启动 Streamlit ───
    # 这样可以避免 exe 打包后无限循环启动自己的问题
    from streamlit.web import cli as stcli

    app_path = APP_DIR / "app.py"
    if not app_path.exists():
        # exe 打包后 app.py 可能在临时解压目录
        app_path = Path(os.path.dirname(__file__)) / "app.py"

    sys.argv = [
        "streamlit", "run", str(app_path),
        "--server.port", str(APP_PORT),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false",
    ]

    sys.exit(stcli.main())


if __name__ == "__main__":
    main()
