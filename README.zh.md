# claude-telegram-bot

通过 Telegram 与 [Claude Code CLI](https://github.com/anthropics/claude-code) 交互的桥接 Bot。随时随地用手机发消息，让服务器上的 Claude Code 帮你干活。

## 功能特性

- **白名单鉴权** — 仅允许指定 Telegram 用户 ID 操作
- **会话持久化** — 通过 `--resume` + `stream-json` 的 `session_id` 实现跨消息上下文连续
- **流式 JSON 解析** — 正确解析 Claude Code 的 `stream-json` 输出格式
- **跨平台服务管理** — `manage.sh` 同时支持 macOS（launchd）和 Linux（systemd）
- **自动重启** — 崩溃后服务自动恢复，重启后 Bot 主动推送通知

## 环境要求

- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20+
- [Claude Code CLI](https://github.com/anthropics/claude-code)（`claude` 命令可用）
- 从 [@BotFather](https://t.me/BotFather) 获取的 Telegram Bot Token

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/xss4755/claude-telegram-bot.git
cd claude-telegram-bot

# 2. 安装 Python 依赖
pip install python-telegram-bot

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入真实值（见下方配置说明）

# 4. 安装并启动服务
./manage.sh install
```

## 配置说明

编辑 `.env` 文件，填写以下变量：

| 变量 | 说明 | 示例 |
|------|------|------|
| `TG_BOT_TOKEN` | 从 @BotFather 获取的 Bot Token | `7123456789:AAF...` |
| `TG_ALLOWED_IDS` | 允许使用 Bot 的 Telegram 用户 ID，逗号分隔 | `123456789,987654321` |
| `CLAUDE_WORK_DIR` | Claude Code 的工作目录（执行命令的根目录） | `/home/user/projects` |
| `CLAUDE_BIN` | `claude` 可执行文件的完整路径（`which claude`） | `/opt/homebrew/bin/claude` |

> **提示：** 不知道自己的 Telegram ID？启动 Bot 后发送 `/id`，Bot 会回复你的数字 ID。

## Bot 命令

| 命令 | 说明 |
|------|------|
| `/start` | 欢迎信息与帮助 |
| `/new` | 清除上下文，开启全新会话 |
| `/status` | 查看当前 session ID 和工作目录 |
| `/restart` | 重启 Bot 进程（launchd/systemd 会自动拉起） |
| `/id` | 查看你的 Telegram 用户 ID |

直接发送普通文本消息即可与 Claude Code 在配置的工作目录中对话。

## manage.sh 命令速查

```bash
./manage.sh install    # 安装服务（macOS: launchd / Linux: systemd）并启动
./manage.sh uninstall  # 停止并卸载服务
./manage.sh start      # 启动服务
./manage.sh stop       # 停止服务
./manage.sh restart    # 重启服务
./manage.sh status     # 查看运行状态和 PID
./manage.sh logs       # 实时查看 stdout 日志（bot.log）
./manage.sh errors     # 实时查看 stderr 日志（bot.error.log）
```

## 平台支持

| 平台 | 服务管理器 | 配置文件 |
|------|-----------|---------|
| macOS | launchd（KeepAlive） | `com.0xiaoyu.tg-claude-bot.plist` |
| Linux | systemd（user） | 自动生成到 `~/.config/systemd/user/tg-claude-bot.service` |

macOS 下以 LaunchAgent 运行，崩溃后自动重启。Linux 下执行 `loginctl enable-linger`，用户退出登录后服务仍持续运行。

## 工作原理

1. 用户向 Telegram Bot 发送消息
2. Bot 从 `sessions.json` 中查找该用户上次的 `session_id`
3. 在 `CLAUDE_WORK_DIR` 下执行：`claude -p --output-format stream-json [--resume <session_id>] "<prompt>"`
4. 解析 stream-json 输出，提取 assistant 文本和新的 `session_id`
5. 将新 `session_id` 写回文件以保持上下文，然后回复用户

## 安全说明

- `.env`（含 Token 和用户 ID）及 `sessions.json` 均已通过 `.gitignore` 排除在版本控制之外
- 只有 `TG_ALLOWED_IDS` 中列出的用户才能触发 Claude Code 执行
- Bot 使用 `--dangerously-skip-permissions` 以支持非交互式运行，请确保 `CLAUDE_WORK_DIR` 和授权用户均可信

## License

[MIT](LICENSE)
