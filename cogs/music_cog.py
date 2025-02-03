# bot/cogs/music_cog.py
from discord.ext import commands, tasks
from utils.ytdl_source import YTDLSource, get_temp_ytdl
from collections import deque
from utils.delete_utils import delete_file
from commands.music_commands import song_queues, play_next
from datetime import datetime, timedelta
import asyncio
import random

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
                # Start tracking inactivity if not already tracking
                if self.last_activity.get(guild_id) is None:
                    self.last_activity[guild_id] = datetime.now()
                # Check if inactive for more than 5 minutes
                elif datetime.now() - self.last_activity[guild_id] > timedelta(minutes=1):
                    # Stop any ongoing playback
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    
                    # Clean up current song file if it exists
                    current_song = getattr(vc, 'current_song', None)
                    if current_song:
                        try:
                            await delete_file(current_song)
                        except Exception as e:
                            print(f"Error deleting file in check_if_alone: {e}")
                    
                    # Clear the queue for this guild
                    if guild_id in song_queues:
                        song_queues[guild_id].clear()
                    
                    # Disconnect from voice channel
                    await vc.disconnect(force=True)
                    self.last_activity[guild_id] = None
                    print(f"Bot disconnected from guild {guild_id} due to inactivity")
            else:
                # Reset inactivity timer when not alone
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
            # Stop any ongoing playback or pause
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()

            # Remove the current song's file if it exists
            current_song = getattr(voice_client, 'current_song', None)
            if current_song:
                try:
                    await delete_file(current_song)
                except Exception as e:
                    print(f"Error deleting file: {e}")

            # Disconnect the bot from the voice channel
            await voice_client.disconnect(force=True)  # Use `force=True` to ensure disconnection

            # Remove guild activity tracking
            self.last_activity.pop(guild_id, None)

            # Clear the music queue for the guild
            if guild_id in song_queues:
                song_queues[guild_id].clear()

            # Notify the user
            await ctx.send("**Disconnected and cleared the queue.**")
        else:
            await ctx.send("The bot is not connected to a voice channel.")

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
                    entries = data['entries']

                    if len(entries) > 1:  # Treat as a playlist
                        # Play the first song immediately
                        song = entries[0]
                        song_queues[ctx.guild.id].append(song['url'])
                        await ctx.send(f'**Playing first song from the playlist:** {song["title"]}')

                        # Add the rest of the songs asynchronously
                        async def add_remaining_songs():
                            for entry in entries[1:]:
                                song_queues[ctx.guild.id].append(entry['url'])
                            await ctx.send(f'**Added remaining {len(entries) - 1} songs from the playlist to the queue.**')

                        # Schedule the addition of the remaining songs
                        asyncio.create_task(add_remaining_songs())

                    else:  # If there's only one entry
                        song = entries[0]
                        song_queues[ctx.guild.id].append(song['url'])
                        await ctx.send(f'**Added to queue:** {song["title"]}')


                else:  # If it's a single video (not a playlist)
                    song_queues[ctx.guild.id].append(data['webpage_url'])
                    await ctx.send(f'**Added to queue:** {data['fulltitle']}')

                # If nothing is currently playing, start playing
                if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                    await play_next(ctx)
                self.last_activity[ctx.guild.id] = datetime.now()

        except Exception as e:
            error_message = str(e)
            if "HTTP Error 403" in error_message:
                await ctx.send("**Error:** Unable to access the video. It might be age-restricted or private.")
            elif "HTTP Error 404" in error_message:
                await ctx.send("**Error:** The video was not found. The URL might be invalid or the video was deleted.")
            elif "Unsupported URL" in error_message:
                await ctx.send("**Error:** The provided URL is not supported. Please provide a valid YouTube URL.")
            elif "No video formats found" in error_message:
                await ctx.send("**Error:** Could not extract audio from this video. It might be unavailable in your region.")
            else:
                await ctx.send("An error occurred while processing your request.")
            print(f"Error details: {error_message}, {e}")

    # Command to skip the current song and play the next if available
    @commands.command(name='salta', help='Skips the current song and plays the next one in the queue if available')
    async def skip(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_playing():
            await ctx.send("There is no song playing to skip.")
        else:
            voice_client.stop()
            self.last_activity[ctx.guild.id] = datetime.now()
            await ctx.send("**Song has been skipped.**")

    # Command to pause the music
    @commands.command(name='yamete', help='Pauses the song')
    async def stop(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_playing():
            await ctx.send("There is no song currently playing to pause.")
        else:
            voice_client.pause()  # Pause the current playback
            self.last_activity[ctx.guild.id] = datetime.now()
            await ctx.send("**Playback has been paused.**")

    # Command to resume the music
    @commands.command(name='kudasai', help='Resumes the paused song')
    async def resume(self, ctx):
        voice_client = ctx.voice_client
        if not voice_client or not voice_client.is_paused():
            await ctx.send("There is no paused song to resume.")
        else:
            voice_client.resume()  # Resume the paused playback
            self.last_activity[ctx.guild.id] = datetime.now()
            await ctx.send("**Playback has been resumed.**")

    # Command to show the current queue
    @commands.command(name='cola', help='Displays the current music queue')
    async def show_queue(self, ctx):
        guild_id = ctx.guild.id
        if guild_id not in song_queues or not song_queues[guild_id]:
            await ctx.send("The queue is currently empty.")
        else:
            async with ctx.typing():
                temp_ytdl = get_temp_ytdl()
                queue_list = []
                for i, url in enumerate(song_queues[guild_id]):
                    try:
                        # Extract title without downloading
                        info = await asyncio.to_thread(temp_ytdl.extract_info, url, download=False)
                        title = info.get('title', 'Unknown Title')
                        queue_list.append(f"{i + 1}. {title}")
                    except Exception as e:
                        queue_list.append(f"{i + 1}. {url} (Could not fetch title)")
                
                formatted_queue = "\n".join(queue_list)
                self.last_activity[ctx.guild.id] = datetime.now()
                await ctx.send(f"**Current queue:**\n{formatted_queue}")

    @commands.command(name='esquizo', help='Shuffles the current music queue randomly')
    async def shuffle(self, ctx):
        guild_id = ctx.guild.id
        
        if guild_id not in song_queues or not song_queues[guild_id]:
            await ctx.send("The queue is empty. Nothing to shuffle! 🎲")
            return
            
        # Convert deque to list for shuffling
        queue_list = list(song_queues[guild_id])
        
        # If there's currently playing song, don't shuffle it
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            current_song = queue_list.pop(0)
            random.shuffle(queue_list)
            queue_list.insert(0, current_song)
        else:
            random.shuffle(queue_list)
            
        # Clear the current queue and add shuffled songs
        song_queues[guild_id].clear()
        song_queues[guild_id].extend(queue_list)
        
        # Update last activity
        self.last_activity[ctx.guild.id] = datetime.now()
        
        # Show the new shuffled queue with titles
        async with ctx.typing():
            temp_ytdl = get_temp_ytdl()
            shuffled_titles = []
            for i, url in enumerate(queue_list):
                try:
                    # Extract title without downloading
                    info = await asyncio.to_thread(temp_ytdl.extract_info, url, download=False)
                    title = info.get('title', 'Unknown Title')
                    shuffled_titles.append(f"{i + 1}. {title}")
                except Exception as e:
                    shuffled_titles.append(f"{i + 1}. {url} (Could not fetch title)")
            
            formatted_queue = "\n".join(shuffled_titles)
            await ctx.send(f"**🎲 Queue has been shuffled!**\nNew queue order:\n{formatted_queue}")

async def setup(bot):
    await bot.add_cog(MusicCog(bot))
