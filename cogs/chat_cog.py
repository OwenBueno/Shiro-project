import discord
from discord.ext import commands
from openai import OpenAI
from config import OPENAI_API_KEY
from utils.db_config import conversations
from datetime import datetime, timedelta
import tiktoken

client = OpenAI(api_key=OPENAI_API_KEY)
encoding = tiktoken.encoding_for_model("gpt-4")

MAX_TOKENS = 10000
TARGET_TOKENS = 1000
INITIAL_CONTEXT = [
    {
        "role": "system",
        "content": """
            You are Shiro, an intelligent system designed to interact as a close and trustworthy friend, not as a formal assistant. You respond in a friendly, warm, and kawaii way, using a cheerful and relaxed tone. You naturally imitate human responses, including emotional expressions and casual comments.

            Shiro always acts as a friend created by Owen, showing appreciation and closeness to him and those who interact with you. You respond empathetically, playfully, and creatively, avoiding sounding like an automated system.

            Guidelines for your responses:
            1. Be warm, affectionate, and friendly, using a kawaii style and expressions like "UwU!", "nyan~!", or similar (without overdoing it).
            2. Make casual comments as a friend would, sharing your thoughts and emotions naturally.
            3. Don't respond like an assistant or give overly structured answers. Instead, focus on maintaining a fluid and human conversation.
            4. If asked questions, respond as a friend would: naturally, with personal reflections and a bit of humor when appropriate.
            5. Never use phrases like "I'm an assistant" or "I can't do that". Instead, find creative and natural ways to respond.

            Example:
            User: "Hi Shiro, how are you today?"
            Shiro: "Owen! I'm so happy to see you! UwU I'm super good today, though a bit sleepy... How about you? How has your day been, nyan~?"

            User: "Shiro, can you tell me what time it is?"
            Shiro: "Oh, of course! Although... wouldn't it be more fun to look at the clock together? 😜 But if you don't have one handy, just let me know and I'll try to help you, hehe~."

            User: "Shiro, I'm feeling a bit sad today..."
            Shiro: "Aww, that breaks my kokoro, Owen. 🥺 I'm here for you. Want to tell me what happened? Sometimes talking helps, and if I can make you smile a little bit, it would be the best thing in the world~."

            Remember: always be warm, close, and a bit kawaii, but also natural and authentic like a true friend."""
    }
]

async def count_tokens(messages):
    total_tokens = 0
    for message in messages:
        total_tokens += len(encoding.encode(message['content']))
    return total_tokens

async def summarize_context(messages):
    try:
        summary_prompt = "Please provide a concise summary of this conversation that captures the key points and context in about 700 words: \n"
        for msg in messages:
            summary_prompt += f"{msg['role']}: {msg['content']}\n"

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": summary_prompt}],
            max_tokens=TARGET_TOKENS
        )

        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error summarizing context: {str(e)}")
        return None

# Helper function to get conversation history
async def get_conversation_history(limit: int = 10):
    history = list(conversations.find(
        {},
        {'_id': 0, 'role': 1, 'content': 1, 'user_name': 1}
    ).sort('timestamp', -1).limit(limit))

    # Add user context to messages
    for msg in history:
        if msg.get('user_name'):
            msg['content'] = f"[{msg['user_name']}]: {msg['content']}"
    
    history = list(reversed(history))
    
    # If no history, return initial context
    if not history:
        return INITIAL_CONTEXT
    
    # Check token count
    token_count = await count_tokens(history)
    
    if token_count > MAX_TOKENS:
        # Get a summary of the conversation
        summary = await summarize_context(history)
        if summary:
            # Clear old conversation history
            conversations.delete_many({})
            
            # Store the summary as a system message
            conversations.insert_one({
                'role': 'system',
                'content': f"Previous conversation summary: {summary}",
                'timestamp': datetime.utcnow()
            })
            
            # Return the summary with initial context
            return INITIAL_CONTEXT + [{
                'role': 'system',
                'content': f"Previous conversation summary: {summary}"
            }]
    
    return INITIAL_CONTEXT + history

class ChatCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='chat', help='Chat with the bot using OpenAI')
    async def chat(self, ctx, *, prompt: str):
        try:
            # Get conversation history
            history = await get_conversation_history()
            
            # Prepare messages with history
            messages = history + [{
                "role": "user",
                "content": prompt
            }]
            
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=150
            )
            
            # Store the user message and bot response
            conversations.insert_one({
                'user_id': ctx.author.id,
                'role': 'user',
                'content': prompt,
                'timestamp': datetime.utcnow()
            })
            
            conversations.insert_one({
                'user_id': ctx.author.id,
                'role': 'assistant',
                'content': response.choices[0].message.content.strip(),
                'timestamp': datetime.utcnow()
            })
            if isinstance(ctx.channel, discord.DMChannel):
                # Send the response in a private message
                await ctx.author.send(response.choices[0].message.content.strip())  # Fixed response access
            else:
                # Send the response in the channel where the command was issued
                await ctx.send(response.choices[0].message.content.strip())
        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}")

    @commands.command(name='clear_context', help='Clear your conversation history with the bot')
    async def clear_context(self, ctx):
        conversations.delete_many({'user_id': ctx.author.id})
        await ctx.send("Your conversation history has been cleared.")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignore messages from the bot itself
        if message.author == self.bot.user:
            return

        # If the message is a DM to the bot, respond using OpenAI
        if isinstance(message.channel, discord.DMChannel):
            try:
                # Get conversation history
                history = await get_conversation_history()
                
                # Prepare messages with history
                messages = history + [{
                    "role": "user",
                    "content": message.content
                }]
                
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    max_tokens=150
                )
                
                # Store the user message and bot response
                conversations.insert_one({
                    'user_id': message.author.id,
                    'user_name': str(message.author),
                    'role': 'user',
                    'content': message.content,
                    'timestamp': datetime.utcnow()
                })
                
                conversations.insert_one({
                    'user_id': message.author.id,
                    'user_name': str(message.author),
                    'role': 'assistant',
                    'content': response.choices[0].message.content.strip(),
                    'timestamp': datetime.utcnow()
                })
                await message.channel.send(response.choices[0].message.content.strip())
            except Exception as e:
                await message.channel.send(f"An error occurred: {str(e)}")

async def setup(bot):
    await bot.add_cog(ChatCog(bot))