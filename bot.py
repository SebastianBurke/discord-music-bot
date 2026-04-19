import discord
from discord.ext import commands
from dotenv import load_dotenv
import os
import ctypes.util

load_dotenv()

# Load opus (required for voice/audio on Mac)
if not discord.opus.is_loaded():
    opus_path = ctypes.util.find_library("opus")
    if opus_path:
        discord.opus.load_opus(opus_path)
    else:
        # Fallback: common Homebrew paths on Mac
        for path in [
            "/opt/homebrew/lib/libopus.dylib",      # Apple Silicon
            "/usr/local/lib/libopus.dylib",          # Intel Mac
        ]:
            if os.path.exists(path):
                discord.opus.load_opus(path)
                break

TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "!")

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name=f"{PREFIX}play | {PREFIX}commands"
    ))
    try:
        synced = await bot.tree.sync()
        print(f"🔗 Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"⚠️  Slash command sync failed: {e}")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument. Use `{PREFIX}help {ctx.command}` for usage.")
    elif isinstance(error, commands.CommandNotFound):
        pass  # Silently ignore unknown commands
    else:
        await ctx.send(f"❌ An error occurred: `{error}`")
        raise error


async def main():
    async with bot:
        await bot.load_extension("cogs.music")
        await bot.start(TOKEN)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())