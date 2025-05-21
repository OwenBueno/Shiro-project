import discord

# Attempt to load Opus library explicitly
opus_paths_to_try = [
    '/opt/homebrew/lib/libopus.dylib', # Apple Silicon Homebrew
    '/usr/local/lib/libopus.dylib',   # Intel Homebrew
    'opus',                           # General name, might work if in PATH/LD_LIBRARY_PATH
    'libopus.so.0',                   # Linux
    'libopus-0.dll'                   # Windows
]
loaded_opus = False
if not discord.opus.is_loaded(): # Check if it's already loaded perhaps by PyNaCl
    for path in opus_paths_to_try:
        try:
            discord.opus.load_opus(path)
            if discord.opus.is_loaded():
                print(f"Successfully loaded opus from: {path}")
                loaded_opus = True
                break
        except (discord.opus.OpusError, OSError):
            # print(f"OpusPy: Failed to load opus from {path}: {e}") # Keep this quiet unless debugging all paths
            pass # Try next path

if not discord.opus.is_loaded(): # Check again after trying all paths
    print("---------------------------------------------------------------------")
    print("Warning: Opus library could not be loaded from any specified path.")
    print("Voice functionality will likely not work. Please ensure libopus is installed")
    print("and accessible. Common solutions: ")
    print("- macOS: 'brew install opus'")
    print("- Debian/Ubuntu: 'sudo apt install libopus0'")
    print("- Windows: Ensure libopus-0.dll is in your PATH or alongside python.exe")
    print("---------------------------------------------------------------------")

from discord.ext import commands
import asyncio
from config import DISCORD_TOKEN
import logging
import signal
import sys
from utils.db_config import init_db
from utils import blacklist_manager
from utils.admin_utils import is_shiro_admin

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('bot')

class Bot:
    def __init__(self):
        self.discord_bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
        self.shutdown_event = asyncio.Event()
        
        if sys.platform != 'win32':
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.signal_handler()))
        else:
            signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(self.signal_handler()))
            signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(self.signal_handler()))

        # Global interaction check for blacklist
        async def global_interaction_check(interaction: discord.Interaction) -> bool:
            user_id = interaction.user.id
            command_name = interaction.command.name if interaction.command else "UnknownCommand"
            command_qualified_name = interaction.command.qualified_name if interaction.command else "UnknownCommand"

            # Allow admins to use any command, including blacklist commands
            if is_shiro_admin(user_id):
                return True

            # If user is blacklisted
            if blacklist_manager.is_blacklisted(user_id):
                # Allow blacklisted admins to use only the /blacklist commands to potentially unban themselves or others
                # This logic is now covered by the above: if admin, all commands are allowed.
                # If a non-admin is blacklisted, block all commands.
                
                # Send blacklist message only once if interaction is not yet responded to
                if not interaction.response.is_done():
                    await interaction.response.send_message(
                        "🚫 You are blacklisted from using Shiro bot. Contact an admin for help.", 
                        ephemeral=True
                    )
                return False # Block command
            
            return True # User is not blacklisted, allow command
        
        self.discord_bot.tree.interaction_check = global_interaction_check

    async def signal_handler(self):
        logger.info("Received shutdown signal")
        self.shutdown_event.set()

    async def init_discord(self):
        @self.discord_bot.event
        async def on_ready():
            logger.info(f'{self.discord_bot.user} has connected to Discord!')
            try:
                synced = await self.discord_bot.tree.sync()
                logger.info(f"Synced {len(synced)} commands globally.")
            except Exception as e:
                logger.error(f"Failed to sync commands: {e}")
        
        await self.discord_bot.load_extension('cogs.music_cog')
        await self.discord_bot.load_extension('cogs.chat_cog')
        await self.discord_bot.load_extension('cogs.blacklist_cog')
        await self.discord_bot.load_extension('cogs.help_cog')
        logger.info("Discord cogs loaded and commands initialized.")

    async def run_discord_bot(self):
        try:
            await self.init_discord()
            await self.discord_bot.start(DISCORD_TOKEN)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self.shutdown_event.set()
            raise

    async def shutdown(self):
        logger.info("Initiating shutdown sequence...")
        try:
            tasks = []
            
            if self.discord_bot:
                tasks.append(asyncio.create_task(self.discord_bot.close()))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def run(self):
        try:
            logger.info("Initializing database connection...")
            await init_db()
            logger.info("Database connection established")

            tasks = [
                asyncio.create_task(self.run_discord_bot(), name='discord'),
                asyncio.create_task(self.shutdown_event.wait(), name='shutdown')
            ]
            
            try:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                for task in done:
                    if task.exception():
                        logger.error(f"Task {task.get_name()} failed with error: {task.exception()}")
                    else:
                        logger.info(f"Task {task.get_name()} completed successfully")

                logger.info("One of the tasks completed or shutdown requested")
                
            finally:
                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        logger.debug(f"Task {task.get_name()} was cancelled")
                    except Exception as e:
                        logger.error(f"Error cancelling task {task.get_name()}: {e}")
                
        except Exception as e:
            logger.error(f"Error in main: {e}", exc_info=True)
        finally:
            logger.info("Shutting down bots...")
            await self.shutdown()

async def main():
    bot = Bot()
    await bot.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
    finally:
        logger.info("Program ended")