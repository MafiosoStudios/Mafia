import discord
from ui import MafiosoLayoutView


class RoleActionView(MafiosoLayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Use Role Ability", style=discord.ButtonStyle.danger)
    async def action_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_message("Role ability queued.", ephemeral=True)


