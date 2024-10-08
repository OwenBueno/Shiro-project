import discord
from discord.ext import commands
import asyncio
from config import DISCORD_TOKEN

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.dm_messages = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')

async def load_extensions():
    await bot.load_extension('cogs.music_cog')
    await bot.load_extension('cogs.chat_cog')

async def main():
    async with bot:
        await load_extensions()
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())