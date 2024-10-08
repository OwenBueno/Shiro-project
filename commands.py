import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from config import YTDL_FORMAT_OPTIONS, FFMPEG_OPTIONS
from utils import delete_file
import yt_dlp as youtube_dl
from collections import deque
import asyncio
import os

# Setup YTDL
ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename, volume=0.5):
        super().__init__(source, volume=volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.filename = filename

    @classmethod
    async def from_url(cls, url, *, loop=None, download=True):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=download))

        if 'entries' in data:
            return data['entries']

        filename = ytdl.prepare_filename(data)
        if not os.path.exists(filename):
            filename = f"{os.path.splitext(filename)[0]}.opus"

        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data, filename=filename)

song_queues = {}
last_activity = {}

async def play_next(ctx):
    guild_id = ctx.guild.id

    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        return

    if guild_id in song_queues and song_queues[guild_id]:
        next_url = song_queues[guild_id].popleft()
        player_data = await YTDLSource.from_url(next_url, loop=ctx.bot.loop, download=True)

        if isinstance(player_data, list):
            player_data = player_data[0]

        filename = player_data.filename

        def after_playing(error):
            if error:
                print(f'Player error: {error}')
            if ctx.voice_client and ctx.voice_client.is_connected():
                ctx.bot.loop.create_task(play_next(ctx))
            ctx.bot.loop.call_later(1, delete_file, filename)

        player = discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS)
        ctx.voice_client.play(player, after=after_playing)
        ctx.voice_client.current_song = filename
        await ctx.send(f'**Now playing:** {player_data.title}')
        last_activity[guild_id] = datetime.now()
