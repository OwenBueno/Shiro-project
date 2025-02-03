from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from utils.chat_utils import ChatManager, ChatError
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger('telegram_handler')

class TelegramBot:
    def __init__(self, token):
        self.token = token
        self.chat_manager = ChatManager()
        self.application = None
        self._running = False
        self._polling_task = None
        self._last_update_id = 0  # Add this to track last processed update

    async def initialize(self):
        """Initialize the application"""
        if not self.application:
            try:
                # Create application with default settings
                self.application = (
                    Application.builder()
                    .token(self.token)
                    .concurrent_updates(True)
                    .build()
                )
                
                self._setup_handlers()
                await self.application.initialize()
                await self.application.bot.get_me()  # Test the connection
                logger.info("Telegram bot initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                raise

    def _setup_handlers(self):
        if not self.application:
            raise RuntimeError("Application not initialized")
            
        # Command handlers
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help))
        self.application.add_handler(CommandHandler("clear", self.clear))
        
        # Message handler
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /start is issued."""
        user = update.effective_user
        welcome_message = (
            f"¡Hola {user.first_name}! Soy Shiro~ ヾ(＾∇＾)\n\n"
            "¡Estoy aquí para charlar contigo! Puedes escribirme cualquier cosa "
            "y estaré encantada de responderte.\n\n"
            "Comandos disponibles:\n"
            "/help - Mostrar esta ayuda\n"
            "/clear - Limpiar el historial de conversación"
        )
        await update.message.reply_text(welcome_message)

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send a message when the command /help is issued."""
        help_text = (
            "¡Aquí tienes algunos comandos útiles!\n\n"
            "/start - Iniciar una conversación\n"
            "/help - Mostrar esta ayuda\n"
            "/clear - Limpiar el historial de conversación\n\n"
            "¡También puedes simplemente escribirme y charlaremos! ^_^"
        )
        await update.message.reply_text(help_text)

    async def clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Clear the conversation history."""
        try:
            user_id = f"telegram_{update.effective_user.id}"
            await self.chat_manager.clear_user_history(user_id)
            await update.message.reply_text("¡Historial de conversación borrado! Empecemos de nuevo~ ✨")
        except Exception as e:
            logger.error(f"Error clearing history: {str(e)}")
            await update.message.reply_text("Ocurrió un error al borrar el historial 😅")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages."""
        try:
            # Ignore messages from bots
            if update.message.from_user.is_bot:
                logger.debug("Ignoring message from bot")
                return

            logger.info(f"Received message from Telegram: {update.message.text}")
            user = update.effective_user
            user_id = f"telegram_{user.id}"
            user_name = f"{user.first_name} {user.last_name or ''}"
            
            logger.debug(f"Processing message for user {user_name} (ID: {user_id})")

            # Get conversation history
            history = await self.chat_manager.get_conversation_history(
                user_name=user_name
            )
            
            logger.debug(f"Got history with {len(history)} messages")
            
            # Add user's message to context
            messages = history + [{"role": "user", "content": update.message.text}]
            
            # Send typing action
            await update.message.chat.send_action('typing')
            logger.debug("Sent typing action")
            
            # Get response from chat manager
            response = await self.chat_manager.get_chat_response(user_id, messages)
            cleaned_content = self.chat_manager.clean_response(response)
            
            logger.debug(f"Got response: {cleaned_content[:50]}...")
            
            # Save messages
            await self.chat_manager.save_message(
                user_id,
                'user',
                update.message.text,
                user_name
            )
            await self.chat_manager.save_message(
                user_id,
                'assistant',
                cleaned_content,
                'Shiro'
            )
            
            logger.debug("Messages saved to database")
            
            # Send response
            await update.message.reply_text(cleaned_content)
            logger.info("Response sent successfully")
            
        except ChatError as ce:
            logger.error(f"Chat error: {str(ce)}")
            await update.message.reply_text(f"¡Ups! Ocurrió un error: {str(ce)}")
        except Exception as e:
            logger.error(f"Unexpected error in handle_message: {str(e)}", exc_info=True)
            await update.message.reply_text("¡Lo siento! Ocurrió un error inesperado 😅")

    async def _polling_loop(self):
        """Internal polling loop"""
        try:
            await self.application.start()
            logger.info("Started polling")
            
            while self._running:
                try:
                    # Get updates with offset to avoid processing old messages
                    updates = await self.application.bot.get_updates(
                        offset=self._last_update_id + 1,  # Get only new messages
                        timeout=30,
                        allowed_updates=Update.ALL_TYPES
                    )
                    
                    # Process updates
                    for update in updates:
                        # Update the last processed update ID
                        if update.update_id > self._last_update_id:
                            self._last_update_id = update.update_id
                            
                        # Process only if it's a new message
                        if update.message and update.message.date.timestamp() > (datetime.now().timestamp() - 30):
                            await self.application.process_update(update)
                        
                except asyncio.CancelledError:
                    logger.info("Polling cancelled")
                    break
                except Exception as e:
                    logger.error(f"Error in polling loop: {e}")
                    await asyncio.sleep(1)  # Wait before retrying
                    
                # Add a small delay between polls to prevent tight loops
                await asyncio.sleep(0.5)
                    
        finally:
            await self.application.stop()
            logger.info("Polling stopped")

    async def start_polling(self):
        """Start the bot."""
        try:
            if not self.application:
                await self.initialize()
            
            self._running = True
            logger.info("Starting Telegram bot polling")
            
            # Start polling in a separate task
            self._polling_task = asyncio.create_task(
                self._polling_loop(),
                name="telegram_polling"
            )
            
            # Wait for the polling task
            await self._polling_task
            
        except Exception as e:
            logger.error(f"Error in start_polling: {e}")
            self._running = False
            raise
        finally:
            logger.info("Telegram polling stopped")

    async def stop(self):
        """Stop the bot."""
        if self.application:
            try:
                logger.info("Stopping Telegram bot")
                self._running = False
                
                if self._polling_task:
                    logger.debug("Cancelling polling task...")
                    self._polling_task.cancel()
                    try:
                        await self._polling_task
                    except asyncio.CancelledError:
                        pass
                
                logger.debug("Stopping application...")
                await self.application.stop()
                await self.application.shutdown()
                self.application = None
                logger.info("Telegram bot stopped successfully")
            except Exception as e:
                logger.error(f"Error stopping Telegram bot: {e}")
                raise                                    