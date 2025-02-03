import discord
from discord.ext import commands
from utils.chat_utils import ChatManager, ChatError
import logging

logger = logging.getLogger('chat_cog')

class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.chat_manager = ChatManager()
        self.processing_messages = set()

    @commands.command(name='chat', help='Chat with the bot using OpenAI')
    async def chat(self, ctx, *, prompt: str):
        message_id = f"{ctx.author.id}-{ctx.message.id}"
        
        if message_id in self.processing_messages:
            return
        
        try:
            self.processing_messages.add(message_id)
            logger.info(f"Procesando comando chat para {ctx.author.id}")
            
            async with ctx.typing():
                history = await self.chat_manager.get_conversation_history(
                    user_name=str(ctx.author)
                )
                
                messages = history + [{"role": "user", "content": prompt}]
                
                response = await self.chat_manager.get_chat_response(ctx.author.id, messages)
                cleaned_content = self.chat_manager.clean_response(response)
                
                await self.chat_manager.save_message(
                    ctx.author.id,
                    'user',
                    prompt,
                    str(ctx.author)
                )
                await self.chat_manager.save_message(
                    ctx.author.id,
                    'assistant',
                    cleaned_content
                )

                if isinstance(ctx.channel, discord.DMChannel):
                    await ctx.author.send(cleaned_content)
                else:
                    await ctx.send(cleaned_content)
                    
        except ChatError as ce:
            error_msg = f"Ocurrió un error específico del chat: {str(ce)}"
            logger.error(error_msg)
            await ctx.send(error_msg)
        except Exception as e:
            error_msg = f"Ocurrió un error inesperado: {str(e)}"
            logger.error(f"Unexpected error in chat command: {str(e)}", exc_info=True)
            await ctx.send(error_msg)
        finally:
            self.processing_messages.remove(message_id)

    @commands.command(name='clear_context', help='Clear global conversation history')
    @commands.has_permissions(administrator=True)
    async def clear_context(self, ctx):
        try:
            conversations.delete_many({})  # Clear all conversations
            await ctx.send("El historial global de conversación ha sido borrado.")
        except Exception as e:
            error_msg = f"Error inesperado al limpiar el historial: {str(e)}"
            logger.error(f"Unexpected error in clear_context: {str(e)}", exc_info=True)
            await ctx.send(error_msg)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        if isinstance(message.channel, discord.DMChannel):
            message_id = f"{message.author.id}-{message.id}"
            
            if message_id in self.processing_messages:
                return
                
            try:
                self.processing_messages.add(message_id)
                logger.info(f"Procesando DM de {message.author.id}")
                
                async with message.channel.typing():
                    history = await self.chat_manager.get_conversation_history(
                        user_name=str(message.author)
                    )
                    
                    messages = history + [{"role": "user", "content": message.content}]
                    
                    response = await self.chat_manager.get_chat_response(message.author.id, messages)
                    cleaned_content = self.chat_manager.clean_response(response)
                    
                    await self.chat_manager.save_message(
                        message.author.id, 
                        'user', 
                        message.content, 
                        str(message.author)
                    )
                    await self.chat_manager.save_message(
                        message.author.id, 
                        'assistant', 
                        cleaned_content, 
                        str(message.author)
                    )

                    await message.channel.send(cleaned_content)
                    
            except ChatError as ce:
                error_msg = f"Error en el chat: {str(ce)}"
                logger.error(error_msg)
                await message.channel.send(error_msg)
            except Exception as e:
                error_msg = f"Error inesperado: {str(e)}"
                logger.error(f"Unexpected error in DM handler: {str(e)}", exc_info=True)
                await message.channel.send(error_msg)
            finally:
                self.processing_messages.remove(message_id)

async def setup(bot):
    await bot.add_cog(ChatCog(bot))