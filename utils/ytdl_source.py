import discord
import yt_dlp as youtube_dl
from config import YTDL_FORMAT_OPTIONS, FFMPEG_OPTIONS, DOWNLOAD_FOLDER
import os
import asyncio

# Create a copy of the format options for the main ytdl instance
main_ytdl_opts = YTDL_FORMAT_OPTIONS.copy()
# Ensure extract_flat is not True for the main instance, we want full processing for downloads
if 'extract_flat' in main_ytdl_opts:
    del main_ytdl_opts['extract_flat'] # Or set to False, but removing ensures it uses yt-dlp default

ytdl = youtube_dl.YoutubeDL(main_ytdl_opts)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename, volume=0.5):
        super().__init__(source, volume=volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.webpage_url = data.get('webpage_url')
        self.uploader = data.get('uploader')
        self.duration = data.get('duration')
        self.thumbnail = data.get('thumbnail')
        self.filename = filename

    @classmethod
    async def from_url(cls, url, *, download=True):
        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER)

        data = await asyncio.to_thread(ytdl.extract_info, url, download=download)

        if 'entries' in data:
            return data['entries']

        filename = ytdl.prepare_filename(data)
        if not os.path.exists(filename):
            filename = f"{os.path.splitext(filename)[0]}.opus"

        return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data, filename=filename)
    
def get_temp_ytdl():
    extract_flat_opts = YTDL_FORMAT_OPTIONS.copy()
    extract_flat_opts['extract_flat'] = 'in_playlist'
    temp_ytdl = youtube_dl.YoutubeDL(extract_flat_opts)
    return temp_ytdl
