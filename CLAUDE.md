# CLAUDE.md — Project Context for AI Assistants

This file provides context for Claude Code and other AI assistants working in this repo.

---

## What This Is

A self-hosted Discord music bot written in Python. It plays audio from YouTube and Spotify in Discord voice channels, with a full queue system, audio filters, slash commands, and moderation features.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Discord library | discord.py 2.3+ (with voice support) |
| Audio source | yt-dlp (YouTube, SoundCloud, etc.) |
| Audio encoding | FFmpeg (via `discord.FFmpegPCMAudio`) |
| Opus | PyNaCl + libopus (loaded at startup in `bot.py`) |
| Spotify | spotipy (optional, requires credentials in `.env`) |
| Lyrics | aiohttp → lyrics.ovh public API |
| Config | python-dotenv (.env file) |

---

## Project Structure

```
discord-music-bot/
├── bot.py              # Bot init, opus loading, slash command tree sync, error handler
├── cogs/
│   └── music.py        # Everything music-related (commands, queue, playback engine)
├── requirements.txt
├── .env                # Secret config (not committed)
├── .env.example        # Template
├── CLAUDE.md           # This file
└── README.md
```

---

## Key Architecture

### `bot.py`
- Loads libopus at startup (searches Homebrew paths then `ctypes.util.find_library`)
- Creates the bot with `message_content` and `voice_states` intents
- Calls `bot.tree.sync()` in `on_ready` to register slash commands
- Loads the `cogs.music` extension

### `cogs/music.py`

**`Song`** — immutable data class: URL, title, duration, requester, thumbnail.

**`GuildQueue`** — per-guild state (one instance per server):
- `queue: deque[Song]` — songs waiting to play
- `current: Optional[Song]` — currently playing
- `_history: deque[Song]` — last 20 played (maxlen=20)
- `volume: float` — persisted across songs (default 0.5)
- `loop_song / loop_queue: bool` — loop modes
- `audio_filter: Optional[str]` — FFmpeg `-af` filter string
- `replay_current: bool` — flag to restart current song (used by `!filter`)
- `play_start: Optional[float]` — `time.time()` when current song started (for progress bar)
- `_skip_votes: set` — user IDs who voted to skip (cleared on song change)
- `stay_mode: bool` — suppress auto-disconnect
- `_inactivity_task` — asyncio Task for auto-disconnect timer
- `last_text_channel` — last text channel used (for inactivity messages)

**`Music` cog** — all commands + playback engine:
- `ensure_voice()` — joins/moves bot to user's channel; shows help embed on first join
- `is_dj()` — returns True if user has `manage_guild` perm or the configured DJ role
- `fetch_song()` — resolves query/URL to a `Song` via yt-dlp (no download)
- `fetch_search_results()` — returns top N YouTube results
- `fetch_playlist()` — fetches all entries from a YouTube playlist URL
- `resolve_spotify()` — resolves Spotify URL → list of search queries → `Song` list
- `download_song()` — downloads audio to `/tmp/discordbot_<id>.<ext>`
- `_play_next()` — sync callback (after= hook); bridges to `_play_next_async()`
- `_play_next_async()` — determines next song (loop/replay logic), calls `_start_playback()`
- `_start_playback()` — downloads, builds FFmpegPCMAudio with optional filter, starts play
- `_start_inactivity_timer()` — starts asyncio Task to disconnect after N minutes
- `on_voice_state_update()` — triggers inactivity timer when all humans leave

---

## Playback Flow

```
!play query
  → ensure_voice()
  → fetch_song() [yt-dlp, no download, runs in executor]
  → guild_queue.add(song)
  → if idle: guild_queue.next() → _start_playback()
      → download_song() [yt-dlp download, runs in executor]
      → FFmpegPCMAudio(filepath, options="-vn [-af filter]")
      → PCMVolumeTransformer(source, volume=guild_queue.volume)
      → voice_client.play(source, after=_play_next)
  → when song ends: _play_next() → _play_next_async()
      → check loop_song / replay_current / loop_queue
      → guild_queue.next() → _start_playback() or "Queue finished!"
```

---

## Config Variables (`.env`)

| Variable | Default | Effect |
|---|---|---|
| `DISCORD_TOKEN` | — | Required |
| `BOT_PREFIX` | `!` | Command prefix |
| `MAX_QUEUE` | `50` | Max songs per guild |
| `AUTO_DISCONNECT_MINUTES` | `5` | Inactivity timeout |
| `DJ_ROLE_NAME` | `DJ` | Role for `!stop`, `!clear`, `!forceskip` |
| `SPOTIFY_CLIENT_ID` | — | Enables Spotify support |
| `SPOTIFY_CLIENT_SECRET` | — | Enables Spotify support |

---

## Command Summary

| Command | Alias | DJ Only | Notes |
|---|---|---|---|
| `!play` | `!p` | No | YouTube URL/search/playlist, Spotify URL |
| `!search` | — | No | Prefix-only (uses wait_for, no slash equivalent) |
| `!skip` | `!s` | No | Alias triggers vote if voteskip would be more appropriate |
| `!forceskip` | `!fs` | Yes | Instant skip regardless of votes |
| `!voteskip` | `!vs` | No | ceil(listeners/2) threshold |
| `!pause` | — | No | |
| `!resume` | `!res` | No | |
| `!stop` | — | Yes | Clears queue + disconnects |
| `!volume` | — | No | Persists across songs |
| `!previous` | `!prev` | No | Uses `_history` deque |
| `!loop` | — | No | Toggles `loop_song`; disables `loop_queue` |
| `!loopqueue` | `!lq` | No | Toggles `loop_queue`; disables `loop_song` |
| `!queue` | `!q` | No | Shows progress bar |
| `!nowplaying` | `!np` | No | Live progress bar |
| `!shuffle` | — | No | |
| `!clear` | — | Yes | Queue only, keeps current song |
| `!move <f> <t>` | — | No | Reorder by position |
| `!jump <pos>` | — | No | Discards songs before pos, triggers skip |
| `!remove <pos>` | — | No | |
| `!history` | — | No | Last 20 songs, newest first |
| `!stay` | — | No | Toggles `stay_mode` |
| `!filter <name\|off>` | — | No | Restarts current song with new filter |
| `!lyrics [song]` | — | No | Prefix-only; paginated if long |
| `!join` | — | No | |
| `!leave` | — | No | |
| `!commands` | `!h` | No | |

---

## Conventions

- All commands use `@commands.hybrid_command()` for dual prefix + slash support, except `!search` and `!lyrics` which use `@commands.command()` (they rely on `wait_for` or multi-message flows incompatible with interactions).
- yt-dlp calls always run in `asyncio.run_in_executor(None, ...)` to avoid blocking the event loop.
- Temp audio files are stored in `TMPDIR` as `discordbot_<object_id>.<ext>` and deleted in the `after=` callback.
- All per-guild state is on `GuildQueue`; no module-level mutable state except `self.queues: dict`.
- The `_history` deque stores songs in chronological order (oldest first); `!history` displays them newest-first by iterating `reversed()`.

---

## Common Tasks

**Add a new command:**
Use `@commands.hybrid_command()` inside the `Music` cog. If it needs DJ restriction, check `self.is_dj(ctx)` at the top. If it modifies playback state, operate on `self.get_queue(ctx.guild.id)`.

**Add a new audio filter:**
Add an entry to the `AUDIO_FILTERS` dict at the top of `music.py`. The value is an FFmpeg `-af` filter string.

**Change auto-disconnect behavior:**
Edit `_start_inactivity_timer()` in `music.py` and/or the `on_voice_state_update` listener.

**Update dependencies:**
Edit `requirements.txt`. Run `pip3.11 install -U yt-dlp` regularly — yt-dlp needs frequent updates as YouTube changes its anti-bot measures.
