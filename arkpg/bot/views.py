import discord


class _CallsignModal(discord.ui.Modal, title="Edit Callsign"):
    callsign = discord.ui.TextInput(label="Callsign", max_length=32)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile editor isn't for you.", ephemeral=True)
            return
        from arkpg.db.session import SessionLocal
        from arkpg.game.service import update_user_profile

        async with SessionLocal() as session:
            _, profile = await update_user_profile(session, interaction.user.id, callsign=str(self.callsign.value))
        await interaction.response.send_message(f"Updated callsign to **{profile['callsign']}**.", ephemeral=True)


class _BioModal(discord.ui.Modal, title="Edit Bio"):
    bio = discord.ui.TextInput(label="Bio", max_length=220, style=discord.TextStyle.paragraph)

    def __init__(self, owner_id: int):
        super().__init__()
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile editor isn't for you.", ephemeral=True)
            return
        from arkpg.db.session import SessionLocal
        from arkpg.game.service import update_user_profile

        async with SessionLocal() as session:
            await update_user_profile(session, interaction.user.id, bio=str(self.bio.value))
        await interaction.response.send_message("Updated your bio.", ephemeral=True)


class _TitleSelect(discord.ui.Select):
    def __init__(self, owner_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose an earned title", min_values=1, max_values=1, options=options[:25])
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile editor isn't for you.", ephemeral=True)
            return
        title_id = self.values[0]
        from sqlalchemy import and_, select
        from arkpg.db.models import UserTitle
        from arkpg.db.session import SessionLocal
        from arkpg.game.service import get_or_create_user

        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            owned = (await session.execute(select(UserTitle).where(and_(UserTitle.user_id == user.id, UserTitle.title_id == title_id)))).scalar_one_or_none()
            if owned is None:
                await interaction.response.send_message("You haven't earned that title.", ephemeral=True)
                return
            user.equipped_title_id = title_id
            await session.commit()
        await interaction.response.send_message("Title equipped.", ephemeral=True)


class _BackgroundSelect(discord.ui.Select):
    def __init__(self, owner_id: int, options: list[discord.SelectOption]):
        super().__init__(placeholder="Choose a collected background", min_values=1, max_values=1, options=options[:25])
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile editor isn't for you.", ephemeral=True)
            return
        background_id = self.values[0]
        from arkpg.db.session import SessionLocal
        from arkpg.game.service import update_user_profile

        async with SessionLocal() as session:
            await update_user_profile(session, interaction.user.id, background_id=background_id)
        await interaction.response.send_message("Background equipped.", ephemeral=True)


class ProfileEditorView(discord.ui.View):
    def __init__(self, owner_id: int, title_options: list[discord.SelectOption], background_options: list[discord.SelectOption], timeout: float = 300):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        if title_options:
            self.add_item(_TitleSelect(owner_id=owner_id, options=title_options))
        if background_options:
            self.add_item(_BackgroundSelect(owner_id=owner_id, options=background_options))

    async def _assert_owner(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This profile editor isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Edit Callsign", style=discord.ButtonStyle.primary)
    async def edit_callsign(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._assert_owner(interaction):
            return
        await interaction.response.send_modal(_CallsignModal(owner_id=self.owner_id))

    @discord.ui.button(label="Edit Bio", style=discord.ButtonStyle.secondary)
    async def edit_bio(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not await self._assert_owner(interaction):
            return
        await interaction.response.send_modal(_BioModal(owner_id=self.owner_id))

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


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
