"""
MonitorBot — Telegram bot for ThinkCentre server monitoring.

Commands:
  /start       — Introduction
  /status      — Server summary (CPU, RAM, disk, uptime)
  /disk        — Mount points & usage %
  /containers  — Docker container status & control
  /net         — IP & Tailscale info
  /top         — Top 5 CPU/RAM processes
  /uptime      — Server uptime

Setup:
  1. pip install -r requirements.txt
  2. cp .env.example .env  → fill BOT_TOKEN
  3. python bot.py
"""

import asyncio
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from collector import (
    cpu_percent,
    cpu_temp,
    disk_info,
    docker_containers,
    docker_group_restart,
    docker_group_start,
    docker_group_stop,
    docker_groups,
    docker_restart,
    docker_start,
    docker_stop,
    full_status,
    net_info,
    ram_info,
    swap_info,
    top_processes,
    uptime_info,
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in .env")

# ── Formatting helpers ──────────────────────────

def fmt_bar(percent: float, width: int = 10) -> str:
    filled = int(percent / 100 * width)
    empty = width - filled
    if percent > 90:
        bar = "█" * filled + "░" * empty
    elif percent > 70:
        bar = "▓" * filled + "░" * empty
    else:
        bar = "▒" * filled + "░" * empty
    return bar

# ── Command handlers ────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *MonitorBot is ready!*\n\n"
        "/status — Server summary\n"
        "/disk — Disk info\n"
        "/containers — Docker container control\n"
        "/net — IP & Tailscale\n"
        "/top — Top processes\n"
        "/uptime — Server uptime",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    data = await asyncio.to_thread(full_status)

    cpu = data["cpu"]
    ram = data["ram"]
    swap = data["swap"]
    disk = data["disk"]
    net = data["network"]
    up = data["uptime"]
    dk = data["docker"]

    # Most important disk (root)
    root_disk = next((d for d in disk if d["mount"] == "/"), disk[0] if disk else None)

    text = (
        f"🖥 *ThinkCentre Status*\n"
        f"⏱ `{datetime.now().strftime('%H:%M %d/%m/%Y')}`\n\n"
        f"*CPU:* `{cpu['percent']}%` 🌡 {cpu['temp']}  {fmt_bar(cpu['percent'])}\n"
        f"*RAM:* `{ram['percent']}%` ({ram['used_gb']}/{ram['total_gb']} GB)  {fmt_bar(ram['percent'])}\n"
        f"*Swap:* `{swap['percent']}%` ({swap['used_gb']}/{swap['total_gb']} GB)\n"
    )

    if root_disk:
        text += (
            f"*Disk (/):* `{root_disk['percent']}%` "
            f"({root_disk['used_gb']}/{root_disk['total_gb']} GB)  {fmt_bar(root_disk['percent'])}\n"
        )

    text += (
        f"\n*Docker:* 🟢{dk['running']} 🔴{dk['stopped']} out of {dk['total']} containers\n"
        f"*Uptime:* {up['uptime']}\n"
    )

    if net.get("tailscale") and net["tailscale"] != "not running":
        text += f"*Tailscale:* `{net['tailscale']}`\n"

    await msg.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_disk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    disks = await asyncio.to_thread(disk_info)

    if not disks:
        await update.message.reply_text("❌ Failed to read disk info.")
        return

    lines = ["💾 *Disk Usage*", ""]
    for d in disks:
        bar = fmt_bar(d["percent"], width=14)
        lines.append(
            f"📁 `{d['mount']}`\n"
            f"   {d['used_gb']}/{d['total_gb']} GB\n"
            f"   `{bar}` `{d['percent']}%`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_containers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = await asyncio.to_thread(docker_groups)

    if not groups:
        await update.message.reply_text("❌ Docker not accessible / no containers.")
        return

    buttons = []
    for project, containers in groups.items():
        running = sum(1 for c in containers if c["status"].startswith("🟢"))
        total = len(containers)
        icon = "🟢" if running == total else ("🔴" if running == 0 else "🟠")
        label = f"{icon} {project} ({running}/{total})"
        buttons.append([InlineKeyboardButton(label, callback_data=f"grp:{project}")])

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("🐳 *Docker Groups:*", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


# ── Callback handler (interactive menu) ──────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data.startswith("grp:"):
        # Show containers in group + group actions
        project = data.split(":", 1)[1]
        groups = await asyncio.to_thread(docker_groups)
        containers = groups.get(project, [])

        lines = [f"🐳 *{project}*", ""]
        for c in containers:
            lines.append(f"{c['status']} `{c['name']}`")

        # monitor_bot: info only, no controls
        if project == "monitor_bot":
            lines.append("\n⚠️ _Manual control via terminal_")
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data="back:list"),
            ]])
            await query.edit_message_text(
                "\n".join(lines), reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
            )
            return

        lines.append("")

        running = sum(1 for c in containers if c["status"].startswith("🟢"))
        stopped = len(containers) - running

        buttons = [
            [
                InlineKeyboardButton("🔄 Restart", callback_data=f"gdo:restart:{project}"),
            ],
        ]

        if stopped > 0:
            buttons[0].append(InlineKeyboardButton("▶️ Start", callback_data=f"gdo:start:{project}"))
        if running > 0:
            buttons[0].append(InlineKeyboardButton("⏹ Stop", callback_data=f"gdo:stop:{project}"))

        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="back:list")])
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(
            "\n".join(lines), reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )

    elif data.startswith("gdo:"):
        # Execute group action
        _, action, project = data.split(":", 2)
        funcs = {
            "restart": docker_group_restart,
            "stop": docker_group_stop,
            "start": docker_group_start,
        }
        ok, msg = await asyncio.to_thread(funcs[action], project)
        emoji = "✅" if ok else "❌"
        label = {"restart": "Restart", "stop": "Stop", "start": "Start"}[action]
        await query.edit_message_text(
            f"{emoji} *{label}* — `{project}`\n\n{msg}",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("cont:"):
        # Single container action
        name = data.split(":", 1)[1]
        buttons = [
            [
                InlineKeyboardButton("🔄 Restart", callback_data=f"do:restart:{name}"),
                InlineKeyboardButton("⏹ Stop", callback_data=f"do:stop:{name}"),
                InlineKeyboardButton("▶️ Start", callback_data=f"do:start:{name}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back:list")],
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text(
            f"🐳 *{name}* — select action:", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )

    elif data.startswith("do:"):
        _, action, name = data.split(":", 2)
        func = {"restart": docker_restart, "stop": docker_stop, "start": docker_start}[action]
        ok, msg = await asyncio.to_thread(func, name)
        emoji = "✅" if ok else "❌"
        label = {"restart": "Restart", "stop": "Stop", "start": "Start"}[action]
        await query.edit_message_text(f"{emoji} *{label}* `{name}`\n{msg}", parse_mode=ParseMode.MARKDOWN)

    elif data == "back:list":
        # Back to group list
        groups = await asyncio.to_thread(docker_groups)
        buttons = []
        for project, containers in groups.items():
            running = sum(1 for c in containers if c["status"].startswith("🟢"))
            total = len(containers)
            icon = "🟢" if running == total else ("🔴" if running == 0 else "🟠")
            label = f"{icon} {project} ({running}/{total})"
            buttons.append([InlineKeyboardButton(label, callback_data=f"grp:{project}")])
        keyboard = InlineKeyboardMarkup(buttons)
        await query.edit_message_text("🐳 *Docker Groups:*", reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def cmd_net(update: Update, context: ContextTypes.DEFAULT_TYPE):
    net = await asyncio.to_thread(net_info)

    lines = ["🌐 *Network Info*", ""]
    for iface, ip in net.items():
        if iface == "tailscale":
            continue
        lines.append(f"`{iface}` → `{ip}`")

    ts = net.get("tailscale", "not installed")
    lines.append(f"\n🔷 *Tailscale:* `{ts}`")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    procs = await asyncio.to_thread(top_processes, 5)

    lines = ["📊 *Top 5 Processes (CPU)*", ""]
    for i, p in enumerate(procs, 1):
        lines.append(
            f"{i}. `{p['name'][:20]}`  CPU:`{p['cpu_percent']:.1f}%`  RAM:`{p['memory_percent']}%`"
        )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    up = await asyncio.to_thread(uptime_info)
    await update.message.reply_text(
        f"⏱ *Server Uptime*\n\n"
        f"Online since: `{up['boot_time']}`\n"
        f"Duration: *{up['uptime']}*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Main ────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Auto-register commands with Telegram (no BotFather needed)
    async def _setup(app):
        commands = [
            BotCommand("start", "Introduction"),
            BotCommand("status", "Server summary"),
            BotCommand("disk", "Disk info"),
            BotCommand("containers", "Docker container control"),
            BotCommand("net", "IP & Tailscale"),
            BotCommand("top", "Top 5 processes"),
            BotCommand("uptime", "Server uptime"),
        ]
        await app.bot.set_my_commands(commands)

    app.post_init = _setup

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("disk", cmd_disk))
    app.add_handler(CommandHandler("containers", cmd_containers))
    app.add_handler(CommandHandler("net", cmd_net))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("uptime", cmd_uptime))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 MonitorBot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
