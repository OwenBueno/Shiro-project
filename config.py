import os
from typing import Optional
from dotenv import load_dotenv

def load_config() -> None:
    """Load or reload environment variables from .env file"""
    load_dotenv(override=True)

    # Validate required environment variables
    required_vars = ['DISCORD_TOKEN', 'OPENAI_API_KEY', 'MONGODB_URI']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Initial load of environment variables
load_config()

def get_env(key: str) -> Optional[str]:
    """Get environment variable with optional reload"""
    return os.getenv(key)

# Environment variables
DISCORD_TOKEN = get_env('DISCORD_TOKEN')
OPENAI_API_KEY = get_env('OPENAI_API_KEY')
MONGODB_URI = get_env('MONGODB_URI')

DOWNLOAD_FOLDER = 'downloads'

YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title).100s.%(ext)s'),  # Save in the folder
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

FFMPEG_OPTIONS = {
    'options': '-vn -b:a 320k -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 10000000 -http_persistent 1 -user_agent "Mozilla/5.0"'
}