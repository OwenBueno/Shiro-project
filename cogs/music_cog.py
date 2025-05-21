# bot/cogs/music_cog.py
import discord
from discord import app_commands
from discord.ext import commands, tasks
from utils.ytdl_source import YTDLSource, get_temp_ytdl, ytdl as global_ytdl
from collections import deque
from utils.delete_utils import delete_file
from config import FFMPEG_OPTIONS, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from datetime import datetime, timedelta
import asyncio
import random
import re
from utils.spotify_client import get_spotify_playlist_tracks, get_spotify_album_tracks, get_spotify_track_info
import logging
from typing import Optional, Dict, NamedTuple, Deque, Tuple, List
import yt_dlp.utils

logger = logging.getLogger(__name__)

class SongQueueItem(NamedTuple):
    url: str  # URL for YTDLSource (original query for search, or resolved URL)
    title: Optional[str]
    webpage_url: Optional[str] # Direct URL to the song's page
    thumbnail: Optional[str]
    duration: Optional[int] # in seconds
    uploader: Optional[str]
    requester_mention: str
    requester_id: int
    # Note: 'filename' is not stored here as it's determined at download time by YTDLSource

# --- BEGIN INTERACTIVE NOW PLAYING VIEW --- #
class NowPlayingView(discord.ui.View):
    def __init__(self, music_cog_instance, interaction_context, timeout=None): # Timeout None for persistent if message is kept
        super().__init__(timeout=timeout)
        self.music_cog = music_cog_instance
        self.interaction_context = interaction_context # Original interaction that started play or context
        self.message: Optional[discord.Message] = None # To store the message this view is attached to
        self.loop_current_song = False # Simple loop state for the current song

        # Update button states (e.g., pause/resume)
        self.update_buttons()

    def update_buttons(self):
        # Pause/Resume button update
        vc = self.interaction_context.guild.voice_client
        if vc and vc.is_playing() and not vc.is_paused():
            self.pause_resume_button.label = "Pause"
            self.pause_resume_button.emoji = "⏯️"
            self.pause_resume_button.style = discord.ButtonStyle.secondary
        else:
            self.pause_resume_button.label = "Resume"
            self.pause_resume_button.emoji = "▶️"
            self.pause_resume_button.style = discord.ButtonStyle.success
        
        # Loop button update (simple example)
        if self.loop_current_song:
            self.loop_button.style = discord.ButtonStyle.primary # Indicate active loop
        else:
            self.loop_button.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only users in the same voice channel (or the requester) can use controls."""
        if not interaction.user.voice or interaction.user.voice.channel != interaction.guild.voice_client.channel:
            await interaction.response.send_message("You need to be in the same voice channel as the bot to use these controls!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.secondary, emoji="⏯️", row=0)
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)
            return

        if vc.is_playing() and not vc.is_paused():
            vc.pause()
            await interaction.response.send_message("Playback paused. ⏸️", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("Playback resumed! ▶️", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is currently playing to pause/resume.", ephemeral=True)
        self.update_buttons()
        await self.message.edit(view=self) # Update the view on the original message

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭️", row=0)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc or (not vc.is_playing() and not vc.is_paused()):
            await interaction.response.send_message("Nothing to skip.", ephemeral=True)
            return
        vc.stop() # This will trigger the after_playing callback in _play_next
        await interaction.response.send_message("Skipped to the next song! ⏭️", ephemeral=True)
        # The view might be removed by _play_next if queue ends, or updated if new song plays

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=0)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        guild_id = interaction.guild_id
        if not vc:
            await interaction.response.send_message("Bot is not in a voice channel.", ephemeral=True)
            return

        if guild_id in self.music_cog.song_queues:
            self.music_cog.song_queues[guild_id].clear()
        
        vc.stop() # Stops current playback
        # await vc.disconnect() # Disconnecting here might be too abrupt, let check_if_alone handle it or a dedicated leave command.
        # For now, stop just clears queue and stops player. User can use /leave

        await interaction.response.send_message("Playback stopped and queue cleared. ⏹️", ephemeral=True)
        if self.message:
            try:
                await self.message.edit(view=None) # Remove buttons after stopping
                await self.message.delete(delay=10) # Optionally delete the message after a delay
            except discord.NotFound:
                pass # Message might have been deleted already
        self.stop() # Stop the view itself

    @discord.ui.button(label="Loop", style=discord.ButtonStyle.secondary, emoji="🔁", row=1)
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.loop_current_song = not self.loop_current_song
        if self.loop_current_song:
            await interaction.response.send_message("Looping the current song! 🔁", ephemeral=True)
        else:
            await interaction.response.send_message("Stopped looping current song.", ephemeral=True)
        self.update_buttons()
        await self.message.edit(view=self)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.secondary, emoji="🎶", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        queue_messages = []
        current_song_display = "Nothing currently playing."
        vc = interaction.guild.voice_client

        # current_song_title is a fallback, ideally we'd have the full current SongQueueItem if possible
        # For now, keeping existing logic for currently playing display via vc.current_song_title
        if vc and (vc.is_playing() or vc.is_paused()) and hasattr(vc, 'current_song_title') and vc.current_song_title:
            current_song_display = f"**Currently Playing:** {vc.current_song_title}"
        queue_messages.append(current_song_display)

        if guild_id not in self.music_cog.song_queues or not self.music_cog.song_queues[guild_id]:
            queue_messages.append("The queue is currently empty. 텅 비었어요!")
        else:
            queue_messages.append("**Up next:**")
            for i, song_item in enumerate(list(self.music_cog.song_queues[guild_id])):
                if i >= 5: # Limit display for ephemeral message
                    queue_messages.append(f"... and {len(self.music_cog.song_queues[guild_id]) - i} more.")
                    break
                title = song_item.title or "Unknown Title" # Use stored title
                queue_messages.append(f"{i + 1}. {title}")
        
        await interaction.response.send_message("\n".join(queue_messages), ephemeral=True)

# --- END INTERACTIVE NOW PLAYING VIEW --- #

class MusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.song_queues: Dict[int, Deque[SongQueueItem]] = {} # Updated type hint
        self.last_activity = {}
        self.now_playing_messages: Dict[int, discord.Message] = {} # Stores guild_id: now_playing_message
        self.active_views: Dict[int, NowPlayingView] = {} # guild_id: active_view_instance

    async def _cleanup_now_playing(self, guild_id: int):
        if guild_id in self.now_playing_messages:
            old_message = self.now_playing_messages.pop(guild_id)
            try:
                await old_message.edit(view=None) # Remove buttons
                # Optionally delete the message after a delay or keep it
                # await old_message.delete(delay=5)
            except discord.NotFound:
                pass # Message was already deleted
            except Exception as e:
                logger.error(f"Error cleaning up old Now Playing message for guild {guild_id}: {e}")
        if guild_id in self.active_views:
            view = self.active_views.pop(guild_id)
            view.stop() # Stop the view to disable buttons

    async def _play_next(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        voice_client = interaction.guild.voice_client

        await self._cleanup_now_playing(guild_id) # Clean up previous Now Playing message/view

        if voice_client is None or not voice_client.is_connected():
            if guild_id in self.song_queues: self.song_queues[guild_id].clear()
            return

        active_view = self.active_views.get(guild_id)
        if active_view and active_view.loop_current_song and hasattr(voice_client, 'current_song_item_for_loop') and voice_client.current_song_item_for_loop:
             # If loop current song is active, add it back to the front of the queue
            self.song_queues[guild_id].appendleft(voice_client.current_song_item_for_loop)
            # Reset loop state after adding to front, so it doesn't loop indefinitely if skip is used
            # Or, manage loop state more robustly based on user intent (e.g. explicit /loop off command)
            # For this button, let's assume if they skip/song ends, loop for *that specific instance* is done.
            # active_view.loop_current_song = False # This would turn off loop after one replay

        if guild_id in self.song_queues and self.song_queues[guild_id]:
            while self.song_queues[guild_id]:
                current_song_item = self.song_queues[guild_id].popleft()
                next_url_to_process = current_song_item.url # URL to pass to YTDLSource
                
                downloaded_player_data = None
                filename_for_deletion_on_error = None
                
                try:
                    # YTDLSource.from_url will download the song. 
                    # Metadata for the embed is already in current_song_item
                    player_data = await YTDLSource.from_url(next_url_to_process, download=True)
                    downloaded_player_data = player_data
                    if isinstance(player_data, list): # Should not happen if we process one URL at a time
                        # This case might indicate an issue if from_url returns a playlist here.
                        # For now, assume we're getting a single song's source.
                        logger.warning(f"YTDLSource.from_url returned a list for {next_url_to_process}, using first item.")
                        player_data = player_data[0] 
                    
                    filename = player_data.filename
                    filename_for_deletion_on_error = filename

                    # Create Now Playing Embed & View using info from SongQueueItem
                    embed = discord.Embed(title="🎶 ¡Now playing! 🎵", color=discord.Color.random())
                    
                    # Use title and webpage_url from SongQueueItem, fallback to player_data if needed (though ideally not)
                    track_title = current_song_item.title or player_data.title
                    track_webpage_url = current_song_item.webpage_url or player_data.webpage_url or next_url_to_process
                    embed.add_field(name="Track", value=f"[{track_title}]({track_webpage_url})", inline=False)

                    if current_song_item.uploader:
                        embed.add_field(name="Artist/Uploader", value=current_song_item.uploader, inline=True)
                    
                    duration_seconds = current_song_item.duration
                    if duration_seconds:
                        m, s = divmod(duration_seconds, 60)
                        h, m = divmod(m, 60)
                        # Ensure h, m, s are integers for formatting
                        h = int(h)
                        m = int(m)
                        s = int(s)
                        duration_formatted = f"{m:02d}:{s:02d}" # Start with M:S
                        if h > 0: duration_formatted = f"{h:d}:{m:02d}:{s:02d}"
                        embed.add_field(name="Duración", value=duration_formatted, inline=True)
                    else:
                        embed.add_field(name="Duración", value="N/A (Livestream?)", inline=True)

                    embed.add_field(name="En cola", value=f"{len(self.song_queues[guild_id])} canciones", inline=True)
                    
                    if current_song_item.thumbnail:
                        embed.set_thumbnail(url=current_song_item.thumbnail)
                    elif player_data.thumbnail: # Fallback to thumbnail from player_data if SongQueueItem doesn't have one
                        embed.set_thumbnail(url=player_data.thumbnail)
                    
                    embed.add_field(name="Pedido por", value=current_song_item.requester_mention, inline=False)
                    embed.set_footer(text=f"Shiro Music | {interaction.guild.name}")
                    embed.timestamp = datetime.utcnow()

                    current_view = NowPlayingView(music_cog_instance=self, interaction_context=interaction)
                    self.active_views[guild_id] = current_view

                    # Send the Now Playing message and store it
                    now_playing_msg = await interaction.channel.send(embed=embed, view=current_view)
                    current_view.message = now_playing_msg # Give the view a reference to its message
                    self.now_playing_messages[guild_id] = now_playing_msg

                    async def tasks_after_playing(error):
                        original_filename_for_deletion = filename 
                        
                        if error:
                            logger.error(f'Player error for {original_filename_for_deletion}: {error}')
                            if interaction.channel:
                                try: await interaction.followup.send(f"Error playing {original_filename_for_deletion[:50]}...", ephemeral=True)
                                except: pass
                        
                        if original_filename_for_deletion:
                            try:
                                await self.bot.loop.run_in_executor(None, delete_file, original_filename_for_deletion, True)
                                logger.info(f"Successfully requested deletion of {original_filename_for_deletion} via executor.")
                            except Exception as e:
                                logger.error(f"Error requesting deletion of file {original_filename_for_deletion} via executor: {e}")
                        
                        # If not looping current song OR if loop is on but song ended naturally (not skipped)
                        # The current active_view might be outdated if a new command was issued fast.
                        # Fetch the latest view for this guild.
                        latest_view_for_guild = self.active_views.get(guild_id)
                        if latest_view_for_guild and latest_view_for_guild.loop_current_song and not error and voice_client.is_connected():
                            # Re-add current song to front if loop is on AND song finished without error
                            # This means it should replay. _play_next will pop it again.
                            logger.info(f"Looping current song: {current_song_item.title}")
                            self.song_queues[guild_id].appendleft(voice_client.current_song_item_for_loop) # Use the stored item
                            # No need to change latest_view_for_guild.loop_current_song here, user toggles it.
                        else:
                            # If loop was on but an error occurred, or if skip happened, or loop is off, effectively turn off loop for this instance.
                            if latest_view_for_guild:
                                pass # loop_current_song state is managed by button

                        current_vc = interaction.guild.voice_client
                        if current_vc and current_vc.is_connected():
                            await self._play_next(interaction) 

                    def sync_after_callback(error):
                        self.bot.loop.create_task(tasks_after_playing(error))
                    
                    player_audio_source = discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS)
                    voice_client.play(player_audio_source, after=sync_after_callback)
                    voice_client.current_song = filename # Still keep track of filename for deletion
                    voice_client.current_song_title = current_song_item.title or player_data.title # For /queue display if needed as fallback
                    voice_client.current_song_item_for_loop = current_song_item # Store the entire SongQueueItem for loop
                    
                    if interaction.channel: # Redundant message, embed is better
                        # Consider removing this or making it optional, as the embed is richer
                        # await interaction.channel.send(f'**Now playing:** {current_song_item.title or player_data.title}')
                        pass

                    self.last_activity[guild_id] = datetime.now()
                    current_view.update_buttons() # Ensure buttons are correct after play starts
                    if current_view.message:
                         try: await current_view.message.edit(view=current_view)
                         except discord.NotFound: pass
                    return
                
                except yt_dlp.utils.DownloadError as e:
                    error_message = str(e).lower()
                    # Construct a more detailed log message
                    detailed_error_log = f"DownloadError: {str(e)}"
                    msg_to_send = "**Error:** Could not download the song."

                    if "http error 403" in error_message or "forbidden" in error_message:
                        msg_to_send = "**Error:** Skipped song (403 Forbidden). This video might be private, age-restricted, or unavailable in your region."
                    elif "video unavailable" in error_message:
                        msg_to_send = "**Error:** Skipped song (Video unavailable)."
                    # Add more specific DownloadError checks if needed
                    
                    if interaction.channel:
                        try: await interaction.channel.send(msg_to_send)
                        except discord.HTTPException:
                            logger.warning(f"Failed to send DownloadError message to channel for guild {guild_id}")
                    
                    logger.error(
                        f"Skipping song '{current_song_item.title}' ({next_url_to_process}) due to DownloadError. Details: {str(e)}",
                        exc_info=False
                    )

                    # Cleanup for DownloadError is similar to generic Exception
                    if filename_for_deletion_on_error:
                        try:
                            logger.info(f"Attempting to delete {filename_for_deletion_on_error} due to DownloadError.")
                            await self.bot.loop.run_in_executor(None, delete_file, filename_for_deletion_on_error, True)
                        except Exception as del_e:
                            logger.error(f"Error deleting {filename_for_deletion_on_error} (DownloadError): {del_e}")
                    elif downloaded_player_data and hasattr(downloaded_player_data, 'filename') and downloaded_player_data.filename:
                        try:
                            logger.info(f"Attempting to delete (fallback) {downloaded_player_data.filename} due to DownloadError.")
                            await self.bot.loop.run_in_executor(None, delete_file, downloaded_player_data.filename, True)
                        except Exception as del_e:
                             logger.error(f"Error deleting (fallback) {downloaded_player_data.filename} (DownloadError): {del_e}")
                    continue # Try next song in queue

                except Exception as e:
                    error_message = str(e).lower()
                    # Construct a more detailed log message
                    detailed_error_log = f"Error type: {type(e).__name__}, Message: {str(e)}"
                    msg_to_send = f"Error processing song: {error_message[:100]}" # Keep user-facing message brief

                    # General error messages (some might be redundant if DownloadError caught it first, but kept for safety)
                    if "http error 403" in error_message or "forbidden" in error_message: # Should be caught by DownloadError primarily
                        msg_to_send = f"**Error:** Skipped song (403 Forbidden). It might be private or unavailable."
                    elif "unable to download" in error_message: # Also likely caught by DownloadError
                         msg_to_send = f"**Error:** Skipped song (download issue). It might be unavailable."
                    elif "video unavailable" in error_message: # Also likely caught by DownloadError
                        msg_to_send = f"**Error:** Skipped song (video unavailable)."
                    # Add more specific error checks based on common YTDLSource issues if needed

                    if interaction.channel:
                        try: await interaction.channel.send(msg_to_send)
                        except discord.HTTPException:
                             logger.warning(f"Failed to send generic error message to channel for guild {guild_id}")
                    
                    # Log the detailed error
                    logger.error(f"Generic error in _play_next for {next_url_to_process}: {detailed_error_log}", exc_info=True) 
                    
                    if filename_for_deletion_on_error:
                        try:
                            logger.info(f"Attempting to delete {filename_for_deletion_on_error} due to generic error.")
                            await self.bot.loop.run_in_executor(None, delete_file, filename_for_deletion_on_error, True)
                        except Exception as del_e:
                            logger.error(f"Error deleting {filename_for_deletion_on_error} (generic error): {del_e}")
                    elif downloaded_player_data and hasattr(downloaded_player_data, 'filename') and downloaded_player_data.filename:
                        try:
                            logger.info(f"Attempting to delete (fallback) {downloaded_player_data.filename} due to generic error.")
                            await self.bot.loop.run_in_executor(None, delete_file, downloaded_player_data.filename, True)
                        except Exception as del_e:
                             logger.error(f"Error deleting (fallback) {downloaded_player_data.filename} (generic error): {del_e}")
                    continue # Try next song in queue

        if guild_id in self.song_queues and not self.song_queues[guild_id]:
            if interaction.channel:
                try: await interaction.channel.send("**Queue finished:** No more songs to play.")
                except: pass
            self.last_activity[guild_id] = datetime.now()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f'{self.bot.user} has connected to Discord! MusicCog loaded.')
        if not self.check_if_alone.is_running():
            self.check_if_alone.start()

    @tasks.loop(minutes=1)
    async def check_if_alone(self):
        for guild_id, vc in [(g.id, g.voice_client) for g in self.bot.guilds if g.voice_client and g.voice_client.is_connected()]:
            if len(vc.channel.members) == 1 and vc.channel.members[0] == self.bot.user: # Bot is alone
                if guild_id not in self.last_activity or self.last_activity[guild_id] is None:
                    self.last_activity[guild_id] = datetime.now()
                    logger.info(f"Bot is now alone in guild {guild_id}. Starting 5-minute inactivity timer.")
                elif datetime.now() - self.last_activity[guild_id] > timedelta(minutes=5): # Changed to 5 minutes
                    logger.info(f"Bot has been alone and inactive in guild {guild_id} for over 5 minutes. Disconnecting.")
                    if vc.is_playing() or vc.is_paused():
                        vc.stop()
                    
                    current_song_filename = getattr(vc, 'current_song', None)
                    if current_song_filename:
                        try:
                            await self.bot.loop.run_in_executor(None, delete_file, current_song_filename, True)
                            logger.info(f"Requested deletion of {current_song_filename} in check_if_alone via executor.")
                            vc.current_song = None
                            vc.current_song_title = None
                        except Exception as e:
                            logger.error(f"Error requesting deletion of file {current_song_filename} in check_if_alone via executor: {e}")
                    
                    if guild_id in self.song_queues:
                        self.song_queues[guild_id].clear()
                    
                    await vc.disconnect(force=True)
                    self.last_activity[guild_id] = None # Reset after disconnecting
                    logger.info(f"Bot disconnected from guild {guild_id} due to inactivity.") # Kept original log, context is clear
            else: # Bot is NOT alone
                if guild_id in self.last_activity and self.last_activity[guild_id] is not None:
                    logger.info(f"Bot is no longer alone in guild {guild_id}. Cancelling inactivity timer.")
                    self.last_activity[guild_id] = None

    @app_commands.command(name='join', description='Tells the bot to join your voice channel')
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
            return
        channel = interaction.user.voice.channel
        if interaction.guild.voice_client is not None:
            await interaction.guild.voice_client.move_to(channel)
            await interaction.response.send_message(f"Moved to {channel.mention}", ephemeral=True)
        else:
            await channel.connect()
            await interaction.response.send_message(f"Joined {channel.mention}", ephemeral=True)
        self.last_activity[interaction.guild_id] = datetime.now()

    @app_commands.command(name='leave', description='Makes the bot leave the voice channel and clears the queue')
    async def leave(self, interaction: discord.Interaction):
        await self._cleanup_now_playing(interaction.guild_id)
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id

        if voice_client:
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()

            current_song = getattr(voice_client, 'current_song', None)
            if current_song:
                try:
                    voice_client.current_song = None 
                except Exception as e:
                    print(f"Error trying to clear current_song attribute: {e}")

            await voice_client.disconnect(force=True)
            self.last_activity.pop(guild_id, None)

            if guild_id in self.song_queues:
                self.song_queues[guild_id].clear()

            await interaction.response.send_message("**Disconnected and cleared the queue.**")
        else:
            await interaction.response.send_message("The bot is not connected to a voice channel.", ephemeral=True)

    # Helper to create SongQueueItem from ytdl data
    def _create_song_item_from_ytdl_data(self, data: dict, requester_mention: str, requester_id: int, query_url: str) -> Optional[SongQueueItem]:
        title = data.get('title')
        webpage_url = data.get('webpage_url', data.get('url')) # prefer webpage_url, fallback to url
        thumbnail = data.get('thumbnail')
        duration = data.get('duration')
        uploader = data.get('uploader')
        # If the initial query was a search, ytdl might give a direct stream url in data.get('url')
        # but we want to store the original query (or resolved webpage_url) for ytdl to re-process later in _play_next
        # If it's a direct link, webpage_url should be correct.
        # query_url is the url passed to extract_info initially.
        # For ytsearch, data.get('webpage_url') is what we need for YTDLSource in _play_next.
        # For direct links, data.get('webpage_url') or query_url are fine.
        url_to_store = data.get('webpage_url') or query_url # This is what YTDLSource will use

        if not title or not url_to_store:
            logger.warning(f"Missing title or URL for data: {data.get('id', 'N/A')}")
            return None

        return SongQueueItem(
            url=url_to_store, # This URL is fed to YTDLSource.from_url in _play_next
            title=title,
            webpage_url=webpage_url, # For display
            thumbnail=thumbnail,
            duration=duration,
            uploader=uploader,
            requester_mention=requester_mention,
            requester_id=requester_id
        )

    @app_commands.command(name='play', description='Plays a song or adds it to the queue. Accepts URL (YouTube/Spotify) or search query.')
    @app_commands.describe(query="Song URL (YouTube/Spotify playlist/album/track) or search query")
    async def play(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer() 
        guild_id = interaction.guild_id
        user_voice = interaction.user.voice
        requester_mention = interaction.user.mention
        requester_id = interaction.user.id

        if not user_voice:
            await interaction.followup.send("You need to be in a voice channel to use this command.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if voice_client is None:
            try:
                voice_client = await user_voice.channel.connect()
            except Exception as e:
                logger.error(f"Failed to connect to voice channel {user_voice.channel.name}: {e}")
                await interaction.followup.send("Could not join your voice channel.", ephemeral=True)
                return
        elif voice_client.channel != user_voice.channel:
            await interaction.followup.send("You must be in the same voice channel as the bot.", ephemeral=True)
            return

        if guild_id not in self.song_queues: self.song_queues[guild_id] = deque()
        
        # Updated regexes to include albums and tracks
        spotify_playlist_match = re.match(r"https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)(\?si=[a-zA-Z0-9]+)?", query)
        spotify_album_match = re.match(r"https?://open\.spotify\.com/album/([a-zA-Z0-9]+)(\?si=[a-zA-Z0-9]+)?", query)
        spotify_track_match = re.match(r"https?://open\.spotify\.com/track/([a-zA-Z0-9]+)(\?si=[a-zA-Z0-9]+)?", query)
        
        temp_ytdl = get_temp_ytdl()

        items_added_to_queue: list[SongQueueItem] = []
        spotify_source_name: Optional[str] = None # To store playlist or album name for feedback
        spotify_tracks_to_process: Optional[List[Dict[str, str]]] = None
        is_spotify_query = False

        if spotify_playlist_match:
            is_spotify_query = True
            playlist_id = spotify_playlist_match.group(1)
            spotify_result = await get_spotify_playlist_tracks(playlist_id)
            if spotify_result:
                spotify_source_name, spotify_tracks_to_process = spotify_result
        elif spotify_album_match:
            is_spotify_query = True
            album_id = spotify_album_match.group(1)
            spotify_result = await get_spotify_album_tracks(album_id)
            if spotify_result:
                spotify_source_name, spotify_tracks_to_process = spotify_result
        elif spotify_track_match:
            is_spotify_query = True
            track_id = spotify_track_match.group(1)
            spotify_result = await get_spotify_track_info(track_id) # Returns Tuple[str, List[Dict[str, str]]]
            if spotify_result:
                 # For a single track, the "source name" is the track's name.
                spotify_source_name, spotify_tracks_to_process = spotify_result
        
        if is_spotify_query:
            if spotify_tracks_to_process is None: # Failed to fetch from Spotify
                if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
                    await interaction.followup.send("**Error:** Spotify support is not configured by the bot owner.", ephemeral=True)
                else:
                    await interaction.followup.send(f"**Error:** Could not fetch Spotify information for the provided link.", ephemeral=True)
                return

            if not spotify_tracks_to_process:
                source_type = "playlist" if spotify_playlist_match else "album" if spotify_album_match else "track"
                await interaction.followup.send(f"The Spotify {source_type} \'{spotify_source_name or 'Unknown'}\' appears to be empty or contains no processable tracks.", ephemeral=True)
                return

            # Use a more generic source type for messages
            display_source_type = "playlist"
            if spotify_album_match: display_source_type = "album"
            elif spotify_track_match: display_source_type = "track"
            
            await interaction.followup.send(f"🎧 Processing Spotify {display_source_type}: **{spotify_source_name or 'link'}**. This may take a moment...", ephemeral=True)
            
            processed_spotify_tracks = 0
            skipped_spotify_tracks = 0

            async def process_spotify_track_to_ytdl_item(track: Dict[str, str]) -> Optional[str]: # Return title for feedback
                nonlocal processed_spotify_tracks, skipped_spotify_tracks
                search_query = f"{track['name']} {track['artist']} audio" # Simplified search query
                try:
                    # Use the global_ytdl instance here for full metadata extraction
                    yt_search_data = await asyncio.to_thread(global_ytdl.extract_info, f"ytsearch1:{search_query}", download=False)
                    if yt_search_data and 'entries' in yt_search_data and yt_search_data['entries']:
                        first_entry = yt_search_data['entries'][0]
                        song_item = self._create_song_item_from_ytdl_data(first_entry, requester_mention, requester_id, first_entry.get('webpage_url'))
                        if song_item:
                            items_added_to_queue.append(song_item)
                            processed_spotify_tracks += 1
                            return song_item.title 
                        else:
                            skipped_spotify_tracks +=1
                            logger.warning(f"Could not create SongQueueItem for Spotify track: {track['name']} (Searched: {search_query})")
                            return None
                    else:
                        logger.warning(f"No YouTube match for Spotify track: {track['name']} (Searched: {search_query})")
                        skipped_spotify_tracks += 1
                        return None
                except Exception as e:
                    logger.error(f"Error processing Spotify track \'{track['name']}\' for YouTube (Searched: {search_query}): {e}", exc_info=True)
                    skipped_spotify_tracks += 1
                    return None

            # Limit processing for playlists/albums, single tracks are just one item.
            max_spotify_tracks_to_process = 25 if (spotify_playlist_match or spotify_album_match) else 1
            spotify_processing_tasks = [process_spotify_track_to_ytdl_item(track) for track in spotify_tracks_to_process[:max_spotify_tracks_to_process]]
            
            await asyncio.gather(*spotify_processing_tasks)

            if items_added_to_queue:
                self.song_queues[guild_id].extend(items_added_to_queue)
                feedback_message = f"✅ Added **{processed_spotify_tracks}** track(s) from Spotify {display_source_type}: **{spotify_source_name or ''}**."
                if len(spotify_tracks_to_process) > max_spotify_tracks_to_process:
                    feedback_message += f" (Processed first {max_spotify_tracks_to_process} of {len(spotify_tracks_to_process)} tracks)."
                if skipped_spotify_tracks > 0:
                    feedback_message += f" ({skipped_spotify_tracks} skipped due to errors/no match.)"
                await interaction.channel.send(feedback_message)
            elif skipped_spotify_tracks > 0 and processed_spotify_tracks == 0:
                 await interaction.channel.send(f"⚠️ No tracks from Spotify {display_source_type} \'{spotify_source_name or ''}\' could be added.")
            # else: # This case means spotify_tracks_to_process was empty or all failed silently (already handled)
            #    await interaction.channel.send(f"No tracks processed from Spotify {display_source_type} \'{spotify_source_name or ''}\'.")

        else: # YouTube URL, YouTube Playlist, or direct search query (non-Spotify)
            try:
                # temp_ytdl is configured with extract_flat: 'in_playlist' by get_temp_ytdl()
                # This single call handles single videos/searches and also extracts playlist entries flatly.
                ytdl_info = await asyncio.to_thread(temp_ytdl.extract_info, query, download=False)

                if not ytdl_info:
                    await interaction.followup.send("Could not fetch information for your query. The source might be unavailable or the URL incorrect.", ephemeral=True)
                    logger.warning(f"yt-dlp returned no data for query: {query}")
                    return

                if 'entries' in ytdl_info: # Indicates a playlist
                    playlist_title = ytdl_info.get('title', 'a YouTube Playlist')
                    # Ensure ephemeral followup is sent before non-ephemeral channel messages if interaction is new
                    if not interaction.response.is_done():
                        await interaction.followup.send(f"💿 Processing YouTube playlist: **{playlist_title}**. This may take a moment...", ephemeral=True)
                    else: # If followup already used (e.g., by defer()), send to channel and also log
                        await interaction.channel.send(f"💿 Processing YouTube playlist: **{playlist_title}**. This may take a moment...")
                    
                    entries = ytdl_info.get('entries')
                    if not entries: # Playlist has an 'entries' key, but it's None or an empty list
                        await interaction.channel.send(f"YouTube playlist '**{playlist_title}**' appears to be empty or its entries are unreadable.")
                        return

                    playlist_items_added = []
                    for entry_data in entries[:75]: # Process up to 75 entries
                        if not entry_data: 
                            logger.warning(f"Skipping a null/empty entry in playlist '{playlist_title}'")
                            continue
                        
                        # The 'url' from a flat extract entry is the video's webpage URL.
                        video_webpage_url = entry_data.get('url')
                        if not video_webpage_url:
                            logger.warning(f"Playlist entry in '{playlist_title}' is missing its 'url'. Entry ID: {entry_data.get('id', 'N/A')}")
                            continue
                        
                        song_item = self._create_song_item_from_ytdl_data(entry_data, requester_mention, requester_id, video_webpage_url)
                        if song_item:
                            playlist_items_added.append(song_item)
                        else:
                            logger.warning(f"Failed to create SongQueueItem for entry in '{playlist_title}'. Entry ID: {entry_data.get('id', 'N/A')}, Title: `{entry_data.get('title')}`, URL: `{video_webpage_url}`. This usually means title or a valid URL was missing in the entry data.")

                    if playlist_items_added:
                        self.song_queues[guild_id].extend(playlist_items_added)
                        items_added_to_queue.extend(playlist_items_added) # For the final _play_next check
                        await interaction.channel.send(f"✅ Added **{len(playlist_items_added)}** tracks from YouTube playlist: **{playlist_title}**.")
                    else:
                        # This message is hit if loop completes with no items added
                        await interaction.channel.send(f"No tracks could be added from YouTube playlist: **{playlist_title}**. This might be due to missing information (like titles) for the playlist items.")
                
                else: # Single video or search result (ytdl_info is the video info)
                    song_item = self._create_song_item_from_ytdl_data(ytdl_info, requester_mention, requester_id, query) 
                    if song_item:
                        self.song_queues[guild_id].append(song_item)
                        items_added_to_queue.append(song_item)
                        # Consistent feedback: followup if possible, else channel message.
                        feedback_message = f'**Added to queue:** {song_item.title}'
                        if not interaction.response.is_done():
                             await interaction.followup.send(feedback_message)
                        else:
                             await interaction.channel.send(feedback_message)
                    else:
                        user_error_msg = "Could not process your request. No valid song data found from the provided link/query."
                        if not interaction.response.is_done():
                            await interaction.followup.send(user_error_msg, ephemeral=True)
                        else:
                             await interaction.channel.send(user_error_msg, ephemeral=True) # Should be rare
                        return

            except Exception as e: # General error handling for the try block
                error_message = str(e)
                user_friendly_error = "An unexpected error occurred while processing your request."
                if "Unsupported URL" in error_message: user_friendly_error = "**Error:** Unsupported URL."
                elif "HTTP Error 403" in error_message: user_friendly_error = "**Error:** Access denied (403)."
                elif "HTTP Error 404" in error_message: user_friendly_error = "**Error:** Video not found (404)."
                elif "No video formats found" in error_message: user_friendly_error = "**Error:** No audio found."
                logger.error(f"Error in play command for query '{query}': {e}", exc_info=True)
                await interaction.followup.send(user_friendly_error, ephemeral=True)
                return 

        # Common logic after adding items
        if items_added_to_queue and not voice_client.is_playing() and not voice_client.is_paused():
            # If the initial interaction was from a slash command, pass it to _play_next
            # If _play_next was called from a button, it might need a different interaction context.
            # For simplicity, we use the current /play interaction context.
            await self._play_next(interaction) 
        elif not items_added_to_queue and interaction.response.is_done() and not spotify_playlist_match: # If no songs were added and we haven't sent a specific message.
            # Avoid sending this if a specific error message was already sent by Spotify or playlist logic.
            # Check if an ephemeral message was already sent by followup
            # This path might be hit if _create_song_item_from_ytdl_data returned None for a single track and no error was caught prior
            if not interaction.is_expired(): # Check if we can still send a followup
                try:
                    # Check if anything was sent on the followup already. This is a bit tricky.
                    # A more robust way would be to track if a followup has been used for specific errors.
                    # For now, assume if items_added_to_queue is empty and it's not Spotify, an error occurred or nothing was found.
                    # The specific error messages should have been sent already in most cases.
                    pass # Most specific errors or success messages are handled within the if/else blocks
                except discord.NotFound: # Interaction may have expired
                    pass 

        self.last_activity[guild_id] = datetime.now()

    @app_commands.command(name='skip', description='Skips the current song')
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild_id
        if not voice_client or (not voice_client.is_playing() and not voice_client.is_paused()):
            await interaction.response.send_message("There is no song playing to skip.", ephemeral=True)
        else:
            voice_client.stop()
            self.last_activity[guild_id] = datetime.now()
            await interaction.response.send_message("**Song has been skipped.**", ephemeral=True)

    @app_commands.command(name='pause', description='Pauses the current song')
    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_playing():
            await interaction.response.send_message("There is no song currently playing to pause.", ephemeral=True)
        else:
            voice_client.pause()
            self.last_activity[interaction.guild_id] = datetime.now()
            active_view = self.active_views.get(interaction.guild_id)
            if active_view:
                active_view.update_buttons()
                if active_view.message: await active_view.message.edit(view=active_view)
            await interaction.response.send_message("**Playback has been paused.** ⏸️", ephemeral=True)

    @app_commands.command(name='resume', description='Resumes the paused song')
    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_paused():
            await interaction.response.send_message("There is no paused song to resume.", ephemeral=True)
        else:
            voice_client.resume()
            self.last_activity[interaction.guild_id] = datetime.now()
            active_view = self.active_views.get(interaction.guild_id)
            if active_view:
                active_view.update_buttons()
                if active_view.message: await active_view.message.edit(view=active_view)
            await interaction.response.send_message("**Playback has been resumed.** ▶️", ephemeral=True)

    @app_commands.command(name='queue', description='Displays the current music queue')
    async def show_queue(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild_id
        
        queue_messages = []
        current_song_display = "Nothing currently playing."
        voice_client = interaction.guild.voice_client

        # vc.current_song_title is a fallback. If current_song_item_for_loop exists and has a title, prefer that.
        current_title_to_display = "Nothing currently playing."
        if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
            if hasattr(voice_client, 'current_song_item_for_loop') and voice_client.current_song_item_for_loop and voice_client.current_song_item_for_loop.title:
                current_title_to_display = f"**Currently Playing:** {voice_client.current_song_item_for_loop.title}"
            elif hasattr(voice_client, 'current_song_title') and voice_client.current_song_title: # Fallback
                current_title_to_display = f"**Currently Playing:** {voice_client.current_song_title}"
        queue_messages.append(current_title_to_display)

        if guild_id not in self.song_queues or not self.song_queues[guild_id]:
            queue_messages.append("The queue is currently empty. 텅 비었어요!")
        else:
            queue_messages.append("**Up next:**")
            for i, song_item in enumerate(list(self.song_queues[guild_id])):
                if i >= 10: # Limit display for main /queue command
                    queue_messages.append(f"... and {len(self.song_queues[guild_id]) - i} more.")
                    break
                title = song_item.title or "Unknown Title" # Use stored title
                duration_str = ""
                if song_item.duration:
                    m, s = divmod(song_item.duration, 60)
                    h, m_rem = divmod(m, 60)
                    if h > 0: duration_str = f" [{h}:{m_rem:02d}:{s:02d}]"
                    else: duration_str = f" [{m_rem:02d}:{s:02d}]"
                queue_messages.append(f"{i + 1}. {title}{duration_str}")
            
        self.last_activity[guild_id] = datetime.now()
        await interaction.followup.send("\n".join(queue_messages), ephemeral=True)

    @app_commands.command(name='shuffle', description='Shuffles the current music queue')
    async def shuffle(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        if guild_id not in self.song_queues or not self.song_queues[guild_id]:
            await interaction.response.send_message("The queue is empty. Nothing to shuffle! 🎲", ephemeral=True)
            return
            
        current_queue_list = list(self.song_queues[guild_id])
        random.shuffle(current_queue_list)
        self.song_queues[guild_id] = deque(current_queue_list)
        self.last_activity[guild_id] = datetime.now()
        
        await interaction.response.send_message("🎲 Queue has been shuffled! Use `/queue` to see the new order.")

async def setup(bot: commands.Bot):
    cog = MusicCog(bot)
    await bot.add_cog(cog)
