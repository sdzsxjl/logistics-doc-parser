@echo off
chcp 65001 >nul
echo ============================================
echo   物流单据智能解析系统 - 一键打包
echo ============================================
echo.
echo 正在安装打包依赖...
pip install pyinstaller -q
echo.
echo 开始打包（单文件模式，约需3-10分钟）...
python scripts/build_exe.py
echo.
echo 打包完成！exe文件在 dist 目录中
pause
