import discord
from discord.ext import commands
from discord import app_commands
import json
import os


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
# DATA FILE
# ============================================================

DATA_FILE = "data.json"


def default_data():
    return {
        "amount": 0,
        "members": {}
    }


def load_data():

    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data

    try:

        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if "amount" not in data:
            data["amount"] = 0

        if "members" not in data:
            data["members"] = {}

        return data

    except Exception as e:

        print(f"Error loading data.json: {e}")

        return default_data()


def save_data(data):

    try:

        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )

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

    # Discord Administrator permission
    if interaction.user.guild_permissions.administrator:
        return True

    # Admin role
    role = interaction.guild.get_role(ADMIN_ROLE_ID)

    if role and role in interaction.user.roles:
        return True

    return False


# ============================================================
# CREATE FUND EMBED
# ============================================================

def create_fund_embed():

    amount = data.get("amount", 0)

    members = data.get("members", {})

    total_members = len(members)

    paid_members = 0

    for paid in members.values():

        if paid is True:
            paid_members += 1

    unpaid_members = total_members - paid_members

    collected = paid_members * amount

    required = total_members * amount

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

        # Discord embed fields have a 1024 character limit.
        # Split the list into multiple fields if necessary.

        chunks = []

        current_chunk = ""

        for line in member_list:

            if len(current_chunk) + len(line) + 1 > 1000:

                chunks.append(current_chunk)

                current_chunk = line

            else:

                if current_chunk:

                    current_chunk += "\n"

                current_chunk += line

        if current_chunk:

            chunks.append(current_chunk)

        for index, chunk in enumerate(chunks):

            if index == 0:

                field_name = "📋 Member List"

            else:

                field_name = "📋 Member List (Continued)"

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

    embed.set_footer(
        text="Use the buttons below to update payments."
    )

    return embed


# ============================================================
# UPDATE FUND PANEL
# ============================================================

async def update_fund_message(interaction):

    try:

        message = interaction.message

        if message is None:
            return

        await message.edit(
            embed=create_fund_embed(),
            view=FundView()
        )

    except discord.NotFound:

        print("Could not update fund panel: message was deleted.")

    except discord.HTTPException as e:

        print(f"Could not update fund panel: {e}")


# ============================================================
# PAID PLAYER SELECT
# ============================================================

class PaidSelect(discord.ui.Select):

    def __init__(self, options):

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
            content=f"✅ **{player}** has been marked as **PAID**.",
            view=None
        )


# ============================================================
# UNPAID PLAYER SELECT
# ============================================================

class UnpaidSelect(discord.ui.Select):

    def __init__(self, options):

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
            content=f"❌ **{player}** has been marked as **UNPAID**.",
            view=None
        )


# ============================================================
# FUND BUTTON VIEW
# ============================================================

class FundView(discord.ui.View):

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

        select = PaidSelect(options)

        view = discord.ui.View(
            timeout=60
        )

        view.add_item(select)

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

        select = UnpaidSelect(options)

        view = discord.ui.View(
            timeout=60
        )

        view.add_item(select)

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

    print(f"Logged in as: {bot.user}")

    print(f"Bot ID: {bot.user.id}")

    print("----------------------------------------")

    # Register persistent buttons.
    # This allows the buttons on an old panel
    # to continue working after a bot restart.

    bot.add_view(FundView())

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
            f"Successfully synced {len(synced)} slash commands."
        )

    except Exception as e:

        print(
            f"ERROR syncing slash commands: {e}"
        )


# ============================================================
# /FUND_ADD
# ============================================================

@bot.tree.command(
    name="fund_add",
    description="Add a player to the gang fund"
)
@app_commands.describe(
    player="Player name"
)
async def fund_add(
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

    player = player.strip()

    if not player:

        await interaction.followup.send(
            "❌ Player name cannot be empty.",
            ephemeral=True
        )

        return

    if player in data["members"]:

        await interaction.followup.send(
            f"❌ **{player}** is already in the fund.",
            ephemeral=True
        )

        return

    data["members"][player] = False

    save_data(data)

    await interaction.followup.send(
        f"✅ Added **{player}** to the gang fund.",
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

    await interaction.followup.send(
        f"💰 Gang fund amount set to **${amount:,}** per player.",
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

    await interaction.followup.send(
        embed=embed,
        view=FundView()
    )


# ============================================================
# /FUND_RESET
# ============================================================

@bot.tree.command(
    name="fund_reset",
    description="Reset all players to unpaid"
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

    await interaction.followup.send(
        "🔄 All players have been reset to **UNPAID**.",
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

    await interaction.channel.send(
        embed=embed,
        view=FundView()
    )

    await interaction.followup.send(
        "✅ Gang fund panel created!",
        ephemeral=True
    )


# ============================================================
# RUN BOT
# ============================================================

try:

    bot.run(TOKEN)

except Exception as e:

    print("----------------------------------------")

    print("BOT FAILED TO START")

    print(f"Error: {e}")

    print("----------------------------------------")
