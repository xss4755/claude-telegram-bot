#!/usr/bin/env bash
# tg-claude Bot 服务管理脚本（跨平台：macOS launchd / Linux systemd）
# 用法: ./manage.sh [install|uninstall|start|stop|restart|status|logs|errors]

set -euo pipefail

# ── 检测操作系统 ──────────────────────────────────────────────
OS=$(uname -s)   # Darwin = macOS, Linux = Linux

# ── 共享变量 ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.0xiaoyu.tg-claude-bot"
LOG_FILE="${SCRIPT_DIR}/bot.log"
ERR_FILE="${SCRIPT_DIR}/bot.error.log"

# ── OS 分支变量 ────────────────────────────────────────────────
if [ "$OS" = "Darwin" ]; then
  PLIST_SRC="${SCRIPT_DIR}/${LABEL}.plist"
  PLIST_DST="$HOME/Library/LaunchAgents/${LABEL}.plist"
  UID_VAL="$(id -u)"
  SERVICE="gui/${UID_VAL}/${LABEL}"
elif [ "$OS" = "Linux" ]; then
  SYSTEMD_SERVICE="tg-claude-bot"
  SERVICE_DST="${HOME}/.config/systemd/user/${SYSTEMD_SERVICE}.service"
else
  echo "不支持的操作系统: $OS"
  exit 1
fi

# ── 颜色 ──────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

cmd="${1:-}"

case "$cmd" in

  install)
    if [ "$OS" = "Darwin" ]; then
      echo -e "${CYAN}>>> 安装服务到 launchd...${NC}"
      if [ ! -f "$PLIST_SRC" ]; then
        echo -e "${RED}错误: plist 文件不存在: $PLIST_SRC${NC}"
        exit 1
      fi
      sed "s|/path/to/tg-claude|${SCRIPT_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"
      echo "已生成 plist → $PLIST_DST"

      # 若已加载先卸载
      if launchctl print "$SERVICE" &>/dev/null 2>&1; then
        launchctl bootout "gui/${UID_VAL}" "$PLIST_DST" 2>/dev/null || true
        sleep 1
      fi

      launchctl bootstrap "gui/${UID_VAL}" "$PLIST_DST"
      echo -e "${GREEN}✅ 服务已安装并启动${NC}"
      sleep 2
      "$0" status

    else  # Linux
      echo -e "${CYAN}>>> 安装服务到 systemd (user)...${NC}"
      mkdir -p "$(dirname "$SERVICE_DST")"

      # 动态生成 service 文件
      cat > "$SERVICE_DST" <<EOF
[Unit]
Description=Telegram Claude Code Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${SCRIPT_DIR}
ExecStart=/bin/bash ${SCRIPT_DIR}/start.sh
Restart=always
RestartSec=5
StandardOutput=append:${SCRIPT_DIR}/bot.log
StandardError=append:${SCRIPT_DIR}/bot.error.log

[Install]
WantedBy=default.target
EOF
      echo "已写入 service 文件 → $SERVICE_DST"

      systemctl --user daemon-reload
      systemctl --user enable "$SYSTEMD_SERVICE"
      systemctl --user start "$SYSTEMD_SERVICE"

      # 让服务在用户未登录时也能运行（服务器必须）
      loginctl enable-linger "$USER" 2>/dev/null \
        || echo -e "${YELLOW}提示: loginctl enable-linger 失败，可手动执行: sudo loginctl enable-linger $USER${NC}" \
        || true

      echo -e "${GREEN}✅ 服务已安装并启动${NC}"
      sleep 2
      "$0" status
    fi
    ;;

  uninstall)
    if [ "$OS" = "Darwin" ]; then
      echo -e "${CYAN}>>> 卸载服务...${NC}"
      if launchctl print "$SERVICE" &>/dev/null 2>&1; then
        launchctl bootout "gui/${UID_VAL}" "$PLIST_DST" 2>/dev/null || true
        echo "已从 launchd 注销"
      else
        echo "服务未注册，跳过注销"
      fi
      if [ -f "$PLIST_DST" ]; then
        rm "$PLIST_DST"
        echo "已删除 $PLIST_DST"
      fi

    else  # Linux
      echo -e "${CYAN}>>> 卸载服务...${NC}"
      systemctl --user stop "$SYSTEMD_SERVICE" 2>/dev/null || true
      systemctl --user disable "$SYSTEMD_SERVICE" 2>/dev/null || true
      if [ -f "$SERVICE_DST" ]; then
        rm "$SERVICE_DST"
        echo "已删除 $SERVICE_DST"
      fi
      systemctl --user daemon-reload
    fi
    echo -e "${GREEN}✅ 卸载完成${NC}"
    ;;

  start)
    echo -e "${CYAN}>>> 启动服务...${NC}"
    if [ "$OS" = "Darwin" ]; then
      launchctl kickstart -k "$SERVICE"
    else
      [ ! -f "$SERVICE_DST" ] && echo -e "${RED}服务未安装，请先运行 install${NC}" && exit 1
      systemctl --user start "$SYSTEMD_SERVICE"
    fi
    sleep 1
    "$0" status
    ;;

  stop)
    echo -e "${CYAN}>>> 停止服务...${NC}"
    if [ "$OS" = "Darwin" ]; then
      launchctl kill SIGTERM "$SERVICE" 2>/dev/null || true
      echo -e "${YELLOW}注意: KeepAlive=true，launchd 会在几秒后自动重启。如需彻底停止请用 uninstall。${NC}"
      sleep 2
      "$0" status
    else
      [ ! -f "$SERVICE_DST" ] && echo -e "${RED}服务未安装，请先运行 install${NC}" && exit 1
      systemctl --user stop "$SYSTEMD_SERVICE"
      echo -e "${GREEN}✅ 服务已停止（可用 start 重启）${NC}"
    fi
    ;;

  restart)
    echo -e "${CYAN}>>> 重启服务...${NC}"
    if [ "$OS" = "Darwin" ]; then
      launchctl kickstart -k "$SERVICE"
    else
      [ ! -f "$SERVICE_DST" ] && echo -e "${RED}服务未安装，请先运行 install${NC}" && exit 1
      systemctl --user restart "$SYSTEMD_SERVICE"
    fi
    sleep 2
    "$0" status
    ;;

  status)
    if [ "$OS" = "Darwin" ]; then
      echo -e "${CYAN}>>> 服务状态：${LABEL}${NC}"
      if ! launchctl print "$SERVICE" &>/dev/null 2>&1; then
        echo -e "${RED}● 未注册（服务未安装）${NC}"
        echo "  运行 ./manage.sh install 安装服务"
        exit 0
      fi

      info="$(launchctl print "$SERVICE" 2>&1)"
      pid="$(echo "$info" | grep -E '^\s+pid\s*=' | awk -F'=' '{print $2}' | tr -d ' ' || true)"
      last_exit="$(echo "$info" | grep -E 'last exit code' | awk -F'=' '{print $2}' | tr -d ' ' || true)"
      state="$(echo "$info" | grep -E 'state\s*=' | awk -F'=' '{print $2}' | tr -d ' ' || true)"

      if [ -n "$pid" ] && [ "$pid" != "0" ]; then
        echo -e "${GREEN}● 运行中${NC}  PID=$pid  state=${state:-running}"
      else
        echo -e "${RED}● 已停止${NC}  last_exit=${last_exit:--}  state=${state:-stopped}"
      fi

      echo ""
      echo "  plist:  $PLIST_DST"
      echo "  日志:   $LOG_FILE"
      echo "  错误:   $ERR_FILE"

    else  # Linux
      echo -e "${CYAN}>>> 服务状态：${SYSTEMD_SERVICE}${NC}"
      if [ ! -f "$SERVICE_DST" ]; then
        echo -e "${RED}● 未安装（服务文件不存在）${NC}"
        echo "  运行 ./manage.sh install 安装服务"
        exit 0
      fi

      # 提取 PID（MainPID）
      pid="$(systemctl --user show "$SYSTEMD_SERVICE" --property=MainPID 2>/dev/null | cut -d= -f2 || true)"
      active="$(systemctl --user is-active "$SYSTEMD_SERVICE" 2>/dev/null || true)"

      if [ "$active" = "active" ] && [ -n "$pid" ] && [ "$pid" != "0" ]; then
        echo -e "${GREEN}● 运行中${NC}  PID=$pid"
      else
        echo -e "${RED}● 已停止${NC}  状态=${active:-unknown}"
      fi

      echo ""
      echo "  service: $SERVICE_DST"
      echo "  日志:    $LOG_FILE"
      echo "  错误:    $ERR_FILE"
    fi
    ;;

  logs)
    echo -e "${CYAN}>>> 实时日志 (Ctrl+C 退出)${NC}"
    touch "$LOG_FILE"
    tail -f "$LOG_FILE"
    ;;

  errors)
    echo -e "${CYAN}>>> 实时错误日志 (Ctrl+C 退出)${NC}"
    touch "$ERR_FILE"
    tail -f "$ERR_FILE"
    ;;

  *)
    echo "用法: $0 {install|uninstall|start|stop|restart|status|logs|errors}"
    echo ""
    if [ "$OS" = "Darwin" ]; then
      echo "  install    安装 plist 到 launchd 并启动（首次使用）"
      echo "  stop       停止服务（KeepAlive 会自动重启，彻底停止用 uninstall）"
    else
      echo "  install    生成 systemd service 文件并启动（首次使用）"
      echo "  stop       停止服务"
    fi
    echo "  uninstall  停止并卸载服务"
    echo "  start      启动服务"
    echo "  restart    重启服务"
    echo "  status     查看运行状态"
    echo "  logs       实时查看 stdout 日志"
    echo "  errors     实时查看 stderr 日志"
    exit 1
    ;;
esac
