from __future__ import annotations

import discord


class NightView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)

    @discord.ui.button(label="Submit Night Action", style=discord.ButtonStyle.primary)
    async def submit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button["NightView"],
    ) -> None:
        await interaction.response.send_message("Night action submitted.", ephemeral=True)
