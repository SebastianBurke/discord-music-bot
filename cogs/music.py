import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
import re
import tempfile
import time
import random
import math
import aiohttp
from collections import deque
from typing import Optional

try:
    import spotipy
    from spotipy.oauth2 import SpotifyClientCredentials
    _SPOTIPY = True
except ImportError:
    _SPOTIPY = False

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────

COOKIES_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt"))
TMPDIR = tempfile.gettempdir()
MAX_QUEUE = int(os.getenv("MAX_QUEUE", "50"))
AUTO_DISCONNECT_MINUTES = int(os.getenv("AUTO_DISCONNECT_MINUTES", "5"))
DJ_ROLE_NAME = os.getenv("DJ_ROLE_NAME", "DJ")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

AUDIO_FILTERS = {
    "bassboost": "bass=g=20",
    "nightcore": "asetrate=44100*1.25,aresample=44100",
    "normalize": "loudnorm",
}


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text).strip()


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return "Unknown"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _progress_bar(elapsed: float, total: float, width: int = 20) -> str:
    if not total:
        return ""
    ratio = min(elapsed / total, 1.0)
    pos = int(ratio * width)
    bar = "▬" * pos + "●" + "▬" * (width - pos)
    return f"`{bar}` {_fmt_duration(int(elapsed))} / {_fmt_duration(int(total))}"


def _ydl_opts(extra: dict = None) -> dict:
    opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "source_address": "0.0.0.0",
        "extractor_args": {"youtube": {"player_client": ["android_vr"]}},
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    if extra:
        opts.update(extra)
    return opts


# ─────────────────────────────────────────────
#  Data classes
# ─────────────────────────────────────────────

class Song:
    def __init__(self, webpage_url: str, title: str, duration: int,
                 requester: discord.Member, thumbnail: str = None):
        self.webpage_url = webpage_url
        self.title = _strip_ansi(title) if title else "Unknown Title"
        self.duration = duration
        self.requester = requester
        self.thumbnail = thumbnail

    @property
    def duration_str(self) -> str:
        return _fmt_duration(self.duration)


class GuildQueue:
    def __init__(self):
        self.queue: deque[Song] = deque()
        self.current: Optional[Song] = None
        self._history: deque[Song] = deque(maxlen=20)

        # Playback state
        self.volume: float = 0.5
        self.loop_song: bool = False
        self.loop_queue: bool = False
        self.stay_mode: bool = False
        self.audio_filter: Optional[str] = None
        self.replay_current: bool = False  # flag to restart current song (e.g. after filter change)
        self.play_start: Optional[float] = None

        # Moderation
        self._skip_votes: set = set()

        # Internal
        self._inactivity_task: Optional[asyncio.Task] = None
        self.last_text_channel: Optional[discord.TextChannel] = None  # for inactivity messages

    @property
    def is_full(self) -> bool:
        return len(self.queue) >= MAX_QUEUE

    def add(self, song: Song):
        self.queue.append(song)

    def next(self) -> Optional[Song]:
        if self.current:
            self._history.append(self.current)
        self._skip_votes.clear()
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        self.current = None
        return None

    def previous(self) -> Optional[Song]:
        """Push current back to front of queue, return last history item."""
        if not self._history:
            return None
        if self.current:
            self.queue.appendleft(self.current)
        prev = self._history.pop()
        self.queue.appendleft(prev)
        self.current = None
        return prev

    def clear(self):
        self.queue.clear()
        self.current = None
        self._skip_votes.clear()


# ─────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict[int, GuildQueue] = {}

    def get_queue(self, guild_id: int) -> GuildQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildQueue()
        return self.queues[guild_id]

    # ── Helpers ──────────────────────────────

    def is_dj(self, ctx: commands.Context) -> bool:
        """True if user has admin perms or the configured DJ role."""
        if ctx.author.guild_permissions.manage_guild:
            return True
        if not DJ_ROLE_NAME:
            return True
        return any(r.name == DJ_ROLE_NAME for r in ctx.author.roles)

    async def ensure_voice(self, ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel first.")
            return False
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()
            embed = discord.Embed(
                title="👋 Hey, I'm The Chosen One!",
                description="I'm your music bot. Type `!commands` to see everything I can do.",
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=embed)
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        return True

    def _cancel_inactivity_timer(self, guild_id: int):
        gq = self.queues.get(guild_id)
        if gq and gq._inactivity_task and not gq._inactivity_task.done():
            gq._inactivity_task.cancel()
            gq._inactivity_task = None

    def _start_inactivity_timer(self, guild: discord.Guild, voice_client: discord.VoiceClient, text_channel: discord.TextChannel = None):
        gq = self.get_queue(guild.id)
        if gq.stay_mode:
            return
        self._cancel_inactivity_timer(guild.id)
        channel = text_channel or gq.last_text_channel

        async def _timer():
            await asyncio.sleep(AUTO_DISCONNECT_MINUTES * 60)
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
                gq.clear()
                if channel:
                    await channel.send(f"👋 Left the channel after {AUTO_DISCONNECT_MINUTES} min of inactivity.")

        gq._inactivity_task = asyncio.create_task(_timer())

    # ── yt-dlp / Spotify helpers ──────────────

    async def fetch_song(self, query: str, requester: discord.Member) -> Song:
        loop = asyncio.get_event_loop()
        if not query.startswith("http"):
            query = f"ytsearch:{query}"
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(query, download=False))
        if "entries" in data:
            data = data["entries"][0]
        video_id = data.get("id", "")
        url = (data.get("webpage_url") or data.get("original_url")
               or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""))
        return Song(url, data.get("title", "Unknown"), data.get("duration", 0), requester, data.get("thumbnail"))

    async def fetch_search_results(self, query: str, requester: discord.Member, n: int = 5) -> list[Song]:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(_ydl_opts({"default_search": f"ytsearch{n}"})) as ydl:
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch{n}:{query}", download=False))
        results = []
        for entry in (data.get("entries") or [])[:n]:
            video_id = entry.get("id", "")
            url = (entry.get("webpage_url") or entry.get("original_url")
                   or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""))
            results.append(Song(url, entry.get("title", "Unknown"), entry.get("duration", 0), requester, entry.get("thumbnail")))
        return results

    async def fetch_playlist(self, url: str, requester: discord.Member) -> list[Song]:
        loop = asyncio.get_event_loop()
        opts = _ydl_opts({"noplaylist": False, "extract_flat": "in_playlist"})
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
        entries = data.get("entries") or []
        songs = []
        for entry in entries[:MAX_QUEUE]:
            if not entry:
                continue
            video_id = entry.get("id", "")
            url_e = (entry.get("webpage_url") or entry.get("url")
                     or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""))
            if not url_e:
                continue
            songs.append(Song(url_e, entry.get("title", "Unknown"), entry.get("duration", 0), requester, entry.get("thumbnail")))
        return songs

    async def resolve_spotify(self, url: str, requester: discord.Member) -> list[Song]:
        """Resolve Spotify URL to a list of YouTube songs via title search."""
        if not _SPOTIPY or not SPOTIFY_CLIENT_ID:
            raise ValueError("Spotify support requires `spotipy` installed and SPOTIFY_CLIENT_ID/SECRET in .env")
        loop = asyncio.get_event_loop()
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET
        ))

        def _get_tracks():
            if "track/" in url:
                t = sp.track(url)
                return [f"{t['name']} {t['artists'][0]['name']}"]
            elif "album/" in url:
                album = sp.album_tracks(url)
                return [f"{t['name']} {t['artists'][0]['name']}" for t in album["items"]]
            elif "playlist/" in url:
                results, queries = [], []
                pl = sp.playlist_items(url, limit=50)
                while pl:
                    for item in pl["items"]:
                        t = item.get("track")
                        if t:
                            queries.append(f"{t['name']} {t['artists'][0]['name']}")
                    pl = sp.next(pl) if pl["next"] else None
                return queries[:MAX_QUEUE]
            return []

        queries = await loop.run_in_executor(None, _get_tracks)
        songs = []
        for q in queries:
            try:
                songs.append(await self.fetch_song(q, requester))
            except Exception:
                pass
        return songs

    async def download_song(self, song: Song, audio_filter: str = None) -> str:
        loop = asyncio.get_event_loop()
        tmpbase = os.path.join(TMPDIR, f"discordbot_{id(song)}")
        opts = _ydl_opts({"noplaylist": True, "outtmpl": tmpbase + ".%(ext)s"})

        def _do():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(song.webpage_url, download=True)
                ext = info.get("ext", "webm")
            return f"{tmpbase}.{ext}"

        return await loop.run_in_executor(None, _do)

    def _cleanup_file(self, filepath: str):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception:
            pass

    # ── Playback engine ───────────────────────

    def _play_next(self, ctx: commands.Context, last_file: str = None):
        if last_file:
            self._cleanup_file(last_file)
        asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

    async def _play_next_async(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)

        # Determine which song plays next
        if guild_queue.replay_current and guild_queue.current:
            guild_queue.replay_current = False
            next_song = guild_queue.current
        elif guild_queue.loop_song and guild_queue.current:
            next_song = guild_queue.current
        else:
            if guild_queue.loop_queue and guild_queue.current:
                guild_queue.queue.append(guild_queue.current)
            next_song = guild_queue.next()

        if next_song is None:
            self._start_inactivity_timer(ctx.guild, ctx.voice_client, ctx.channel)
            await ctx.send("✅ Queue finished!")
            return

        await self._start_playback(ctx, next_song, guild_queue)

    async def _start_playback(self, ctx: commands.Context, song: Song, guild_queue: GuildQueue):
        if not ctx.voice_client:
            return
        guild_queue.last_text_channel = ctx.channel
        msg = await ctx.send(f"⏳ Loading **{song.title}**…")
        try:
            filepath = await self.download_song(song, guild_queue.audio_filter)
            af = guild_queue.audio_filter
            ffmpeg_opts = f"-vn -af {af}" if af else "-vn"
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(filepath, options=ffmpeg_opts),
                volume=guild_queue.volume,
            )
            guild_queue.play_start = time.time()
            ctx.voice_client.play(source, after=lambda _: self._play_next(ctx, last_file=filepath))
            await msg.delete()
            await ctx.send(content=f"🎵 **Now Playing:** {song.title}", embed=self._np_embed(song, guild_queue))
        except Exception as e:
            await msg.edit(content=f"❌ Error: `{_strip_ansi(str(e))}`")

    def _np_embed(self, song: Song, guild_queue: GuildQueue) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.blurple())
        if song.webpage_url:
            embed.url = song.webpage_url
        embed.add_field(name="Duration", value=song.duration_str, inline=True)
        embed.add_field(name="Requested by", value=song.requester.mention, inline=True)
        if guild_queue.audio_filter:
            embed.add_field(name="Filter", value=guild_queue.audio_filter.split("=")[0], inline=True)
        if guild_queue.loop_song:
            embed.add_field(name="Loop", value="🔂 Song", inline=True)
        elif guild_queue.loop_queue:
            embed.add_field(name="Loop", value="🔁 Queue", inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return embed

    # ── Commands ─────────────────────────────

    @commands.hybrid_command(name="commands", aliases=["h"], help="Show all available commands.")
    async def show_commands(self, ctx: commands.Context):
        embed = discord.Embed(title="🎵 The Chosen One — Commands", color=discord.Color.blurple())
        embed.add_field(name="▶️ Playback", value=(
            "`!play <song/URL>` — Play from YouTube or Spotify\n"
            "`!search <query>` — Pick from top 5 results\n"
            "`!skip` / `!forceskip` — Skip current song\n"
            "`!pause` / `!resume` — Pause and resume\n"
            "`!stop` — Stop and disconnect\n"
            "`!volume <0–100>` — Set the volume\n"
            "`!previous` — Play previous song\n"
            "`!loop` — Toggle song loop\n"
            "`!loopqueue` — Toggle queue loop"
        ), inline=False)
        embed.add_field(name="📋 Queue", value=(
            "`!queue` — View queue\n"
            "`!nowplaying` — Current song with progress bar\n"
            "`!shuffle` — Shuffle the queue\n"
            "`!clear` — Clear the queue\n"
            "`!move <from> <to>` — Reorder songs\n"
            "`!jump <pos>` — Skip to position\n"
            "`!remove <#>` — Remove a song\n"
            "`!history` — Last 20 played songs"
        ), inline=False)
        embed.add_field(name="🎛️ Filters & Extras", value=(
            "`!filter <bassboost|nightcore|normalize|off>` — Audio filter\n"
            "`!lyrics [song]` — Fetch lyrics\n"
            "`!voteskip` — Vote to skip\n"
            "`!stay` — Toggle 24/7 mode\n"
            "`!join` / `!leave` — Connect / disconnect"
        ), inline=False)
        embed.set_footer(text="Aliases: !p, !s, !q, !np, !res, !h, !prev")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="join", help="Join your voice channel.")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice:
            return await ctx.send("❌ You need to be in a voice channel first.")
        channel = ctx.author.voice.channel
        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)
            await ctx.send(f"➡️ Moved to **{channel.name}**.")
        else:
            await channel.connect()
            await ctx.send(f"✅ Joined **{channel.name}**.")

    @commands.hybrid_command(aliases=["p"], help="Play a song. Accepts YouTube/Spotify URL or search query.")
    async def play(self, ctx: commands.Context, *, query: str):
        if not await self.ensure_voice(ctx):
            return
        guild_queue = self.get_queue(ctx.guild.id)
        self._cancel_inactivity_timer(ctx.guild.id)

        is_spotify = "open.spotify.com" in query or query.startswith("spotify:")
        is_yt_playlist = ("youtube.com/playlist" in query or "list=" in query) and "open.spotify.com" not in query
        is_playing_now = ctx.voice_client.is_playing() or ctx.voice_client.is_paused()

        async with ctx.typing():
            try:
                if is_spotify:
                    songs = await self.resolve_spotify(query, ctx.author)
                    if not songs:
                        return await ctx.send("❌ No tracks found from that Spotify link.")
                    added = 0
                    for song in songs:
                        if guild_queue.is_full:
                            break
                        guild_queue.add(song)
                        added += 1
                    await ctx.send(f"➕ Added **{added}** Spotify track(s) to the queue.")

                elif is_yt_playlist:
                    songs = await self.fetch_playlist(query, ctx.author)
                    if not songs:
                        return await ctx.send("❌ Couldn't load playlist.")
                    added = 0
                    for song in songs:
                        if guild_queue.is_full:
                            break
                        guild_queue.add(song)
                        added += 1
                    await ctx.send(f"➕ Added **{added}** songs from playlist to the queue.")

                else:
                    if guild_queue.is_full:
                        return await ctx.send(f"❌ Queue is full ({MAX_QUEUE} songs).")
                    song = await self.fetch_song(query, ctx.author)
                    guild_queue.add(song)
                    if is_playing_now:
                        embed = discord.Embed(title="➕ Added to Queue", description=f"**{song.title}**", color=discord.Color.green())
                        if song.webpage_url:
                            embed.url = song.webpage_url
                        embed.add_field(name="Duration", value=song.duration_str, inline=True)
                        embed.add_field(name="Position", value=f"#{len(guild_queue.queue)}/{MAX_QUEUE}", inline=True)
                        await ctx.send(embed=embed)
                        return

            except Exception as e:
                return await ctx.send(f"❌ {_strip_ansi(str(e))}")

        if not is_playing_now:
            guild_queue.next()
            if guild_queue.current:
                await self._start_playback(ctx, guild_queue.current, guild_queue)

    @commands.command(name="search", help="Search YouTube and pick from top 5 results.")
    async def search(self, ctx: commands.Context, *, query: str):
        if not await self.ensure_voice(ctx):
            return
        async with ctx.typing():
            try:
                results = await self.fetch_search_results(query, ctx.author)
            except Exception as e:
                return await ctx.send(f"❌ Search failed: `{_strip_ansi(str(e))}`")

        if not results:
            return await ctx.send("❌ No results found.")

        embed = discord.Embed(title=f"🔍 Results for: {query}", color=discord.Color.blurple())
        for i, s in enumerate(results, 1):
            embed.add_field(name=f"{i}. {s.title}", value=s.duration_str, inline=False)
        embed.set_footer(text="Type a number (1–5) to pick, or 'cancel' to abort. You have 30 seconds.")
        await ctx.send(embed=embed)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=30)
        except asyncio.TimeoutError:
            return await ctx.send("⏰ Search timed out.")

        if msg.content.lower() == "cancel":
            return await ctx.send("❌ Search cancelled.")
        if not msg.content.isdigit() or not 1 <= int(msg.content) <= len(results):
            return await ctx.send("❌ Invalid selection.")

        chosen = results[int(msg.content) - 1]
        guild_queue = self.get_queue(ctx.guild.id)
        self._cancel_inactivity_timer(ctx.guild.id)

        if guild_queue.is_full:
            return await ctx.send(f"❌ Queue is full ({MAX_QUEUE} songs).")

        guild_queue.add(chosen)
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            await ctx.send(f"➕ Added **{chosen.title}** to the queue at position #{len(guild_queue.queue)}.")
        else:
            guild_queue.next()
            if guild_queue.current:
                await self._start_playback(ctx, guild_queue.current, guild_queue)

    @commands.hybrid_command(aliases=["s"], help="Skip the current song.")
    async def skip(self, ctx: commands.Context):
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            return await ctx.send("❌ Nothing is playing right now.")
        title = self.get_queue(ctx.guild.id).current.title if self.get_queue(ctx.guild.id).current else "song"
        ctx.voice_client.stop()
        await ctx.send(f"⏭️ Skipped **{title}**.")

    @commands.hybrid_command(name="forceskip", aliases=["fs"], help="Force skip (DJ/admin only).")
    async def forceskip(self, ctx: commands.Context):
        if not self.is_dj(ctx):
            return await ctx.send(f"❌ You need the **{DJ_ROLE_NAME}** role or Manage Server permission.")
        if not ctx.voice_client or not (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            return await ctx.send("❌ Nothing is playing right now.")
        title = self.get_queue(ctx.guild.id).current.title if self.get_queue(ctx.guild.id).current else "song"
        ctx.voice_client.stop()
        await ctx.send(f"⏭️ Force skipped **{title}**.")

    @commands.hybrid_command(name="voteskip", aliases=["vs"], help="Vote to skip the current song.")
    async def voteskip(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send("❌ Nothing is playing right now.")
        vc = ctx.voice_client.channel
        listeners = [m for m in vc.members if not m.bot]
        threshold = math.ceil(len(listeners) / 2)
        guild_queue._skip_votes.add(ctx.author.id)
        votes = len(guild_queue._skip_votes)
        if votes >= threshold:
            ctx.voice_client.stop()
            await ctx.send(f"⏭️ Vote passed ({votes}/{threshold}) — skipping!")
        else:
            await ctx.send(f"🗳️ Skip vote: **{votes}/{threshold}** needed.")

    @commands.hybrid_command(help="Pause playback.")
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Paused.")
        else:
            await ctx.send("❌ Nothing is playing.")

    @commands.hybrid_command(aliases=["res"], help="Resume paused playback.")
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Resumed.")
        else:
            await ctx.send("❌ Playback isn't paused.")

    @commands.hybrid_command(help="Set the volume (0–100).")
    async def volume(self, ctx: commands.Context, vol: int):
        guild_queue = self.get_queue(ctx.guild.id)
        if not 0 <= vol <= 100:
            return await ctx.send("❌ Volume must be between 0 and 100.")
        guild_queue.volume = vol / 100
        if ctx.voice_client and isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
            ctx.voice_client.source.volume = guild_queue.volume
        await ctx.send(f"🔊 Volume set to **{vol}%**.")

    @commands.hybrid_command(help="Stop playback and clear the queue.")
    async def stop(self, ctx: commands.Context):
        if not self.is_dj(ctx):
            return await ctx.send(f"❌ You need the **{DJ_ROLE_NAME}** role or Manage Server permission.")
        self._cancel_inactivity_timer(ctx.guild.id)
        self.get_queue(ctx.guild.id).clear()
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.hybrid_command(help="Disconnect the bot from the voice channel.")
    async def leave(self, ctx: commands.Context):
        self._cancel_inactivity_timer(ctx.guild.id)
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            self.get_queue(ctx.guild.id).clear()
            await ctx.send("👋 Left the voice channel.")
        else:
            await ctx.send("❌ I'm not in a voice channel.")

    @commands.hybrid_command(aliases=["q"], help="Show the current queue.")
    async def queue(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue.current and not guild_queue.queue:
            return await ctx.send("📭 The queue is empty. Use `!play` to add songs!")
        embed = discord.Embed(title="🎵 Queue", color=discord.Color.blurple())
        if guild_queue.current:
            elapsed = time.time() - guild_queue.play_start if guild_queue.play_start else 0
            bar = _progress_bar(elapsed, guild_queue.current.duration)
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{guild_queue.current.title}**\n{bar}",
                inline=False,
            )
        if guild_queue.queue:
            lines = [
                f"`{i+1}.` **{s.title}** — {s.duration_str} | {s.requester.display_name}"
                for i, s in enumerate(guild_queue.queue)
            ]
            embed.add_field(
                name=f"⏭️ Up Next ({len(guild_queue.queue)}/{MAX_QUEUE})",
                value="\n".join(lines[:15]),
                inline=False,
            )
        else:
            embed.add_field(name="⏭️ Up Next", value="Nothing queued. Use `!play` to add more!", inline=False)
        flags = []
        if guild_queue.loop_song: flags.append("🔂 Loop Song")
        if guild_queue.loop_queue: flags.append("🔁 Loop Queue")
        if guild_queue.stay_mode: flags.append("🕐 24/7")
        if flags:
            embed.set_footer(text=" | ".join(flags))
        await ctx.send(embed=embed)

    @commands.hybrid_command(aliases=["np"], help="Show the currently playing song with progress bar.")
    async def nowplaying(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue.current:
            return await ctx.send("❌ Nothing is playing right now.")
        elapsed = time.time() - guild_queue.play_start if guild_queue.play_start else 0
        bar = _progress_bar(elapsed, guild_queue.current.duration)
        embed = self._np_embed(guild_queue.current, guild_queue)
        if bar:
            embed.add_field(name="Progress", value=bar, inline=False)
        await ctx.send(content=f"🎵 **Now Playing:** {guild_queue.current.title}", embed=embed)

    @commands.hybrid_command(help="Remove a song from the queue by position.")
    async def remove(self, ctx: commands.Context, position: int):
        if not self.is_dj(ctx) and not ctx.author == self.get_queue(ctx.guild.id).current.requester:
            pass  # allow requesters to remove their own songs; DJs can remove any
        guild_queue = self.get_queue(ctx.guild.id)
        if position < 1 or position > len(guild_queue.queue):
            return await ctx.send(f"❌ Invalid position. Queue has {len(guild_queue.queue)} song(s).")
        removed = list(guild_queue.queue)[position - 1]
        del guild_queue.queue[position - 1]
        await ctx.send(f"🗑️ Removed **{removed.title}** from the queue.")

    @commands.hybrid_command(help="Toggle looping the current song.")
    async def loop(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        guild_queue.loop_song = not guild_queue.loop_song
        if guild_queue.loop_song:
            guild_queue.loop_queue = False
            await ctx.send("🔂 Loop **song** enabled.")
        else:
            await ctx.send("🔂 Loop **song** disabled.")

    @commands.hybrid_command(name="loopqueue", aliases=["lq"], help="Toggle looping the entire queue.")
    async def loopqueue(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        guild_queue.loop_queue = not guild_queue.loop_queue
        if guild_queue.loop_queue:
            guild_queue.loop_song = False
            await ctx.send("🔁 Loop **queue** enabled.")
        else:
            await ctx.send("🔁 Loop **queue** disabled.")

    @commands.hybrid_command(help="Shuffle the queue.")
    async def shuffle(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if len(guild_queue.queue) < 2:
            return await ctx.send("❌ Not enough songs in the queue to shuffle.")
        lst = list(guild_queue.queue)
        random.shuffle(lst)
        guild_queue.queue = deque(lst)
        await ctx.send("🔀 Queue shuffled!")

    @commands.hybrid_command(name="clear", help="Clear the queue without stopping current song.")
    async def clear_queue(self, ctx: commands.Context):
        if not self.is_dj(ctx):
            return await ctx.send(f"❌ You need the **{DJ_ROLE_NAME}** role or Manage Server permission.")
        guild_queue = self.get_queue(ctx.guild.id)
        guild_queue.queue.clear()
        await ctx.send("🗑️ Queue cleared.")

    @commands.hybrid_command(name="move", help="Move a song to a different position. Usage: !move <from> <to>")
    async def move(self, ctx: commands.Context, from_pos: int, to_pos: int):
        guild_queue = self.get_queue(ctx.guild.id)
        n = len(guild_queue.queue)
        if not (1 <= from_pos <= n and 1 <= to_pos <= n):
            return await ctx.send(f"❌ Positions must be between 1 and {n}.")
        lst = list(guild_queue.queue)
        song = lst.pop(from_pos - 1)
        lst.insert(to_pos - 1, song)
        guild_queue.queue = deque(lst)
        await ctx.send(f"↕️ Moved **{song.title}** to position **{to_pos}**.")

    @commands.hybrid_command(name="jump", help="Jump to a specific position in the queue.")
    async def jump(self, ctx: commands.Context, position: int):
        guild_queue = self.get_queue(ctx.guild.id)
        if position < 1 or position > len(guild_queue.queue):
            return await ctx.send(f"❌ Invalid position. Queue has {len(guild_queue.queue)} song(s).")
        # Discard songs before the target position
        for _ in range(position - 1):
            if guild_queue.queue:
                guild_queue.queue.popleft()
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        else:
            guild_queue.next()
            if guild_queue.current:
                await self._start_playback(ctx, guild_queue.current, guild_queue)
        await ctx.send(f"⏩ Jumping to position **{position}**…")

    @commands.hybrid_command(aliases=["prev"], help="Play the previous song.")
    async def previous(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue._history:
            return await ctx.send("❌ No previous songs in history.")
        guild_queue.previous()  # pushes prev to front of queue
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        elif ctx.voice_client:
            guild_queue.next()
            if guild_queue.current:
                await self._start_playback(ctx, guild_queue.current, guild_queue)
        else:
            await ctx.send("❌ Bot is not in a voice channel.")

    @commands.hybrid_command(name="history", help="Show recently played songs.")
    async def history(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue._history:
            return await ctx.send("📭 No history yet.")
        embed = discord.Embed(title="📜 Recently Played", color=discord.Color.blurple())
        lines = [
            f"`{i+1}.` **{s.title}** — {s.duration_str}"
            for i, s in enumerate(reversed(guild_queue._history))
        ]
        embed.description = "\n".join(lines)
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="stay", help="Toggle 24/7 mode (bot never auto-disconnects).")
    async def stay(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        guild_queue.stay_mode = not guild_queue.stay_mode
        if guild_queue.stay_mode:
            self._cancel_inactivity_timer(ctx.guild.id)
            await ctx.send("🕐 **24/7 mode** enabled. I'll stay in the channel.")
        else:
            await ctx.send("🕐 **24/7 mode** disabled. I'll leave after inactivity.")

    @commands.hybrid_command(name="filter", help="Apply an audio filter. Options: bassboost, nightcore, normalize, off")
    async def audio_filter(self, ctx: commands.Context, name: str):
        guild_queue = self.get_queue(ctx.guild.id)
        name = name.lower()
        if name == "off":
            guild_queue.audio_filter = None
            await ctx.send("🎵 Audio filter removed.")
        elif name in AUDIO_FILTERS:
            guild_queue.audio_filter = AUDIO_FILTERS[name]
            await ctx.send(f"🎛️ Filter set to **{name}**.")
        else:
            opts = ", ".join(AUDIO_FILTERS.keys())
            return await ctx.send(f"❌ Unknown filter. Options: `{opts}`, `off`")

        # Restart current song with new filter
        if (ctx.voice_client and guild_queue.current and
                (ctx.voice_client.is_playing() or ctx.voice_client.is_paused())):
            guild_queue.replay_current = True
            ctx.voice_client.stop()

    @commands.command(name="lyrics", help="Fetch lyrics for the current song or a search query.")
    async def lyrics(self, ctx: commands.Context, *, query: str = None):
        guild_queue = self.get_queue(ctx.guild.id)
        if not query:
            if not guild_queue.current:
                return await ctx.send("❌ Nothing is playing. Provide a song name: `!lyrics <song>`")
            query = guild_queue.current.title

        # Try to split "Artist - Title"
        if " - " in query:
            artist, title = query.split(" - ", 1)
        else:
            artist = title = query

        async with ctx.typing():
            url = f"https://api.lyrics.ovh/v1/{artist.strip()}/{title.strip()}"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status != 200:
                            return await ctx.send(f"❌ Lyrics not found for **{query}**.")
                        data = await resp.json()
                        lyrics_text = data.get("lyrics", "").strip()
            except Exception as e:
                return await ctx.send(f"❌ Lyrics fetch failed: `{e}`")

        if not lyrics_text:
            return await ctx.send(f"❌ No lyrics found for **{query}**.")

        # Paginate if long (Discord embed limit ~4096 chars)
        chunks = [lyrics_text[i:i+3900] for i in range(0, len(lyrics_text), 3900)]
        for i, chunk in enumerate(chunks):
            embed = discord.Embed(
                title=f"🎤 {query}" if i == 0 else f"🎤 {query} (cont.)",
                description=chunk,
                color=discord.Color.blurple(),
            )
            await ctx.send(embed=embed)

    # ── Voice state listener (auto-disconnect) ─

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        guild = member.guild
        vc = guild.voice_client
        if not vc:
            return
        # If everyone left the bot's channel, start inactivity timer
        humans = [m for m in vc.channel.members if not m.bot]
        if not humans:
            self._start_inactivity_timer(guild, vc)  # uses last_text_channel if available


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
