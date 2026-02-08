import discord


class ConfirmView(discord.ui.View):
    def __init__(self, owner_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.confirmed = False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return
        self.confirmed = True
        await interaction.response.edit_message(content="Confirmed.", view=None)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return
        self.confirmed = False
        await interaction.response.edit_message(content="Cancelled.", view=None)
        self.stop()
