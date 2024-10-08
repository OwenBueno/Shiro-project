import discord
import yt_dlp as youtube_dl
from config import YTDL_FORMAT_OPTIONS, FFMPEG_OPTIONS
import os
import asyncio

ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename, volume=0.5):
        super().__init__(source, volume=volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.filename = filename

    @classmethod
    async def from_url(cls, url, *, download=True):
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
