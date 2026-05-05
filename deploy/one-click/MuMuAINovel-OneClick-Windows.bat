@echo off
chcp 65001 >nul
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS_SCRIPT=%SCRIPT_DIR%scripts\install-windows.ps1"

if not exist "%PS_SCRIPT%" (
  echo 未找到部署脚本：%PS_SCRIPT%
  echo 请确认你是在完整解压后的 MuMuAINovel 目录中运行本文件。
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%"

echo.
echo 部署窗口即将关闭。如需查看日志，请重新双击本文件或在当前目录运行 docker compose logs -f。
pause
