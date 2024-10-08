### cogs/chat_cog.py
import discord
from discord.ext import commands
from openai import OpenAI
from config import OPENAI_API_KEY
client = OpenAI(api_key=OPENAI_API_KEY)

class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='chat', help='Chat with the bot using OpenAI')
    async def chat(self, ctx, *, prompt: str):
        try:
            response = client.chat.completions.create(engine="gpt-3.5-turbo",
            messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
            max_tokens=150)
            if isinstance(ctx.channel, discord.DMChannel):
                # Send the response in a private message
                await ctx.author.send(response.choices[0].text.strip())
            else:
                # Send the response in the channel where the command was issued
                await ctx.send(response.choices[0].message.content.strip())
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # If the message is a DM to the bot, respond using OpenAI
        if isinstance(message.channel, discord.DMChannel):
            try:
                response = client.chat.completions.create(model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "user",
                        "content": message.content
                    }
                ],
                max_tokens=150)
                await message.channel.send(response.choices[0].message.content.strip())
            except Exception as e:
                await message.channel.send(f"An error occurred: {str(e)}")

async def setup(bot):
    await bot.add_cog(ChatCog(bot))