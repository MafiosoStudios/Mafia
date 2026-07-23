from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import ui

from config import get_emoji
from roles import ROLES_METADATA
from ui.base import MafiosoLayoutView
from ui.theme import (
    COLOR_PRIMARY,
    COLOR_SUCCESS,
    COLOR_ERROR,
    heading,
    subheading,
    small_footer,
)

if TYPE_CHECKING:
    from database import Database

logger = logging.getLogger(__name__)


def parse_option_emoji(emoji_str: str) -> discord.PartialEmoji | str | None:
    """Parses custom Discord emojis (<:name:id>) or unicode strings into PartialEmoji or str for UI controls."""
    if not emoji_str:
        return None
    emoji_str = emoji_str.strip()
    if emoji_str.startswith("<") and emoji_str.endswith(">"):
        try:
            return discord.PartialEmoji.from_str(emoji_str)
        except Exception:
            return None
    return emoji_str


class CustomRoleListMenuView(MafiosoLayoutView):
    """All-in-One Custom Role List Menu View using pure Components V2 Container layout."""

    def __init__(self, db: Database, guild_id: int, user_id: int, active_name: str | None = None):
        super().__init__(timeout=180.0)
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self.active_name = active_name
        self.saved_lists: dict[str, list[str]] = {}

    async def init_data(self) -> None:
        """Loads saved role lists from database."""
        try:
            self.saved_lists = await self.db.get_custom_role_lists(self.guild_id)
        except Exception:
            logger.exception("Failed to fetch custom role lists for guild %s", self.guild_id)
            self.saved_lists = {}
        self.build_components()

    def build_v2_card(self) -> MafiosoLayoutView:
        color = COLOR_PRIMARY
        header_text = f"{heading('Guild Custom Role Lists')}\nManage and select custom gamemode role lists for your server."

        lines: list[str] = []
        if not self.saved_lists:
            lines.append(f"{get_emoji('roster')} *No saved custom role lists found for this server.*")
            lines.append("Click **Create Rolelist** below to build one!")
        else:
            lines.append(f"{get_emoji('roster')} **Saved Role Lists ({len(self.saved_lists)})**\n")
            for name, r_list in self.saved_lists.items():
                is_active = f" {get_emoji('alive')} (Active)" if name == self.active_name else ""
                counts: dict[str, int] = {}
                for r in r_list:
                    counts[r] = counts.get(r, 0) + 1

                formatted_roles = []
                for r, count in counts.items():
                    meta = ROLES_METADATA.get(r, {})
                    r_name = meta.get("name", r)
                    r_emoji = get_emoji(r) or meta.get("emoji", "")
                    count_suffix = f" x{count}" if count > 1 else ""
                    formatted_roles.append(f"{r_emoji} {r_name}{count_suffix}")

                role_summary = ", ".join(formatted_roles[:8])
                if len(formatted_roles) > 8:
                    role_summary += f" ... (+{len(formatted_roles) - 8} more)"

                lines.append(
                    f"• **{name}**{is_active} — `{len(r_list)} Roles`\n  └ {role_summary or 'Empty'}"
                )

        body_md = "\n".join(lines)
        footer_md = f"Currently Active List: {self.active_name}" if self.active_name else "Select a role list from the dropdown below to set it as active."

        container = ui.Container(accent_color=color)
        container.add_item(ui.TextDisplay(header_text))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(body_md))

        items_to_add = [c for c in self.children if not isinstance(c, ui.Container)]
        if items_to_add:
            container.add_item(ui.Separator())
            current_row = ui.ActionRow()
            for item in items_to_add:
                if isinstance(item, ui.Select):
                    if current_row.children:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                    s_row = ui.ActionRow()
                    s_row.add_item(item)
                    container.add_item(s_row)
                elif isinstance(item, ui.Button):
                    current_row.add_item(item)
                    if len(current_row.children) == 5:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
            if current_row.children:
                container.add_item(current_row)

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer(footer_md)))

        layout = MafiosoLayoutView(timeout=self.timeout or 180.0)
        layout.add_item(container)
        return layout

    def build_components(self) -> None:
        self.clear_items()

        if self.saved_lists:
            options = []
            for name, r_list in self.saved_lists.items():
                is_def = (name == self.active_name)
                options.append(
                    discord.SelectOption(
                        label=name,
                        value=name,
                        description=f"{len(r_list)} custom roles in pool",
                        emoji=parse_option_emoji(get_emoji("roster")),
                        default=is_def,
                    )
                )

            select = discord.ui.Select(
                placeholder="Select a custom role list to load as active...",
                options=options[:25],
                custom_id="custom_list_select_active",
            )
            select.callback = self.on_select_active
            self.add_item(select)

        create_btn = discord.ui.Button(
            label="Create Rolelist",
            style=discord.ButtonStyle.success,
            emoji=parse_option_emoji(get_emoji("join")),
            custom_id="custom_list_btn_create",
        )
        create_btn.callback = self.on_click_create
        self.add_item(create_btn)

        if self.saved_lists:
            delete_btn = discord.ui.Button(
                label="Delete Rolelist",
                style=discord.ButtonStyle.danger,
                emoji=parse_option_emoji(get_emoji("trash")),
                custom_id="custom_list_btn_delete",
            )
            delete_btn.callback = self.on_click_delete
            self.add_item(delete_btn)

    async def on_select_active(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id != self.user_id:
            await interaction.followup.send("Only the menu invoker can select the active list.", ephemeral=True)
            return

        select_component = interaction.data.get("values", [])
        if not select_component:
            return

        chosen_name = select_component[0]
        self.active_name = chosen_name
        self.build_components()
        v2_card = self.build_v2_card()

        await interaction.edit_original_response(view=v2_card)
        await interaction.followup.send(f"Loaded **{chosen_name}** as active custom role list.", ephemeral=True)

    async def on_click_create(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        create_view = CustomRoleListCreateView(self.db, self.guild_id, interaction.user.id, parent_view=self)
        v2_card = create_view.build_v2_card()
        await interaction.followup.send(view=v2_card, ephemeral=True)

    async def on_click_delete(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        delete_view = CustomRoleListDeleteView(self.db, self.guild_id, interaction.user.id, self.saved_lists, parent_view=self)
        v2_card = delete_view.build_v2_card()
        await interaction.followup.send(view=v2_card, ephemeral=True)


class CustomListNameModal(discord.ui.Modal, title="Set Custom Role List Name"):
    name_input = discord.ui.TextInput(
        label="Role List Name",
        placeholder="e.g. Higuruma Madness, Chaos Mode",
        min_length=2,
        max_length=32,
        required=True,
    )

    def __init__(self, create_view: CustomRoleListCreateView):
        super().__init__()
        self.create_view = create_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        self.create_view.list_name = self.name_input.value.strip()
        self.create_view.build_components()
        v2_card = self.create_view.build_v2_card()
        await interaction.edit_original_response(view=v2_card)


class CustomRoleListCreateView(MafiosoLayoutView):
    """Interactive Builder View for creating/editing a custom role list using V2 Container card layout."""

    def __init__(
        self,
        db: Database,
        guild_id: int,
        user_id: int,
        parent_view: CustomRoleListMenuView | None = None,
    ):
        super().__init__(timeout=300.0)
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self.parent_view = parent_view
        self.list_name: str = "My Custom List"
        self.draft_roles: list[str] = []
        self.build_components()

    def build_v2_card(self) -> MafiosoLayoutView:
        color = COLOR_PRIMARY
        header_text = f"{heading(f'Role List Builder: {self.list_name}')}\nAdd roles using the dropdowns below. You can select the same role multiple times."

        counts: dict[str, int] = {}
        for r in self.draft_roles:
            counts[r] = counts.get(r, 0) + 1

        if not self.draft_roles:
            role_breakdown = f"{get_emoji('roster')} *No roles added yet. Use the dropdown below to add roles!*"
        else:
            role_lines = [f"{get_emoji('roster')} **Current Draft Pool ({len(self.draft_roles)} Roles)**\n"]
            for idx, (r_key, count) in enumerate(counts.items(), 1):
                meta = ROLES_METADATA.get(r_key, {})
                name = meta.get("name", r_key)
                r_emoji = get_emoji(r_key) or meta.get("emoji", "")
                faction = meta.get("faction", "Unknown")
                faction_emoji = get_emoji(faction)
                role_lines.append(f"`{idx}.` {r_emoji} **{name}** ({faction_emoji} {faction}) — **x{count}**")
            role_breakdown = "\n".join(role_lines)

        container = ui.Container(accent_color=color)
        container.add_item(ui.TextDisplay(header_text))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(role_breakdown))

        items_to_add = [c for c in self.children if not isinstance(c, ui.Container)]
        if items_to_add:
            container.add_item(ui.Separator())
            current_row = ui.ActionRow()
            for item in items_to_add:
                if isinstance(item, ui.Select):
                    if current_row.children:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                    s_row = ui.ActionRow()
                    s_row.add_item(item)
                    container.add_item(s_row)
                elif isinstance(item, ui.Button):
                    current_row.add_item(item)
                    if len(current_row.children) == 5:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
            if current_row.children:
                container.add_item(current_row)

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer("Click 'Save Rolelist' when finished to store for your server.")))

        layout = MafiosoLayoutView(timeout=self.timeout or 300.0)
        layout.add_item(container)
        return layout

    def build_components(self) -> None:
        self.clear_items()

        name_btn = discord.ui.Button(
            label=f"Name: {self.list_name[:15]}",
            style=discord.ButtonStyle.secondary,
            emoji=parse_option_emoji(get_emoji("settings")),
            custom_id="create_btn_set_name",
        )
        name_btn.callback = self.on_set_name
        self.add_item(name_btn)

        add_options = []
        for r_key, meta in ROLES_METADATA.items():
            name = meta.get("name", r_key)
            r_emoji = get_emoji(r_key) or meta.get("emoji", "")
            faction = meta.get("faction", "")
            add_options.append(
                discord.SelectOption(
                    label=name,
                    value=r_key,
                    description=f"{faction} faction",
                    emoji=parse_option_emoji(r_emoji),
                )
            )

        if add_options:
            add_select = discord.ui.Select(
                placeholder="Select a role to add (can add multiple)...",
                options=add_options[:25],
                custom_id="create_select_add_role",
            )
            add_select.callback = self.on_add_role
            self.add_item(add_select)

        if self.draft_roles:
            unique_draft = list(dict.fromkeys(self.draft_roles))
            rem_options = []
            for r_key in unique_draft:
                meta = ROLES_METADATA.get(r_key, {})
                name = meta.get("name", r_key)
                r_emoji = get_emoji(r_key) or meta.get("emoji", "")
                rem_options.append(
                    discord.SelectOption(
                        label=f"Remove 1x {name}",
                        value=r_key,
                        emoji=parse_option_emoji(r_emoji),
                    )
                )

            rem_select = discord.ui.Select(
                placeholder="Select a role to remove 1x...",
                options=rem_options[:25],
                custom_id="create_select_rem_role",
            )
            rem_select.callback = self.on_remove_role
            self.add_item(rem_select)

        save_btn = discord.ui.Button(
            label="Save Rolelist",
            style=discord.ButtonStyle.success,
            emoji=parse_option_emoji(get_emoji("save")),
            custom_id="create_btn_save",
        )
        save_btn.callback = self.on_save
        self.add_item(save_btn)

    async def on_set_name(self, interaction: discord.Interaction) -> None:
        modal = CustomListNameModal(self)
        await interaction.response.send_modal(modal)

    async def on_add_role(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        values = interaction.data.get("values", [])
        if values:
            r_key = values[0]
            self.draft_roles.append(r_key)
            self.build_components()
            v2_card = self.build_v2_card()
            await interaction.edit_original_response(view=v2_card)

    async def on_remove_role(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        values = interaction.data.get("values", [])
        if values:
            r_key = values[0]
            if r_key in self.draft_roles:
                self.draft_roles.remove(r_key)
                self.build_components()
                v2_card = self.build_v2_card()
                await interaction.edit_original_response(view=v2_card)

    async def on_save(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.draft_roles:
            await interaction.followup.send("You must add at least 1 role before saving.", ephemeral=True)
            return

        try:
            await self.db.save_custom_role_list(self.guild_id, self.list_name, self.draft_roles)
        except Exception:
            logger.exception("Failed to save custom role list %s for guild %s", self.list_name, self.guild_id)
            await interaction.followup.send("Failed to save role list to database.", ephemeral=True)
            return

        if self.parent_view:
            await self.parent_view.init_data()
            self.parent_view.active_name = self.list_name
            self.parent_view.build_components()
            parent_v2 = self.parent_view.build_v2_card()
            try:
                await interaction.edit_original_response(view=parent_v2)
            except Exception:
                pass

        await interaction.followup.send(
            f"Saved **{self.list_name}** with `{len(self.draft_roles)}` roles and set it as active.",
            ephemeral=True,
        )


class CustomRoleListDeleteView(MafiosoLayoutView):
    """Ephemeral view to select and delete a saved custom role list using V2 Container card layout."""

    def __init__(
        self,
        db: Database,
        guild_id: int,
        user_id: int,
        saved_lists: dict[str, list[str]],
        parent_view: CustomRoleListMenuView | None = None,
    ):
        super().__init__(timeout=120.0)
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self.saved_lists = saved_lists
        self.parent_view = parent_view
        self.build_components()

    def build_v2_card(self) -> MafiosoLayoutView:
        color = COLOR_ERROR
        header_text = f"{heading('Delete Custom Role List')}\nSelect a custom role list from the dropdown below to permanently delete it."

        container = ui.Container(accent_color=color)
        container.add_item(ui.TextDisplay(header_text))
        container.add_item(ui.Separator())

        items_to_add = [c for c in self.children if not isinstance(c, ui.Container)]
        if items_to_add:
            current_row = ui.ActionRow()
            for item in items_to_add:
                if isinstance(item, ui.Select):
                    if current_row.children:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                    s_row = ui.ActionRow()
                    s_row.add_item(item)
                    container.add_item(s_row)
                elif isinstance(item, ui.Button):
                    current_row.add_item(item)
                    if len(current_row.children) == 5:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
            if current_row.children:
                container.add_item(current_row)

        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer("Warning: Deletion is permanent and cannot be undone.")))

        layout = MafiosoLayoutView(timeout=self.timeout or 120.0)
        layout.add_item(container)
        return layout

    def build_components(self) -> None:
        self.clear_items()
        if not self.saved_lists:
            return

        options = [
            discord.SelectOption(
                label=name,
                value=name,
                description=f"Delete {name} ({len(r_list)} roles)",
                emoji=parse_option_emoji(get_emoji("trash")),
            )
            for name, r_list in self.saved_lists.items()
        ]

        select = discord.ui.Select(
            placeholder="Select a role list to delete...",
            options=options[:25],
            custom_id="delete_select_list",
        )
        select.callback = self.on_delete_select
        self.add_item(select)

    async def on_delete_select(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        values = interaction.data.get("values", [])
        if not values:
            return

        target_name = values[0]
        try:
            await self.db.delete_custom_role_list(self.guild_id, target_name)
        except Exception:
            logger.exception("Failed to delete custom role list %s", target_name)
            await interaction.followup.send("Failed to delete role list.", ephemeral=True)
            return

        if self.parent_view:
            await self.parent_view.init_data()
            if self.parent_view.active_name == target_name:
                self.parent_view.active_name = None
            self.parent_view.build_components()
            parent_v2 = self.parent_view.build_v2_card()
            try:
                await interaction.edit_original_response(view=parent_v2)
            except Exception:
                pass

        await interaction.followup.send(f"Successfully deleted custom role list **{target_name}**.", ephemeral=True)
