import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
import threading
from flask import Flask


# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")

# Optional: a private channel ID the bot posts a data.json backup
# to. Because most hosts (Render included) wipe local disk on
# every redeploy, this is what actually survives a redeploy —
# on startup, if there's no local data.json, the bot restores
# from the latest backup found in this channel.
BACKUP_CHANNEL_ID = os.getenv("BACKUP_CHANNEL_ID")

if not TOKEN:
    raise ValueError("ERROR: TOKEN environment variable is missing!")

if not GUILD_ID:
    raise ValueError("ERROR: GUILD_ID environment variable is missing!")

if not ADMIN_ROLE_ID:
    raise ValueError("ERROR: ADMIN_ROLE_ID environment variable is missing!")

GUILD_ID = int(GUILD_ID)
ADMIN_ROLE_ID = int(ADMIN_ROLE_ID)

if BACKUP_CHANNEL_ID:
    BACKUP_CHANNEL_ID = int(BACKUP_CHANNEL_ID)


# ============================================================
# RENDER WEB SERVER
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "GTA RP Gang Fund Bot is online!"


@app.route("/health")
def health():
    return "OK"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))

    print("----------------------------------------")
    print(f"Starting web server on port {port}")
    print("----------------------------------------")

    app.run(
        host="0.0.0.0",
        port=port
    )


# ============================================================
# DATA FILE
# ============================================================

DATA_FILE = "data.json"

# Captured BEFORE load_data() runs (which creates the file if it's
# missing), so we can tell whether this is a fresh container with
# no local data — the signal to restore from the backup channel.
_data_file_existed_at_boot = os.path.exists(DATA_FILE)


def default_data():
    return {
        "amount": 0,
        "members": {},
        # Tracks every panel message that has ever been posted
        # (via /fund_list or /fund_panel) so they can all be
        # auto-updated whenever the fund data changes.
        "panels": [],
        # Optional free-text note shown at the bottom of the
        # fund embed, set with /fund_message.
        "message": ""
    }


def load_data():

    if not os.path.exists(DATA_FILE):

        data = default_data()

        save_data(data)

        return data

    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if "amount" not in data:
            data["amount"] = 0

        if "members" not in data:
            data["members"] = {}

        if "panels" not in data:
            data["panels"] = []

        if "message" not in data:
            data["message"] = ""

        return data

    except Exception as e:

        print(
            f"Error loading data.json: {e}"
        )

        return default_data()


def save_data(data):

    try:

        with open(
            DATA_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )

    except Exception as e:

        print(
            f"Error saving data.json: {e}"
        )


data = load_data()


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()

intents.members = True


class GangFundBot(commands.Bot):

    def __init__(self):

        super().__init__(
            command_prefix="!",
            intents=intents
        )

        self.synced = False


bot = GangFundBot()


# ============================================================
# PERMISSION CHECK
# ============================================================

def is_admin(interaction: discord.Interaction):

    if interaction.guild is None:
        return False

    # Discord Administrator permission
    if interaction.user.guild_permissions.administrator:
        return True

    # Admin role
    role = interaction.guild.get_role(
        ADMIN_ROLE_ID
    )

    if role and role in interaction.user.roles:
        return True

    return False


# ============================================================
# CREATE FUND EMBED
# ============================================================

def create_fund_embed():

    amount = data.get(
        "amount",
        0
    )

    members = data.get(
        "members",
        {}
    )

    total_members = len(
        members
    )

    paid_members = 0

    for paid in members.values():

        if paid is True:

            paid_members += 1

    unpaid_members = (
        total_members
        - paid_members
    )

    collected = (
        paid_members
        * amount
    )

    required = (
        total_members
        * amount
    )

    embed = discord.Embed(
        title="💰 GTA RP GANG FUND",
        description="Gang fund payment tracker",
        color=discord.Color.green()
    )

    embed.add_field(
        name="💵 Fund Per Player",
        value=f"${amount:,}",
        inline=True
    )

    embed.add_field(
        name="👥 Members",
        value=str(total_members),
        inline=True
    )

    embed.add_field(
        name="💰 Collected",
        value=f"${collected:,} / ${required:,}",
        inline=True
    )

    embed.add_field(
        name="✅ Paid",
        value=str(paid_members),
        inline=True
    )

    embed.add_field(
        name="❌ Unpaid",
        value=str(unpaid_members),
        inline=True
    )

    # --------------------------------------------------------
    # MEMBER LIST
    # --------------------------------------------------------

    if members:

        member_list = []

        for name, paid in members.items():

            if paid is True:

                member_list.append(
                    f"✅ **{name}** — Paid"
                )

            else:

                member_list.append(
                    f"❌ **{name}** — Unpaid"
                )

        chunks = []

        current_chunk = ""

        for line in member_list:

            if (
                len(current_chunk)
                + len(line)
                + 1
                > 1000
            ):

                chunks.append(
                    current_chunk
                )

                current_chunk = line

            else:

                if current_chunk:

                    current_chunk += "\n"

                current_chunk += line

        if current_chunk:

            chunks.append(
                current_chunk
            )

        for index, chunk in enumerate(
            chunks
        ):

            if index == 0:

                field_name = (
                    "📋 Member List"
                )

            else:

                field_name = (
                    "📋 Member List (Continued)"
                )

            embed.add_field(
                name=field_name,
                value=chunk,
                inline=False
            )

    else:

        embed.add_field(
            name="📋 Member List",
            value="No members added yet.",
            inline=False
        )

    # --------------------------------------------------------
    # CUSTOM NOTE (set with /fund_message)
    # --------------------------------------------------------

    note = data.get(
        "message",
        ""
    )

    if note:

        embed.add_field(
            name="📝 Message",
            value=note,
            inline=False
        )

    embed.set_footer(
        text="Use the buttons below to update payments."
    )

    return embed


# ============================================================
# DISCORD-CHANNEL BACKUP / RESTORE
# ============================================================
#
# Solves data loss on redeploy: local disk on most hosts (Render
# included) is wiped on every redeploy. This backs up data.json
# as a file attachment in a private channel, and restores it on
# startup if the local file doesn't exist. No paid disk needed.
# ============================================================

_backup_message_id = None


async def push_backup():

    if not BACKUP_CHANNEL_ID:
        return

    global _backup_message_id

    try:

        channel = bot.get_channel(
            BACKUP_CHANNEL_ID
        )

        if channel is None:

            channel = await bot.fetch_channel(
                BACKUP_CHANNEL_ID
            )

    except Exception as e:

        print(
            f"Backup channel not accessible: {e}"
        )

        return

    buffer = io.BytesIO(
        json.dumps(
            data,
            indent=4,
            ensure_ascii=False
        ).encode("utf-8")
    )

    file = discord.File(
        buffer,
        filename="gang_fund_backup.json"
    )

    try:

        if _backup_message_id:

            message = await channel.fetch_message(
                _backup_message_id
            )

            await message.edit(
                content="🗄️ Gang fund data backup (auto-updated, do not delete)",
                attachments=[file]
            )

            return

    except discord.NotFound:

        _backup_message_id = None

    except Exception as e:

        print(
            f"Failed to edit backup message: {e}"
        )

        return

    try:

        message = await channel.send(
            content="🗄️ Gang fund data backup (auto-updated, do not delete)",
            file=file
        )

        _backup_message_id = message.id

    except Exception as e:

        print(
            f"Failed to send backup message: {e}"
        )


async def restore_backup_if_needed():

    if not BACKUP_CHANNEL_ID:
        return

    global data, _backup_message_id

    try:

        channel = bot.get_channel(
            BACKUP_CHANNEL_ID
        )

        if channel is None:

            channel = await bot.fetch_channel(
                BACKUP_CHANNEL_ID
            )

    except Exception as e:

        print(
            f"Backup channel not accessible: {e}"
        )

        return

    try:

        async for message in channel.history(limit=50):

            if message.author.id != bot.user.id:
                continue

            for attachment in message.attachments:

                if attachment.filename != "gang_fund_backup.json":
                    continue

                # Cache this message so future backups edit it
                # instead of spamming new messages.
                _backup_message_id = message.id

                if _data_file_existed_at_boot:
                    # Local data already exists (e.g. a persistent
                    # disk is attached) — don't overwrite it.
                    return

                raw = await attachment.read()

                restored = json.loads(
                    raw.decode("utf-8")
                )

                if "amount" not in restored:
                    restored["amount"] = 0

                if "members" not in restored:
                    restored["members"] = {}

                if "panels" not in restored:
                    restored["panels"] = []

                if "message" not in restored:
                    restored["message"] = ""

                data = restored

                save_data(data)

                print(
                    "Restored gang fund data from Discord backup channel "
                    f"({len(data['members'])} players)."
                )

                return

    except Exception as e:

        print(
            f"Error scanning backup channel for restore: {e}"
        )


# ============================================================
# PANEL AUTO-UPDATE
# ============================================================
#
# Every panel message ever posted with /fund_list or /fund_panel
# gets tracked in data["panels"]. Whenever fund data changes, we
# push the updated embed to every tracked panel automatically.
# If a panel message was deleted, it's dropped from the list.
# ============================================================

async def register_panel(message: discord.Message):

    data["panels"].append(
        {
            "channel_id": message.channel.id,
            "message_id": message.id
        }
    )

    save_data(data)


async def update_all_panels():

    await push_backup()

    if not data.get("panels"):
        return

    embed = create_fund_embed()

    still_valid = []

    for panel in data["panels"]:

        try:

            channel = bot.get_channel(
                panel["channel_id"]
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    panel["channel_id"]
                )

            message = await channel.fetch_message(
                panel["message_id"]
            )

            await message.edit(
                embed=embed,
                view=FundView()
            )

            still_valid.append(panel)

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ) as e:

            print(
                f"Dropping stale panel "
                f"{panel}: {e}"
            )

    data["panels"] = still_valid

    save_data(data)


# ============================================================
# AUTOCOMPLETE FOR EXISTING PLAYERS
# ============================================================

async def player_autocomplete(
    interaction: discord.Interaction,
    current: str
):

    current_lower = current.lower()

    matches = [
        name
        for name in data["members"].keys()
        if current_lower in name.lower()
    ]

    return [
        app_commands.Choice(
            name=name,
            value=name
        )
        for name in matches[:25]
    ]


# ============================================================
# PAID PLAYER SELECT
# ============================================================

class PaidSelect(
    discord.ui.Select
):

    def __init__(
        self,
        options
    ):

        super().__init__(
            placeholder="Choose a player...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        player = self.values[0]

        data["members"][player] = True

        save_data(data)

        await interaction.response.edit_message(
            content=(
                f"✅ **{player}** "
                f"has been marked as **PAID**."
            ),
            view=None
        )

        await update_all_panels()


# ============================================================
# UNPAID PLAYER SELECT
# ============================================================

class UnpaidSelect(
    discord.ui.Select
):

    def __init__(
        self,
        options
    ):

        super().__init__(
            placeholder="Choose a player...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        player = self.values[0]

        data["members"][player] = False

        save_data(data)

        await interaction.response.edit_message(
            content=(
                f"❌ **{player}** "
                f"has been marked as **UNPAID**."
            ),
            view=None
        )

        await update_all_panels()


# ============================================================
# FUND BUTTON VIEW
# ============================================================

class FundView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    # --------------------------------------------------------
    # MARK PAID BUTTON
    # --------------------------------------------------------

    @discord.ui.button(
        label="Mark Paid",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="gang_fund_mark_paid"
    )
    async def mark_paid(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You don't have permission to manage the gang fund.",
                ephemeral=True
            )

            return

        if not data["members"]:

            await interaction.response.send_message(
                "❌ No players have been added yet.",
                ephemeral=True
            )

            return

        options = []

        for name in data["members"]:

            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=name[:100]
                )
            )

        if len(options) > 25:

            await interaction.response.send_message(
                "❌ There are more than 25 players. Use `/fund_paid` instead.",
                ephemeral=True
            )

            return

        select = PaidSelect(
            options
        )

        view = discord.ui.View(
            timeout=60
        )

        view.add_item(
            select
        )

        await interaction.response.send_message(
            "Select the player who paid:",
            view=view,
            ephemeral=True
        )


    # --------------------------------------------------------
    # MARK UNPAID BUTTON
    # --------------------------------------------------------

    @discord.ui.button(
        label="Mark Unpaid",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="gang_fund_mark_unpaid"
    )
    async def mark_unpaid(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You don't have permission to manage the gang fund.",
                ephemeral=True
            )

            return

        if not data["members"]:

            await interaction.response.send_message(
                "❌ No players have been added yet.",
                ephemeral=True
            )

            return

        options = []

        for name in data["members"]:

            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=name[:100]
                )
            )

        if len(options) > 25:

            await interaction.response.send_message(
                "❌ There are more than 25 players. Use `/fund_unpaid` instead.",
                ephemeral=True
            )

            return

        select = UnpaidSelect(
            options
        )

        view = discord.ui.View(
            timeout=60
        )

        view.add_item(
            select
        )

        await interaction.response.send_message(
            "Select the player who is unpaid:",
            view=view,
            ephemeral=True
        )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print("----------------------------------------")

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print("----------------------------------------")

    # Prevent adding the persistent view
    # multiple times after reconnects.
    if not bot.synced:

        await restore_backup_if_needed()

        bot.add_view(
            FundView()
        )

        try:

            guild = discord.Object(
                id=GUILD_ID
            )

            bot.tree.copy_global_to(
                guild=guild
            )

            synced = await bot.tree.sync(
                guild=guild
            )

            print(
                f"Successfully synced "
                f"{len(synced)} slash commands."
            )

            bot.synced = True

        except Exception as e:

            print(
                f"ERROR syncing slash commands: {e}"
            )

        # Make sure any already-posted panels reflect whatever
        # data we just booted with (including a restored backup).
        await update_all_panels()

    print(
        "GTA RP Gang Fund Bot is ready!"
    )


# ============================================================
# /FUND_ADD
# ============================================================
# Uses a real Discord member picker instead of free text, so the
# stored name is always a proper display name — never a raw
# mention string like <@123456789012345678>.
# ============================================================

@bot.tree.command(
    name="fund_add",
    description="Add a player to the gang fund"
)
@app_commands.describe(
    player="Select the player to add"
)
async def fund_add(
    interaction: discord.Interaction,
    player: discord.Member
):

    # Respond immediately so Discord
    # does not expire the interaction.
    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    name = player.display_name

    if name in data["members"]:

        await interaction.followup.send(
            f"❌ **{name}** is already in the fund.",
            ephemeral=True
        )

        return

    data["members"][name] = False

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        f"✅ Added **{name}** to the gang fund.",
        ephemeral=True
    )


# ============================================================
# /FUND_REMOVE
# ============================================================

@bot.tree.command(
    name="fund_remove",
    description="Remove a player from the gang fund"
)
@app_commands.describe(
    player="Player name"
)
@app_commands.autocomplete(
    player=player_autocomplete
)
async def fund_remove(
    interaction: discord.Interaction,
    player: str
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    if player not in data["members"]:

        await interaction.followup.send(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return

    del data["members"][player]

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        f"🗑️ Removed **{player}** from the gang fund.",
        ephemeral=True
    )


# ============================================================
# /FUND_PAID
# ============================================================

@bot.tree.command(
    name="fund_paid",
    description="Mark a player as paid"
)
@app_commands.describe(
    player="Player name"
)
@app_commands.autocomplete(
    player=player_autocomplete
)
async def fund_paid(
    interaction: discord.Interaction,
    player: str
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    if player not in data["members"]:

        await interaction.followup.send(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return

    data["members"][player] = True

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        f"✅ **{player}** has paid the gang fund.",
        ephemeral=True
    )


# ============================================================
# /FUND_UNPAID
# ============================================================

@bot.tree.command(
    name="fund_unpaid",
    description="Mark a player as unpaid"
)
@app_commands.describe(
    player="Player name"
)
@app_commands.autocomplete(
    player=player_autocomplete
)
async def fund_unpaid(
    interaction: discord.Interaction,
    player: str
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    if player not in data["members"]:

        await interaction.followup.send(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return

    data["members"][player] = False

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        f"❌ **{player}** is now marked as unpaid.",
        ephemeral=True
    )


# ============================================================
# /FUND_AMOUNT
# ============================================================

@bot.tree.command(
    name="fund_amount",
    description="Set the required gang fund amount"
)
@app_commands.describe(
    amount="Amount required from each player"
)
async def fund_amount(
    interaction: discord.Interaction,
    amount: int
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    if amount < 0:

        await interaction.followup.send(
            "❌ Amount cannot be negative.",
            ephemeral=True
        )

        return

    data["amount"] = amount

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        f"💰 Gang fund amount set to "
        f"**${amount:,}** per player.",
        ephemeral=True
    )


# ============================================================
# /FUND_MESSAGE
# ============================================================
# Sets (or clears) a free-text note shown at the bottom of the
# fund embed, above the footer. Leave "text" empty to clear it.
# ============================================================

@bot.tree.command(
    name="fund_message",
    description="Set or clear a custom note shown at the bottom of the fund embed"
)
@app_commands.describe(
    text="The note to show (leave empty to clear the current note)"
)
async def fund_message(
    interaction: discord.Interaction,
    text: str = ""
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    data["message"] = text.strip()

    save_data(data)

    await update_all_panels()

    if data["message"]:

        await interaction.followup.send(
            f"📝 Fund message updated to:\n> {data['message']}",
            ephemeral=True
        )

    else:

        await interaction.followup.send(
            "🧹 Fund message cleared.",
            ephemeral=True
        )


# ============================================================
# /FUND_LIST
# ============================================================
# Posts a panel and registers it so future changes auto-update it.
# ============================================================

@bot.tree.command(
    name="fund_list",
    description="Show the gang fund list"
)
async def fund_list(
    interaction: discord.Interaction
):

    # Defer immediately.
    # Then use followup instead of response.
    await interaction.response.defer()

    embed = create_fund_embed()

    message = await interaction.followup.send(
        embed=embed,
        view=FundView(),
        wait=True
    )

    await register_panel(message)


# ============================================================
# /FUND_RESET
# ============================================================

@bot.tree.command(
    name="fund_reset",
    description="Mark all players as unpaid again (does NOT remove anyone from the list)"
)
async def fund_reset(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    for player in data["members"]:

        data["members"][player] = False

    save_data(data)

    await update_all_panels()

    await interaction.followup.send(
        "🔄 All players have been reset to **UNPAID**.",
        ephemeral=True
    )


# ============================================================
# /FUND_RESET_LIST
# ============================================================
# The ONLY command that removes players from the list wholesale.
# Gated behind a confirmation button since it's destructive and
# cannot be undone (aside from restoring an older backup).
# ============================================================

class ConfirmResetListView(discord.ui.View):

    def __init__(self, owner_id: int):

        super().__init__(timeout=30)

        self.owner_id = owner_id
        self.confirmed = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "❌ This confirmation isn't for you.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="Yes, clear the list",
        style=discord.ButtonStyle.danger,
        emoji="🗑️"
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        self.confirmed = True

        self.stop()

        await interaction.response.edit_message(
            content="🗑️ Clearing the player list...",
            view=None
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        self.confirmed = False

        self.stop()

        await interaction.response.edit_message(
            content="❌ Cancelled. Player list unchanged.",
            view=None
        )


@bot.tree.command(
    name="fund_reset_list",
    description="Permanently remove ALL players from the gang fund list"
)
async def fund_reset_list(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    if not data["members"]:

        await interaction.followup.send(
            "❌ The player list is already empty.",
            ephemeral=True
        )

        return

    count = len(data["members"])

    view = ConfirmResetListView(
        owner_id=interaction.user.id
    )

    await interaction.followup.send(
        f"⚠️ This will permanently remove all **{count}** players "
        f"from the list. This cannot be undone. Are you sure?",
        view=view,
        ephemeral=True
    )

    await view.wait()

    if view.confirmed:

        data["members"] = {}

        save_data(data)

        await update_all_panels()

        await interaction.followup.send(
            "✅ Player list cleared.",
            ephemeral=True
        )


# ============================================================
# /FUND_PANEL
# ============================================================
# Posts a panel and registers it so future changes auto-update it.
# ============================================================

@bot.tree.command(
    name="fund_panel",
    description="Create the gang fund tracking panel"
)
async def fund_panel(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    if not is_admin(interaction):

        await interaction.followup.send(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    embed = create_fund_embed()

    message = await interaction.channel.send(
        embed=embed,
        view=FundView()
    )

    await register_panel(message)

    await interaction.followup.send(
        "✅ Gang fund panel created!",
        ephemeral=True
    )


# ============================================================
# ============================================================
# GENERAL-PURPOSE EMBED BUILDER  (/embed create)
# ============================================================
# ============================================================
#
# A standalone embed creation tool, unrelated to the gang fund
# tracker, for posting any custom embed (announcements, rules,
# info panels, etc). Supports title/description, author, footer,
# image/thumbnail, color, up to 25 fields, and up to 10 embeds
# in a single message — similar to the Discord embed builder UI.
#
# Usage: /embed create  -> opens an interactive, ephemeral builder
# ============================================================


def safe_color(text: str) -> discord.Color:

    text = text.strip().lstrip("#")

    if not text:

        return discord.Color.blurple()

    try:

        return discord.Color(
            int(text, 16)
        )

    except ValueError:

        return discord.Color.blurple()


class BodyModal(discord.ui.Modal, title="Title & Description"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        embed = builder_view.current_embed()

        self.title_input = discord.ui.TextInput(
            label="Title",
            required=False,
            max_length=256,
            default=embed.title or ""
        )

        self.description_input = discord.ui.TextInput(
            label="Description",
            style=discord.TextStyle.paragraph,
            required=False,
            max_length=4000,
            default=embed.description or ""
        )

        self.add_item(self.title_input)
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        embed.title = self.title_input.value or None
        embed.description = self.description_input.value or None

        await self.builder_view.refresh(interaction)


class ColorModal(discord.ui.Modal, title="Embed Color"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        self.color_input = discord.ui.TextInput(
            label="Hex color (e.g. 2ecc71)",
            required=False,
            max_length=7
        )

        self.add_item(self.color_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        embed.color = safe_color(
            self.color_input.value
        )

        await self.builder_view.refresh(interaction)


class AuthorModal(discord.ui.Modal, title="Author"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        embed = builder_view.current_embed()

        current_author = embed.author

        self.name_input = discord.ui.TextInput(
            label="Author name",
            required=False,
            max_length=256,
            default=current_author.name or "" if current_author else ""
        )

        self.icon_input = discord.ui.TextInput(
            label="Author icon URL",
            required=False,
            default=current_author.icon_url or "" if current_author else ""
        )

        self.url_input = discord.ui.TextInput(
            label="Author link URL",
            required=False,
            default=current_author.url or "" if current_author else ""
        )

        self.add_item(self.name_input)
        self.add_item(self.icon_input)
        self.add_item(self.url_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        if self.name_input.value:

            embed.set_author(
                name=self.name_input.value,
                icon_url=self.icon_input.value or None,
                url=self.url_input.value or None
            )

        else:

            embed.remove_author()

        await self.builder_view.refresh(interaction)


class FooterModal(discord.ui.Modal, title="Footer"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        embed = builder_view.current_embed()

        self.text_input = discord.ui.TextInput(
            label="Footer text",
            required=False,
            max_length=2048,
            default=embed.footer.text or "" if embed.footer else ""
        )

        self.icon_input = discord.ui.TextInput(
            label="Footer icon URL",
            required=False,
            default=embed.footer.icon_url or "" if embed.footer else ""
        )

        self.add_item(self.text_input)
        self.add_item(self.icon_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        if self.text_input.value:

            embed.set_footer(
                text=self.text_input.value,
                icon_url=self.icon_input.value or None
            )

        else:

            embed.remove_footer()

        await self.builder_view.refresh(interaction)


class ImagesModal(discord.ui.Modal, title="Images"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        embed = builder_view.current_embed()

        self.image_input = discord.ui.TextInput(
            label="Large image URL",
            required=False,
            default=embed.image.url or "" if embed.image else ""
        )

        self.thumbnail_input = discord.ui.TextInput(
            label="Thumbnail URL (small, top-right)",
            required=False,
            default=embed.thumbnail.url or "" if embed.thumbnail else ""
        )

        self.add_item(self.image_input)
        self.add_item(self.thumbnail_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        if self.image_input.value:
            embed.set_image(url=self.image_input.value)
        else:
            embed.set_image(url=None)

        if self.thumbnail_input.value:
            embed.set_thumbnail(url=self.thumbnail_input.value)
        else:
            embed.set_thumbnail(url=None)

        await self.builder_view.refresh(interaction)


class AddFieldModal(discord.ui.Modal, title="Add Field"):

    def __init__(self, builder_view):

        super().__init__()

        self.builder_view = builder_view

        self.name_input = discord.ui.TextInput(
            label="Field name",
            required=True,
            max_length=256
        )

        self.value_input = discord.ui.TextInput(
            label="Field value",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1024
        )

        self.inline_input = discord.ui.TextInput(
            label="Inline? (yes/no)",
            required=False,
            default="yes",
            max_length=3
        )

        self.add_item(self.name_input)
        self.add_item(self.value_input)
        self.add_item(self.inline_input)

    async def on_submit(self, interaction: discord.Interaction):

        embed = self.builder_view.current_embed()

        if len(embed.fields) >= 25:

            await interaction.response.send_message(
                "❌ This embed already has the max of 25 fields.",
                ephemeral=True
            )

            return

        inline = self.inline_input.value.strip().lower() not in (
            "no", "false", "n", "0"
        )

        embed.add_field(
            name=self.name_input.value,
            value=self.value_input.value,
            inline=inline
        )

        await self.builder_view.refresh(interaction)


class EmbedSwitchSelect(discord.ui.Select):

    def __init__(self, builder_view):

        self.builder_view = builder_view

        options = [
            discord.SelectOption(
                label=f"Embed {i + 1}",
                value=str(i),
                default=(i == builder_view.active_index)
            )
            for i in range(len(builder_view.embeds))
        ]

        super().__init__(
            placeholder="Choose which embed to edit...",
            options=options,
            row=2
        )

    async def callback(self, interaction: discord.Interaction):

        self.builder_view.active_index = int(self.values[0])

        await self.builder_view.refresh(interaction)


class SendChannelSelect(discord.ui.ChannelSelect):

    def __init__(self, builder_view):

        self.builder_view = builder_view

        super().__init__(
            placeholder="Choose a channel to send to...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):

        channel = self.values[0]

        try:

            await channel.send(
                embeds=self.builder_view.embeds
            )

        except discord.HTTPException as e:

            await interaction.response.edit_message(
                content=f"❌ Failed to send: {e}",
                embeds=[],
                view=None
            )

            return

        await interaction.response.edit_message(
            content=f"✅ Sent to {channel.mention}.",
            embeds=[],
            view=None
        )


class EmbedBuilderView(discord.ui.View):

    def __init__(self, owner_id: int):

        super().__init__(timeout=900)

        self.owner_id = owner_id
        self.embeds = [discord.Embed(color=discord.Color.blurple())]
        self.active_index = 0

        self.build_items()

    def current_embed(self) -> discord.Embed:

        return self.embeds[self.active_index]

    async def interaction_check(self, interaction: discord.Interaction) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "❌ This isn't your embed builder.",
                ephemeral=True
            )

            return False

        return True

    async def refresh(self, interaction: discord.Interaction):

        self.build_items()

        await interaction.response.edit_message(
            content=(
                f"**Editing embed {self.active_index + 1} "
                f"of {len(self.embeds)}.** "
                f"Use the buttons below, then hit Send."
            ),
            embeds=self.embeds,
            view=self
        )

    def build_items(self):

        self.clear_items()

        def make_button(label, callback, row, style=discord.ButtonStyle.primary, disabled=False, emoji=None):

            button = discord.ui.Button(
                label=label,
                style=style,
                row=row,
                disabled=disabled,
                emoji=emoji
            )

            async def _callback(interaction: discord.Interaction, cb=callback):
                await cb(interaction)

            button.callback = _callback

            self.add_item(button)

        make_button("Title & Description", self.open_body, 0)
        make_button("Author", self.open_author, 0)
        make_button("Footer", self.open_footer, 0)
        make_button("Images", self.open_images, 0)
        make_button("Color", self.open_color, 0)

        make_button("Add Field", self.open_add_field, 1)
        make_button(
            "Remove Last Field",
            self.remove_last_field,
            1,
            style=discord.ButtonStyle.secondary,
            disabled=len(self.current_embed().fields) == 0
        )
        make_button("Add Embed", self.add_embed, 1, style=discord.ButtonStyle.secondary)
        make_button(
            "Remove Embed",
            self.remove_embed,
            1,
            style=discord.ButtonStyle.secondary,
            disabled=len(self.embeds) <= 1
        )

        if len(self.embeds) > 1:

            self.add_item(
                EmbedSwitchSelect(self)
            )

        make_button("Send", self.open_send, 3, style=discord.ButtonStyle.success)
        make_button("Cancel", self.cancel, 3, style=discord.ButtonStyle.danger)

    # ----------------------------------------------------
    # Button handlers
    # ----------------------------------------------------

    async def open_body(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BodyModal(self))

    async def open_author(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AuthorModal(self))

    async def open_footer(self, interaction: discord.Interaction):
        await interaction.response.send_modal(FooterModal(self))

    async def open_images(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ImagesModal(self))

    async def open_color(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ColorModal(self))

    async def open_add_field(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AddFieldModal(self))

    async def remove_last_field(self, interaction: discord.Interaction):

        embed = self.current_embed()

        if embed.fields:
            embed.remove_field(len(embed.fields) - 1)

        await self.refresh(interaction)

    async def add_embed(self, interaction: discord.Interaction):

        if len(self.embeds) >= 10:

            await interaction.response.send_message(
                "❌ Discord allows a max of 10 embeds per message.",
                ephemeral=True
            )

            return

        self.embeds.append(
            discord.Embed(color=discord.Color.blurple())
        )

        self.active_index = len(self.embeds) - 1

        await self.refresh(interaction)

    async def remove_embed(self, interaction: discord.Interaction):

        if len(self.embeds) <= 1:

            await interaction.response.send_message(
                "❌ You must keep at least one embed.",
                ephemeral=True
            )

            return

        del self.embeds[self.active_index]

        self.active_index = max(0, self.active_index - 1)

        await self.refresh(interaction)

    async def open_send(self, interaction: discord.Interaction):

        view = discord.ui.View(timeout=120)

        view.add_item(
            SendChannelSelect(self)
        )

        await interaction.response.send_message(
            "Choose a channel to send this to:",
            view=view,
            ephemeral=True
        )

    async def cancel(self, interaction: discord.Interaction):

        await interaction.response.edit_message(
            content="❌ Embed builder cancelled.",
            embeds=[],
            view=None
        )


embed_group = app_commands.Group(
    name="embed",
    description="Build and send custom embeds"
)


@embed_group.command(
    name="create",
    description="Open an interactive embed builder to design and send a custom embed"
)
async def embed_create(interaction: discord.Interaction):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return

    view = EmbedBuilderView(
        owner_id=interaction.user.id
    )

    await interaction.response.send_message(
        content="**Editing embed 1 of 1.** Use the buttons below, then hit Send.",
        embeds=view.embeds,
        view=view,
        ephemeral=True
    )


bot.tree.add_command(embed_group)


# ============================================================
# START BOT + RENDER WEB SERVER
# ============================================================

if __name__ == "__main__":

    print("----------------------------------------")
    print("Starting GTA RP Gang Fund Bot...")
    print("----------------------------------------")

    # Start Flask web server in a separate thread.
    # This is required because Render Web Services
    # expects the application to listen on PORT.

    web_thread = threading.Thread(
        target=run_web_server,
        daemon=True
    )

    web_thread.start()

    # Start Discord bot
    bot.run(
        TOKEN
    )
