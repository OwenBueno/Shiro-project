# utils/admin_utils.py
import discord
from discord import app_commands
from functools import wraps
from config import SHIRO_ADMINS # Import the list of admin IDs

def is_shiro_admin(user_id: int) -> bool:
    """Check if a user ID is in the SHIRO_ADMINS list."""
    return user_id in SHIRO_ADMINS

def admin_only():
    """Decorator to restrict a slash command to Shiro admins only."""
    def predicate(interaction: discord.Interaction) -> bool:
        """The check function for the decorator."""
        return is_shiro_admin(interaction.user.id)

    async def on_error(interaction: discord.Interaction, error: app_commands.CheckFailure):
        """Callback for when the check fails."""
        await interaction.response.send_message(
            "🔒 Sorry, this command can only be used by Shiro bot admins.", 
            ephemeral=True
        )

    # Apply the check and set the error handler
    # app_commands.check returns a decorator that needs to be called
    return app_commands.check(predicate)
    # For the error handler, we can't directly attach it to the check like this easily
    # Instead, the cog-level or command-level error handler should catch app_commands.CheckFailure
    # and then check if the failed check was due to admin_only. 
    # However, for simplicity, discord.py handles the CheckFailure by default and 
    # the on_error within the check decorator isn't standard for app_commands.check.
    # A more common way is to handle app_commands.CheckFailure in a cog_app_command_error handler.

    # Corrected approach for a simple decorator:
    # The predicate is enough for app_commands.check. The error message is generic
    # or handled by a global/cog error handler.
    # For a custom message directly from the check, we'd typically raise a specific error.

    # Let's simplify and rely on a cog-level error handler to give the custom message.
    # The check itself will just return True or False.
    # The custom message will be handled in the cog where this decorator is used.
    # So, the decorator just becomes:
    # def admin_only_decorator(command):
    #     @wraps(command)
    #     async def wrapper(interaction: discord.Interaction, *args, **kwargs):
    #         if not is_shiro_admin(interaction.user.id):
    #             await interaction.response.send_message(
    #                 "🔒 Sorry, this command can only be used by Shiro bot admins.", 
    #                 ephemeral=True
    #             )
    #             return
    #         return await command(interaction, *args, **kwargs)
    #     return wrapper
    # return admin_only_decorator
    #
    # However, discord.py's app_commands.check is the idiomatic way.
    # The CheckFailure error it raises can be caught by an error handler in the cog.

    # Final simplified version for the decorator using app_commands.check:
    # The predicate itself is what app_commands.check needs.
    # The error message for CheckFailure will be generic unless a specific error handler is made in the cog.
    # To provide a direct custom message for *this specific check*, we'd raise a custom exception derived from CheckFailure.

    # Let's use a standard app_commands.check. The cog will handle the CheckFailure.
    return app_commands.check(predicate)

# Example of how it would be used in a cog:
# class MyCog(commands.Cog):
#     ...
#     @admin_only()
#     @app_commands.command(name="adminstuff")
#     async def my_admin_command(self, interaction: discord.Interaction):
#         await interaction.response.send_message("Admin stuff done!", ephemeral=True)

#     async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
#         if isinstance(error, app_commands.CheckFailure):
#             # Here you could check if the error.payload (if you set one) or the failed check name matches your admin_only check
#             # For simplicity, if any CheckFailure happens on an admin command, we send this message.
#             # This assumes admin_only() is the primary check on these commands.
#             await interaction.response.send_message(
#                 "🔒 Sorry, this command can only be used by Shiro bot admins.", 
#                 ephemeral=True
#             )
#         else:
#             # Handle other errors or re-raise
#             print(f"Unhandled error in cog: {error}") 