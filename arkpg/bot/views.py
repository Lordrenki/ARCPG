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


class PaginatedEmbedView(discord.ui.View):
    def __init__(self, owner_id: int, pages: list[discord.Embed], timeout: float = 180):
        super().__init__(timeout=timeout)
        if not pages:
            raise ValueError("At least one embed page is required.")
        self.owner_id = owner_id
        self.pages = pages
        self.page_index = 0
        self._sync_buttons()

    def current_embed(self) -> discord.Embed:
        return self.pages[self.page_index]

    def _sync_buttons(self) -> None:
        page_count = len(self.pages)
        self.previous.disabled = self.page_index == 0
        self.next.disabled = self.page_index >= page_count - 1

    async def _change_page(self, interaction: discord.Interaction, delta: int) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This menu isn't for you.", ephemeral=True)
            return
        self.page_index = max(0, min(self.page_index + delta, len(self.pages) - 1))
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._change_page(interaction, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._change_page(interaction, 1)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
