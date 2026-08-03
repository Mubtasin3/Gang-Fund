import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
import datetime
import threading
import uuid
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
    app.run(host="0.0.0.0", port=port)


# ============================================================
# DATA FILE
# ============================================================

DATA_FILE = "data.json"
_data_file_existed_at_boot = os.path.exists(DATA_FILE)


def default_data():
    return {
        "amount": 0,
        "members": {},
        "panels": [],
        "message": "",
        "treasury_balance": 0,
        "transactions": [],
        "treasury_panels": [],
        "tasks": [],
        "task_panels": []
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        defaults = default_data()
        for key in defaults:
            if key not in data:
                data[key] = defaults[key]

        for task in data.get("tasks", []):
            if "id" not in task:
                task["id"] = str(uuid.uuid4())
            if "name" not in task:
                task["name"] = "Unnamed Task"
            if "description" not in task:
                task["description"] = ""
            if "reward" not in task:
                task["reward"] = 0
            if "created_by" not in task:
                task["created_by"] = "Unknown"
            if "created_at" not in task:
                task["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if "participants" not in task:
                task["participants"] = {}

        return data
    except Exception as e:
        print(f"Error loading data.json: {e}")
        return default_data()


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving data.json: {e}")


data = load_data()


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.members = True

class GangFundBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)
        self.synced = False

bot = GangFundBot()


# ============================================================
# PERMISSION CHECK
# ============================================================

def is_admin(interaction: discord.Interaction):
    if interaction.guild is None:
        return False
    if interaction.user.guild_permissions.administrator:
        return True
    role = interaction.guild.get_role(ADMIN_ROLE_ID)
    if role and role in interaction.user.roles:
        return True
    return False


# ============================================================
# FUND EMBEDS (unchanged)
# ============================================================

def create_fund_embed():
    amount = data.get("amount", 0)
    members = data.get("members", {})
    total_members = len(members)
    paid_members = sum(1 for v in members.values() if v is True)
    unpaid_members = total_members - paid_members
    collected = paid_members * amount
    required = total_members * amount

    embed = discord.Embed(title="💰 GANG FUND - TITAN", description="Gang fund payment tracker", color=discord.Color.green())
    embed.add_field(name="💵 Fund Per Player", value=f"${amount:,}", inline=True)
    embed.add_field(name="👥 Members", value=str(total_members), inline=True)
    embed.add_field(name="💰 Collected", value=f"${collected:,} / ${required:,}", inline=True)
    embed.add_field(name="✅ Paid", value=str(paid_members), inline=True)
    embed.add_field(name="❌ Unpaid", value=str(unpaid_members), inline=True)

    if members:
        member_list = [f"✅ **{n}** — Paid" if p else f"❌ **{n}** — Unpaid" for n, p in members.items()]
        chunks = []
        current = ""
        for line in member_list:
            if len(current) + len(line) + 1 > 1000:
                chunks.append(current)
                current = line
            else:
                current += ("\n" + line) if current else line
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            name = "📋 Member List" if i == 0 else "📋 Member List (Continued)"
            embed.add_field(name=name, value=chunk, inline=False)
    else:
        embed.add_field(name="📋 Member List", value="No members added yet.", inline=False)

    note = data.get("message", "")
    if note:
        embed.add_field(name="────────", value=note, inline=False)

    embed.set_footer(text="Use the buttons below to update payments.")
    return embed


# ============================================================
# TREASURY EMBEDS (unchanged)
# ============================================================

TRANSACTION_TYPE_LABELS = {"deposit": "🟢 Deposit", "withdraw": "🔴 Withdraw"}

def format_transaction_line(entry):
    label = TRANSACTION_TYPE_LABELS.get(entry.get("type"), entry.get("type", "Transaction"))
    amount = entry.get("amount", 0)
    reason = entry.get("reason") or "No reason provided"
    user_name = entry.get("user_name", "Unknown")
    ts = entry.get("timestamp")
    time_text = f"<t:{int(datetime.datetime.fromisoformat(ts).timestamp())}:R>" if ts else ""
    return f"{label} **${amount:,}** by **{user_name}** {time_text}\n> {reason}"

def create_treasury_embed():
    balance = data.get("treasury_balance", 0)
    transactions = data.get("transactions", [])
    embed = discord.Embed(title="🏦 GANG TREASURY - TITAN", description="Deposit or withdraw funds. Every transaction is logged.",
                          color=discord.Color.green() if balance >= 0 else discord.Color.red())
    embed.add_field(name="💰 Current Balance", value=f"${balance:,}", inline=False)

    recent = transactions[-10:]
    if recent:
        lines = [format_transaction_line(e) for e in recent]
        chunks = []
        current = ""
        for line in lines:
            if len(current) + len(line) + 2 > 1000:
                chunks.append(current)
                current = line
            else:
                current += ("\n\n" + line) if current else line
        if current:
            chunks.append(current)
        for i, chunk in enumerate(chunks):
            name = "🧾 Recent Transactions" if i == 0 else "🧾 Recent Transactions (Continued)"
            embed.add_field(name=name, value=chunk, inline=False)
    else:
        embed.add_field(name="🧾 Recent Transactions", value="No transactions yet.", inline=False)

    embed.set_footer(text=f"Showing the last {len(recent)} of {len(transactions)} transaction(s) • Use /fund_transcript for full history")
    return embed


# ============================================================
# TASK EMBED (UPDATED - BIGGER TASK NAME)
# ============================================================

def create_task_embed(page=0, per_page=5):
    tasks = data.get("tasks", [])
    total = len(tasks)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    page_items = tasks[start:start+per_page]

    embed = discord.Embed(title="📋 GANG TASKS - TITAN", color=discord.Color.blurple())
    if page_items:
        for task in page_items:
            reward = task.get("reward", 0)
            reward_str = f" (Reward: ${reward:,} each)" if reward > 0 else ""
            # Use a big emoji and bold name on its own line
            field_name = f"📌 Task (ID: {task.get('id', '?')[:6]})"
            
            participants = task.get("participants", {})
            total_parts = len(participants)
            completed = sum(1 for v in participants.values() if v)
            status_line = f"**Progress:** {completed}/{total_parts} completed"
            
            if participants:
                player_lines = []
                for player_name, done in participants.items():
                    icon = "✅" if done else "❌"
                    player_lines.append(f"{icon} **{player_name}**")
                player_text = "\n".join(player_lines)
            else:
                player_text = "No players assigned yet."
            
            # Task name in bold, larger feel
            field_value = f"**__{task.get('name', 'Unnamed Task')}__**\n{status_line}\n{player_text}{reward_str}\n> {task.get('description', 'No description')}"
            embed.add_field(name=field_name, value=field_value, inline=False)
    else:
        embed.add_field(name="No tasks", value="Use `/task_create` to add tasks.", inline=False)

    embed.set_footer(text=f"Page {page+1} of {total_pages}")
    return embed, page, total_pages


# ============================================================
# BACKUP / RESTORE (permanent new-message backups)
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
            print(f"Could not fetch guild for backups: {e}")
            return None
    if _backup_channel_override_id:
        try:
            channel = bot.get_channel(_backup_channel_override_id)
            if channel is None:
                channel = await bot.fetch_channel(_backup_channel_override_id)
            _backup_channel = channel
            return _backup_channel
        except Exception as e:
            print(f"BACKUP_CHANNEL_ID not accessible ({e}). Falling back.")
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return None
    for channel in guild.text_channels:
        if channel.name == BACKUP_CHANNEL_NAME:
            _backup_channel = channel
            return _backup_channel
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True)
        }
        channel = await guild.create_text_channel(name=BACKUP_CHANNEL_NAME, overwrites=overwrites,
                                                  reason="Auto-created to back up gang fund data")
        print(f"Created backup channel #{channel.name} ({channel.id})")
        _backup_channel = channel
        return _backup_channel
    except discord.Forbidden:
        print("Bot missing 'Manage Channels' – cannot auto-create backup channel.")
        return None
    except Exception as e:
        print(f"Failed to create backup channel: {e}")
        return None

async def push_backup():
    global _last_backup_ok, _last_backup_error, _last_backup_time
    channel = await get_backup_channel()
    if channel is None:
        _last_backup_ok = False
        _last_backup_error = "No backup channel available."
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)
        return
    buffer = io.BytesIO(json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8"))
    file = discord.File(buffer, filename="gang_fund_backup.json")
    try:
        content = f"🗄️ Gang fund data backup — {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        await channel.send(content=content, file=file)
        _last_backup_ok = True
        _last_backup_error = None
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)
    except Exception as e:
        print(f"Failed to push backup: {e}")
        _last_backup_ok = False
        _last_backup_error = str(e)
        _last_backup_time = datetime.datetime.now(datetime.timezone.utc)

async def restore_backup_if_needed():
    global data
    channel = await get_backup_channel()
    if channel is None:
        return
    try:
        async for message in channel.history(limit=50):
            if message.author.id != bot.user.id:
                continue
            for attachment in message.attachments:
                if attachment.filename == "gang_fund_backup.json":
                    if _data_file_existed_at_boot:
                        return
                    raw = await attachment.read()
                    restored = json.loads(raw.decode("utf-8"))
                    defaults = default_data()
                    for key in defaults:
                        if key not in restored:
                            restored[key] = defaults[key]
                    data = restored
                    save_data(data)
                    print(f"Restored gang fund data from Discord backup ({len(data['members'])} players, {len(data['tasks'])} tasks).")
                    return
    except Exception as e:
        print(f"Error scanning backup channel for restore: {e}")


# ============================================================
# AUTO-UPDATE HELPERS (panels)
# ============================================================

async def register_panel(message):
    data["panels"].append({"channel_id": message.channel.id, "message_id": message.id})
    save_data(data)

async def update_all_panels():
    await push_backup()
    if not data.get("panels"):
        return
    embed = create_fund_embed()
    still_valid = []
    for panel in data["panels"]:
        try:
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=embed, view=FundView())
            still_valid.append(panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"Dropping stale panel {panel}: {e}")
    data["panels"] = still_valid
    save_data(data)

async def register_treasury_panel(message):
    data["treasury_panels"].append({"channel_id": message.channel.id, "message_id": message.id})
    save_data(data)

async def update_all_treasury_panels():
    await push_backup()
    if not data.get("treasury_panels"):
        return
    embed = create_treasury_embed()
    still_valid = []
    for panel in data["treasury_panels"]:
        try:
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=embed, view=TreasuryView())
            still_valid.append(panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"Dropping stale treasury panel {panel}: {e}")
    data["treasury_panels"] = still_valid
    save_data(data)

async def register_task_panel(message):
    data["task_panels"].append({"channel_id": message.channel.id, "message_id": message.id})
    save_data(data)

async def update_all_task_panels():
    await push_backup()
    if not data.get("task_panels"):
        return
    embed, _, _ = create_task_embed()
    still_valid = []
    for panel in data["task_panels"]:
        try:
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])
            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=embed, view=TaskPanelView())
            still_valid.append(panel)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"Dropping stale task panel {panel}: {e}")
    data["task_panels"] = still_valid
    save_data(data)


# ============================================================
# TRANSCRIPT CHANNEL (Treasury)
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
            print(f"Could not fetch guild for transcript channel: {e}")
            return None
    if _transcript_channel_override_id:
        try:
            channel = bot.get_channel(_transcript_channel_override_id)
            if channel is None:
                channel = await bot.fetch_channel(_transcript_channel_override_id)
            _transcript_channel = channel
            return _transcript_channel
        except Exception as e:
            print(f"TRANSCRIPT_CHANNEL_ID not accessible ({e}). Falling back.")
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return None
    for channel in guild.text_channels:
        if channel.name == TRANSCRIPT_CHANNEL_NAME:
            _transcript_channel = channel
            return _transcript_channel
    try:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=True, send_messages=False),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, read_message_history=True)
        }
        channel = await guild.create_text_channel(name=TRANSCRIPT_CHANNEL_NAME, overwrites=overwrites,
                                                  reason="Auto-created for gang treasury transcript")
        print(f"Created transcript channel #{channel.name} ({channel.id})")
        _transcript_channel = channel
        return _transcript_channel
    except discord.Forbidden:
        print("Bot missing 'Manage Channels' – cannot auto-create transcript channel.")
        return None
    except Exception as e:
        print(f"Failed to create transcript channel: {e}")
        return None

async def post_transcript_entry(entry):
    channel = await get_transcript_channel()
    if channel is None:
        return
    is_deposit = entry.get("type") == "deposit"
    embed = discord.Embed(title="🟢 Deposit Recorded" if is_deposit else "🔴 Withdrawal Recorded",
                          color=discord.Color.green() if is_deposit else discord.Color.red(),
                          timestamp=datetime.datetime.now(datetime.timezone.utc))
    embed.add_field(name="Amount", value=f"${entry.get('amount', 0):,}", inline=True)
    embed.add_field(name="New Balance", value=f"${entry.get('balance_after', 0):,}", inline=True)
    embed.add_field(name="By", value=f"<@{entry.get('user_id')}>", inline=True)
    embed.add_field(name="Reason", value=entry.get("reason") or "No reason provided", inline=False)
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"Failed to post transcript entry: {e}")

async def record_transaction(transaction_type: str, amount: int, reason: str, user: discord.abc.User):
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
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
    data["transactions"].append(entry)
    save_data(data)
    await post_transcript_entry(entry)
    await update_all_treasury_panels()
    return entry


# ============================================================
# AUTOCOMPLETE FOR PLAYERS (Fund)
# ============================================================

async def player_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=n, value=n) for n in data["members"] if current.lower() in n.lower()][:25]


# ============================================================
# FUND VIEWS AND MODALS (unchanged)
# ============================================================

class PaidSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        player = self.values[0]
        data["members"][player] = True
        save_data(data)
        await interaction.response.edit_message(content=f"✅ **{player}** has been marked as **PAID**.", view=None)
        await update_all_panels()

class UnpaidSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Choose a player...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        player = self.values[0]
        data["members"][player] = False
        save_data(data)
        await interaction.response.edit_message(content=f"❌ **{player}** has been marked as **UNPAID**.", view=None)
        await update_all_panels()

class FundView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Mark Paid", style=discord.ButtonStyle.success, emoji="✅", custom_id="gang_fund_mark_paid")
    async def mark_paid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        if not data["members"]:
            return await interaction.response.send_message("❌ No players.", ephemeral=True)
        options = [discord.SelectOption(label=n[:100], value=n[:100]) for n in data["members"]]
        if len(options) > 25:
            return await interaction.response.send_message("❌ Too many players. Use `/fund_paid`.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(PaidSelect(options))
        await interaction.response.send_message("Select who paid:", view=view, ephemeral=True)

    @discord.ui.button(label="Mark Unpaid", style=discord.ButtonStyle.danger, emoji="❌", custom_id="gang_fund_mark_unpaid")
    async def mark_unpaid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        if not data["members"]:
            return await interaction.response.send_message("❌ No players.", ephemeral=True)
        options = [discord.SelectOption(label=n[:100], value=n[:100]) for n in data["members"]]
        if len(options) > 25:
            return await interaction.response.send_message("❌ Too many players. Use `/fund_unpaid`.", ephemeral=True)
        view = discord.ui.View(timeout=60)
        view.add_item(UnpaidSelect(options))
        await interaction.response.send_message("Select who is unpaid:", view=view, ephemeral=True)


def parse_amount(raw: str):
    raw = raw.strip().replace(",", "").replace("$", "")
    try:
        val = int(raw)
        return val if val > 0 else None
    except ValueError:
        return None

class DepositModal(discord.ui.Modal, title="Deposit to Gang Fund"):
    amount_input = discord.ui.TextInput(label="Amount", placeholder="e.g. 5000", required=True, max_length=15)
    reason_input = discord.ui.TextInput(label="Reason", placeholder="Reason...", style=discord.TextStyle.paragraph, required=False, max_length=300)
    async def on_submit(self, interaction: discord.Interaction):
        amount = parse_amount(self.amount_input.value)
        if amount is None:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        entry = await record_transaction("deposit", amount, self.reason_input.value, interaction.user)
        await interaction.followup.send(f"🟢 Deposited **${amount:,}**. New balance: **${entry['balance_after']:,}**.", ephemeral=True)

class WithdrawModal(discord.ui.Modal, title="Withdraw from Gang Fund"):
    amount_input = discord.ui.TextInput(label="Amount", placeholder="e.g. 2500", required=True, max_length=15)
    reason_input = discord.ui.TextInput(label="Reason", placeholder="Reason...", style=discord.TextStyle.paragraph, required=False, max_length=300)
    async def on_submit(self, interaction: discord.Interaction):
        amount = parse_amount(self.amount_input.value)
        if amount is None:
            return await interaction.response.send_message("❌ Invalid amount.", ephemeral=True)
        if amount > data.get("treasury_balance", 0):
            return await interaction.response.send_message(f"❌ Insufficient funds. Balance: **${data['treasury_balance']:,}**.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        entry = await record_transaction("withdraw", amount, self.reason_input.value, interaction.user)
        await interaction.followup.send(f"🔴 Withdrew **${amount:,}**. New balance: **${entry['balance_after']:,}**.", ephemeral=True)

class TreasuryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Deposit", style=discord.ButtonStyle.success, emoji="🟢", custom_id="gang_fund_deposit")
    async def deposit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(DepositModal())
    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.danger, emoji="🔴", custom_id="gang_fund_withdraw")
    async def withdraw(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        await interaction.response.send_modal(WithdrawModal())


# ============================================================
# TASK PANEL VIEW & MODALS (UPDATED - DROPDOWN ADD PLAYER)
# ============================================================

class TaskPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add Player", style=discord.ButtonStyle.success, emoji="➕", custom_id="task_add_player")
    async def add_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        if not data["tasks"]:
            return await interaction.response.send_message("❌ No tasks.", ephemeral=True)
        # Step 1: Choose task
        options = [discord.SelectOption(label=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in data["tasks"]]
        select = discord.ui.Select(placeholder="Select a task...", options=options[:25])
        async def task_select_callback(sel_interaction):
            task_id = select.values[0]
            task = next((t for t in data["tasks"] if t["id"] == task_id), None)
            if not task:
                return await sel_interaction.response.edit_message(content="❌ Task not found.", view=None)
            # Get eligible players: gang fund members not already in task
            all_members = set(data["members"].keys())
            already_in = set(task["participants"].keys())
            eligible = sorted(all_members - already_in)
            if not eligible:
                return await sel_interaction.response.edit_message(content="❌ All gang members are already in this task.", view=None)
            player_options = [discord.SelectOption(label=name[:100], value=name) for name in eligible[:25]]
            player_select = discord.ui.Select(placeholder="Select a player to add...", options=player_options)
            async def add_callback(player_interaction):
                player_name = player_select.values[0]
                task["participants"][player_name] = False
                save_data(data)
                await update_all_task_panels()
                await player_interaction.response.edit_message(content=f"✅ Added **{player_name}** to task '{task['name']}'.", view=None)
            player_select.callback = add_callback
            view = discord.ui.View(timeout=60)
            view.add_item(player_select)
            await sel_interaction.response.edit_message(content="Select a player to add:", view=view)
        select.callback = task_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a task:", view=view, ephemeral=True)

    @discord.ui.button(label="Mark Complete", style=discord.ButtonStyle.primary, emoji="✅", custom_id="task_mark_complete")
    async def mark_complete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        tasks = data.get("tasks", [])
        if not tasks:
            return await interaction.response.send_message("❌ No tasks.", ephemeral=True)
        options = [discord.SelectOption(label=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in tasks]
        select = discord.ui.Select(placeholder="Select a task...", options=options[:25])
        async def task_select_callback(sel_interaction):
            task_id = select.values[0]
            task = next((t for t in tasks if t["id"] == task_id), None)
            if not task:
                return await sel_interaction.response.edit_message(content="❌ Task not found.", view=None)
            incomplete = [(name, done) for name, done in task.get("participants", {}).items() if not done]
            if not incomplete:
                return await sel_interaction.response.edit_message(content="❌ No incomplete players in this task.", view=None)
            player_options = [discord.SelectOption(label=name, value=name) for name, _ in incomplete[:25]]
            player_select = discord.ui.Select(placeholder="Select a player to mark complete...", options=player_options)
            async def mark_callback(player_interaction):
                player_name = player_select.values[0]
                reward = task.get("reward", 0)
                if reward > data["treasury_balance"]:
                    return await player_interaction.response.edit_message(
                        content=f"❌ Insufficient treasury funds for reward ${reward:,}. Balance: ${data['treasury_balance']:,}.", view=None)
                if reward > 0:
                    await record_transaction("withdraw", reward, f"Task completion: {task['name']} - {player_name}", player_interaction.user)
                task["participants"][player_name] = True
                save_data(data)
                await update_all_task_panels()
                await player_interaction.response.edit_message(
                    content=f"✅ Marked **{player_name}** complete on task '{task['name']}'.{' Reward $'+format(reward,',')+' paid.' if reward else ''}", view=None)
            player_select.callback = mark_callback
            view = discord.ui.View(timeout=60)
            view.add_item(player_select)
            await sel_interaction.response.edit_message(content="Select a player:", view=view)
        select.callback = task_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a task:", view=view, ephemeral=True)

    @discord.ui.button(label="Mark Incomplete", style=discord.ButtonStyle.secondary, emoji="❌", custom_id="task_mark_incomplete")
    async def mark_incomplete(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        tasks = data.get("tasks", [])
        if not tasks:
            return await interaction.response.send_message("❌ No tasks.", ephemeral=True)
        options = [discord.SelectOption(label=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in tasks]
        select = discord.ui.Select(placeholder="Select a task...", options=options[:25])
        async def task_select_callback(sel_interaction):
            task_id = select.values[0]
            task = next((t for t in tasks if t["id"] == task_id), None)
            if not task:
                return await sel_interaction.response.edit_message(content="❌ Task not found.", view=None)
            completed = [(name, True) for name, done in task.get("participants", {}).items() if done]
            if not completed:
                return await sel_interaction.response.edit_message(content="❌ No completed players in this task.", view=None)
            player_options = [discord.SelectOption(label=name, value=name) for name, _ in completed[:25]]
            player_select = discord.ui.Select(placeholder="Select a player to mark incomplete...", options=player_options)
            async def mark_callback(player_interaction):
                player_name = player_select.values[0]
                task["participants"][player_name] = False
                save_data(data)
                await update_all_task_panels()
                await player_interaction.response.edit_message(content=f"❌ Marked **{player_name}** incomplete on task '{task['name']}'.", view=None)
            player_select.callback = mark_callback
            view = discord.ui.View(timeout=60)
            view.add_item(player_select)
            await sel_interaction.response.edit_message(content="Select a player:", view=view)
        select.callback = task_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a task:", view=view, ephemeral=True)

    @discord.ui.button(label="Remove Player", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="task_remove_player")
    async def remove_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        tasks = data.get("tasks", [])
        if not tasks:
            return await interaction.response.send_message("❌ No tasks.", ephemeral=True)
        options = [discord.SelectOption(label=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in tasks]
        select = discord.ui.Select(placeholder="Select a task...", options=options[:25])
        async def task_select_callback(sel_interaction):
            task_id = select.values[0]
            task = next((t for t in tasks if t["id"] == task_id), None)
            if not task:
                return await sel_interaction.response.edit_message(content="❌ Task not found.", view=None)
            if not task.get("participants"):
                return await sel_interaction.response.edit_message(content="❌ No players in this task.", view=None)
            player_options = [discord.SelectOption(label=name, value=name) for name in task["participants"]][:25]
            player_select = discord.ui.Select(placeholder="Select a player to remove...", options=player_options)
            async def remove_callback(player_interaction):
                player_name = player_select.values[0]
                del task["participants"][player_name]
                save_data(data)
                await update_all_task_panels()
                await player_interaction.response.edit_message(content=f"🗑️ Removed **{player_name}** from task '{task['name']}'.", view=None)
            player_select.callback = remove_callback
            view = discord.ui.View(timeout=60)
            view.add_item(player_select)
            await sel_interaction.response.edit_message(content="Select a player:", view=view)
        select.callback = task_select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a task:", view=view, ephemeral=True)

    @discord.ui.button(label="Delete Task", style=discord.ButtonStyle.danger, emoji="❌", custom_id="task_delete_button")
    async def delete_task_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("❌ No permission.", ephemeral=True)
        if not data["tasks"]:
            return await interaction.response.send_message("❌ No tasks.", ephemeral=True)
        options = [discord.SelectOption(label=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in data["tasks"]]
        select = discord.ui.Select(placeholder="Select a task to delete...", options=options[:25])
        async def select_callback(sel_interaction):
            task_id = select.values[0]
            data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
            save_data(data)
            await update_all_task_panels()
            await sel_interaction.response.edit_message(content="✅ Task deleted.", view=None)
        select.callback = select_callback
        view = discord.ui.View(timeout=60)
        view.add_item(select)
        await interaction.response.send_message("Select a task to delete:", view=view, ephemeral=True)


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():
    print("----------------------------------------")
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("----------------------------------------")
    if not bot.synced:
        await restore_backup_if_needed()
        bot.add_view(FundView())
        bot.add_view(TreasuryView())
        bot.add_view(TaskPanelView())
        try:
            guild = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Successfully synced {len(synced)} slash commands.")
            bot.synced = True
        except Exception as e:
            print(f"ERROR syncing slash commands: {e}")
        await update_all_panels()
        await update_all_treasury_panels()
        await update_all_task_panels()
    print("GTA RP Gang Fund Bot is ready!")


# ============================================================
# /FUND_... COMMANDS (unchanged)
# ============================================================

@bot.tree.command(name="fund_add", description="Add a player to the gang fund")
@app_commands.describe(player="Select the player to add")
async def fund_add(interaction: discord.Interaction, player: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    name = player.display_name
    if name in data["members"]: return await interaction.followup.send(f"❌ **{name}** already in fund.", ephemeral=True)
    data["members"][name] = False
    save_data(data)
    await update_all_panels()
    await interaction.followup.send(f"✅ Added **{name}**.", ephemeral=True)

@bot.tree.command(name="fund_remove", description="Remove a player from the gang fund")
@app_commands.describe(player="Player name")
@app_commands.autocomplete(player=player_autocomplete)
async def fund_remove(interaction: discord.Interaction, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if player not in data["members"]: return await interaction.followup.send(f"❌ **{player}** not in fund.", ephemeral=True)
    del data["members"][player]
    save_data(data)
    await update_all_panels()
    await interaction.followup.send(f"🗑️ Removed **{player}**.", ephemeral=True)

@bot.tree.command(name="fund_paid", description="Mark a player as paid")
@app_commands.describe(player="Player name")
@app_commands.autocomplete(player=player_autocomplete)
async def fund_paid(interaction: discord.Interaction, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if player not in data["members"]: return await interaction.followup.send(f"❌ **{player}** not in fund.", ephemeral=True)
    data["members"][player] = True
    save_data(data)
    await update_all_panels()
    await interaction.followup.send(f"✅ **{player}** has paid.", ephemeral=True)

@bot.tree.command(name="fund_unpaid", description="Mark a player as unpaid")
@app_commands.describe(player="Player name")
@app_commands.autocomplete(player=player_autocomplete)
async def fund_unpaid(interaction: discord.Interaction, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if player not in data["members"]: return await interaction.followup.send(f"❌ **{player}** not in fund.", ephemeral=True)
    data["members"][player] = False
    save_data(data)
    await update_all_panels()
    await interaction.followup.send(f"❌ **{player}** now unpaid.", ephemeral=True)

@bot.tree.command(name="fund_amount", description="Set the required gang fund amount")
@app_commands.describe(amount="Amount required from each player")
async def fund_amount(interaction: discord.Interaction, amount: int):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if amount < 0: return await interaction.followup.send("❌ Amount cannot be negative.", ephemeral=True)
    data["amount"] = amount
    save_data(data)
    await update_all_panels()
    await interaction.followup.send(f"💰 Gang fund amount set to **${amount:,}** per player.", ephemeral=True)

@bot.tree.command(name="fund_message", description="Set or clear a custom note in the fund embed")
@app_commands.describe(text="The note (leave empty to clear)")
async def fund_message(interaction: discord.Interaction, text: str = ""):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    data["message"] = text.strip()
    save_data(data)
    await update_all_panels()
    msg = f"📝 Fund message updated to:\n> {data['message']}" if data["message"] else "🧹 Fund message cleared."
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="fund_list", description="Show the gang fund list")
async def fund_list(interaction: discord.Interaction):
    await interaction.response.defer()
    embed = create_fund_embed()
    message = await interaction.followup.send(embed=embed, view=FundView(), wait=True)
    await register_panel(message)

@bot.tree.command(name="fund_reset", description="Mark all players as unpaid")
async def fund_reset(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    for p in data["members"]:
        data["members"][p] = False
    save_data(data)
    await update_all_panels()
    await interaction.followup.send("🔄 All players reset to **UNPAID**.", ephemeral=True)

@bot.tree.command(name="fund_reset_list", description="Permanently remove ALL players")
async def fund_reset_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if not data["members"]: return await interaction.followup.send("❌ List already empty.", ephemeral=True)
    class Confirm(discord.ui.View):
        def __init__(self, owner):
            super().__init__(timeout=30)
            self.owner = owner
            self.confirmed = False
        async def interaction_check(self, inter): return inter.user.id == self.owner
        @discord.ui.button(label="Yes, clear", style=discord.ButtonStyle.danger)
        async def yes(self, inter: discord.Interaction, _):
            self.confirmed = True; self.stop()
            await inter.response.edit_message(content="🗑️ Clearing...", view=None)
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def no(self, inter: discord.Interaction, _):
            self.stop()
            await inter.response.edit_message(content="❌ Cancelled.", view=None)
    view = Confirm(interaction.user.id)
    await interaction.followup.send(f"⚠️ Remove all **{len(data['members'])}** players? Cannot be undone.", view=view, ephemeral=True)
    await view.wait()
    if view.confirmed:
        data["members"] = {}
        save_data(data)
        await update_all_panels()
        await interaction.followup.send("✅ Player list cleared.", ephemeral=True)

@bot.tree.command(name="fund_backup_status", description="Check backup status")
async def fund_backup_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    channel = await get_backup_channel()
    embed = discord.Embed(title="🗄️ Backup Status", color=discord.Color.green() if channel else discord.Color.red())
    if channel:
        embed.add_field(name="Backup Channel", value=channel.mention, inline=False)
        embed.add_field(name="Info", value="All backups are kept permanently. Each data change creates a new message.", inline=False)
    else:
        embed.add_field(name="Backup Channel", value="❌ Not available.", inline=False)
    if _last_backup_time:
        status = "✅ Success" if _last_backup_ok else f"❌ Failed — {_last_backup_error}"
        embed.add_field(name="Last Backup", value=f"{status}\n<t:{int(_last_backup_time.timestamp())}:R>", inline=False)
    embed.add_field(name="Local data.json", value="Exists" if os.path.exists(DATA_FILE) else "Missing", inline=True)
    embed.add_field(name="Players", value=str(len(data["members"])), inline=True)
    embed.add_field(name="Tasks", value=str(len(data["tasks"])), inline=True)
    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="fund_backup_now", description="Force an immediate backup")
async def fund_backup_now(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    await push_backup()
    if _last_backup_ok:
        await interaction.followup.send("✅ Backup saved.", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Backup failed: {_last_backup_error}", ephemeral=True)

@bot.tree.command(name="fund_import", description="Import gang fund data from a backup JSON file")
@app_commands.describe(backup_file="The backup .json file")
async def fund_import(interaction: discord.Interaction, backup_file: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if not backup_file.filename.endswith(".json"): return await interaction.followup.send("❌ Please upload a .json file.", ephemeral=True)
    try:
        raw = await backup_file.read()
        imported = json.loads(raw.decode("utf-8"))
    except Exception as e: return await interaction.followup.send(f"❌ Failed to read JSON: {e}", ephemeral=True)
    if "members" not in imported or "amount" not in imported: return await interaction.followup.send("❌ Invalid backup (missing members/amount).", ephemeral=True)
    for key, default in default_data().items():
        if key not in imported: imported[key] = default
    global data
    data = imported
    save_data(data)
    await update_all_panels(); await update_all_treasury_panels(); await update_all_task_panels()
    await push_backup()
    await interaction.followup.send(f"✅ Backup imported. {len(data['members'])} players, {len(data['tasks'])} tasks loaded. New backup saved.", ephemeral=True)

@bot.tree.command(name="fund_panel", description="Create a gang fund tracking panel")
async def fund_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    embed = create_fund_embed()
    message = await interaction.channel.send(embed=embed, view=FundView())
    await register_panel(message)
    await interaction.followup.send("✅ Gang fund panel created!", ephemeral=True)

@bot.tree.command(name="fund_treasury", description="Create a gang treasury panel")
async def fund_treasury(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    embed = create_treasury_embed()
    message = await interaction.channel.send(embed=embed, view=TreasuryView())
    await register_treasury_panel(message)
    await interaction.followup.send("✅ Treasury panel created!", ephemeral=True)

@bot.tree.command(name="fund_deposit", description="Deposit money into the gang treasury")
@app_commands.describe(amount="Amount to deposit", reason="Reason")
async def fund_deposit(interaction: discord.Interaction, amount: int, reason: str = ""):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if amount <= 0: return await interaction.followup.send("❌ Amount must be > 0.", ephemeral=True)
    entry = await record_transaction("deposit", amount, reason, interaction.user)
    await interaction.followup.send(f"🟢 Deposited **${amount:,}**. New balance: **${entry['balance_after']:,}**.", ephemeral=True)

@bot.tree.command(name="fund_withdraw", description="Withdraw money from the gang treasury")
@app_commands.describe(amount="Amount to withdraw", reason="Reason")
async def fund_withdraw(interaction: discord.Interaction, amount: int, reason: str = ""):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if amount <= 0: return await interaction.followup.send("❌ Amount must be > 0.", ephemeral=True)
    if amount > data.get("treasury_balance", 0): return await interaction.followup.send(f"❌ Insufficient funds. Balance: **${data['treasury_balance']:,}**.", ephemeral=True)
    entry = await record_transaction("withdraw", amount, reason, interaction.user)
    await interaction.followup.send(f"🔴 Withdrew **${amount:,}**. New balance: **${entry['balance_after']:,}**.", ephemeral=True)

@bot.tree.command(name="fund_transcript", description="View the full gang treasury transaction history")
async def fund_transcript(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    TRANSCRIPT_PAGE_SIZE = 10
    total = len(data["transactions"])
    total_pages = max(1, (total + TRANSCRIPT_PAGE_SIZE - 1) // TRANSCRIPT_PAGE_SIZE)
    def make_page(p):
        embed = discord.Embed(title="🧾 Gang Treasury Transcript", description=f"Balance: **${data.get('treasury_balance',0):,}** • {total} transaction(s)", color=discord.Color.blurple())
        ordered = list(reversed(data["transactions"]))
        page_items = ordered[p*TRANSCRIPT_PAGE_SIZE:(p+1)*TRANSCRIPT_PAGE_SIZE]
        for entry in page_items:
            ts = entry.get("timestamp")
            time_text = f"<t:{int(datetime.datetime.fromisoformat(ts).timestamp())}:f>" if ts else "Unknown"
            embed.add_field(name=f"{TRANSACTION_TYPE_LABELS.get(entry['type'],entry['type'])} — ${entry['amount']:,}",
                            value=f"By **{entry.get('user_name','Unknown')}** • {time_text}\nReason: {entry.get('reason') or 'None'}\nBalance after: ${entry.get('balance_after',0):,}", inline=False)
        embed.set_footer(text=f"Page {p+1} of {total_pages}")
        return embed
    class TranscriptPaginator(discord.ui.View):
        def __init__(self, owner):
            super().__init__(timeout=180)
            self.owner = owner
            self.page = 0
        async def interaction_check(self, inter): return inter.user.id == self.owner
        @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
        async def prev(self, inter: discord.Interaction, _):
            self.page -= 1
            await inter.response.edit_message(embed=make_page(self.page), view=self)
        @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
        async def next(self, inter: discord.Interaction, _):
            self.page += 1
            await inter.response.edit_message(embed=make_page(self.page), view=self)
    view = TranscriptPaginator(interaction.user.id)
    embed = make_page(0)
    if total_pages <= 1:
        view.prev.disabled = view.next.disabled = True
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


# ============================================================
# TASK COMMANDS (unchanged - slash commands still work)
# ============================================================

async def task_autocomplete(interaction: discord.Interaction, current: str):
    tasks = data.get("tasks", [])
    matches = [t for t in tasks if current.lower() in t.get("name","").lower() or current.lower() in t["id"][:6]]
    return [app_commands.Choice(name=f"{t['name'][:80]} (ID:{t['id'][:6]})", value=t["id"]) for t in matches[:25]]

@bot.tree.command(name="task_create", description="Create a new gang task")
@app_commands.describe(name="Task name", description="Task details", reward="Reward per player completion (0 for none)")
async def task_create(interaction: discord.Interaction, name: str, description: str = "", reward: int = 0):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if reward < 0: return await interaction.followup.send("❌ Reward cannot be negative.", ephemeral=True)
    task = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "description": description.strip(),
        "reward": reward,
        "created_by": str(interaction.user.display_name),
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "participants": {}
    }
    data["tasks"].append(task)
    save_data(data)
    await update_all_task_panels()
    msg = f"✅ Task '{name}' created (ID: {task['id'][:6]})."
    if reward: msg += f" Reward per player: ${reward:,}."
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="task_add_player", description="Add a player to a task")
@app_commands.describe(task_id="Task ID", player="Player name")
@app_commands.autocomplete(task_id=task_autocomplete)
async def task_add_player(interaction: discord.Interaction, task_id: str, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    if player not in data["members"]: return await interaction.followup.send("❌ Player not in gang fund.", ephemeral=True)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task: return await interaction.followup.send("❌ Task not found.", ephemeral=True)
    if player in task["participants"]: return await interaction.followup.send(f"❌ {player} is already a participant.", ephemeral=True)
    task["participants"][player] = False
    save_data(data)
    await update_all_task_panels()
    await interaction.followup.send(f"✅ Added **{player}** to task '{task['name']}'.", ephemeral=True)

@bot.tree.command(name="task_remove_player", description="Remove a player from a task")
@app_commands.describe(task_id="Task ID", player="Player name")
@app_commands.autocomplete(task_id=task_autocomplete)
async def task_remove_player(interaction: discord.Interaction, task_id: str, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task: return await interaction.followup.send("❌ Task not found.", ephemeral=True)
    if player not in task["participants"]: return await interaction.followup.send(f"❌ {player} is not a participant.", ephemeral=True)
    del task["participants"][player]
    save_data(data)
    await update_all_task_panels()
    await interaction.followup.send(f"🗑️ Removed **{player}** from task '{task['name']}'.", ephemeral=True)

@bot.tree.command(name="task_mark_complete", description="Mark a player as having completed a task")
@app_commands.describe(task_id="Task ID", player="Player name")
@app_commands.autocomplete(task_id=task_autocomplete)
async def task_mark_complete(interaction: discord.Interaction, task_id: str, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task: return await interaction.followup.send("❌ Task not found.", ephemeral=True)
    if player not in task["participants"]: return await interaction.followup.send("❌ Player not a participant.", ephemeral=True)
    if task["participants"][player]: return await interaction.followup.send("❌ Already completed.", ephemeral=True)
    reward = task.get("reward", 0)
    if reward > data["treasury_balance"]:
        return await interaction.followup.send(f"❌ Insufficient funds for reward ${reward:,}. Balance: ${data['treasury_balance']:,}.", ephemeral=True)
    if reward > 0:
        await record_transaction("withdraw", reward, f"Task completion: {task['name']} - {player}", interaction.user)
    task["participants"][player] = True
    save_data(data)
    await update_all_task_panels()
    msg = f"✅ Marked **{player}** complete on task '{task['name']}'."
    if reward: msg += f" Paid ${reward:,} reward."
    await interaction.followup.send(msg, ephemeral=True)

@bot.tree.command(name="task_mark_incomplete", description="Unmark a player as completed on a task")
@app_commands.describe(task_id="Task ID", player="Player name")
@app_commands.autocomplete(task_id=task_autocomplete)
async def task_mark_incomplete(interaction: discord.Interaction, task_id: str, player: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task: return await interaction.followup.send("❌ Task not found.", ephemeral=True)
    if player not in task["participants"]: return await interaction.followup.send("❌ Player not a participant.", ephemeral=True)
    if not task["participants"][player]: return await interaction.followup.send("❌ Already incomplete.", ephemeral=True)
    task["participants"][player] = False
    save_data(data)
    await update_all_task_panels()
    await interaction.followup.send(f"❌ Marked **{player}** incomplete on task '{task['name']}'.", ephemeral=True)

@bot.tree.command(name="task_delete", description="Delete a task")
@app_commands.describe(task_id="Task ID")
@app_commands.autocomplete(task_id=task_autocomplete)
async def task_delete(interaction: discord.Interaction, task_id: str):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    task = next((t for t in data["tasks"] if t["id"] == task_id), None)
    if not task: return await interaction.followup.send("❌ Task not found.", ephemeral=True)
    data["tasks"].remove(task)
    save_data(data)
    await update_all_task_panels()
    await interaction.followup.send(f"🗑️ Deleted task '{task['name']}'.", ephemeral=True)

@bot.tree.command(name="task_list", description="List all gang tasks (paginated)")
async def task_list(interaction: discord.Interaction, page: int = 1):
    await interaction.response.defer(ephemeral=True)
    embed, _, total_pages = create_task_embed(page-1)
    view = discord.ui.View(timeout=180)
    if total_pages > 1:
        async def prev_callback(inter):
            nonlocal page
            page -= 1
            embed, _, _ = create_task_embed(page-1)
            await inter.response.edit_message(embed=embed, view=view)
        async def next_callback(inter):
            nonlocal page
            page += 1
            embed, _, _ = create_task_embed(page-1)
            await inter.response.edit_message(embed=embed, view=view)
        prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary)
        prev_btn.callback = prev_callback
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
        next_btn.callback = next_callback
        if page <= 1: prev_btn.disabled = True
        if page >= total_pages: next_btn.disabled = True
        view.add_item(prev_btn)
        view.add_item(next_btn)
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="task_panel", description="Create a persistent task management panel")
async def task_panel(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    if not is_admin(interaction): return await interaction.followup.send("❌ No permission.", ephemeral=True)
    embed, _, _ = create_task_embed()
    message = await interaction.channel.send(embed=embed, view=TaskPanelView())
    await register_task_panel(message)
    await interaction.followup.send("✅ Task panel created!", ephemeral=True)


# ============================================================
# EMBED BUILDER (unchanged)
# ============================================================

def is_embed_empty(embed: discord.Embed) -> bool:
    has_author = bool(embed.author and embed.author.name)
    has_image = bool(embed.image and embed.image.url)
    has_thumbnail = bool(embed.thumbnail and embed.thumbnail.url)
    return not (embed.title or embed.description or embed.fields or has_author or has_image or has_thumbnail)

def preview_embeds(embeds: list) -> list:
    result = []
    for embed in embeds:
        if is_embed_empty(embed):
            placeholder = embed.copy()
            placeholder.description = "*(empty — use the buttons below to add content)*"
            result.append(placeholder)
        else:
            result.append(embed)
    return result

def safe_color(text: str) -> discord.Color:
    text = text.strip().lstrip("#")
    if not text:
        return discord.Color.blurple()
    try:
        return discord.Color(int(text, 16))
    except ValueError:
        return discord.Color.blurple()

class BodyModal(discord.ui.Modal, title="Title & Description"):
    def __init__(self, builder_view):
        super().__init__()
        self.builder_view = builder_view
        embed = builder_view.current_embed()
        self.title_input = discord.ui.TextInput(label="Title", required=False, max_length=256, default=embed.title or "")
        self.description_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False, max_length=4000, default=embed.description or "")
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
        self.color_input = discord.ui.TextInput(label="Hex color (e.g. 2ecc71)", required=False, max_length=7)
        self.add_item(self.color_input)
    async def on_submit(self, interaction: discord.Interaction):
        embed = self.builder_view.current_embed()
        embed.color = safe_color(self.color_input.value)
        await self.builder_view.refresh(interaction)

class AuthorModal(discord.ui.Modal, title="Author"):
    def __init__(self, builder_view):
        super().__init__()
        self.builder_view = builder_view
        embed = builder_view.current_embed()
        current_author = embed.author
        self.name_input = discord.ui.TextInput(label="Author name", required=False, max_length=256,
                                               default=current_author.name or "" if current_author else "")
        self.icon_input = discord.ui.TextInput(label="Author icon URL", required=False,
                                                default=current_author.icon_url or "" if current_author else "")
        self.url_input = discord.ui.TextInput(label="Author link URL", required=False,
                                              default=current_author.url or "" if current_author else "")
        self.add_item(self.name_input)
        self.add_item(self.icon_input)
        self.add_item(self.url_input)
    async def on_submit(self, interaction: discord.Interaction):
        embed = self.builder_view.current_embed()
        if self.name_input.value:
            embed.set_author(name=self.name_input.value, icon_url=self.icon_input.value or None, url=self.url_input.value or None)
        else:
            embed.remove_author()
        await self.builder_view.refresh(interaction)

class FooterModal(discord.ui.Modal, title="Footer"):
    def __init__(self, builder_view):
        super().__init__()
        self.builder_view = builder_view
        embed = builder_view.current_embed()
        self.text_input = discord.ui.TextInput(label="Footer text", required=False, max_length=2048,
                                               default=embed.footer.text or "" if embed.footer else "")
        self.icon_input = discord.ui.TextInput(label="Footer icon URL", required=False,
                                               default=embed.footer.icon_url or "" if embed.footer else "")
        self.add_item(self.text_input)
        self.add_item(self.icon_input)
    async def on_submit(self, interaction: discord.Interaction):
        embed = self.builder_view.current_embed()
        if self.text_input.value:
            embed.set_footer(text=self.text_input.value, icon_url=self.icon_input.value or None)
        else:
            embed.remove_footer()
        await self.builder_view.refresh(interaction)

class ImagesModal(discord.ui.Modal, title="Images"):
    def __init__(self, builder_view):
        super().__init__()
        self.builder_view = builder_view
        embed = builder_view.current_embed()
        self.image_input = discord.ui.TextInput(label="Large image URL", required=False,
                                                default=embed.image.url or "" if embed.image else "")
        self.thumbnail_input = discord.ui.TextInput(label="Thumbnail URL (small, top-right)", required=False,
                                                    default=embed.thumbnail.url or "" if embed.thumbnail else "")
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
        self.name_input = discord.ui.TextInput(label="Field name", required=True, max_length=256)
        self.value_input = discord.ui.TextInput(label="Field value", style=discord.TextStyle.paragraph, required=True, max_length=1024)
        self.inline_input = discord.ui.TextInput(label="Inline? (yes/no)", required=False, default="yes", max_length=3)
        self.add_item(self.name_input)
        self.add_item(self.value_input)
        self.add_item(self.inline_input)
    async def on_submit(self, interaction: discord.Interaction):
        embed = self.builder_view.current_embed()
        if len(embed.fields) >= 25:
            await interaction.response.send_message("❌ This embed already has the max of 25 fields.", ephemeral=True)
            return
        inline = self.inline_input.value.strip().lower() not in ("no", "false", "n", "0")
        embed.add_field(name=self.name_input.value, value=self.value_input.value, inline=inline)
        await self.builder_view.refresh(interaction)

class EmbedSwitchSelect(discord.ui.Select):
    def __init__(self, builder_view):
        self.builder_view = builder_view
        options = [discord.SelectOption(label=f"Embed {i+1}", value=str(i), default=(i == builder_view.active_index))
                   for i in range(len(builder_view.embeds))]
        super().__init__(placeholder="Choose which embed to edit...", options=options, row=2)
    async def callback(self, interaction: discord.Interaction):
        self.builder_view.active_index = int(self.values[0])
        await self.builder_view.refresh(interaction)

class SendChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, builder_view):
        self.builder_view = builder_view
        super().__init__(placeholder="Choose a channel to send to...", channel_types=[discord.ChannelType.text], min_values=1, max_values=1)
    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        try:
            await channel.send(embeds=self.builder_view.embeds)
        except discord.HTTPException as e:
            await interaction.response.edit_message(content=f"❌ Failed to send: {e}", embeds=[], view=None)
            return
        await interaction.response.edit_message(content=f"✅ Sent to {channel.mention}.", embeds=[], view=None)

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
            await interaction.response.send_message("❌ This isn't your embed builder.", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction: discord.Interaction):
        self.build_items()
        await interaction.response.edit_message(
            content=f"**Editing embed {self.active_index+1} of {len(self.embeds)}.** Use the buttons below, then hit Send.",
            embeds=preview_embeds(self.embeds),
            view=self
        )

    def build_items(self):
        self.clear_items()
        def make_button(label, callback, row, style=discord.ButtonStyle.primary, disabled=False, emoji=None):
            button = discord.ui.Button(label=label, style=style, row=row, disabled=disabled, emoji=emoji)
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
        make_button("Remove Last Field", self.remove_last_field, 1, style=discord.ButtonStyle.secondary, disabled=len(self.current_embed().fields) == 0)
        make_button("Add Embed", self.add_embed, 1, style=discord.ButtonStyle.secondary)
        make_button("Remove Embed", self.remove_embed, 1, style=discord.ButtonStyle.secondary, disabled=len(self.embeds) <= 1)

        if len(self.embeds) > 1:
            self.add_item(EmbedSwitchSelect(self))

        make_button("Send", self.open_send, 3, style=discord.ButtonStyle.success)
        make_button("Cancel", self.cancel, 3, style=discord.ButtonStyle.danger)

    async def open_body(self, interaction): await interaction.response.send_modal(BodyModal(self))
    async def open_author(self, interaction): await interaction.response.send_modal(AuthorModal(self))
    async def open_footer(self, interaction): await interaction.response.send_modal(FooterModal(self))
    async def open_images(self, interaction): await interaction.response.send_modal(ImagesModal(self))
    async def open_color(self, interaction): await interaction.response.send_modal(ColorModal(self))
    async def open_add_field(self, interaction): await interaction.response.send_modal(AddFieldModal(self))

    async def remove_last_field(self, interaction: discord.Interaction):
        embed = self.current_embed()
        if embed.fields:
            embed.remove_field(len(embed.fields) - 1)
        await self.refresh(interaction)

    async def add_embed(self, interaction: discord.Interaction):
        if len(self.embeds) >= 10:
            await interaction.response.send_message("❌ Discord allows a max of 10 embeds per message.", ephemeral=True)
            return
        self.embeds.append(discord.Embed(color=discord.Color.blurple()))
        self.active_index = len(self.embeds) - 1
        await self.refresh(interaction)

    async def remove_embed(self, interaction: discord.Interaction):
        if len(self.embeds) <= 1:
            await interaction.response.send_message("❌ You must keep at least one embed.", ephemeral=True)
            return
        del self.embeds[self.active_index]
        self.active_index = max(0, self.active_index - 1)
        await self.refresh(interaction)

    async def open_send(self, interaction: discord.Interaction):
        empty_numbers = [str(i+1) for i, embed in enumerate(self.embeds) if is_embed_empty(embed)]
        if empty_numbers:
            await interaction.response.send_message(
                f"❌ Embed {', '.join(empty_numbers)} has no content yet. Add a title, description, field, author, or image before sending.",
                ephemeral=True
            )
            return
        view = discord.ui.View(timeout=120)
        view.add_item(SendChannelSelect(self))
        await interaction.response.send_message("Choose a channel to send this to:", view=view, ephemeral=True)

    async def cancel(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="❌ Embed builder cancelled.", embeds=[], view=None)


embed_group = app_commands.Group(name="embed", description="Build and send custom embeds")

@embed_group.command(name="create", description="Open an interactive embed builder to design and send a custom embed")
async def embed_create(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    view = EmbedBuilderView(owner_id=interaction.user.id)
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
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    bot.run(TOKEN)
