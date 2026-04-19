# 🎵 Discord Music Bot

A self-hosted Discord music bot built with Python that supports YouTube and Spotify.

---

## Features

- Play music from **YouTube** (URLs or search queries)
- Play tracks, playlists, and albums from **Spotify** (resolved to YouTube audio)
- Queue management (add, remove, view)
- Loop current song or entire queue
- Pause, resume, skip, stop
- Volume control
- Embeds with song info and thumbnails

---

## Prerequisites

Before running the bot you need:

1. **Python 3.11+** — [python.org](https://python.org)
2. **FFmpeg** installed and on your PATH
   - macOS: `brew install ffmpeg`
   - Ubuntu/Debian: `sudo apt install ffmpeg`
   - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
3. A **Discord Bot Token** — see setup below
4. A **Spotify App** — see setup below

---

## Setup

Note: YouTube actively blocks bot access to audio streams. This bot works around that by configuring yt-dlp to impersonate YouTube's Android VR app (android_vr client), which bypasses the JavaScript signature challenges that block most bots. No extra setup needed.
If the bot stops playing music, run pip3.11 install -U yt-dlp — yt-dlp updates frequently to keep up with YouTube's changes, and keeping it up to date is the first fix to try if anything breaks.

### 1. Clone / download this project

```bash
cd discord-music-bot
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Create your Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** → give it a name
3. Go to **Bot** → click **Add Bot**
4. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent**
   - **Server Members Intent**
5. Copy your **Bot Token**
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Read Message History`
7. Open the generated URL in your browser to invite the bot to your server

### 4. Create your Spotify App

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard)
2. Click **Create app**
3. Copy your **Client ID** and **Client Secret**

### 5. Configure your environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your tokens:

```
DISCORD_TOKEN=your_discord_bot_token
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
BOT_PREFIX=!
```

### 6. Run the bot

```bash
python bot.py
```

You should see: `✅ Logged in as YourBot#1234`

---

## Commands

| Command | Aliases | Description |
|---|---|---|
| `!play <query>` | `!p` | Play a song (YouTube URL, Spotify URL, or search term) |
| `!skip` | `!s` | Skip the current song |
| `!pause` | — | Pause playback |
| `!resume` | `!res` | Resume paused playback |
| `!stop` | — | Stop and clear the queue |
| `!queue` | `!q` | Show the current queue |
| `!nowplaying` | `!np` | Show what's currently playing |
| `!remove <pos>` | — | Remove song at position from queue |
| `!volume <0-100>` | — | Set playback volume |
| `!loop` | — | Toggle looping the current song |
| `!loopqueue` | `!lq` | Toggle looping the entire queue |
| `!join` | — | Join your voice channel |
| `!leave` | — | Leave the voice channel |

### Example usage

```
!play never gonna give you up
!play https://www.youtube.com/watch?v=dQw4w9WgXcQ
!play https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT
!play https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
```

---

## Project Structure

```
discord-music-bot/
├── bot.py              # Entry point
├── cogs/
│   └── music.py        # All music commands
├── requirements.txt
├── .env.example
└── README.md
```

---

## Troubleshooting

**Bot joins but no sound plays**
→ Make sure FFmpeg is installed and accessible from your terminal (`ffmpeg -version`)

**"Sign in to confirm you're not a bot" error from YouTube**
→ yt-dlp may need cookies. Run `yt-dlp --cookies-from-browser chrome <url>` once to cache auth, or use a VPN.

**Spotify links not working**
→ Double-check your `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env`. The bot never streams from Spotify directly — it searches YouTube for matching audio.

**Bot disconnects after a while**
→ This is normal for free hosting. For 24/7 uptime, host on a VPS (e.g. DigitalOcean, Railway, Fly.io).
