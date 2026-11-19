@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   书单视频生成
echo   直接双击 = 处理 queue 里的任务
echo   拖拽 json 到本文件 = 只处理这一条
echo ============================================
echo.
if "%~1"=="" (
  python scripts\build.py
) else (
  python scripts\build.py %*
)
echo.
pause
