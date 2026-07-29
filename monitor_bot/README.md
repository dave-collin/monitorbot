# 🐳 MonitorBot

A self-hosted Telegram bot for monitoring your home server — CPU, RAM, disk, network, Docker containers, and Tailscale.

Built with `python-telegram-bot`, `psutil`, and the Docker SDK. Runs in a container (of course).

## ✨ Features

- **`/status`** — CPU, RAM, swap, root disk, Docker summary, uptime
- **`/disk`** — All physical mount points with usage bars
- **`/containers`** — Docker containers grouped by compose project with inline restart/stop/start
- **`/net`** — Local IPs & Tailscale IP
- **`/top`** — Top 5 processes by CPU
- **`/uptime`** — How long since last reboot
- **Auto-registered commands** — no need to set them up in BotFather

## 🚀 Quick Start

```bash
git clone https://github.com/YOUR_USER/monitorbot.git
cd monitorbot

cp .env.example .env
# Edit .env → paste your BOT_TOKEN from @BotFather

docker compose up -d --build
```

## 📋 Requirements

- Docker & Docker Compose
- A [Telegram Bot Token](https://t.me/BotFather)

## 📁 Project Structure

```
monitorbot/
├── bot.py              # Telegram bot handlers
├── collector.py         # Server data collection (CPU, RAM, disk, Docker, etc.)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── LICENSE
```

## 📜 License

MIT — see [LICENSE](LICENSE)
