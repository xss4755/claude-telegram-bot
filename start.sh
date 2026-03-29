#!/bin/bash
# 启动脚本 — 自动加载 .env

# 加载 nvm 环境
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ 找不到 .env 文件，请先复制 .env.example 并填写配置"
    echo "   cp $SCRIPT_DIR/.env.example $ENV_FILE"
    exit 1
fi

# 加载 .env（跳过注释和空行）
export $(grep -v '^#' "$ENV_FILE" | grep -v '^$' | xargs)

echo "🚀 启动 Claude Code Bot..."
echo "   工作目录: $CLAUDE_WORK_DIR"
echo "   允许用户: $TG_ALLOWED_IDS"

"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/bot.py"
