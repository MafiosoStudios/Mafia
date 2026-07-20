from __future__ import annotations

from dataclasses import dataclass
import discord
from discord import ui
from config import get_emoji, get_event_image
from ui.base import MafiosoLayoutView
from ui.theme import (
    COLOR_PRIMARY,
    heading,
    subheading,
    small_footer,
)


@dataclass(frozen=True, slots=True)
class TutorialTopic:
    value: str
    label: str
    description: str
    title: str
    body: str
    color: discord.Color
    image_key: str | None = None


TUTORIAL_TOPICS: tuple[TutorialTopic, ...] = (
    TutorialTopic(
        value="overview",
        label="General Overview",
        description="Learn the base factions, objectives, and win conditions.",
        title=f"{get_emoji('book')} Tutorial: The Anime Arena of Shadow & Deception",
        body=(
            "Welcome to the battlefield. Here, you are cast into a deadly game of secrets, social deduction, and anime-themed abilities.\n\n"
            f"{get_emoji('roster')} **The Factions:**\n"
            f"• **Protagonists (Town) {get_emoji('Protagonist')}:** The majority. You do not know who your allies are, but you must find and eliminate the Villains through voting and deductive abilities.\n"
            f"• **Villains (Mafia) {get_emoji('Antagonist')}:** The informed minority. You know your teammates and share a private conspiracy channel. Plot in the dark and eliminate the Protagonists until you match or exceed their numbers.\n"
            f"• **Neutrals (Wildcards) {get_emoji('Neutral')}:** Solitary agents with unique, game-bending win conditions (e.g., Lelouch, Gilgamesh)."
        ),
        color=discord.Color.purple(),
        image_key="rules",
    ),
    TutorialTopic(
        value="phases",
        label="Game Phases",
        description="Understand the day/night cycle, trial, and verdicts.",
        title=f"{get_emoji('night')} Tutorial: The Cycle of Day & Night",
        body=(
            "Time in the arena is structured in distinct, repeating cycles. Master the phases to dominate:\n\n"
            f"{get_emoji('milky_way')} **1. Night Phase (Sneaky Phase):**\n"
            "• Silence falls upon the main channel. No player can send messages.\n"
            "• Everyone checks their DMs or uses the buttons in the main channel to submit secret abilities.\n"
            "• Villains discuss in their private corner and nominate a target to eliminate.\n\n"
            f"{get_emoji('sun')} **2. Day Discussion:**\n"
            "• Sunrise! The channel is unmuted. Dead players are announced, and their secret roles are revealed.\n"
            "• Discuss evidence, form alliances, and spot contradictions.\n\n"
            f"{get_emoji('trial')} **3. Nomination & Trial:**\n"
            "• Nominate players to stand trial. Once a player receives a majority of nominations, they are dragged onto the stand.\n"
            "• The defendant has a brief **Plea Phase** to defend themselves.\n"
            "• Finally, everyone votes **Guilty** or **Innocent**."
        ),
        color=discord.Color.blue(),
        image_key="night",
    ),
    TutorialTopic(
        value="roles",
        label="Roles & Factions",
        description="Discover active/passive abilities and power roles.",
        title=f"{get_emoji('sword')} Tutorial: Unique Characters & Faction Wars",
        body=(
            "Every player is assigned a unique character role with specialized actions:\n\n"
            f"{get_emoji('dna')} **Abilities:**\n"
            "• **Active Abilities:** Actions you manually queue during the Night (e.g., healing, roleblocking, investigating, killing).\n"
            "• **Passive Abilities:** Automatic effects that trigger under specific conditions (e.g., death immunity, redirection immunity, revenge tags).\n\n"
            f"{get_emoji('fire')} **Power Roles:**\n"
            "• **Ayanokoji:** Absolute manipulation, scanning factions, and altering vote weight.\n"
            "• **Frieza:** Absolute villainy, building up kills to become **Golden Frieza**.\n"
            "• **Gilgamesh:** Accumulating swords from dead players to trigger the **Apocalypse**.\n"
            "• **Lelouch:** Controlling targets with **Geass** to force their votes/actions."
        ),
        color=discord.Color.red(),
        image_key="match_start",
    ),
    TutorialTopic(
        value="commands",
        label="Commands Quickstart",
        description="Quick guide to lobby, profile, shop, and ranks.",
        title=f"{get_emoji('lobby')} Tutorial: Commands & Interface Guide",
        body=(
            "Navigate the arena and manage your progression using these core commands:\n\n"
            f"{get_emoji('pushpin')} **Lobby & Matches:**\n"
            "• `/lobby` - View active lobby status, join/leave a lobby.\n"
            "• `/lobby_create` - Create a new match lobby.\n"
            "• `/game status` - View the active match's player list and alive status.\n\n"
            f"{get_emoji('moneybag')} **Economy & Shop:**\n"
            "• `/profile` - View your global level, XP, coins, favorite character, and stats.\n"
            "• `/shop` - Spend your coins to buy character cards, icons, and cosmetics.\n"
            "• `/inventory` - View and equip your purchased characters and cosmetics.\n"
            "• `/leaderboard` - Compare global wins and see who reigns supreme!"
        ),
        color=discord.Color.green(),
        image_key="vote",
    ),
)


def _build_tutorial_card(selected_value: str | None = None) -> ui.Container:
    topic = next((t for t in TUTORIAL_TOPICS if t.value == selected_value), None)

    if topic:
        accent_color = topic.color
        header_md = heading(topic.title)
        body_md = topic.body
        image_key = topic.image_key
    else:
        accent_color = COLOR_PRIMARY
        header_md = heading(f"{get_emoji('book')} Mafioso Remastered Tutorial")
        body_md = (
            "Welcome to the **Mafioso Interactive Walkthrough**!\n\n"
            "Use the dropdown select menu below to explore different guides:\n"
            "• **General Overview:** Objective, Factions (Town, Mafia, Neutral).\n"
            "• **Game Phases:** Day/Night cycle, discussion, trial, voting.\n"
            "• **Roles & Factions:** Active/passive abilities and key characters.\n"
            "• **Commands Quickstart:** Playing matches, profile, shop, rankings."
        )
        image_key = "rules"

    container = ui.Container(accent_color=accent_color)
    container.add_item(ui.TextDisplay(f"{header_md}\n\n{body_md}"))

    if image_key:
        img_url = get_event_image(image_key)
        if img_url:
            container.add_item(ui.MediaGallery(discord.MediaGalleryItem(img_url)))

    return container


class TutorialSelect(ui.Select):
    def __init__(self, current_value: str | None = None) -> None:
        options = [
            discord.SelectOption(
                label=topic.label,
                value=topic.value,
                description=topic.description,
                default=(topic.value == current_value),
            )
            for topic in TUTORIAL_TOPICS
        ]
        super().__init__(
            placeholder="Select a tutorial topic...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="tutorial_topic_select",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        val = self.values[0]
        new_view = TutorialView(selected_value=val)
        try:
            await interaction.response.edit_message(view=new_view)
        except (discord.NotFound, discord.InteractionResponded):
            try:
                if interaction.message:
                    await interaction.followup.edit_message(message_id=interaction.message.id, view=new_view)
            except Exception:
                pass
        except Exception:
            pass


class TutorialView(MafiosoLayoutView):
    """Components V2 LayoutView for the interactive tutorial guide."""

    def __init__(self, selected_value: str | None = None) -> None:
        super().__init__(timeout=180)
        self.selected_value = selected_value

        container = _build_tutorial_card(selected_value)
        container.add_item(ui.Separator())
        container.add_item(ui.ActionRow(TutorialSelect(selected_value)))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer("Anime Mafia")))


        self.add_item(container)
