import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
import datetime
import threading
from flask import Flask


# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")

if not TOKEN:
    raise ValueError("ERROR: TOKEN environment variable is missing!")

if not GUILD_ID:
    raise ValueError("ERROR: GUILD_ID environment variable is missing!")

if not ADMIN_ROLE_ID:
    raise ValueError("ERROR: ADMIN_ROLE_ID environment variable is missing!")

GUILD_ID = int(GUILD_ID)
ADMIN_ROLE_ID = int(ADMIN_ROLE_ID)


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
        "panels": [],
        "message": "",
        "treasury_balance": 0,
        "transactions": [],
        "treasury_panels": []
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

        # Ensure all keys exist
        for key in ["amount", "members", "panels", "message", "treasury_balance", "transactions", "treasury_panels"]:
            if key not in data:
                if key in ["members"]:
                    data[key] = {}
                elif key in ["panels", "treasury_panels", "transactions"]:
                    data[key] = []
                else:
                    data[key] = "" if key == "message" else 0

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
        title="💰 GANG FUND - TITAN",
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
            name="────────",
            value=note,
            inline=False
        )

    embed.set_footer(
        text="Use the buttons below to update payments."
    )

    return embed


# ============================================================
# CREATE TREASURY EMBED
# ============================================================

TRANSACTION_TYPE_LABELS = {
    "deposit": "🟢 Deposit",
    "withdraw": "🔴 Withdraw"
}


def format_transaction_line(entry):

    label = TRANSACTION_TYPE_LABELS.get(
        entry.get("type"),
        entry.get("type", "Transaction")
    )

    amount = entry.get("amount", 0)

    reason = entry.get("reason") or "No reason provided"

    user_name = entry.get("user_name", "Unknown")

    timestamp = entry.get("timestamp")

    if timestamp:

        try:

            dt = datetime.datetime.fromisoformat(timestamp)

            time_text = f"<t:{int(dt.timestamp())}:R>"

        except ValueError:

            time_text = ""

    else:

        time_text = ""

    return (
        f"{label} **${amount:,}** by **{user_name}** {time_text}\n"
        f"> {reason}"
    )


def create_treasury_embed():

    balance = data.get(
        "treasury_balance",
        0
    )

    transactions = data.get(
        "transactions",
        []
    )

    embed = discord.Embed(
        title="🏦 GANG TREASURY - TITAN",
        description="Deposit or withdraw funds. Every transaction is logged.",
        color=(
            discord.Color.green()
            if balance >= 0
            else discord.Color.red()
        )
    )

    embed.add_field(
        name="💰 Current Balance",
        value=f"${balance:,}",
        inline=False
    )

    recent = transactions[-10:]

    if recent:

        lines = [
            format_transaction_line(entry)
            for entry in reversed(recent)
        ]

        chunks = []

        current_chunk = ""

        for line in lines:

            if (
                len(current_chunk)
                + len(line)
                + 2
                > 1000
            ):

                chunks.append(
                    current_chunk
                )

                current_chunk = line

            else:

                if current_chunk:

                    current_chunk += "\n\n"

                current_chunk += line

        if current_chunk:

            chunks.append(
                current_chunk
            )

        for index, chunk in enumerate(chunks):

            field_name = (
                "🧾 Recent Transactions"
                if index == 0
                else "🧾 Recent Transactions (Continued)"
            )

            embed.add_field(
                name=field_name,
                value=chunk,
                inline=False
            )

    else:

        embed.add_field(
            name="🧾 Recent Transactions",
            value="No transactions yet.",
            inline=False
        )

    embed.set_footer(
        text=(
            f"Showing the last {len(recent)} of {len(transactions)} "
            f"transaction(s) • Use /fund_transcript for the full history"
        )
    )

    return embed


# ============================================================
# DISCORD-CHANNEL BACKUP / RESTORE
# ============================================================
#
# Every backup creates a NEW message (with timestamp) in
# #gang-fund-backups, keeping all historical backups.
#
# The channel is found/created AUTOMATICALLY. If BACKUP_CHANNEL_ID
# is set, that channel is used instead (override).
# ============================================================

BACKUP_CHANNEL_NAME = "gang-fund-backups"

_backup_channel_override_id = os.getenv("BACKUP_CHANNEL_ID")

if _backup_channel_override_id:
    _backup_channel_override_id = int(_backup_channel_override_id)

_backup_channel = None

_last_backup_ok = None
_last_backup_error = None
_last_backup_time = None


async def get_backup_channel():

    global _backup_channel

    if _backup_channel is not None:
        return _backup_channel

    guild = bot.get_guild(GUILD_ID)

    if guild is None:

        try:

            guild = await bot.fetch_guild(GUILD_ID)

        except Exception as e:

            print(
                f"Could not fetch guild for backups: {e}"
            )

            return None

    # Explicit override via BACKUP_CHANNEL_ID env var.
    if _backup_channel_override_id:

        try:

            channel = bot.get_channel(
                _backup_channel_override_id
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    _backup_channel_override_id
                )

            _backup_channel = channel

            return _backup_channel

        except Exception as e:

            print(
                f"BACKUP_CHANNEL_ID is set but not accessible "
                f"({e}). Falling back to auto-managed channel."
            )

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        return None

    for channel in guild.text_channels:

        if channel.name == BACKUP_CHANNEL_NAME:

            _backup_channel = channel

            return _backup_channel

    # Auto-create
    try:

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True
            )
        }

        channel = await guild.create_text_channel(
            name=BACKUP_CHANNEL_NAME,
            overwrites=overwrites,
            reason=(
                "Auto-created to back up gang fund data"
            )
        )

        print(
            f"Created backup channel #{channel.name} ({channel.id})"
        )

        _backup_channel = channel

        return _backup_channel

    except discord.Forbidden:

        print(
            "Bot missing 'Manage Channels' — cannot auto-create backup channel."
        )

        return None

    except Exception as e:

        print(
            f"Failed to create backup channel: {e}"
        )

        return None


async def push_backup():
    """Sends a **new** backup message every time (no editing)."""

    global _last_backup_ok, _last_backup_error, _last_backup_time

    channel = await get_backup_channel()

    if channel is None:

        _last_backup_ok = False
        _last_backup_error = "No backup channel available."
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)

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

        content = (
            f"🗄️ Gang fund data backup — "
            f"{datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )

        await channel.send(content=content, file=file)

        _last_backup_ok = True
        _last_backup_error = None
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)

    except Exception as e:

        print(
            f"Failed to push backup: {e}"
        )

        _last_backup_ok = False
        _last_backup_error = str(e)
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)


async def restore_backup_if_needed():
    """On startup, if local data.json is missing, restore from the latest backup in the channel."""

    global data

    channel = await get_backup_channel()

    if channel is None:
        return

    try:
        async for message in channel.history(limit=50):

            if message.author.id != bot.user.id:
                continue

            for attachment in message.attachments:

                if attachment.filename != "gang_fund_backup.json":
                    continue

                if _data_file_existed_at_boot:
                    return

                raw = await attachment.read()

                restored = json.loads(
                    raw.decode("utf-8")
                )

                for key in ["amount", "members", "panels", "message", "treasury_balance", "transactions", "treasury_panels"]:
                    if key not in restored:
                        if key in ["members"]:
                            restored[key] = {}
                        elif key in ["panels", "treasury_panels", "transactions"]:
                            restored[key] = []
                        else:
                            restored[key] = "" if key == "message" else 0

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
# TREASURY TRANSCRIPT CHANNEL
# ============================================================

TRANSCRIPT_CHANNEL_NAME = "gang-fund-transcript"

_transcript_channel_override_id = os.getenv("TRANSCRIPT_CHANNEL_ID")

if _transcript_channel_override_id:
    _transcript_channel_override_id = int(_transcript_channel_override_id)

_transcript_channel = None


async def get_transcript_channel():

    global _transcript_channel

    if _transcript_channel is not None:
        return _transcript_channel

    guild = bot.get_guild(GUILD_ID)

    if guild is None:

        try:

            guild = await bot.fetch_guild(GUILD_ID)

        except Exception as e:

            print(
                f"Could not fetch guild for transcript channel: {e}"
            )

            return None

    if _transcript_channel_override_id:

        try:

            channel = bot.get_channel(
                _transcript_channel_override_id
            )

            if channel is None:

                channel = await bot.fetch_channel(
                    _transcript_channel_override_id
                )

            _transcript_channel = channel

            return _transcript_channel

        except Exception as e:

            print(
                f"TRANSCRIPT_CHANNEL_ID is set but not accessible "
                f"({e}). Falling back to auto-managed channel."
            )

    guild = bot.get_guild(GUILD_ID)

    if guild is None:
        return None

    for channel in guild.text_channels:

        if channel.name == TRANSCRIPT_CHANNEL_NAME:

            _transcript_channel = channel

            return _transcript_channel

    try:

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True
            )
        }

        channel = await guild.create_text_channel(
            name=TRANSCRIPT_CHANNEL_NAME,
            overwrites=overwrites,
            reason=(
                "Auto-created to keep a permanent transcript of "
                "every gang treasury deposit/withdraw."
            )
        )

        print(
            f"Created transcript channel #{channel.name} ({channel.id})"
        )

        _transcript_channel = channel

        return _transcript_channel

    except discord.Forbidden:

        print(
            "Bot missing 'Manage Channels' — cannot auto-create transcript channel."
        )

        return None

    except Exception as e:

        print(
            f"Failed to create transcript channel: {e}"
        )

        return None


async def post_transcript_entry(entry):

    channel = await get_transcript_channel()

    if channel is None:
        return

    is_deposit = entry.get("type") == "deposit"

    embed = discord.Embed(
        title=(
            "🟢 Deposit Recorded"
            if is_deposit
            else "🔴 Withdrawal Recorded"
        ),
        color=(
            discord.Color.green()
            if is_deposit
            else discord.Color.red()
        ),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

    embed.add_field(
        name="Amount",
        value=f"${entry.get('amount', 0):,}",
        inline=True
    )

    embed.add_field(
        name="New Balance",
        value=f"${entry.get('balance_after', 0):,}",
        inline=True
    )

    embed.add_field(
        name="By",
        value=f"<@{entry.get('user_id')}>",
        inline=True
    )

    embed.add_field(
        name="Reason",
        value=entry.get("reason") or "No reason provided",
        inline=False
    )

    try:

        await channel.send(embed=embed)

    except Exception as e:

        print(
            f"Failed to post transcript entry: {e}"
        )


async def record_transaction(
    transaction_type: str,
    amount: int,
    reason: str,
    user: discord.abc.User
):

    if transaction_type == "deposit":

        data["treasury_balance"] += amount

    else:

        data["treasury_balance"] -= amount

    entry = {
        "type": transaction_type,
        "amount": amount,
        "reason": reason.strip() if reason else "",
        "user_id": user.id,
        "user_name": str(user.display_name),
        "balance_after": data["treasury_balance"],
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
    }

    data["transactions"].append(entry)

    save_data(data)

    await post_transcript_entry(entry)

    # This is where the treasury panel gets auto‑updated after every transaction.
    await update_all_treasury_panels()

    return entry


# ============================================================
# TREASURY PANEL AUTO-UPDATE
# ============================================================

async def register_treasury_panel(message: discord.Message):

    data["treasury_panels"].append(
        {
            "channel_id": message.channel.id,
            "message_id": message.id
        }
    )

    save_data(data)


async def update_all_treasury_panels():

    await push_backup()

    if not data.get("treasury_panels"):
        return

    embed = create_treasury_embed()

    still_valid = []

    for panel in data["treasury_panels"]:

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
                view=TreasuryView()
            )

            still_valid.append(panel)

        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException
        ) as e:

            print(
                f"Dropping stale treasury panel "
                f"{panel}: {e}"
            )

    data["treasury_panels"] = still_valid

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
# DEPOSIT / WITHDRAW MODALS
# ============================================================

def parse_amount(raw: str):

    raw = raw.strip().replace(",", "").replace("$", "")

    try:

        value = int(raw)

    except ValueError:

        return None

    if value <= 0:

        return None

    return value


class DepositModal(discord.ui.Modal, title="Deposit to Gang Fund"):

    amount_input = discord.ui.TextInput(
        label="Amount",
        placeholder="e.g. 5000",
        required=True,
        max_length=15
    )

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="e.g. Weekly member dues, robbery payout...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):

        amount = parse_amount(
            self.amount_input.value
        )

        if amount is None:

            await interaction.response.send_message(
                "❌ Enter a valid whole number greater than 0.",
                ephemeral=True
            )

            return

        await interaction.response.defer(
            ephemeral=True
        )

        entry = await record_transaction(
            "deposit",
            amount,
            self.reason_input.value,
            interaction.user
        )

        await interaction.followup.send(
            f"🟢 Deposited **${amount:,}**. "
            f"New balance: **${entry['balance_after']:,}**.",
            ephemeral=True
        )


class WithdrawModal(discord.ui.Modal, title="Withdraw from Gang Fund"):

    amount_input = discord.ui.TextInput(
        label="Amount",
        placeholder="e.g. 2500",
        required=True,
        max_length=15
    )

    reason_input = discord.ui.TextInput(
        label="Reason",
        placeholder="e.g. Bought supplies, gang expenses...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300
    )

    async def on_submit(self, interaction: discord.Interaction):

        amount = parse_amount(
            self.amount_input.value
        )

        if amount is None:

            await interaction.response.send_message(
                "❌ Enter a valid whole number greater than 0.",
                ephemeral=True
            )

            return

        if amount > data.get("treasury_balance", 0):

            await interaction.response.send_message(
                f"❌ Insufficient funds. Current balance is "
                f"**${data.get('treasury_balance', 0):,}**.",
                ephemeral=True
            )

            return

        await interaction.response.defer(
            ephemeral=True
        )

        entry = await record_transaction(
            "withdraw",
            amount,
            self.reason_input.value,
            interaction.user
        )

        await interaction.followup.send(
            f"🔴 Withdrew **${amount:,}**. "
            f"New balance: **${entry['balance_after']:,}**.",
            ephemeral=True
        )


# ============================================================
# TREASURY BUTTON VIEW
# ============================================================

class TreasuryView(
    discord.ui.View
):

    def __init__(self):

        super().__init__(
            timeout=None
        )

    # --------------------------------------------------------
    # DEPOSIT BUTTON
    # --------------------------------------------------------

    @discord.ui.button(
        label="Deposit",
        style=discord.ButtonStyle.success,
        emoji="🟢",
        custom_id="gang_fund_deposit"
    )
    async def deposit(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You don't have permission to manage the gang treasury.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            DepositModal()
        )

    # --------------------------------------------------------
    # WITHDRAW BUTTON
    # --------------------------------------------------------

    @discord.ui.button(
        label="Withdraw",
        style=discord.ButtonStyle.danger,
        emoji="🔴",
        custom_id="gang_fund_withdraw"
    )
    async def withdraw(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):

            await interaction.response.send_message(
                "❌ You don't have permission to manage the gang treasury.",
                ephemeral=True
            )

            return

        await interaction.response.send_modal(
            WithdrawModal()
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

        bot.add_view(
            TreasuryView()
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

        # Auto‑refresh all panels to reflect current data.
        await update_all_panels()
        await update_all_treasury_panels()

    print(
        "GTA RP Gang Fund Bot is ready!"
    )


# ============================================================
# /FUND_ADD
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

@bot.tree.command(
    name="fund_list",
    description="Show the gang fund list"
)
async def fund_list(
    interaction: discord.Interaction
):

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
# /FUND_BACKUP_STATUS
# ============================================================

@bot.tree.command(
    name="fund_backup_status",
    description="Check whether gang fund data backups are working"
)
async def fund_backup_status(
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

    channel = await get_backup_channel()

    embed = discord.Embed(
        title="🗄️ Backup Status",
        color=(
            discord.Color.green()
            if channel is not None
            else discord.Color.red()
        )
    )

    if channel is not None:

        embed.add_field(
            name="Backup Channel",
            value=channel.mention,
            inline=False
        )

        embed.add_field(
            name="Info",
            value="All backups are kept permanently. Each data change creates a new message.",
            inline=False
        )

    else:

        embed.add_field(
            name="Backup Channel",
            value=(
                "❌ Not available — the bot likely needs the "
                "**Manage Channels** permission to auto-create "
                "`#gang-fund-backups`."
            ),
            inline=False
        )

    if _last_backup_time is not None:

        status_text = (
            "✅ Success"
            if _last_backup_ok
            else f"❌ Failed — {_last_backup_error}"
        )

        embed.add_field(
            name="Last Backup Attempt",
            value=(
                f"{status_text}\n"
                f"<t:{int(_last_backup_time.timestamp())}:R>"
            ),
            inline=False
        )

    else:

        embed.add_field(
            name="Last Backup Attempt",
            value="No backup has been attempted yet this session.",
            inline=False
        )

    embed.add_field(
        name="Local data.json",
        value=(
            "Exists" if os.path.exists(DATA_FILE) else "Missing"
        ),
        inline=True
    )

    embed.add_field(
        name="Players Tracked",
        value=str(len(data["members"])),
        inline=True
    )

    await interaction.followup.send(
        embed=embed,
        ephemeral=True
    )


@bot.tree.command(
    name="fund_backup_now",
    description="Force an immediate backup of the gang fund data"
)
async def fund_backup_now(
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

    await push_backup()

    if _last_backup_ok:

        await interaction.followup.send(
            f"✅ Backup saved successfully to "
            f"{_backup_channel.mention if _backup_channel else 'the backup channel'}.",
            ephemeral=True
        )

    else:

        await interaction.followup.send(
            f"❌ Backup failed: {_last_backup_error}",
            ephemeral=True
        )


# ============================================================
# /FUND_IMPORT – Import a backup JSON file
# ============================================================

@bot.tree.command(
    name="fund_import",
    description="Import gang fund data from a backup JSON file"
)
@app_commands.describe(
    backup_file="The backup .json file to import"
)
async def fund_import(
    interaction: discord.Interaction,
    backup_file: discord.Attachment
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

    if not backup_file.filename.endswith(".json"):

        await interaction.followup.send(
            "❌ Please upload a `.json` file.",
            ephemeral=True
        )

        return

    try:

        raw = await backup_file.read()
        imported = json.loads(raw.decode("utf-8"))

    except Exception as e:

        await interaction.followup.send(
            f"❌ Failed to read JSON: {e}",
            ephemeral=True
        )

        return

    # Validate required keys
    if "members" not in imported or "amount" not in imported:

        await interaction.followup.send(
            "❌ Invalid backup file – missing 'members' or 'amount'.",
            ephemeral=True
        )

        return

    # Defaults for missing keys
    for key in ["panels", "treasury_panels", "transactions"]:
        if key not in imported:
            imported[key] = []

    if "message" not in imported:
        imported["message"] = ""

    if "treasury_balance" not in imported:
        imported["treasury_balance"] = 0

    # Overwrite local data
    global data
    data = imported
    save_data(data)

    # Refresh all panels immediately
    await update_all_panels()
    await update_all_treasury_panels()

    # Push a fresh backup of the imported state
    await push_backup()

    await interaction.followup.send(
        f"✅ Backup imported successfully! Loaded {len(data['members'])} players "
        f"and ${data.get('treasury_balance', 0):,} treasury balance. "
        f"A new backup has been saved.",
        ephemeral=True
    )


# ============================================================
# /FUND_PANEL
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
# /FUND_TREASURY
# ============================================================

@bot.tree.command(
    name="fund_treasury",
    description="Create the gang treasury panel (deposit / withdraw buttons)"
)
async def fund_treasury(
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

    embed = create_treasury_embed()

    message = await interaction.channel.send(
        embed=embed,
        view=TreasuryView()
    )

    await register_treasury_panel(message)

    await interaction.followup.send(
        "✅ Gang treasury panel created!",
        ephemeral=True
    )


# ============================================================
# /FUND_DEPOSIT and /FUND_WITHDRAW
# ============================================================

@bot.tree.command(
    name="fund_deposit",
    description="Deposit money into the gang treasury"
)
@app_commands.describe(
    amount="Amount to deposit",
    reason="Why this money is being deposited"
)
async def fund_deposit(
    interaction: discord.Interaction,
    amount: int,
    reason: str = ""
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

    if amount <= 0:

        await interaction.followup.send(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )

        return

    entry = await record_transaction(
        "deposit",
        amount,
        reason,
        interaction.user
    )

    await interaction.followup.send(
        f"🟢 Deposited **${amount:,}**. "
        f"New balance: **${entry['balance_after']:,}**.",
        ephemeral=True
    )


@bot.tree.command(
    name="fund_withdraw",
    description="Withdraw money from the gang treasury"
)
@app_commands.describe(
    amount="Amount to withdraw",
    reason="Why this money is being withdrawn"
)
async def fund_withdraw(
    interaction: discord.Interaction,
    amount: int,
    reason: str = ""
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

    if amount <= 0:

        await interaction.followup.send(
            "❌ Amount must be greater than 0.",
            ephemeral=True
        )

        return

    if amount > data.get("treasury_balance", 0):

        await interaction.followup.send(
            f"❌ Insufficient funds. Current balance is "
            f"**${data.get('treasury_balance', 0):,}**.",
            ephemeral=True
        )

        return

    entry = await record_transaction(
        "withdraw",
        amount,
        reason,
        interaction.user
    )

    await interaction.followup.send(
        f"🔴 Withdrew **${amount:,}**. "
        f"New balance: **${entry['balance_after']:,}**.",
        ephemeral=True
    )


# ============================================================
# /FUND_TRANSCRIPT
# ============================================================

TRANSCRIPT_PAGE_SIZE = 10


def create_transcript_page_embed(page: int):

    transactions = data.get(
        "transactions",
        []
    )

    total = len(transactions)

    total_pages = max(
        1,
        (total + TRANSCRIPT_PAGE_SIZE - 1) // TRANSCRIPT_PAGE_SIZE
    )

    page = max(
        0,
        min(page, total_pages - 1)
    )

    # Newest first.
    ordered = list(
        reversed(transactions)
    )

    start = page * TRANSCRIPT_PAGE_SIZE

    page_items = ordered[start:start + TRANSCRIPT_PAGE_SIZE]

    embed = discord.Embed(
        title="🧾 Gang Treasury Transcript",
        description=(
            f"Current balance: **${data.get('treasury_balance', 0):,}** "
            f"• {total} total transaction(s)"
        ),
        color=discord.Color.blurple()
    )

    if page_items:

        for entry in page_items:

            label = TRANSACTION_TYPE_LABELS.get(
                entry.get("type"),
                entry.get("type", "Transaction")
            )

            timestamp = entry.get("timestamp")

            if timestamp:

                try:

                    dt = datetime.datetime.fromisoformat(timestamp)

                    time_text = f"<t:{int(dt.timestamp())}:f>"

                except ValueError:

                    time_text = "Unknown time"

            else:

                time_text = "Unknown time"

            embed.add_field(
                name=f"{label} — ${entry.get('amount', 0):,}",
                value=(
                    f"By **{entry.get('user_name', 'Unknown')}** • {time_text}\n"
                    f"Reason: {entry.get('reason') or 'No reason provided'}\n"
                    f"Balance after: ${entry.get('balance_after', 0):,}"
                ),
                inline=False
            )

    else:

        embed.add_field(
            name="No transactions yet",
            value="Use the Deposit / Withdraw buttons on the treasury panel to get started.",
            inline=False
        )

    embed.set_footer(
        text=f"Page {page + 1} of {total_pages}"
    )

    return embed, page, total_pages


class TranscriptPaginatorView(discord.ui.View):

    def __init__(self, owner_id: int):

        super().__init__(timeout=180)

        self.owner_id = owner_id
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:

        if interaction.user.id != self.owner_id:

            await interaction.response.send_message(
                "❌ This isn't your transcript view.",
                ephemeral=True
            )

            return False

        return True

    @discord.ui.button(
        label="◀ Previous",
        style=discord.ButtonStyle.secondary
    )
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        self.page -= 1

        embed, self.page, _ = create_transcript_page_embed(
            self.page
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary
    )
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        self.page += 1

        embed, self.page, _ = create_transcript_page_embed(
            self.page
        )

        await interaction.response.edit_message(
            embed=embed,
            view=self
        )


@bot.tree.command(
    name="fund_transcript",
    description="View the full gang treasury transaction history"
)
async def fund_transcript(
    interaction: discord.Interaction
):

    await interaction.response.defer(
        ephemeral=True
    )

    embed, page, total_pages = create_transcript_page_embed(0)

    view = TranscriptPaginatorView(
        owner_id=interaction.user.id
    )

    view.page = page

    if total_pages <= 1:

        view.previous.disabled = True
        view.next.disabled = True

    await interaction.followup.send(
        embed=embed,
        view=view,
        ephemeral=True
    )


# ============================================================
# GENERAL-PURPOSE EMBED BUILDER  (/embed create)
# ============================================================

def is_embed_empty(embed: discord.Embed) -> bool:

    has_author = bool(embed.author and embed.author.name)
    has_image = bool(embed.image and embed.image.url)
    has_thumbnail = bool(embed.thumbnail and embed.thumbnail.url)

    return not (
        embed.title
        or embed.description
        or embed.fields
        or has_author
        or has_image
        or has_thumbnail
    )


def preview_embeds(embeds: list) -> list:

    result = []

    for embed in embeds:

        if is_embed_empty(embed):

            placeholder = embed.copy()

            placeholder.description = (
                "*(empty — use the buttons below to add content)*"
            )

            result.append(placeholder)

        else:

            result.append(embed)

    return result


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
            embeds=preview_embeds(self.embeds),
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

        empty_numbers = [
            str(i + 1)
            for i, embed in enumerate(self.embeds)
            if is_embed_empty(embed)
        ]

        if empty_numbers:

            await interaction.response.send_message(
                f"❌ Embed {', '.join(empty_numbers)} has no content yet. "
                f"Add a title, description, field, author, or image "
                f"before sending.",
                ephemeral=True
            )

            return

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
        embeds=preview_embeds(view.embeds),
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
