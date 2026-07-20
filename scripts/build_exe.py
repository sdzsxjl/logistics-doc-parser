"""
PyInstaller 打包脚本 - 将系统打包为单个exe文件
用法:
    python scripts/build_exe.py              # 打包为单文件exe
    python scripts/build_exe.py --onedir      # 打包为文件夹（启动更快）
    python scripts/build_exe.py --console     # 保留控制台窗口（调试用）
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


def clean_build():
    """清理旧的构建文件"""
    for d in ["build", "dist"]:
        path = PROJECT_ROOT / d
        if path.exists():
            shutil.rmtree(path)
            print(f"  🧹 清理: {d}")
    for f in PROJECT_ROOT.glob("*.spec"):
        f.unlink()
        print(f"  🧹 清理: {f.name}")


def get_hidden_imports():
    """Streamlit 需要额外声明的隐式导入"""
    return [
        # Streamlit 核心
        "streamlit", "streamlit.runtime", "streamlit.web",
        "streamlit.web.bootstrap", "streamlit.web.cli",
        "streamlit.watcher",
        # 数据处理
        "pandas", "openpyxl", "pydantic",
        # PDF 处理
        "pdfplumber", "fitz",  # PyMuPDF
        # AI
        "openai",
        # 工具
        "dotenv", "watchdog",
        # 系统
        "sqlite3", "hashlib", "json", "threading",
        # 其他可能隐式依赖
        "altair", "pyarrow", "numpy", "PIL",
        "yaml", "toml", "rich", "click",
        "git", "blinker", "cachetools",
    ]


def get_datas():
    """需要一并打包的数据文件"""
    datas = []
    src_dir = PROJECT_ROOT / "src"
    data_dir = PROJECT_ROOT / "data"

    # data 目录
    if data_dir.exists():
        datas.append((str(data_dir), "data"))

    return datas


def build(onefile=True, console=False):
    """运行 PyInstaller 打包"""
    print("=" * 60)
    print("  📦 物流单据智能解析系统 - PyInstaller 打包")
    print("=" * 60)

    mode = "单文件exe" if onefile else "文件夹"
    print(f"\n  模式: {mode}")
    print(f"  控制台: {'是' if console else '否（窗口模式）'}")

    # 构建命令
    launcher = str(PROJECT_ROOT / "run.py")
    name = "物流单据智能解析系统"
    icon = str(PROJECT_ROOT / "icon.ico") if (PROJECT_ROOT / "icon.ico").exists() else None

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", name,
        "--add-data", f"{PROJECT_ROOT / 'app.py'}{os.pathsep}.",
        "--add-data", f"{PROJECT_ROOT / 'src'}{os.pathsep}src",
    ]

    # 添加 data 目录
    data_dir = PROJECT_ROOT / "data"
    if data_dir.exists():
        cmd += ["--add-data", f"{data_dir}{os.pathsep}data"]

    # 隐式导入
    for imp in get_hidden_imports():
        cmd += ["--hidden-import", imp]

    # 模式
    if onefile:
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    if not console:
        cmd.append("--noconsole")
        cmd.append("--windowed")

    if icon:
        cmd += ["--icon", icon]

    # 排除不需要的模块减小体积
    excludes = [
        "tkinter", "unittest", "test", "pytest",
        "matplotlib", "scipy", "IPython", "jupyter",
        "notebook", "sphinx", "docutils",
    ]
    for ex in excludes:
        cmd += ["--exclude-module", ex]

    # 入口
    cmd.append(launcher)

    print(f"\n  🔨 开始打包...")
    print(f"  这可能需要 3-10 分钟，请耐心等待...\n")

    try:
        subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)
        print("\n" + "=" * 60)
        print("  ✅ 打包完成!")
        print("=" * 60)

        dist_dir = PROJECT_ROOT / "dist"
        if onefile:
            exe_path = dist_dir / f"{name}.exe"
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print(f"\n  📁 输出文件: {exe_path}")
                print(f"  📏 文件大小: {size_mb:.1f} MB")
        else:
            folder = dist_dir / name
            if folder.exists():
                total_size = sum(f.stat().st_size for f in folder.rglob("*")) / (1024 * 1024)
                print(f"\n  📁 输出目录: {folder}")
                print(f"  📏 总大小: {total_size:.1f} MB")
                print(f"  🚀 启动文件: {folder / f'{name}.exe'}")

        print("\n  💡 部署提示:")
        print("     1. 将 dist 目录中的文件复制到目标电脑")
        print("     2. 首次运行需要配置 .env 文件设置 DEEPSEEK_API_KEY")
        print("     3. 双击 exe 即可启动")
        print("     4. 系统会自动打开浏览器到解析页面")
        print()

    except subprocess.CalledProcessError as e:
        print(f"\n  ❌ 打包失败: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PyInstaller 打包工具")
    parser.add_argument("--onedir", action="store_true", help="打包为文件夹（启动更快）")
    parser.add_argument("--console", action="store_true", help="保留控制台窗口")
    parser.add_argument("--clean", action="store_true", help="清理旧的构建文件")
    args = parser.parse_args()

    if args.clean:
        clean_build()

    sys.exit(build(onefile=not args.onedir, console=args.console))
