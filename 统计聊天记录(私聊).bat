@echo off
chcp 65001 >nul
setlocal

set "JSON_PATH=%~1"
if not defined JSON_PATH set /p "JSON_PATH=请输入聊天记录 JSON 文件路径："
set "JSON_PATH=%JSON_PATH:"=%"

if not defined JSON_PATH (
    echo 未输入 JSON 文件路径。
    pause
    exit /b 1
)

python "%~dp0chat_history_stats.py" "%JSON_PATH%"
if errorlevel 1 (
    echo.
    echo 统计失败，请查看上方错误信息。
    pause
    exit /b 1
)

echo.
pause