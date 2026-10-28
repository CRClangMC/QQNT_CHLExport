@echo off
chcp 65001 >nul
setlocal

set "JSON_DIR=%~1"
if not defined JSON_DIR set /p "JSON_DIR=请输入包含聊天记录 JSON 的目录："
set "JSON_DIR=%JSON_DIR:"=%"

if not defined JSON_DIR (
    echo 未输入目录。
    pause
    exit /b 1
)

python "%~dp0chat_history_stats_all.py" "%JSON_DIR%"
if errorlevel 1 (
    echo.
    echo 汇总失败，请查看上方错误信息。
    pause
    exit /b 1
)

echo.
pause