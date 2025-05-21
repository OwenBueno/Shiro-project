import os
from typing import Optional
from dotenv import load_dotenv

def load_env_and_get_discord_token_key() -> str:
    """Loads .env, determines Discord token key based on ENVIRONMENT, and validates required env vars."""
    load_dotenv(override=True)
    ENVIRONMENT = os.getenv('ENVIRONMENT', 'production').lower()

    if ENVIRONMENT == 'development':
        discord_token_env_key = 'BOT_TOKEN_ALTERNATIVE'
    else:
        discord_token_env_key = 'BOT_TOKEN'

    required_vars = [
        discord_token_env_key, 
        'OPENAI_API_KEY', 
        'MONGODB_URI', 
        'SHIRO_ADMINS',
        'SPOTIFY_CLIENT_ID',      # Added for Spotify
        'SPOTIFY_CLIENT_SECRET'   # Added for Spotify
    ]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    return discord_token_env_key

ACTUAL_DISCORD_TOKEN_ENV_KEY = load_env_and_get_discord_token_key()

def get_env(key: str) -> Optional[str]:
    """Get environment variable (assumes .env is already loaded)"""
    return os.getenv(key)

DISCORD_TOKEN = get_env(ACTUAL_DISCORD_TOKEN_ENV_KEY)
OPENAI_API_KEY = get_env('OPENAI_API_KEY')
MONGODB_URI = get_env('MONGODB_URI')
GPT4_BASE_URL = get_env('GPT4_BASE_URL')

# Spotify Credentials
SPOTIFY_CLIENT_ID = get_env('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = get_env('SPOTIFY_CLIENT_SECRET')

# Parse SHIRO_ADMINS from comma-separated string to a list of ints
shiro_admins_str = get_env('SHIRO_ADMINS')
SHIRO_ADMINS: list[int] = []
if shiro_admins_str:
    try:
        SHIRO_ADMINS = [int(admin_id.strip()) for admin_id in shiro_admins_str.split(',')]
    except ValueError:
        # This error will be caught by the missing_vars check if SHIRO_ADMINS is empty or malformed,
        # but good to log if it's present but not parsable.
        # For a more robust setup, one might raise an immediate error here.
        # However, the required_vars check will handle if it's missing.
        # If it's present but malformed, it will likely lead to an empty SHIRO_ADMINS list,
        # which means no one is an admin, or a ValueError if parsing fails.
        # The required_vars check ensures it *must* be present.
        # Let's assume if it's present, it's correctly formatted or the bot owner will fix it.
        # A stricter approach would be to raise ValueError here if parsing fails.
        print("Warning: SHIRO_ADMINS environment variable is present but could not be parsed into a list of integers. Ensure it's a comma-separated list of user IDs.")
        # Or, to be stricter:
        # raise ValueError("SHIRO_ADMINS environment variable is malformed. Please provide a comma-separated list of user IDs.")
else:
    # This case should ideally be caught by 'SHIRO_ADMINS' in required_vars.
    # If somehow it's not, SHIRO_ADMINS will be an empty list.
    pass

DOWNLOAD_FOLDER = 'downloads'

YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': os.path.join(DOWNLOAD_FOLDER, '%(title).100s.%(ext)s'),
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1',
    # 'source_address': '0.0.0.0', # Commenting out as a test
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