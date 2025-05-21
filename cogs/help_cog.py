# cogs/help_cog.py
import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import get

class HelpSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, cog_map: dict):
        self.bot = bot
        self.cog_map = cog_map # To map display name back to cog object/name
        options = [discord.SelectOption(label="Overview", description="Show all categories.", value="_overview_")]
        for cog_name in cog_map.keys():
            if cog_name: # Ensure cog_name is not None or empty
                options.append(discord.SelectOption(label=cog_name, description=f"Commands in {cog_name}", value=cog_name))
        
        super().__init__(placeholder="Choose a category...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        embed = discord.Embed(title="Shiro Bot Help", color=discord.Color.purple())

        if selected_value == "_overview_":
            embed.title = "Help - All Categories"
            embed.description = "Hello! I'm Shiro, your friendly companion bot! Here are my command categories. Select one from the dropdown to see its commands~ UwU"
            for cog_name, cog_data in self.cog_map.items():
                if cog_data and cog_data.get_app_commands(): # Check if cog has app commands
                    command_count = len(cog_data.get_app_commands())
                    embed.add_field(name=f"{cog_name} ({command_count} commands)", value=cog_data.description or "No description.", inline=False)
            if not any(cog_data.get_app_commands() for cog_data in self.cog_map.values()):
                embed.add_field(name="No Commands Found", value="It seems there are no slash commands available right now.", inline=False)

        elif selected_value in self.cog_map: # Check if it's a known cog name
            cog = self.cog_map[selected_value]
            embed.title = f"Help - {cog.qualified_name}"
            embed.description = cog.description or f"Commands available in the {cog.qualified_name} category:"
            
            app_cmds = cog.get_app_commands()
            if app_cmds:
                for cmd in sorted(app_cmds, key=lambda c: c.name):
                    if isinstance(cmd, app_commands.Group):
                        sub_cmds_formatted = []
                        for sub_cmd in sorted(cmd.commands, key=lambda sc: sc.name):
                            sub_cmds_formatted.append(f"> `/{cmd.name} {sub_cmd.name}` - {sub_cmd.description or 'No description'}") 
                        if sub_cmds_formatted:
                             embed.add_field(name=f"`/{cmd.name}` (Group)", value="\n".join(sub_cmds_formatted), inline=False)
                        else:
                            embed.add_field(name=f"`/{cmd.name}` (Group)", value="This group has no subcommands.", inline=False)
                    else:
                        embed.add_field(name=f"`/{cmd.name}`", value=cmd.description or "No description", inline=False)
            else:
                embed.add_field(name="No Commands", value="This category has no slash commands.", inline=False)
        else:
            embed.title = "Error"
            embed.description = "Sorry, I couldn't find that category!"
            embed.color = discord.Color.red()

        # Ensure the original interaction can still be edited
        try:
            await interaction.response.edit_message(embed=embed, view=self.view) # self.view is the parent View
        except discord.InteractionResponded:
             # If the interaction was already responded to (e.g. by a defer), edit the original message
            await interaction.edit_original_response(embed=embed, view=self.view)
        except discord.NotFound: # If original message was deleted
            await interaction.followup.send(embed=embed, view=self.view, ephemeral=True)

class HelpView(discord.ui.View):
    def __init__(self, bot: commands.Bot, cog_map: dict, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(HelpSelect(bot, cog_map))

class HelpCog(commands.Cog, name="Help"):
    """Displays this help message, nya~"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="Shows Shiro's command categories and commands.")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False) # Defer for potentially longer processing

        embed = discord.Embed(title="Help - All Categories", color=discord.Color.purple())
        embed.description = "Hello! I'm Shiro, your friendly companion bot! Here are my command categories. Select one from the dropdown to see its commands~ UwU"
        embed.set_footer(text="Use the dropdown to explore categories.")

        # Prepare cog_map: Map cog qualified name to cog object
        # Filter out cogs without app commands if desired, or cogs with specific names like "Help"
        cog_map = {}
        for cog_name, cog_instance in self.bot.cogs.items():
            # Exclude cogs with no app commands or specific cogs like this HelpCog itself if desired.
            # For now, list all cogs that have a qualified_name.
            if hasattr(cog_instance, 'qualified_name') and cog_instance.get_app_commands():
                 # Use qualified_name for uniqueness and user-friendliness
                cog_map[cog_instance.qualified_name] = cog_instance
        
        # Initial embed population (overview)
        if not cog_map:
            embed.add_field(name="No Commands Found", value="It seems there are no slash commands registered or cogs loaded.", inline=False)
        else:
            for cog_name, cog_data in cog_map.items():
                command_count = len(cog_data.get_app_commands())
                embed.add_field(name=f"{cog_name} ({command_count} commands)", value=cog_data.description or "No description provided.", inline=False)

        view = HelpView(self.bot, cog_map)
        await interaction.followup.send(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(HelpCog(bot)) 