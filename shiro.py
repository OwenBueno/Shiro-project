import os
import discord
from discord.ext import commands, tasks
import yt_dlp as youtube_dl
from collections import deque
from datetime import datetime, timedelta

# Set up intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

# Set up the bot with the intents and command prefix
bot = commands.Bot(command_prefix="!", intents=intents)

# Set up yt-dlp options
youtube_dl.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(title).100s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1',
    'source_address': '0.0.0.0',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '320'
    }],
    'extract_flat': True
}

ffmpeg_options = {
    'options': '-vn -b:a 320k -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 10000000 -http_persistent 1 -user_agent "Mozilla/5.0"'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

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

        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data, filename=filename)

# Dictionary to manage song queues and last activity per guild
song_queues = {}
last_activity = {}

# Background task to check if the bot is alone in the voice channel
@tasks.loop(minutes=1)
async def check_if_alone():
    for guild_id, vc in [(vc.guild.id, vc) for vc in bot.voice_clients]:
        if len(vc.channel.members) == 1 and vc.channel.members[0] == bot.user:
            if last_activity.get(guild_id) is None:
                last_activity[guild_id] = datetime.now()
            elif datetime.now() - last_activity[guild_id] > timedelta(minutes=5):
                await vc.disconnect()
                last_activity[guild_id] = None
        else:
            last_activity[guild_id] = None

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    check_if_alone.start()

# Function to play the next song in the queue
async def play_next(ctx):
    guild_id = ctx.guild.id

    # Check if the voice client is still connected
    if ctx.voice_client is None or not ctx.voice_client.is_connected():
        return  # Do not attempt to play if the bot is not connected to a voice channel

    if guild_id in song_queues and song_queues[guild_id]:
        next_url = song_queues[guild_id].popleft()
        player_data = await YTDLSource.from_url(next_url, loop=bot.loop, download=True)

        if isinstance(player_data, list):
            player_data = player_data[0]

        filename = player_data.filename

        def after_playing(error):
            if error:
                print(f'Player error: {error}')
            # Check again if the bot is still connected before trying to play next
            if ctx.voice_client and ctx.voice_client.is_connected():
                bot.loop.create_task(play_next(ctx))
            bot.loop.call_later(1, delete_file, filename)

        player = discord.FFmpegPCMAudio(filename, **ffmpeg_options)
        ctx.voice_client.play(player, after=after_playing)
        ctx.voice_client.current_song = filename  # Track the current song file
        await ctx.send(f'**Now playing:** {player_data.title}')
        last_activity[guild_id] = datetime.now()

# Function to delete the downloaded file
def delete_file(filename):
    try:
        if os.path.exists(filename):
            os.remove(filename)
            print(f"Deleted file: {filename}")
        else:
            print(f"File not found: {filename}")
    except Exception as e:
        print(f"Error deleting file {filename}: {e}")

# Command to join the voice channel
@bot.command(name='vente', help='Tells the bot to join the voice channel')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send("You are not connected to a voice channel.")
        return

    channel = ctx.message.author.voice.channel
    await channel.connect()
    last_activity[ctx.guild.id] = datetime.now()

# Command to leave the voice channel and clear downloaded files and the queue
@bot.command(name='vete', help='Makes the bot leave the voice channel and clears the music queue')
async def leave(ctx):
    voice_client = ctx.voice_client
    guild_id = ctx.guild.id

    if voice_client:
        # Stop playback if currently playing
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        # Clear the current downloaded file if available
        current_song = getattr(ctx.voice_client, 'current_song', None)
        if current_song:
            delete_file(current_song)

        # Disconnect the bot from the voice channel
        await voice_client.disconnect()

        # Clear last activity for the guild
        last_activity.pop(guild_id, None)

        # Clear the song queue completely
        if guild_id in song_queues:
            song_queues[guild_id].clear()

        await ctx.send("**Disconnected and cleared the queue.**")

@bot.command(name='canta', help='Joins the voice channel and plays a song by URL, searches for the song name, or plays a playlist')
async def play(ctx, *, query):
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
            # Extract minimal metadata (do not download) to quickly get playlist or video details
            extract_flat_opts = ytdl_format_options.copy()
            extract_flat_opts['extract_flat'] = 'in_playlist'
            temp_ytdl = youtube_dl.YoutubeDL(extract_flat_opts)

            data = await bot.loop.run_in_executor(None, lambda: temp_ytdl.extract_info(query, download=False))
            
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
                    bot.loop.create_task(add_remaining_songs())

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
@bot.command(name='salta', help='Skips the current song and plays the next one in the queue if available')
async def skip(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        await ctx.send("There is no song playing to skip.")
    else:
        voice_client.stop()
        await ctx.send("**Song has been skipped.**")

# Command to pause the music
@bot.command(name='yamete', help='Pauses the song')
async def stop(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_playing():
        await ctx.send("There is no song currently playing to pause.")
    else:
        voice_client.pause()  # Pause the current playback
        await ctx.send("**Playback has been paused.**")

# Command to resume the music
@bot.command(name='kudasai', help='Resumes the paused song')
async def resume(ctx):
    voice_client = ctx.voice_client
    if not voice_client or not voice_client.is_paused():
        await ctx.send("There is no paused song to resume.")
    else:
        voice_client.resume()  # Resume the paused playback
        await ctx.send("**Playback has been resumed.**")

# Command to show the current queue
@bot.command(name='cola', help='Displays the current music queue')
async def show_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id not in song_queues or not song_queues[guild_id]:
        await ctx.send("The queue is currently empty.")
    else:
        queue_list = "\n".join([f"{i + 1}. {url}" for i, url in enumerate(song_queues[guild_id])])
        await ctx.send(f"**Current queue:**\n{queue_list}")

bot.run('#')
# #