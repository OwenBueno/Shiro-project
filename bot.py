import discord
from discord.ext import commands
import asyncio
from config import DISCORD_TOKEN, TELEGRAM_TOKEN
from telegram_bot.telegram_handler import TelegramBot
import logging
import signal
import sys
from utils.db_config import init_db

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('bot')

class Bot:
    def __init__(self):
        self.discord_bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
        self.telegram_bot = None
        self.shutdown_event = asyncio.Event()
        
        # Set up signal handlers in a platform-independent way
        if sys.platform != 'win32':
            # Unix-like systems
            for sig in (signal.SIGINT, signal.SIGTERM):
                asyncio.get_event_loop().add_signal_handler(
                    sig, lambda: asyncio.create_task(self.signal_handler()))
        else:
            # Windows systems
            signal.signal(signal.SIGINT, lambda s, f: asyncio.create_task(self.signal_handler()))
            signal.signal(signal.SIGTERM, lambda s, f: asyncio.create_task(self.signal_handler()))

    async def signal_handler(self):
        logger.info("Received shutdown signal")
        self.shutdown_event.set()

    async def init_discord(self):
        @self.discord_bot.event
        async def on_ready():
            logger.info(f'{self.discord_bot.user} has connected to Discord!')
        
        await self.discord_bot.load_extension('cogs.music_cog')
        await self.discord_bot.load_extension('cogs.chat_cog')
        logger.info("Discord bot initialized")

    async def run_discord_bot(self):
        try:
            await self.init_discord()
            await self.discord_bot.start(DISCORD_TOKEN)
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
            self.shutdown_event.set()
            raise

    async def run_telegram_bot(self):
        try:
            self.telegram_bot = TelegramBot(TELEGRAM_TOKEN)
            logger.info("Starting Telegram bot...")
            await self.telegram_bot.start_polling()
        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
            self.shutdown_event.set()
            raise

    async def shutdown(self):
        logger.info("Initiating shutdown sequence...")
        try:
            tasks = []
            
            if self.discord_bot:
                tasks.append(asyncio.create_task(self.discord_bot.close()))
            
            if self.telegram_bot:
                tasks.append(asyncio.create_task(self.telegram_bot.stop()))
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def run(self):
        try:
            # Initialize database connection first
            logger.info("Initializing database connection...")
            await init_db()
            logger.info("Database connection established")

            # Create tasks for both bots
            tasks = [
                asyncio.create_task(self.run_discord_bot(), name='discord'),
                asyncio.create_task(self.run_telegram_bot(), name='telegram'),
                asyncio.create_task(self.shutdown_event.wait(), name='shutdown')
            ]
            
            # Wait for either task to complete or shutdown signal
            try:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED
                )

                # Log which task completed
                for task in done:
                    if task.exception():
                        logger.error(f"Task {task.get_name()} failed with error: {task.exception()}")
                    else:
                        logger.info(f"Task {task.get_name()} completed successfully")

                logger.info("One of the tasks completed or shutdown requested")
                
            finally:
                # Cancel pending tasks
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