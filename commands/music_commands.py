# bot/commands/music_commands.py
import discord
from utils.ytdl_source import YTDLSource
from utils.delete_utils import delete_file
from config import FFMPEG_OPTIONS
from datetime import datetime
from collections import deque

song_queues = {}  # Dictionary to hold queues for each server/guild
last_activity = {}  # Dictionary to track last activity in each server

async def play_next(ctx):
    guild_id = ctx.guild.id

    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        return

    if guild_id in song_queues and song_queues[guild_id]:
        while song_queues[guild_id]:  # Keep trying songs until one works or queue is empty
            try:
                next_url = song_queues[guild_id].popleft()
                player_data = await YTDLSource.from_url(next_url, download=True)

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
                return  # Successfully started playing a song
                
            except Exception as e:
                error_message = str(e)
                if any(error in error_message for error in ["HTTP Error 403", "Forbidden", "unable to download"]):
                    await ctx.send(f"**Error:** Unable to play a song (403 Forbidden). Skipping to next...")
                    continue  # Try the next song
                else:
                    print(f"Error in play_next: {e}")
                    break  # Stop on other errors

        # If we get here and queue is empty, notify
        if not song_queues[guild_id]:
            await ctx.send("**Queue finished:** No more songs to play.")
