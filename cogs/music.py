import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import re
import tempfile
from collections import deque
from typing import Optional

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────

COOKIES_FILE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cookies.txt"))
TMPDIR = tempfile.gettempdir()
MAX_QUEUE = 10  # Max songs in queue (not counting current)

def _strip_ansi(text: str) -> str:
    """Remove ANSI colour codes that yt-dlp sometimes includes in titles."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text).strip()

def _ydl_opts(extra: dict = None) -> dict:
    opts = {
        "format": "bestaudio/best",
        "noplaylist": False,
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
        if not self.duration:
            return "Unknown"
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class GuildQueue:
    def __init__(self):
        self.queue = deque()
        self.current: Optional[Song] = None
        self._history = deque(maxlen=20)

    def add(self, song: Song):
        self.queue.append(song)

    @property
    def is_full(self) -> bool:
        return len(self.queue) >= MAX_QUEUE

    def next(self) -> Optional[Song]:
        if self.current:
            self._history.append(self.current)
        if self.queue:
            self.current = self.queue.popleft()
            return self.current
        self.current = None
        return None

    def clear(self):
        self.queue.clear()
        self.current = None


# ─────────────────────────────────────────────
#  Cog
# ─────────────────────────────────────────────

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: dict = {}

    def get_queue(self, guild_id: int) -> GuildQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildQueue()
        return self.queues[guild_id]

    async def ensure_voice(self, ctx: commands.Context) -> bool:
        if not ctx.author.voice:
            await ctx.send("❌ You need to be in a voice channel first.")
            return False
        if not ctx.voice_client:
            await ctx.author.voice.channel.connect()
            # Announce commands on first join
            embed = discord.Embed(
                title="👋 Hey, I'm The Chosen One!",
                description="I'm your music bot. Here's what I can do — type `!commands` anytime to see this again.",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="▶️ Playback", value=(
                "`!play <song>` — Play a YouTube URL or search query\n"
                "`!skip` — Skip the current song\n"
                "`!pause` / `!resume` — Pause and resume\n"
                "`!stop` — Stop and disconnect\n"
                "`!volume <0–100>` — Set the volume"
            ), inline=False)
            embed.add_field(name="📋 Queue", value=(
                "`!queue` — View the queue (max 10 songs)\n"
                "`!nowplaying` — Show the current song\n"
                "`!remove <#>` — Remove a song by position"
            ), inline=False)
            embed.set_footer(text="Aliases: !p, !s, !q, !np, !res, !h")
            await ctx.send(embed=embed)
        elif ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        return True

    async def fetch_song(self, query: str, requester: discord.Member) -> Song:
        loop = asyncio.get_event_loop()
        if not query.startswith("http"):
            query = f"ytsearch:{query}"
        with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
            data = await loop.run_in_executor(
                None, lambda: ydl.extract_info(query, download=False)
            )
        if "entries" in data:
            data = data["entries"][0]
        video_id = data.get("id", "")
        webpage_url = (
            data.get("webpage_url")
            or data.get("original_url")
            or (f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        )
        return Song(
            webpage_url=webpage_url,
            title=data.get("title", "Unknown Title"),
            duration=data.get("duration", 0),
            requester=requester,
            thumbnail=data.get("thumbnail"),
        )

    async def download_song(self, song: Song) -> str:
        loop = asyncio.get_event_loop()
        tmpbase = os.path.join(TMPDIR, f"discordbot_{id(song)}")
        opts = _ydl_opts({
            "noplaylist": True,
            "outtmpl": tmpbase + ".%(ext)s",
        })
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

    def _play_next(self, ctx: commands.Context, last_file: str = None):
        if last_file:
            self._cleanup_file(last_file)
        asyncio.run_coroutine_threadsafe(self._play_next_async(ctx), self.bot.loop)

    async def _play_next_async(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        next_song = guild_queue.next()
        if next_song is None:
            await ctx.send("✅ Queue finished!")
            return
        msg = await ctx.send(f"⏳ Loading **{next_song.title}**…")
        try:
            filepath = await self.download_song(next_song)
            source = discord.PCMVolumeTransformer(
                discord.FFmpegPCMAudio(filepath, options="-vn"),
                volume=0.5,
            )
            ctx.voice_client.play(
                source,
                after=lambda _: self._play_next(ctx, last_file=filepath)
            )
            await msg.delete()
            await ctx.send(content=self._now_playing_text(next_song), embed=self._now_playing_embed(next_song))
        except Exception as e:
            await msg.edit(content=f"❌ Error: `{e}`")

    def _now_playing_text(self, song: Song) -> str:
        return f"🎵 **Now Playing:** {song.title}"

    def _now_playing_embed(self, song: Song) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.blurple())
        if song.webpage_url:
            embed.url = song.webpage_url
        embed.add_field(name="Duration", value=song.duration_str, inline=True)
        embed.add_field(name="Requested by", value=song.requester.mention, inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        return embed

    # ── Commands ─────────────────────────────

    @commands.command(name="commands", aliases=["h"], help="Show all available commands.")
    async def show_commands(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🎵 The Chosen One — Commands",
            description="Here's everything I can do:",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="▶️ Playback", value=(
            "`!play <song>` — Play a YouTube URL or search query\n"
            "`!skip` — Skip the current song\n"
            "`!pause` — Pause playback\n"
            "`!resume` — Resume playback\n"
            "`!stop` — Stop and disconnect\n"
            "`!volume <0–100>` — Set the volume"
        ), inline=False)
        embed.add_field(name="📋 Queue", value=(
            "`!queue` — View the queue (max 10 songs)\n"
            "`!nowplaying` — Show the current song\n"
            "`!remove <#>` — Remove a song by position"
        ), inline=False)
        embed.add_field(name="🔧 Other", value=(
            "`!join` — Join your voice channel\n"
            "`!leave` — Leave the voice channel\n"
            "`!commands` — Show this message"
        ), inline=False)
        embed.set_footer(text="Aliases: !p, !s, !q, !np, !res, !h")
        await ctx.send(embed=embed)
    @commands.command(aliases=["p"], help="Play a song. Accepts a YouTube URL or search query.")
    async def play(self, ctx: commands.Context, *, query: str):
        if not await self.ensure_voice(ctx):
            return
        guild_queue = self.get_queue(ctx.guild.id)

        # Check queue limit before fetching
        if guild_queue.is_full:
            return await ctx.send(f"❌ Queue is full! Max {MAX_QUEUE} songs. Use `!skip` or wait for songs to finish.")

        async with ctx.typing():
            try:
                song = await self.fetch_song(query, ctx.author)
            except Exception as e:
                return await ctx.send(f"❌ Couldn't find track: `{_strip_ansi(str(e))}`")

            guild_queue.add(song)

            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                embed = discord.Embed(
                    title="➕ Added to Queue",
                    description=f"**{song.title}**",
                    color=discord.Color.green(),
                )
                if song.webpage_url:
                    embed.url = song.webpage_url
                embed.add_field(name="Duration", value=song.duration_str, inline=True)
                embed.add_field(name="Position", value=f"#{len(guild_queue.queue)}/{MAX_QUEUE}", inline=True)
                await ctx.send(embed=embed)
                return

        # Start playback if idle
        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            guild_queue.next()
            if guild_queue.current:
                msg = await ctx.send(f"⏳ Loading **{guild_queue.current.title}**…")
                try:
                    filepath = await self.download_song(guild_queue.current)
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(filepath, options="-vn"),
                        volume=0.5,
                    )
                    ctx.voice_client.play(
                        source,
                        after=lambda _: self._play_next(ctx, last_file=filepath)
                    )
                    await msg.delete()
                    await ctx.send(
                        content=self._now_playing_text(guild_queue.current),
                        embed=self._now_playing_embed(guild_queue.current)
                    )
                except Exception as e:
                    await msg.edit(content=f"❌ Couldn't start playback: `{_strip_ansi(str(e))}`")

    @commands.command(aliases=["s"], help="Skip the current song.")
    async def skip(self, ctx: commands.Context):
        if not ctx.voice_client or not ctx.voice_client.is_playing():
            return await ctx.send("❌ Nothing is playing right now.")
        title = self.get_queue(ctx.guild.id).current.title if self.get_queue(ctx.guild.id).current else "song"
        ctx.voice_client.stop()
        await ctx.send(f"⏭️ Skipped **{title}**.")

    @commands.command(aliases=["q"], help="Show the current queue.")
    async def queue(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue.current and not guild_queue.queue:
            return await ctx.send("📭 The queue is empty. Use `!play` to add songs!")

        embed = discord.Embed(title="🎵 Queue", color=discord.Color.blurple())

        if guild_queue.current:
            embed.add_field(
                name="▶️ Now Playing",
                value=f"**{guild_queue.current.title}** — {guild_queue.current.duration_str}",
                inline=False,
            )

        if guild_queue.queue:
            lines = [
                f"`{i+1}.` **{s.title}** — {s.duration_str} | {s.requester.display_name}"
                for i, s in enumerate(guild_queue.queue)
            ]
            embed.add_field(
                name=f"⏭️ Up Next ({len(guild_queue.queue)}/{MAX_QUEUE})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="⏭️ Up Next", value="Nothing queued. Use `!play` to add more!", inline=False)

        await ctx.send(embed=embed)

    @commands.command(aliases=["np"], help="Show the currently playing song.")
    async def nowplaying(self, ctx: commands.Context):
        guild_queue = self.get_queue(ctx.guild.id)
        if not guild_queue.current:
            return await ctx.send("❌ Nothing is playing right now.")
        await ctx.send(
            content=self._now_playing_text(guild_queue.current),
            embed=self._now_playing_embed(guild_queue.current)
        )

    @commands.command(help="Remove a song from the queue by position.")
    async def remove(self, ctx: commands.Context, position: int):
        guild_queue = self.get_queue(ctx.guild.id)
        if position < 1 or position > len(guild_queue.queue):
            return await ctx.send(f"❌ Invalid position. Queue has {len(guild_queue.queue)} song(s).")
        removed = list(guild_queue.queue)[position - 1]
        del guild_queue.queue[position - 1]
        await ctx.send(f"🗑️ Removed **{removed.title}** from the queue.")

    @commands.command(help="Pause playback.")
    async def pause(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.pause()
            await ctx.send("⏸️ Paused.")
        else:
            await ctx.send("❌ Nothing is playing.")

    @commands.command(aliases=["res"], help="Resume paused playback.")
    async def resume(self, ctx: commands.Context):
        if ctx.voice_client and ctx.voice_client.is_paused():
            ctx.voice_client.resume()
            await ctx.send("▶️ Resumed.")
        else:
            await ctx.send("❌ Playback isn't paused.")

    @commands.command(help="Set the volume (0–100).")
    async def volume(self, ctx: commands.Context, vol: int):
        if not ctx.voice_client or not isinstance(ctx.voice_client.source, discord.PCMVolumeTransformer):
            return await ctx.send("❌ Nothing is playing right now.")
        if not 0 <= vol <= 100:
            return await ctx.send("❌ Volume must be between 0 and 100.")
        ctx.voice_client.source.volume = vol / 100
        await ctx.send(f"🔊 Volume set to **{vol}%**.")

    @commands.command(help="Stop playback and clear the queue.")
    async def stop(self, ctx: commands.Context):
        self.get_queue(ctx.guild.id).clear()
        if ctx.voice_client:
            ctx.voice_client.stop()
            await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Stopped and cleared the queue.")

    @commands.command(help="Disconnect the bot from the voice channel.")
    async def leave(self, ctx: commands.Context):
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            self.get_queue(ctx.guild.id).clear()
            await ctx.send("👋 Left the voice channel.")
        else:
            await ctx.send("❌ I'm not in a voice channel.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))