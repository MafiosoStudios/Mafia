from __future__ import annotations

from dataclasses import dataclass

import discord

from utils.embeds import build_embed, build_status_embed


@dataclass(frozen=True, slots=True)
class HelpTopic:
    value: str
    label: str
    description: str
    title: str
    body: str
    color: discord.Color


HELP_TOPICS: tuple[HelpTopic, ...] = (
    HelpTopic(
        value="lobby",
        label="Lobby",
        description="Create, join, leave, and start matches.",
        title="Lobby Commands",
        body=(
            "`lobby create` - open a new match lobby\n"
            "`lobby join` - join the current server lobby\n"
            "`lobby leave` - leave the lobby\n"
            "`lobby start` - begin the match if you are the leader, an admin, or have a bypass role"
        ),
        color=discord.Color.from_rgb(53, 169, 166),
    ),
    HelpTopic(
        value="game",
        label="Game",
        description="Check game state and access match tools.",
        title="Game Commands",
        body="`game status` - view the current match state",
        color=discord.Color.from_rgb(110, 58, 190),
    ),
    HelpTopic(
        value="profile",
        label="Profile",
        description="View your stats and player profile.",
        title="Profile Commands",
        body="`profile` - open your anime mafia profile",
        color=discord.Color.from_rgb(110, 58, 190),
    ),
    HelpTopic(
        value="shop",
        label="Shop",
        description="Browse cosmetics and inventory.",
        title="Shop Commands",
        body=(
            "`shop inventory` - view your cosmetic inventory\n"
            "`shop cosmetics` - browse available cosmetics"
        ),
        color=discord.Color.from_rgb(53, 169, 166),
    ),
    HelpTopic(
        value="leaderboard",
        label="Leaderboard",
        description="See the top players in the server.",
        title="Leaderboard Commands",
        body="`leaderboard wins` - see the top win totals",
        color=discord.Color.from_rgb(212, 175, 55),
    ),
    HelpTopic(
        value="admin",
        label="Admin",
        description="Moderator controls and maintenance tools.",
        title="Admin Commands",
        body="`admin sync` - sync application commands",
        color=discord.Color.from_rgb(201, 72, 72),
    ),
)


class HelpSelect(discord.ui.Select):
    def __init__(self, view: "HelpView") -> None:
        self.view_ref = view
        super().__init__(
            placeholder="Choose a command category...",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=topic.label, value=topic.value, description=topic.description)
                for topic in HELP_TOPICS
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        topic = next(topic for topic in HELP_TOPICS if topic.value == self.values[0])
        self.view_ref.selected_topic = topic.value
        embed = build_embed(topic.title, topic.body, color=topic.color)
        embed.add_field(name="Prefix", value=f"`{self.view_ref.prefix}{topic.label.lower()} ...`", inline=False)
        embed.add_field(name="Slash", value=f"`/{topic.label.lower()} ...`", inline=False)
        await interaction.response.edit_message(embed=embed, view=self.view_ref)


class HelpView(discord.ui.View):
    def __init__(self, prefix: str) -> None:
        super().__init__(timeout=180)
        self.prefix = prefix
        self.selected_topic: str | None = None
        self.add_item(HelpSelect(self))

    @staticmethod
    def build_index_embed(prefix: str) -> discord.Embed:
        lines = [
            f"`{prefix}lobby` - lobby management",
            f"`{prefix}game` - active match controls",
            f"`{prefix}profile` - player stats",
            f"`{prefix}shop` - cosmetics and inventory",
            f"`{prefix}leaderboard` - server rankings",
            f"`{prefix}admin` - moderator tools",
        ]
        embed = build_status_embed("Anime Mafia Help", "\n".join(lines))
        embed.add_field(name="How to use", value="Pick a category from the menu below to see a short explanation.", inline=False)
        return embed
