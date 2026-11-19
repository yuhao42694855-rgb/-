@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 守护模式：每 60 秒扫一次 queue 目录，Ctrl+C 退出
:loop
python scripts\build.py
timeout /t 60 /nobreak >nul
goto loop
