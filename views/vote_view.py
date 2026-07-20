import discord
from ui import MafiosoLayoutView


class VoteView(MafiosoLayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Confirm Vote", style=discord.ButtonStyle.primary)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_message("Vote received.", ephemeral=True)


