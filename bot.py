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


async def run_claude(prompt: str, session_id: str | None = None) -> tuple[str, str | None]:
    """
    异步调用 claude -p --output-format stream-json，返回 (响应文本, 新session_id)。
    session_id 不为空时用 --resume 继续上次会话。
    """
    cmd = [
        CLAUDE_BIN, "-p",
        "--output-format", "stream-json",
        "--dangerously-skip-permissions",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    cmd.append(prompt)

    logger.info("执行: %s (session=%s, cwd=%s)", " ".join(cmd[:4]) + " ...", session_id, WORK_DIR)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORK_DIR,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        logger.error("claude 退出码 %d: %s", proc.returncode, err)
        return f"❌ 执行出错（退出码 {proc.returncode}）:\n{err or '无错误信息'}", None

    # 解析 stream-json：每行一个 JSON 对象
    text_parts = []
    new_session_id = None
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # 提取 assistant 消息中的文本内容
            if obj.get("type") == "assistant":
                for block in obj.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
            # 从 result 行提取 session_id
            if obj.get("type") == "result":
                new_session_id = obj.get("session_id")
        except json.JSONDecodeError:
            pass  # 忽略非 JSON 行

    response_text = "".join(text_parts).strip() or "（无输出）"
    return response_text, new_session_id


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


# ── 消息处理 ──────────────────────────────────────────────────────────────────
@restricted
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = update.message.text.strip()
    if not prompt:
        return

    # 发送"处理中"提示
    thinking = await update.message.reply_text("⏳ 正在处理，请稍候...")

    uid = update.effective_user.id
    session_id = get_session(uid)  # 从文件获取上次会话 ID

    try:
        result, new_session_id = await run_claude(prompt, session_id)
    except Exception as e:
        logger.exception("run_claude 异常")
        await thinking.edit_text(f"❌ 内部错误：{e}")
        return

    # 保存新 session_id，供下次消息续会话
    if new_session_id:
        save_session(uid, new_session_id)

    # 删除"处理中"消息
    await thinking.delete()

    # 分块发送结果
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
    app.add_handler(CommandHandler("restart", cmd_restart))

    # 普通文本消息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # 启动后：设置命令菜单 + 向所有授权用户发启动通知
    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start",   "欢迎 & 帮助"),
            BotCommand("new",     "开启新会话"),
            BotCommand("status",  "查看会话状态"),
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
