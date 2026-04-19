# 🎵 The Chosen One — Discord Music Bot

A self-hosted Discord music bot built with Python. Plays music from YouTube and Spotify, with a full queue system, audio filters, slash commands, lyrics, and more.

---

## Features

- **YouTube** playback — URLs, search queries, and full playlists
- **Spotify** support — single tracks, albums, and playlists (resolved via YouTube search)
- **Queue management** — up to 50 songs, shuffle, move, jump, clear
- **Loop modes** — loop current song or the entire queue
- **Audio filters** — bass boost, nightcore, normalize (applied via FFmpeg)
- **Vote to skip** — majority vote required; admins can force skip
- **DJ role** — restrict destructive commands to a configurable role
- **Auto-disconnect** — leaves after configurable inactivity, with optional 24/7 mode
- **Progress bar** — live playback position in `!nowplaying` and `!queue`
- **Lyrics** — fetched from lyrics.ovh, paginated for long songs
- **History** — track and replay the last 20 songs
- **Slash commands** — all major commands available as `/play`, `/skip`, etc.
- **Now Playing embeds** — thumbnails, duration, requester, active filter/loop indicators

---

## Prerequisites

1. **Python 3.11+** — [python.org](https://python.org)
2. **FFmpeg** — `brew install ffmpeg` (Mac) or `sudo apt install ffmpeg` (Linux)
3. **Node.js** — `brew install node` (required by yt-dlp's JS solver)
4. A **Discord Bot Token** — see setup below

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/SebastianBurke/discord-music-bot.git
cd discord-music-bot
```

### 2. Install dependencies

```bash
pip3.11 install -r requirements.txt
```

### 3. Create your Discord Bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. **New Application** → name it → Create
3. Go to **Bot** in the sidebar
4. Under **Privileged Gateway Intents**, enable:
   - ✅ Message Content Intent
   - ✅ Server Members Intent
5. **Reset Token** and copy it
6. Go to **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Connect`, `Speak`, `Send Messages`, `Embed Links`, `Read Message History`
7. Open the generated URL to invite the bot to your server

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — at minimum set your token:

```env
DISCORD_TOKEN=your_discord_bot_token_here
BOT_PREFIX=!
MAX_QUEUE=50
AUTO_DISCONNECT_MINUTES=5
DJ_ROLE_NAME=DJ
```

For Spotify support, also add:

```env
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
```

Create a Spotify app at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard).

### 5. Run the bot

```bash
python3.11 bot.py
```

You should see:
```
✅ Logged in as YourBot#1234
🔗 Synced N slash command(s).
```

---

## Commands

### Playback

| Command | Aliases | Description |
|---|---|---|
| `!play <query/URL>` | `!p` | Play from YouTube, YouTube playlist, or Spotify |
| `!search <query>` | — | Pick from top 5 YouTube results |
| `!skip` | `!s` | Skip the current song (starts a vote if enabled) |
| `!forceskip` | `!fs` | Force skip — DJ/admin only |
| `!voteskip` | `!vs` | Vote to skip (majority required) |
| `!pause` | — | Pause playback |
| `!resume` | `!res` | Resume playback |
| `!stop` | — | Stop, clear queue, and disconnect — DJ/admin only |
| `!volume <0–100>` | — | Set volume (persists across songs) |
| `!previous` | `!prev` | Replay the previous song |
| `!loop` | — | Toggle repeating the current song |
| `!loopqueue` | `!lq` | Toggle looping the entire queue |

### Queue

| Command | Aliases | Description |
|---|---|---|
| `!queue` | `!q` | Show queue with live progress bar |
| `!nowplaying` | `!np` | Current song with progress bar and details |
| `!shuffle` | — | Randomly reorder the queue |
| `!clear` | — | Clear the queue without stopping — DJ/admin only |
| `!move <from> <to>` | — | Reorder a song by position |
| `!jump <pos>` | — | Skip directly to a position in the queue |
| `!remove <pos>` | — | Remove a song from the queue |
| `!history` | — | Show the last 20 played songs |

### Filters & Extras

| Command | Description |
|---|---|
| `!filter bassboost` | Apply bass boost EQ |
| `!filter nightcore` | Speed up and pitch up (1.25×) |
| `!filter normalize` | Normalize volume levels |
| `!filter off` | Remove current filter |
| `!lyrics [song]` | Fetch lyrics (defaults to current song) |
| `!stay` | Toggle 24/7 mode — bot never auto-disconnects |

### Connection

| Command | Description |
|---|---|
| `!join` | Join your voice channel |
| `!leave` | Leave the voice channel |
| `!commands` / `!h` | Show the command guide |

> All major commands are also available as Discord slash commands (`/play`, `/skip`, etc.)

---

## Configuration

All settings live in `.env`:

| Variable | Default | Description |
|---|---|---|
| `DISCORD_TOKEN` | — | Your bot token (required) |
| `BOT_PREFIX` | `!` | Command prefix |
| `MAX_QUEUE` | `50` | Max songs in queue |
| `AUTO_DISCONNECT_MINUTES` | `5` | Inactivity timeout before leaving |
| `DJ_ROLE_NAME` | `DJ` | Role name for DJ-only commands |
| `SPOTIFY_CLIENT_ID` | — | Spotify app client ID (optional) |
| `SPOTIFY_CLIENT_SECRET` | — | Spotify app client secret (optional) |

---

## How It Works

YouTube actively blocks most bots. This bot uses yt-dlp's `android_vr` player client, which impersonates YouTube's Android VR app and bypasses signature challenges without needing cookies.

Spotify links are resolved by looking up the track/album/playlist via the Spotify API, then searching YouTube for each song title and artist name.

Audio filters are applied as FFmpeg `-af` filter chains. When a filter changes mid-song, the current song restarts from the beginning with the new filter applied.

---

## Troubleshooting

**Bot joins but no sound**
→ Run `ffmpeg -version`. If not found, install FFmpeg and make sure it's on your PATH.

**Songs fail to load / "Requested format not available"**
→ Update yt-dlp: `pip3.11 install -U yt-dlp`

**Bot ignores commands**
→ Make sure **Message Content Intent** is enabled in the Discord Developer Portal under Bot → Privileged Gateway Intents.

**Slash commands don't appear**
→ Re-invite the bot with the `applications.commands` scope. It can take up to an hour for Discord to propagate new slash commands globally.

**Spotify links don't work**
→ Make sure `spotipy` is installed (`pip3.11 install spotipy`) and `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` are set in `.env`.

**Bot auto-disconnects too fast**
→ Increase `AUTO_DISCONNECT_MINUTES` in `.env`, or use `!stay` to disable auto-disconnect entirely.

---

## Project Structure

```
discord-music-bot/
├── bot.py              # Entry point, slash command sync
├── cogs/
│   └── music.py        # All commands, queue logic, audio engine
├── requirements.txt
├── .env
├── .env.example
├── CLAUDE.md           # AI assistant context
└── README.md
```
