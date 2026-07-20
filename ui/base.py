from __future__ import annotations

import logging
import discord
from discord import ui

from ui.theme import COLOR_ERROR, heading, small_footer

logger = logging.getLogger(__name__)


from typing import Any


class MafiosoLayoutView(ui.LayoutView):
    """Base LayoutView for all Mafioso Components V2 views.
    
    Provides standardized error handling, automatic ActionRow wrapping for top-level interactive components,
    and consistent interaction behavior across the bot.
    """

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        # Ensure all decorated @ui.button and @ui.select methods are included in __view_children_items__
        for base in reversed(cls.__mro__):
            for name, member in base.__dict__.items():
                if hasattr(member, "__discord_ui_model_type__"):
                    if name not in cls.__view_children_items__:
                        cls.__view_children_items__[name] = member

    def to_components(self) -> list[dict[str, Any]]:
        raw = super().to_components()
        container_idx = next((i for i, c in enumerate(raw) if c.get("type") == 17), None)
        
        if container_idx is not None:
            container = raw[container_idx]
            container_comps = container.get("components", [])
            
            footer_idx = len(container_comps)
            for i in range(len(container_comps) - 1, -1, -1):
                if container_comps[i].get("type") == 14:
                    footer_idx = i
                    break
                    
            loose_items = []
            new_raw = []
            for i, comp in enumerate(raw):
                if i == container_idx:
                    new_raw.append(comp)
                elif comp.get("type") in (1, 2, 3, 5, 6, 7, 8):
                    loose_items.append(comp)
                else:
                    new_raw.append(comp)
                    
            if loose_items:
                inserted_rows: list[dict[str, Any]] = []
                current_action_row: list[dict[str, Any]] = []
                def flush_action_row() -> None:
                    nonlocal current_action_row
                    if current_action_row:
                        inserted_rows.append({"type": 1, "components": current_action_row})
                        current_action_row = []

                for item in loose_items:
                    itype = item.get("type")
                    if itype == 1:
                        flush_action_row()
                        inserted_rows.append(item)
                    elif itype in (3, 5, 6, 7, 8):
                        flush_action_row()
                        inserted_rows.append({"type": 1, "components": [item]})
                    elif itype == 2:
                        current_action_row.append(item)
                        if len(current_action_row) == 5:
                            flush_action_row()
                flush_action_row()

                if inserted_rows:
                    new_container_comps = (
                        container_comps[:footer_idx]
                        + [{"type": 14, "divider": True, "spacing": 1}]
                        + inserted_rows
                        + container_comps[footer_idx:]
                    )
                    container["components"] = new_container_comps
            return new_raw

        result: list[dict[str, Any]] = []
        current_action_row: list[dict[str, Any]] = []

        def flush_action_row_fallback() -> None:
            nonlocal current_action_row
            if current_action_row:
                result.append({"type": 1, "components": current_action_row})
                current_action_row = []

        for comp in raw:
            ctype = comp.get("type")
            if ctype in (2, 3, 5, 6, 7, 8):
                if ctype in (3, 5, 6, 7, 8):
                    flush_action_row_fallback()
                    result.append({"type": 1, "components": [comp]})
                else:
                    current_action_row.append(comp)
                    if len(current_action_row) == 5:
                        flush_action_row_fallback()
            else:
                flush_action_row_fallback()
                result.append(comp)

        flush_action_row_fallback()
        return result


    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: ui.Item[ui.LayoutView],
    ) -> None:
        if isinstance(error, discord.NotFound) and getattr(error, "code", None) == 10062:
            logger.debug("Interaction expired for %s in %s", item, self.__class__.__name__)
            return

        logger.error(
            "Unhandled exception in LayoutView %s for item %s",
            self.__class__.__name__,
            item,
            exc_info=error,
        )
        
        container = ui.Container(accent_color=COLOR_ERROR)
        container.add_item(ui.TextDisplay(f"{heading('An Error Occurred')}\nSomething went wrong while processing your request."))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer("Mafioso Game System")))
        
        error_view = ui.LayoutView(timeout=30)
        error_view.add_item(container)
        
        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=error_view, ephemeral=True)
            else:
                await interaction.response.send_message(view=error_view, ephemeral=True)
        except Exception as send_err:
            if not (isinstance(send_err, discord.NotFound) and getattr(send_err, "code", None) == 10062):
                logger.error("Failed to send error response card: %s", send_err)

