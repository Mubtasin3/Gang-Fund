"""
GTA RP Gang Fund Bot
=====================

A Discord bot that tracks a per-player "gang fund" payment amount and
whether each member has paid. Includes a live, self-updating panel
(embed + buttons) and a full set of slash commands.

Requirements:
    pip install -U discord.py

Environment variables:
    TOKEN            - your bot token
    GUILD_ID         - the guild (server) ID to sync commands to
    ADMIN_ROLE_ID    - role ID allowed to manage the fund
"""

import asyncio
import json
import os
import re

import discord
from discord import app_commands
from discord.ext import commands

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")

if not TOKEN:
    raise ValueError("TOKEN environment variable is missing!")
if not GUILD_ID:
    raise ValueError("GUILD_ID environment variable is missing!")
if not ADMIN_ROLE_ID:
    raise ValueError("ADMIN_ROLE_ID environment variable is missing!")

try:
    GUILD_ID = int(GUILD_ID)
    ADMIN_ROLE_ID = int(ADMIN_ROLE_ID)
except ValueError:
    raise ValueError("GUILD_ID and ADMIN_ROLE_ID must be numeric Discord IDs!")

DATA_FILE = "data.json"
SELECT_PAGE_SIZE = 25  # Discord's hard limit per select menu

# A lock so concurrent interactions can't corrupt data.json with
# interleaved read-modify-write cycles.
data_lock = asyncio.Lock()


# ============================================================
# DATA LAYER
# ============================================================

def default_data():
    return {
        "amount": 0,
        "members": {},   # {user_id(str): bool paid}
        "panels": [],     # [{"channel_id": int, "message_id": int}, ...]
    }


def save_data():
    try:
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
        os.replace(temp_file, DATA_FILE)
    except Exception as e:
        print(f"[DATA ERROR] Could not save data: {e}")


def load_data():
    if not os.path.exists(DATA_FILE):
        new_data = default_data()
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as file:
                json.dump(new_data, file, indent=4)
        except Exception as e:
            print(f"[DATA ERROR] Could not create data.json: {e}")
        return new_data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            return default_data()

        loaded.setdefault("amount", 0)
        loaded.setdefault("members", {})
        loaded.setdefault("panels", [])

        return loaded

    except Exception as e:
        print(f"[DATA ERROR] Could not load data.json: {e}")
        return default_data()


data = load_data()


# ============================================================
# CONVERT OLD DATA TO DISCORD IDS
# ============================================================

def convert_old_member_ids():
    members = data.get("members", {})
    converted = {}
    changed = False

    for key, paid in members.items():
        key = str(key)

        if key.isdigit():
            converted[key] = bool(paid)
            continue

        # Convert legacy "<@123456789>" / "<@!123456789>" style keys
        match = re.fullmatch(r"<@!?(\d+)>", key)
        if match:
            converted[match.group(1)] = bool(paid)
            changed = True
        else:
            converted[key] = bool(paid)

    if changed:
        data["members"] = converted
        save_data()
        print("[DATA] Converted old Discord mentions to IDs.")


convert_old_member_ids()


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.members = True  # Requires the "Server Members Intent" enabled
                          # in the Discord Developer Portal.


class GangFundBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False
        self.views_added = False


bot = GangFundBot()


# ============================================================
# SAFE INTERACTION HELPERS
# ============================================================

async def safe_defer(interaction: discord.Interaction, ephemeral=False):
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.NotFound:
        print("[INTERACTION] Interaction expired before defer.")
        return False
    except discord.HTTPException as e:
        print(f"[INTERACTION] Defer failed: {e}")
        return False


async def safe_followup(interaction: discord.Interaction, content=None,
                         embed=None, view=None, ephemeral=False):
    try:
        return await interaction.followup.send(
            content=content, embed=embed, view=view, ephemeral=ephemeral
        )
    except discord.NotFound:
        print("[INTERACTION] Interaction expired before followup.")
        return None
    except discord.HTTPException as e:
        print(f"[INTERACTION] Followup failed: {e}")
        return None


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(interaction: discord.Interaction):
    if not interaction.guild:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    role = interaction.guild.get_role(ADMIN_ROLE_ID)
    return bool(role and role in interaction.user.roles)


# ============================================================
# MEMBER HELPERS
# ============================================================

async def get_member(guild: discord.Guild, user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    member = guild.get_member(user_id)
    if member:
        return member

    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None


async def get_display_name(guild: discord.Guild, user_id):
    member = await get_member(guild, user_id)
    if member:
        return member.display_name
    return f"Unknown User ({user_id})"


# ============================================================
# FUND EMBED
# ============================================================

async def create_fund_embed(guild: discord.Guild):
    amount = int(data.get("amount", 0))
    members = data.get("members", {})

    total_members = len(members)
    paid_members = sum(1 for paid in members.values() if paid is True)
    unpaid_members = total_members - paid_members

    collected = paid_members * amount
    required = total_members * amount

    embed = discord.Embed(
        title="💰 GTA RP GANG FUND",
        description=(
            "Gang fund payment tracker\n\n"
            "Use the buttons below to mark members as paid or unpaid."
        ),
        color=discord.Color.green(),
    )

    embed.add_field(name="💵 Fund Per Player", value=f"${amount:,}", inline=True)
    embed.add_field(name="👥 Members", value=str(total_members), inline=True)
    embed.add_field(name="💰 Collected", value=f"${collected:,} / ${required:,}", inline=True)
    embed.add_field(name="✅ Paid", value=str(paid_members), inline=True)
    embed.add_field(name="❌ Unpaid", value=str(unpaid_members), inline=True)

    if members:
        member_lines = []
        for user_id, paid in members.items():
            player_name = await get_display_name(guild, user_id)
            mark = "✅" if paid is True else "❌"
            status = "Paid" if paid is True else "Unpaid"
            member_lines.append(f"{mark} **{player_name}** — {status}")

        chunks = []
        current = ""
        for line in member_lines:
            if len(current) + len(line) + 1 > 1000:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks):
            name = "📋 Member List" if index == 0 else "📋 Member List (Continued)"
            embed.add_field(name=name, value=chunk, inline=False)
    else:
        embed.add_field(name="📋 Member List", value="No members added yet.", inline=False)

    embed.set_footer(text="Gang Fund System")
    return embed


# ============================================================
# PANEL TRACKING — keeps every posted panel in sync, everywhere
# ============================================================

async def register_panel(channel_id: int, message_id: int):
    async with data_lock:
        data["panels"].append({"channel_id": channel_id, "message_id": message_id})
        save_data()


async def refresh_all_panels(guild: discord.Guild):
    """Re-render every known panel message with fresh data.
    Silently forgets panels that no longer exist."""
    if not data["panels"]:
        return

    embed = await create_fund_embed(guild)
    still_valid = []

    for ref in data["panels"]:
        channel = guild.get_channel(ref["channel_id"])
        if channel is None:
            try:
                channel = await guild.fetch_channel(ref["channel_id"])
            except discord.HTTPException:
                continue  # channel gone, drop this panel ref

        try:
            message = await channel.fetch_message(ref["message_id"])
            await message.edit(embed=embed, view=FundView())
            still_valid.append(ref)
        except discord.NotFound:
            continue  # message deleted, drop this panel ref
        except discord.HTTPException as e:
            print(f"[PANEL] Could not update panel {ref}: {e}")
            still_valid.append(ref)  # transient error, keep it around

    if len(still_valid) != len(data["panels"]):
        data["panels"] = still_valid
        save_data()


# ============================================================
# PAGINATED PLAYER SELECT (handles any number of members)
# ============================================================

class PlayerSelect(discord.ui.Select):
    """One page of up to 25 players. `mark_as` is the paid-state
    this select will set when a player is chosen."""

    def __init__(self, options, mark_as: bool):
        self.mark_as = mark_as
        placeholder = "Choose a player who paid..." if mark_as else "Choose a player who is unpaid..."
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        user_id = self.values[0]

        success = await safe_defer(interaction, ephemeral=True)
        if not success:
            return

        async with data_lock:
            if user_id not in data["members"]:
                await safe_followup(
                    interaction,
                    content="❌ This player is no longer in the gang fund.",
                    ephemeral=True,
                )
                return

            data["members"][user_id] = self.mark_as
            save_data()

        player_name = await get_display_name(interaction.guild, user_id)
        status = "PAID" if self.mark_as else "UNPAID"
        await safe_followup(
            interaction,
            content=f"{'✅' if self.mark_as else '❌'} **{player_name}** has been marked as **{status}**.",
            ephemeral=True,
        )

        await refresh_all_panels(interaction.guild)


class PlayerPaginatedView(discord.ui.View):
    """Ephemeral view with a player select plus Prev/Next paging."""

    def __init__(self, guild: discord.Guild, entries, mark_as: bool):
        super().__init__(timeout=60)
        self.guild = guild
        self.entries = entries  # list of (user_id, discord.SelectOption)
        self.mark_as = mark_as
        self.page = 0
        self._render_page()

    @property
    def max_page(self):
        return max(0, (len(self.entries) - 1) // SELECT_PAGE_SIZE)

    def _render_page(self):
        self.clear_items()

        start = self.page * SELECT_PAGE_SIZE
        page_options = [opt for _, opt in self.entries[start:start + SELECT_PAGE_SIZE]]

        select = PlayerSelect(page_options, self.mark_as)
        self.add_item(select)

        if self.max_page > 0:
            prev_button = discord.ui.Button(
                label="◀ Prev", style=discord.ButtonStyle.secondary,
                disabled=(self.page == 0),
            )
            next_button = discord.ui.Button(
                label="Next ▶", style=discord.ButtonStyle.secondary,
                disabled=(self.page == self.max_page),
            )
            prev_button.callback = self._go_prev
            next_button.callback = self._go_next
            self.add_item(prev_button)
            self.add_item(next_button)

    async def _go_prev(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self._render_page()
        await interaction.response.edit_message(view=self)

    async def _go_next(self, interaction: discord.Interaction):
        self.page = min(self.max_page, self.page + 1)
        self._render_page()
        await interaction.response.edit_message(view=self)


async def build_player_entries(guild: discord.Guild, want_paid: bool):
    """Return SelectOption entries for members whose current status
    is the OPPOSITE of want_paid (i.e. the people eligible to be
    flipped to want_paid)."""
    entries = []
    for user_id, paid in data["members"].items():
        if bool(paid) == want_paid:
            continue  # already in that state, skip

        member = await get_member(guild, user_id)
        if member:
            label = member.display_name
            description = f"@{member.name}"[:100]
        else:
            label = f"Unknown User ({user_id})"
            description = "User is no longer in this server"

        entries.append((
            user_id,
            discord.SelectOption(label=label[:100], value=str(user_id), description=description[:100]),
        ))
    return entries


# ============================================================
# CONFIRMATION VIEW (used for destructive actions)
# ============================================================

class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Only the person who ran this command can confirm it.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content="✅ Confirmed.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", view=None)


# ============================================================
# FUND PANEL BUTTONS
# ============================================================

class FundView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Mark Paid", style=discord.ButtonStyle.success, emoji="✅",
        custom_id="gang_fund_mark_paid",
    )
    async def mark_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = await safe_defer(interaction, ephemeral=True)
        if not success:
            return

        if not is_admin(interaction):
            await safe_followup(interaction, content="❌ You don't have permission to manage the gang fund.", ephemeral=True)
            return

        if not data["members"]:
            await safe_followup(interaction, content="❌ No players have been added yet.", ephemeral=True)
            return

        entries = await build_player_entries(interaction.guild, want_paid=True)
        if not entries:
            await safe_followup(interaction, content="✅ Everyone has already paid!", ephemeral=True)
            return

        view = PlayerPaginatedView(interaction.guild, entries, mark_as=True)
        await safe_followup(interaction, content="Select the player who paid:", view=view, ephemeral=True)

    @discord.ui.button(
        label="Mark Unpaid", style=discord.ButtonStyle.danger, emoji="❌",
        custom_id="gang_fund_mark_unpaid",
    )
    async def mark_unpaid(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = await safe_defer(interaction, ephemeral=True)
        if not success:
            return

        if not is_admin(interaction):
            await safe_followup(interaction, content="❌ You don't have permission to manage the gang fund.", ephemeral=True)
            return

        if not data["members"]:
            await safe_followup(interaction, content="❌ No players have been added yet.", ephemeral=True)
            return

        entries = await build_player_entries(interaction.guild, want_paid=False)
        if not entries:
            await safe_followup(interaction, content="❌ No one has paid yet.", ephemeral=True)
            return

        view = PlayerPaginatedView(interaction.guild, entries, mark_as=False)
        await safe_followup(interaction, content="Select the player who is unpaid:", view=view, ephemeral=True)


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():
    print("========================================")
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("========================================")

    if not bot.views_added:
        bot.add_view(FundView())
        bot.views_added = True

    if not bot.synced:
        try:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            bot.synced = True
            print(f"Successfully synced {len(synced)} slash commands.")
        except Exception as e:
            print(f"[SYNC ERROR] {e}")

    print("Bot is ready!")


# ============================================================
# /FUND_ADD
# ============================================================

@bot.tree.command(name="fund_add", description="Add a Discord member to the gang fund")
@app_commands.describe(player="Select the Discord member")
async def fund_add(interaction: discord.Interaction, player: discord.Member):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    user_id = str(player.id)

    async with data_lock:
        if user_id in data["members"]:
            await safe_followup(interaction, content=f"❌ **{player.display_name}** is already in the fund.", ephemeral=True)
            return
        data["members"][user_id] = False
        save_data()

    await safe_followup(interaction, content=f"✅ Added **{player.display_name}** to the gang fund.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_REMOVE
# ============================================================

@bot.tree.command(name="fund_remove", description="Remove a Discord member from the gang fund")
@app_commands.describe(player="Select the Discord member")
async def fund_remove(interaction: discord.Interaction, player: discord.Member):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    user_id = str(player.id)

    async with data_lock:
        if user_id not in data["members"]:
            await safe_followup(interaction, content=f"❌ **{player.display_name}** is not in the fund.", ephemeral=True)
            return
        del data["members"][user_id]
        save_data()

    await safe_followup(interaction, content=f"🗑️ Removed **{player.display_name}** from the gang fund.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_PAID
# ============================================================

@bot.tree.command(name="fund_paid", description="Mark a Discord member as paid")
@app_commands.describe(player="Select the Discord member")
async def fund_paid(interaction: discord.Interaction, player: discord.Member):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    user_id = str(player.id)

    async with data_lock:
        if user_id not in data["members"]:
            await safe_followup(interaction, content=f"❌ **{player.display_name}** is not in the fund.", ephemeral=True)
            return
        data["members"][user_id] = True
        save_data()

    await safe_followup(interaction, content=f"✅ **{player.display_name}** has been marked as paid.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_UNPAID
# ============================================================

@bot.tree.command(name="fund_unpaid", description="Mark a Discord member as unpaid")
@app_commands.describe(player="Select the Discord member")
async def fund_unpaid(interaction: discord.Interaction, player: discord.Member):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    user_id = str(player.id)

    async with data_lock:
        if user_id not in data["members"]:
            await safe_followup(interaction, content=f"❌ **{player.display_name}** is not in the fund.", ephemeral=True)
            return
        data["members"][user_id] = False
        save_data()

    await safe_followup(interaction, content=f"❌ **{player.display_name}** has been marked as unpaid.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_AMOUNT
# ============================================================

@bot.tree.command(name="fund_amount", description="Set the required gang fund amount")
@app_commands.describe(amount="Amount required from each player")
async def fund_amount(interaction: discord.Interaction, amount: int):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return
    if amount < 0:
        await safe_followup(interaction, content="❌ Amount cannot be negative.", ephemeral=True)
        return

    async with data_lock:
        data["amount"] = amount
        save_data()

    await safe_followup(interaction, content=f"💰 Gang fund amount set to **${amount:,}** per player.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_LIST
# ============================================================

@bot.tree.command(name="fund_list", description="Show the gang fund list")
async def fund_list(interaction: discord.Interaction):
    if not await safe_defer(interaction, ephemeral=False):
        return
    embed = await create_fund_embed(interaction.guild)
    await safe_followup(interaction, embed=embed, view=FundView())


# ============================================================
# /FUND_RESET  (destructive — requires confirmation)
# ============================================================

@bot.tree.command(name="fund_reset", description="Reset all players to unpaid")
async def fund_reset(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return

    if not data["members"]:
        await interaction.response.send_message("❌ No players have been added yet.", ephemeral=True)
        return

    view = ConfirmView(author_id=interaction.user.id)
    await interaction.response.send_message(
        "⚠️ This will mark **every player** as unpaid. Are you sure?",
        view=view,
        ephemeral=True,
    )
    await view.wait()

    if not view.confirmed:
        return

    async with data_lock:
        for user_id in data["members"]:
            data["members"][user_id] = False
        save_data()

    await interaction.followup.send("🔄 All players have been **reset to UNPAID**.", ephemeral=True)
    await refresh_all_panels(interaction.guild)


# ============================================================
# /FUND_PANEL
# ============================================================

@bot.tree.command(name="fund_panel", description="Create the gang fund tracking panel")
async def fund_panel(interaction: discord.Interaction):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    embed = await create_fund_embed(interaction.guild)

    try:
        panel_message = await interaction.channel.send(embed=embed, view=FundView())
    except discord.HTTPException as e:
        print(f"[PANEL ERROR] {e}")
        await safe_followup(interaction, content="❌ Could not create the fund panel.", ephemeral=True)
        return

    await register_panel(interaction.channel.id, panel_message.id)
    await safe_followup(interaction, content="✅ Gang fund panel created!", ephemeral=True)


# ============================================================
# /FUND_REFRESH — manually force every panel to re-sync
# ============================================================

@bot.tree.command(name="fund_refresh", description="Force-refresh all gang fund panels")
async def fund_refresh(interaction: discord.Interaction):
    if not await safe_defer(interaction, ephemeral=True):
        return
    if not is_admin(interaction):
        await safe_followup(interaction, content="❌ You don't have permission.", ephemeral=True)
        return

    await refresh_all_panels(interaction.guild)
    await safe_followup(interaction, content="🔄 All panels refreshed.", ephemeral=True)


# ============================================================
# /FUND_HELP
# ============================================================

@bot.tree.command(name="fund_help", description="List gang fund commands")
async def fund_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💰 Gang Fund — Commands",
        color=discord.Color.blurple(),
        description=(
            "**/fund_panel** — Post the live tracker panel (admin)\n"
            "**/fund_list** — Show the current fund status\n"
            "**/fund_add** `player` — Add a member (admin)\n"
            "**/fund_remove** `player` — Remove a member (admin)\n"
            "**/fund_paid** `player` — Mark a member paid (admin)\n"
            "**/fund_unpaid** `player` — Mark a member unpaid (admin)\n"
            "**/fund_amount** `amount` — Set required amount per player (admin)\n"
            "**/fund_reset** — Reset everyone to unpaid (admin, confirmation required)\n"
            "**/fund_refresh** — Force-resync all panels (admin)\n"
        ),
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"[COMMAND ERROR] {error}")

    if isinstance(error, app_commands.CommandOnCooldown):
        return

    try:
        message = "❌ An error occurred while running this command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":
    print("Starting GTA RP Gang Fund Bot...")
    try:
        bot.run(TOKEN)
    except KeyboardInterrupt:
        print("Bot stopped.")
    except Exception as e:
        print("========================================")
        print("BOT FAILED TO START")
        print(f"Error: {e}")
        print("========================================")
