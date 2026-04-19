# 🎵 Discord Music Bot

A self-hosted Discord music bot built with Python that plays music from YouTube.

---

## Features

- Play music from **YouTube** (URLs or search queries)
- Queue management with a max of 10 songs
- Skip, pause, resume, stop
- Volume control
- Now playing embeds with thumbnails
- Command guide on first join

---

## Prerequisites

1. **Python 3.11+** — [python.org](https://python.org)
2. **FFmpeg** — `brew install ffmpeg` (Mac) or `sudo apt install ffmpeg` (Linux)
3. **Node.js** — `brew install node` (required for yt-dlp's JavaScript solver)
4. A **Discord Bot Token** — see setup below

---

## Setup

### 1. Clone the project

```bash
git clone https://github.com/SebastianBurke/discord-music-bot.git
cd discord-music-bot
```

### 2. Install dependencies

```bash
pip3.11 install -r requirements.txt
pip3.11 install "yt-dlp[default]"
```

### 3. Create your Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name → Create
3. Go to **Bot** in the left sidebar
4. Under **Privileged Gateway Intents**, enable:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
5. Click **Save Changes**, then **Reset Token** and copy it
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Read Message History`
7. Open the generated URL to invite the bot to your server

### 4. Configure your environment

```bash
cp .env.example .env
```

Edit `.env`:

```
DISCORD_TOKEN=your_discord_bot_token_here
BOT_PREFIX=!
```

### 5. Run the bot

```bash
python3.11 bot.py
```

You should see: `✅ Logged in as YourBot#1234`

---

## Commands

| Command | Aliases | Description |
|---|---|---|
| `!play <query>` | `!p` | Play a YouTube URL or search query |
| `!skip` | `!s` | Skip the current song |
| `!pause` | — | Pause playback |
| `!resume` | `!res` | Resume playback |
| `!stop` | — | Stop and disconnect |
| `!queue` | `!q` | Show the queue (max 10 songs) |
| `!nowplaying` | `!np` | Show the current song |
| `!remove <pos>` | — | Remove a song from the queue |
| `!volume <0-100>` | — | Set playback volume |
| `!join` | — | Join your voice channel |
| `!leave` | — | Leave the voice channel |
| `!commands` | `!h` | Show the command guide |

---

## How it works

YouTube actively blocks most bots from accessing audio streams. This bot works around that by using yt-dlp's `android_vr` client, which impersonates YouTube's Android VR app and bypasses the signature challenges that block standard requests. No cookies or browser session needed.

If the bot stops playing music, updating yt-dlp is usually the fix:

```bash
pip3.11 install -U yt-dlp
```

---

## Troubleshooting

**Bot joins but no sound**
→ Run `ffmpeg -version` to confirm FFmpeg is installed and on your PATH.

**"Requested format is not available"**
→ Run `pip3.11 install -U yt-dlp` to update yt-dlp.

**Bot is online but ignoring commands**
→ Check that **Message Content Intent** is enabled in the Discord Developer Portal under Bot → Privileged Gateway Intents.

**Bot disconnects after a while**
→ This is expected when running locally. For 24/7 uptime, host on a VPS (DigitalOcean, Railway, Fly.io).

---

## Project Structure

```
discord-music-bot/
├── bot.py           # Entry point
├── cogs/
│   └── music.py     # All music commands
├── requirements.txt
├── .env.example
└── README.md
```