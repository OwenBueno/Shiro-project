# bot/cogs/music_cog.py
from discord.ext import commands, tasks
from utils.ytdl_source import YTDLSource, get_temp_ytdl
from collections import deque
from utils.delete_utils import delete_file
from commands.music_commands import song_queues, play_next
from datetime import datetime, timedelta
import asyncio
import datetime

class MusicCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_activity = {}

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'{self.bot.user} has connected to Discord!')
        self.check_if_alone.start()

    @tasks.loop(minutes=1)
    async def check_if_alone(self):
        for guild_id, vc in [(vc.guild.id, vc) for vc in self.bot.voice_clients]:
            if len(vc.channel.members) == 1 and vc.channel.members[0] == self.bot.user:
                if self.last_activity.get(guild_id) is None:
                    self.last_activity[guild_id] = datetime.now()
                elif datetime.now() - self.last_activity[guild_id] > timedelta(minutes=5):
                    await vc.disconnect()
                    self.last_activity[guild_id] = None
            else:
                self.last_activity[guild_id] = None

    @commands.command(name='vente', help='Tells the bot to join the voice channel')
    async def join(self, ctx):
        if not ctx.message.author.voice:
            await ctx.send("You are not connected to a voice channel.")
            return

        channel = ctx.message.author.voice.channel
        await channel.connect()
        self.last_activity[ctx.guild.id] = datetime.now()

    @commands.command(name='vete', help='Makes the bot leave the voice channel and clears the music queue')
    async def leave(self, ctx):
        voice_client = ctx.voice_client
        guild_id = ctx.guild.id

        if voice_client:
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()

            current_song = getattr(ctx.voice_client, 'current_song', None)
            if current_song:
                await delete_file(current_song)

            await voice_client.disconnect()
            self.last_activity.pop(guild_id, None)

            if guild_id in song_queues:
                song_queues[guild_id].clear()

            await ctx.send("**Disconnected and cleared the queue.**")

    @commands.command(name='canta', help='Joins the voice channel and plays a song by URL, searches for the song name, or plays a playlist')
    async def play(self, ctx, *, query):
        try:
            # Check if the bot is already connected to a voice channel
            if ctx.voice_client is None:
                if ctx.author.voice:
                    channel = ctx.author.voice.channel
                    await channel.connect()
                else:
                    await ctx.send("You need to be in a voice channel to use this command.")
                    return

            async with ctx.typing():
                temp_ytdl = get_temp_ytdl()

                data = await asyncio.to_thread(temp_ytdl.extract_info, query, download=False)
                
                if ctx.guild.id not in song_queues:
                    song_queues[ctx.guild.id] = deque()

                if 'entries' in data:  # If it's a playlist
                    # Extract the list of entries
                    entries = data['entries']

                    # If there are more than one entries, treat as a playlist
                    if len(entries) > 1:
                        # Play the first song immediately by extracting complete metadata
                        song = entries[0]
                        song_queues[ctx.guild.id].append(song['url'])
                        await ctx.send(f'**Playing first song from the playlist:** {song['title']}')
    
                        # Add the rest of the songs asynchronously
                        async def add_remaining_songs():
                            for entry in entries[1:]:
                                song_queues[ctx.guild.id].append(entry['url'])
                            await ctx.send(f'**Added remaining {len(entries) - 1} songs from the playlist to the queue.**')

                        # Schedule the addition of the remaining songs
                        commands.loop.create_task(add_remaining_songs())

                    else:  # If there's only one entry, treat it as a single video
                        song = entries[0]
                        song_queues[ctx.guild.id].append(song['url'])
                        await ctx.send(f'**Added to queue:** {song['title']}')

                else:  # If it's a single video (not a playlist)
                    song_queues[ctx.guild.id].append(data['webpage_url'])
                    await ctx.send(f'**Added to queue:** {data['fulltitle']}')

                # If nothing is currently playing, start playing
                if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                    await play_next(ctx)

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    # Command to skip the current song and play the next if available
    @commands.command(name='salta', help='Skips the current song and plays the next one in the queue if available')
    async def skip(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_playing():
            await ctx.send("There is no song playing to skip.")
        else:
            voice_client.stop()
            await ctx.send("**Song has been skipped.**")

    # Command to pause the music
    @commands.command(name='yamete', help='Pauses the song')
    async def stop(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_playing():
            await ctx.send("There is no song currently playing to pause.")
        else:
            voice_client.pause()  # Pause the current playback
            await ctx.send("**Playback has been paused.**")

    # Command to resume the music
    @commands.command(name='kudasai', help='Resumes the paused song')
    async def resume(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_paused():
            await ctx.send("There is no paused song to resume.")
        else:
            voice_client.resume()  # Resume the paused playback
            await ctx.send("**Playback has been resumed.**")

    # Command to show the current queue
    @commands.command(name='cola', help='Displays the current music queue')
    async def show_queue(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in song_queues or not song_queues[guild_id]:
            await ctx.send("The queue is currently empty.")
        else:
            queue_list = "\n".join([f"{i + 1}. {url}" for i, url in enumerate(song_queues[guild_id])])
            await ctx.send(f"**Current queue:**\n{queue_list}")

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
