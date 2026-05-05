#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_SCRIPT="$SCRIPT_DIR/scripts/install-macos.sh"

if [ ! -f "$INSTALL_SCRIPT" ]; then
  echo "未找到部署脚本：$INSTALL_SCRIPT"
  echo "请确认你是在完整解压后的 MuMuAINovel 目录中运行本文件。"
  read -r -p "按回车退出..."
  exit 1
fi

chmod +x "$INSTALL_SCRIPT" 2>/dev/null || true
"$INSTALL_SCRIPT"

echo
read -r -p "部署流程结束，按回车关闭窗口..."
