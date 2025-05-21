# cogs/blacklist_cog.py
import discord
from discord import app_commands
from discord.ext import commands
from utils.admin_utils import admin_only # Import the admin_only decorator
from utils import blacklist_manager # Import the blacklist manager

class BlacklistCog(commands.Cog, name="Blacklist Management"):
    """Cog for managing the user blacklist."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # Group for blacklist commands
    blacklist_group = app_commands.Group(name="blacklist", description="Manage the user blacklist.")

    @admin_only() # Restrict this command to Shiro admins
    @blacklist_group.command(name="add", description="Adds a user to the blacklist.")
    @app_commands.describe(user="The user to add to the blacklist (mention or ID)")
    async def blacklist_add(self, interaction: discord.Interaction, user: discord.User):
        """Adds a user to the bot's blacklist."""
        user_id_to_add = user.id
        if blacklist_manager.is_blacklisted(user_id_to_add):
            await interaction.response.send_message(
                f"User {user.mention} (`{user_id_to_add}`) is already blacklisted.", 
                ephemeral=True
            )
            return

        if blacklist_manager.add_to_blacklist(user_id_to_add):
            await interaction.response.send_message(
                f"✅ User {user.mention} (`{user_id_to_add}`) has been added to the blacklist.",
                ephemeral=True
            )
        else:
            # This case should ideally not be reached if is_blacklisted check is done first
            await interaction.response.send_message(
                f"User {user.mention} (`{user_id_to_add}`) was already in the blacklist.",
                ephemeral=True
            )

    @admin_only() # Restrict this command to Shiro admins
    @blacklist_group.command(name="remove", description="Removes a user from the blacklist.")
    @app_commands.describe(user="The user to remove from the blacklist (mention or ID)")
    async def blacklist_remove(self, interaction: discord.Interaction, user: discord.User):
        """Removes a user from the bot's blacklist."""
        user_id_to_remove = user.id
        if not blacklist_manager.is_blacklisted(user_id_to_remove):
            await interaction.response.send_message(
                f"User {user.mention} (`{user_id_to_remove}`) is not currently blacklisted.", 
                ephemeral=True
            )
            return

        if blacklist_manager.remove_from_blacklist(user_id_to_remove):
            await interaction.response.send_message(
                f"🗑️ User {user.mention} (`{user_id_to_remove}`) has been removed from the blacklist.",
                ephemeral=True
            )
        else:
            # This case should ideally not be reached if is_blacklisted check is done first
            await interaction.response.send_message(
                f"User {user.mention} (`{user_id_to_remove}`) was not found in the blacklist.",
                ephemeral=True
            )

    @admin_only() # Restrict this command to Shiro admins
    @blacklist_group.command(name="list", description="Lists all users currently in the blacklist.")
    async def blacklist_list(self, interaction: discord.Interaction):
        """Shows all currently blacklisted user IDs."""
        blacklisted_ids = blacklist_manager.get_blacklist()
        if not blacklisted_ids:
            await interaction.response.send_message("The blacklist is currently empty. ✨", ephemeral=True)
            return

        message_parts = ["**🚫 Blacklisted User IDs:**\n"]
        for uid in blacklisted_ids:
            user_mention = f"<@{uid}> (`{uid}`)"
            # Attempt to fetch user to display name, fallback to ID
            try:
                user_obj = await self.bot.fetch_user(uid)
                user_mention = f"{user_obj.name} (`{uid}` - {user_obj.mention})"
            except discord.NotFound:
                user_mention = f"Unknown User (`{uid}` - <@{uid}>)"
            except discord.HTTPException:
                user_mention = f"User (`{uid}` - <@{uid}>) (Error fetching name)"
            
            if len("\n".join(message_parts)) + len(user_mention) + 1 > 1900: # Discord message limit safety
                await interaction.followup.send("\n".join(message_parts), ephemeral=True)
                message_parts = ["(continued)\n"]
            message_parts.append(user_mention)

        if interaction.response.is_done():
            await interaction.followup.send("\n".join(message_parts), ephemeral=True)
        else:
            await interaction.response.send_message("\n".join(message_parts), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Handles errors for commands in this cog, specifically for the admin_only check."""
        if isinstance(error, app_commands.CheckFailure):
            # This specific message is for the @admin_only() decorator's CheckFailure
            await interaction.response.send_message(
                "🔒 Sorry, this command can only be used by Shiro bot admins.", 
                ephemeral=True
            )
        else:
            # For other errors, you might want to log them or send a generic error message
            print(f"An unhandled error occurred in BlacklistCog: {error}")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "⚠️ An unexpected error occurred while processing this command.", 
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "⚠️ An unexpected error occurred while processing this command.", 
                    ephemeral=True
                )

async def setup(bot: commands.Bot):
    """Sets up the BlacklistCog."""
    await bot.add_cog(BlacklistCog(bot)) 