# claude-telegram-bot

[中文文档](README.zh.md) | English

A Telegram bot that bridges messages to [Claude Code CLI](https://github.com/anthropics/claude-code), enabling you to interact with Claude Code from anywhere via Telegram.

## Features

- **Whitelist auth** — Only specified Telegram user IDs can interact with the bot
- **Session persistence** — Conversations resume across messages using `--resume` (stream-json session_id)
- **Multi-API Key management** — Configure multiple API keys with automatic failover when one fails
- **Smart key switching** — System environment variables take priority, falls back to keys.json on error
- **Stream-JSON parsing** — Properly parses Claude Code's `stream-json` output format
- **Cross-platform service management** — `manage.sh` supports both macOS (launchd) and Linux (systemd)
- **Auto-restart** — Service restarts automatically on crash; bot sends a notification on startup

## Prerequisites

- Python 3.10+
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v20+
- [Claude Code CLI](https://github.com/anthropics/claude-code) (`claude` command available)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/0xiaoyu/claude-telegram-bot.git
cd claude-telegram-bot

# 2. Install Python dependencies
pip install python-telegram-bot

# 3. Configure environment
cp .env.example .env
# Edit .env and fill in your values (see Configuration section below)

# 4. Install & start the service
./manage.sh install
```

## Configuration

Edit `.env` with the following variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `TG_BOT_TOKEN` | Telegram bot token from @BotFather | `7123456789:AAF...` |
| `TG_ALLOWED_IDS` | Comma-separated Telegram user IDs allowed to use the bot | `123456789,987654321` |
| `CLAUDE_WORK_DIR` | Working directory where Claude Code runs | `/home/user/projects` |
| `CLAUDE_BIN` | Path to the `claude` executable | `/opt/homebrew/bin/claude` |
| `ANTHROPIC_API_KEY` | (Optional) Default API key, takes priority over keys.json | `sk-ant-...` |
| `ANTHROPIC_BASE_URL` | (Optional) Custom API endpoint (proxy/relay) | `https://api.example.com` |

> **Tip:** Don't know your Telegram ID? Start the bot and send `/id` — it replies with your numeric ID.

### Multi-API Key Setup

You can manage multiple API keys using `keys.json` for automatic failover:

```bash
# Copy the example config
cp keys.json.example keys.json
# Edit keys.json with your API keys
```

**Priority order:**
1. System environment variable (`ANTHROPIC_API_KEY`) — tried first
2. Keys in `keys.json` — tried sequentially if system key fails

When a key fails (401/403/rate limit), the bot automatically switches to the next available key and clears the session.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message & help |
| `/new` | Clear context and start a fresh session |
| `/status` | Show current session ID and working directory |
| `/key` | Manage API keys (view/switch/add/remove) |
| `/restart` | Restart the bot process (launchd/systemd will auto-revive) |
| `/id` | Display your Telegram user ID |

**API Key Management:**
- `/key` — List all configured keys (masked)
- `/key use <name>` — Switch to a specific key
- `/key add <name> <api_key> [base_url]` — Add a new key
- `/key remove <name>` — Remove a key

Send any plain text message to chat with Claude Code in the configured working directory.

## manage.sh Reference

```bash
./manage.sh install    # Install service (launchd on macOS, systemd on Linux) and start
./manage.sh uninstall  # Stop and remove the service
./manage.sh start      # Start the service
./manage.sh stop       # Stop the service
./manage.sh restart    # Restart the service
./manage.sh status     # Show running status and PID
./manage.sh logs       # Tail stdout log (bot.log)
./manage.sh errors     # Tail stderr log (bot.error.log)
```

## Platform Support

| Platform | Service Manager | Config File |
|----------|----------------|-------------|
| macOS | launchd (KeepAlive) | `com.0xiaoyu.tg-claude-bot.plist` |
| Linux | systemd (user) | Auto-generated at `~/.config/systemd/user/tg-claude-bot.service` |

On macOS, the service runs as a LaunchAgent and restarts automatically after crashes. On Linux, `loginctl enable-linger` is set so the service survives user logout.

## How It Works

1. User sends a message to the Telegram bot
2. Bot looks up the user's last `session_id` from `sessions.json`
3. Runs `claude -p --output-format stream-json [--resume <session_id>] "<prompt>"` in `CLAUDE_WORK_DIR`
4. Parses the stream-json output to extract the assistant's text and new `session_id`
5. Saves the new `session_id` for continuity, then replies to the user

## Security Notes

- `.env` and `sessions.json` are excluded from git via `.gitignore`
- Only users in `TG_ALLOWED_IDS` can trigger Claude Code execution
- The bot uses `--dangerously-skip-permissions` for non-interactive use — ensure your `CLAUDE_WORK_DIR` and allowed users are trusted

## License

[MIT](LICENSE)
