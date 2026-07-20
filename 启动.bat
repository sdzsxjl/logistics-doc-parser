@echo off
chcp 65001 >nul
title 物流单据智能解析系统
echo ============================================
echo   物流单据智能解析系统
echo   Powered by DeepSeek AI
echo ============================================
echo.
echo 正在启动服务...
echo 浏览器将自动打开 http://localhost:8501
echo 关闭此窗口即停止服务
echo.

cd /d "%~dp0"
python run.py
pause
