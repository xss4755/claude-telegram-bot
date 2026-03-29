#!/usr/bin/env python3
"""
Telegram Bot → Claude Code 控制器
仅允许指定用户 ID 操作，在 duihua 目录下执行 claude -p
支持 stream-json 模式解析 session_id，实现跨消息上下文连续性
"""

import os
import signal
import json
import asyncio
import logging
from pathlib import Path
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ── 配置 ──────────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.getenv("TG_BOT_TOKEN", "")
ALLOWED_IDS = set(int(x) for x in os.getenv("TG_ALLOWED_IDS", "").split(",") if x.strip())
WORK_DIR    = os.getenv("CLAUDE_WORK_DIR", "")
CLAUDE_BIN  = os.getenv("CLAUDE_BIN", "/opt/homebrew/bin/claude")
MAX_MSG_LEN = 4000  # Telegram 单条消息上限 4096，留余量

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Session 持久化 ────────────────────────────────────────────────────────────
SESSIONS_FILE = Path(__file__).parent / "sessions.json"

# ── API Key 管理 ──────────────────────────────────────────────────────────────
KEYS_FILE = Path(__file__).parent / "keys.json"


class KeyManager:
    """管理多个 API Key 配置"""

    def __init__(self):
        self.data = self._load()

    def _load(self) -> dict:
        if KEYS_FILE.exists():
            try:
                return json.loads(KEYS_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                return {"current": None, "keys": []}
        return {"current": None, "keys": []}

    def _save(self):
        KEYS_FILE.write_text(json.dumps(self.data, indent=2, ensure_ascii=False))

    def get_current(self) -> dict | None:
        """返回当前激活的 key 配置"""
        name = self.data.get("current")
        if not name:
            return None
        for k in self.data["keys"]:
            if k["name"] == name and k.get("enabled", True):
                return k
        return None

    def rotate(self) -> dict | None:
        """切换到下一个 enabled key"""
        keys = [k for k in self.data["keys"] if k.get("enabled", True)]
        if not keys:
            return None
        current = self.data.get("current")
        idx = next((i for i, k in enumerate(keys) if k["name"] == current), -1)
        next_idx = (idx + 1) % len(keys)
        self.data["current"] = keys[next_idx]["name"]
        self._save()
        return keys[next_idx]

    def switch(self, name: str) -> bool:
        """切换到指定 name 的 key"""
        for k in self.data["keys"]:
            if k["name"] == name and k.get("enabled", True):
                self.data["current"] = name
                self._save()
                return True
        return False

    def add(self, name: str, api_key: str, base_url: str = "") -> bool:
        """添加新 key"""
        if any(k["name"] == name for k in self.data["keys"]):
            return False
        self.data["keys"].append({
            "name": name,
            "api_key": api_key,
            "base_url": base_url,
            "enabled": True
        })
        if not self.data.get("current"):
            self.data["current"] = name
        self._save()
        return True

    def remove(self, name: str) -> bool:
        """删除 key"""
        self.data["keys"] = [k for k in self.data["keys"] if k["name"] != name]
        if self.data.get("current") == name:
            self.data["current"] = self.data["keys"][0]["name"] if self.data["keys"] else None
        self._save()
        return True

    def list_keys(self) -> list[dict]:
        """返回所有 key 列表（api_key 脱敏）"""
        result = []
        for k in self.data["keys"]:
            key = k["api_key"]
            masked = f"{key[:7]}***{key[-4:]}" if len(key) > 11 else "***"
            result.append({
                "name": k["name"],
                "api_key": masked,
                "base_url": k.get("base_url", ""),
                "enabled": k.get("enabled", True),
                "is_current": k["name"] == self.data.get("current")
            })
        return result


key_manager = KeyManager()


def load_sessions() -> dict:
    """从文件加载 user_id → session_id 映射"""
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_session(user_id: int, session_id: str):
    """保存用户的 session_id"""
    data = load_sessions()
    data[str(user_id)] = session_id
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))
    logger.info("保存 session: user=%d, session_id=%s", user_id, session_id)


def get_session(user_id: int) -> str | None:
    """获取用户上次的 session_id"""
    return load_sessions().get(str(user_id))


def clear_session(user_id: int):
    """清除用户的 session_id"""
    data = load_sessions()
    data.pop(str(user_id), None)
    SESSIONS_FILE.write_text(json.dumps(data, indent=2))
    logger.info("清除 session: user=%d", user_id)


# ── 权限检查装饰器 ────────────────────────────────────────────────────────────
def restricted(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ALLOWED_IDS:
            logger.warning("拒绝未授权用户: %s", uid)
            await update.message.reply_text("⛔ 无权限。请联系管理员添加你的 ID。")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


# ── 工具函数 ──────────────────────────────────────────────────────────────────
def split_text(text: str) -> list[str]:
    """将长文本按 MAX_MSG_LEN 分块"""
    return [text[i:i+MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]


def detect_key_error(stderr: str, returncode: int) -> bool:
    """检测是否为 API Key 相关错误"""
    if returncode == 0:
        return False
    err_lower = stderr.lower()
    keywords = ["401", "403", "invalid_api_key", "authentication", "rate_limit", "quota"]
    return any(kw in err_lower for kw in keywords)


async def run_claude(prompt: str, session_id: str | None = None, key_config: dict | None = None) -> tuple[str, str | None, bool]:
    """
    异步调用 claude -p --output-format stream-json，返回 (响应文本, 新session_id, 是否key错误)。
    key_config: {"name": ..., "api_key": ..., "base_url": ...}
    """
    cmd = [
        CLAUDE_BIN, "-p",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)

    env = os.environ.copy()
    if key_config:
        if key_config.get("api_key"):
            env["ANTHROPIC_API_KEY"] = key_config["api_key"]
        if key_config.get("base_url"):
            env["ANTHROPIC_BASE_URL"] = key_config["base_url"]

    logger.info("执行: %s (session=%s, key=%s, cwd=%s)",
                " ".join(cmd[:4]) + " ...", session_id,
                key_config.get("name") if key_config else "default", WORK_DIR)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORK_DIR,
        env=env,
    )
    stdout, stderr = await proc.communicate()

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    is_key_error = detect_key_error(stderr_text, proc.returncode)

    if proc.returncode != 0:
        logger.error("claude 退出码 %d: %s", proc.returncode, stderr_text)
        return f"❌ 执行出错（退出码 {proc.returncode}）:\n{stderr_text or '无错误信息'}", None, is_key_error

    # 解析 stream-json：每行一个 JSON 对象
    text_parts = []
    new_session_id = None
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("type") == "assistant":
                for block in obj.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
            if obj.get("type") == "result":
                new_session_id = obj.get("session_id")
        except json.JSONDecodeError:
            pass

    response_text = "".join(text_parts).strip() or "（无输出）"
    return response_text, new_session_id, False


# ── 命令处理 ──────────────────────────────────────────────────────────────────
@restricted
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (
        f"👋 你好！我是 Claude Code Bot\n"
        f"你的 Telegram ID：`{uid}`\n\n"
        f"📁 工作目录：`{WORK_DIR}`\n\n"
        f"**命令说明：**\n"
        f"/new — 开启新会话（清除上下文）\n"
        f"/id — 查看你的 Telegram ID\n"
        f"/status — 查看当前会话状态\n\n"
        f"直接发送消息即可与 Claude Code 对话 🚀"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"你的 Telegram ID：`{uid}`", parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_new(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """清除会话上下文，开启全新对话"""
    clear_session(update.effective_user.id)
    await update.message.reply_text("✅ 已开启新会话，上下文已清除。")


@restricted
async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """优雅退出，让 launchd KeepAlive 自动重启"""
    await update.message.reply_text("🔄 正在重启 Bot，稍后会收到启动通知...")
    os.kill(os.getpid(), signal.SIGTERM)


@restricted
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sid = get_session(update.effective_user.id)
    if sid:
        msg = f"📌 当前会话 ID：`{sid}`\n工作目录：`{WORK_DIR}`"
    else:
        msg = f"📌 无持续会话（下一条消息将创建新会话）\n工作目录：`{WORK_DIR}`"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


@restricted
async def cmd_key(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """管理 API Key"""
    args = ctx.args or []

    if not args:
        # 显示当前 key 和列表
        current = key_manager.get_current()
        keys = key_manager.list_keys()

        if not keys:
            await update.message.reply_text("📋 未配置任何 API Key\n\n使用 `/key add <name> <api_key> [base_url]` 添加", parse_mode=ParseMode.MARKDOWN)
            return

        msg = f"🔑 当前使用：`{current['name'] if current else '无'}`\n\n**所有 Key：**\n"
        for k in keys:
            status = "✅" if k["is_current"] else ("🟢" if k["enabled"] else "⚫")
            url_info = f" | {k['base_url']}" if k["base_url"] else ""
            msg += f"{status} `{k['name']}` - `{k['api_key']}`{url_info}\n"

        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    subcmd = args[0]

    if subcmd == "use" and len(args) >= 2:
        name = args[1]
        if key_manager.switch(name):
            await update.message.reply_text(f"✅ 已切换到 Key: `{name}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ Key `{name}` 不存在或未启用", parse_mode=ParseMode.MARKDOWN)

    elif subcmd == "add" and len(args) >= 3:
        name, api_key = args[1], args[2]
        base_url = args[3] if len(args) >= 4 else ""
        if key_manager.add(name, api_key, base_url):
            await update.message.reply_text(f"✅ 已添加 Key: `{name}`\n⚠️ 建议删除此消息以保护密钥", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ Key `{name}` 已存在", parse_mode=ParseMode.MARKDOWN)

    elif subcmd == "remove" and len(args) >= 2:
        name = args[1]
        key_manager.remove(name)
        await update.message.reply_text(f"✅ 已删除 Key: `{name}`", parse_mode=ParseMode.MARKDOWN)

    else:
        await update.message.reply_text(
            "**用法：**\n"
            "`/key` - 查看所有 Key\n"
            "`/key use <name>` - 切换 Key\n"
            "`/key add <name> <api_key> [base_url]` - 添加 Key\n"
            "`/key remove <name>` - 删除 Key",
            parse_mode=ParseMode.MARKDOWN
        )


# ── 消息处理 ──────────────────────────────────────────────────────────────────
@restricted
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()
    if not prompt:
        return

    thinking = await update.message.reply_text("⏳ 正在处理，请稍候...")
    uid = update.effective_user.id
    session_id = get_session(uid)

    # 构建重试队列：系统环境变量优先，然后是 keys.json
    retry_queue = []
    if os.getenv("ANTHROPIC_API_KEY"):
        retry_queue.append({"name": "系统环境", "api_key": None, "base_url": None})

    enabled_keys = [k for k in key_manager.data["keys"] if k.get("enabled", True)]
    retry_queue.extend(enabled_keys)

    if not retry_queue:
        await thinking.edit_text("❌ 未配置 API Key\n请设置环境变量或使用 /key add 添加")
        return

    result, new_session_id, is_key_error = None, None, False

    for attempt, key_config in enumerate(retry_queue):
        try:
            result, new_session_id, is_key_error = await run_claude(prompt, session_id, key_config)
        except Exception as e:
            logger.exception("run_claude 异常")
            await thinking.edit_text(f"❌ 内部错误：{e}")
            return

        if not is_key_error:
            break

        # Key 错误，尝试下一个
        if attempt < len(retry_queue) - 1:
            next_key = retry_queue[attempt + 1]
            key_name = key_config.get("name", "未知")
            next_name = next_key.get("name", "未知")
            await thinking.edit_text(f"⚠️ Key [{key_name}] 出错，切换到 [{next_name}]...")
            clear_session(uid)
            session_id = None
            await asyncio.sleep(1)

    if new_session_id:
        save_session(uid, new_session_id)

    await thinking.delete()
    for chunk in split_text(result):
        await update.message.reply_text(chunk)


# ── 主入口 ────────────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        raise ValueError("TG_BOT_TOKEN 未设置，请在 .env 中配置")
    if not ALLOWED_IDS:
        raise ValueError("TG_ALLOWED_IDS 未设置，请填入你的 Telegram ID")

    logger.info("启动 Bot，允许用户: %s", ALLOWED_IDS)
    logger.info("工作目录: %s", WORK_DIR)

    app = Application.builder().token(BOT_TOKEN).build()

    # 注册命令
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("id",      cmd_id))
    app.add_handler(CommandHandler("new",     cmd_new))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("key",     cmd_key))
    app.add_handler(CommandHandler("restart", cmd_restart))

    # 普通文本消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 启动后：设置命令菜单 + 向所有授权用户发启动通知
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start",   "欢迎 & 帮助"),
            BotCommand("new",     "开启新会话"),
            BotCommand("status",  "查看会话状态"),
            BotCommand("key",     "管理 API Key"),
            BotCommand("restart", "重启 Bot"),
            BotCommand("id",      "查看我的 Telegram ID"),
        ])
        for uid in ALLOWED_IDS:
            try:
                await application.bot.send_message(uid, "🟢 Bot 已启动/重启")
            except Exception:
                pass  # 用户可能从未开启过 bot，忽略
    app.post_init = post_init

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
