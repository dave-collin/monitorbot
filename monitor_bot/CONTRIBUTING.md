# Contributing to MonitorBot

Thanks for wanting to help! Here's how to get started.

## 🧩 What You Can Contribute

- **Bug reports** — found something broken? [Open an issue](https://github.com/Rahmat/monitorbot/issues)
- **Feature requests** — ideas for new commands or sensors
- **Code** — pick an issue and send a PR
- **Docs** — fix typos, improve README, translate
- **New collectors** — add support for Proxmox, ZFS, UPS, whatever your setup uses

---

## 🚀 Development Setup

```bash
# Fork & clone your fork
git clone https://github.com/YOUR_USER/monitorbot.git
cd monitorbot

# Create .env
cp .env.example .env
# Edit .env → paste your BOT_TOKEN

# Run with Docker
docker compose up -d --build
```

---

## 🔄 Pull Request Workflow

### 1. Branch off `main`
```bash
git checkout -b feature/add-gpu-monitor
```
Never commit directly to `main`.

### 2. Keep it focused
One PR = one thing. Don't fix a bug and add a feature in the same PR — split them.

### 3. Follow the existing style
- English for code, comments, and commit messages
- Type hints where it makes sense
- Keep `collector.py` pure (data only, no bot logic)
- Keep `bot.py` handlers clean (parse → format → reply)

### 4. Test locally
```bash
docker compose up -d --build
# Chat your bot and test the affected commands
```

### 5. Commit with [conventional commits](https://www.conventionalcommits.org/)
```
feat: add GPU temperature collector
fix: handle missing Tailscale interface
docs: update README with new commands
chore: bump python-telegram-bot to 22.0
```

### 6. Push & open PR
```bash
git push origin feature/add-gpu-monitor
```
Go to your fork on GitHub → **Pull requests** → **New pull request**

---

## ✅ PR Checklist

- [ ] Code works? (tested with Docker)
- [ ] New dependencies added to `requirements.txt`?
- [ ] No debug prints or leftover comments?
- [ ] Commits are clean? (squash if messy)

---

## 🐛 Reporting Bugs

Open an issue and include:
1. What you did
2. What you expected
3. What happened instead
4. Bot logs: `docker compose logs --tail 50`
5. Your setup: OS, Docker version, which commands have issues

---

## 💬 Questions?

Just open a [discussion](https://github.com/Rahmat/monitorbot/discussions) — no question is too basic. This project started as someone learning Python too 🙂
