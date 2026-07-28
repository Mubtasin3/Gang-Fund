import discord
from discord.ext import commands
from discord import app_commands
import json
import os

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID"))


# =========================
# LOAD DATA
# =========================

DATA_FILE = "data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "amount": 0,
            "members": {}
        }

    with open(DATA_FILE, "r") as file:
        return json.load(file)


def save_data(data):
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=4)


data = load_data()


# =========================
# BOT SETUP
# =========================

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)


# =========================
# ADMIN CHECK
# =========================

def is_admin(interaction: discord.Interaction):

    if interaction.user.guild_permissions.administrator:
        return True

    role = interaction.guild.get_role(ADMIN_ROLE_ID)

    if role and role in interaction.user.roles:
        return True

    return False


# =========================
# BOT READY
# =========================

@bot.event
async def on_ready():

    print(f"Logged in as {bot.user}")

    try:

        guild = discord.Object(id=GUILD_ID)

        bot.tree.copy_global_to(guild=guild)

        await bot.tree.sync(guild=guild)

        print("Slash commands synced successfully!")

    except Exception as e:

        print(f"Command sync error: {e}")


# =========================
# FUND EMBED
# =========================

def create_fund_embed():

    amount = data["amount"]
    members = data["members"]

    total_members = len(members)

    paid_members = 0

    for status in members.values():

        if status:
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

    if members:

        member_list = []

        for name, paid in members.items():

            if paid:
                member_list.append(f"✅ **{name}** — Paid")

            else:
                member_list.append(f"❌ **{name}** — Unpaid")

        embed.add_field(
            name="📋 Member List",
            value="\n".join(member_list),
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


# =========================
# BUTTON VIEW
# =========================

class FundView(discord.ui.View):

    def __init__(self):

        super().__init__(
            timeout=None
        )


    @discord.ui.button(
        label="Mark Paid",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="fund_mark_paid"
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
                    label=name,
                    value=name
                )
            )


        if len(options) > 25:

            await interaction.response.send_message(
                "❌ You have more than 25 members. Use `/fund paid` instead.",
                ephemeral=True
            )

            return


        select = PaidSelect(options)

        view = discord.ui.View()

        view.add_item(select)

        await interaction.response.send_message(
            "Select the player who paid:",
            view=view,
            ephemeral=True
        )


    @discord.ui.button(
        label="Mark Unpaid",
        style=discord.ButtonStyle.danger,
        emoji="❌",
        custom_id="fund_mark_unpaid"
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
                    label=name,
                    value=name
                )
            )


        if len(options) > 25:

            await interaction.response.send_message(
                "❌ You have more than 25 members. Use `/fund unpaid` instead.",
                ephemeral=True
            )

            return


        select = UnpaidSelect(options)

        view = discord.ui.View()

        view.add_item(select)

        await interaction.response.send_message(
            "Select the player who has not paid:",
            view=view,
            ephemeral=True
        )


# =========================
# PAID SELECT
# =========================

class PaidSelect(discord.ui.Select):

    def __init__(self, options):

        super().__init__(
            placeholder="Choose a player...",
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
            content=f"✅ **{player}** has been marked as PAID.",
            view=None
        )


# =========================
# UNPAID SELECT
# =========================

class UnpaidSelect(discord.ui.Select):

    def __init__(self, options):

        super().__init__(
            placeholder="Choose a player...",
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
            content=f"❌ **{player}** has been marked as UNPAID.",
            view=None
        )


# =========================
# /FUND ADD
# =========================

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

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    if player in data["members"]:

        await interaction.response.send_message(
            f"❌ **{player}** is already in the fund.",
            ephemeral=True
        )

        return


    data["members"][player] = False

    save_data(data)

    await interaction.response.send_message(
        f"✅ Added **{player}** to the gang fund."
    )


# =========================
# /FUND REMOVE
# =========================

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

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    if player not in data["members"]:

        await interaction.response.send_message(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return


    del data["members"][player]

    save_data(data)

    await interaction.response.send_message(
        f"🗑️ Removed **{player}** from the gang fund."
    )


# =========================
# /FUND PAID
# =========================

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

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    if player not in data["members"]:

        await interaction.response.send_message(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return


    data["members"][player] = True

    save_data(data)

    await interaction.response.send_message(
        f"✅ **{player}** has paid the gang fund."
    )


# =========================
# /FUND UNPAID
# =========================

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

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    if player not in data["members"]:

        await interaction.response.send_message(
            f"❌ **{player}** is not in the fund.",
            ephemeral=True
        )

        return


    data["members"][player] = False

    save_data(data)

    await interaction.response.send_message(
        f"❌ **{player}** is now marked as unpaid."
    )


# =========================
# /FUND AMOUNT
# =========================

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

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    if amount < 0:

        await interaction.response.send_message(
            "❌ Amount cannot be negative.",
            ephemeral=True
        )

        return


    data["amount"] = amount

    save_data(data)

    await interaction.response.send_message(
        f"💰 Gang fund amount set to **${amount:,}** per player."
    )


# =========================
# /FUND LIST
# =========================

@bot.tree.command(
    name="fund_list",
    description="Show the gang fund list"
)
async def fund_list(
    interaction: discord.Interaction
):

    embed = create_fund_embed()

    await interaction.response.send_message(
        embed=embed,
        view=FundView()
    )


# =========================
# /FUND RESET
# =========================

@bot.tree.command(
    name="fund_reset",
    description="Reset all players to unpaid"
)
async def fund_reset(
    interaction: discord.Interaction
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    for player in data["members"]:

        data["members"][player] = False


    save_data(data)

    await interaction.response.send_message(
        "🔄 All players have been reset to UNPAID."
    )


# =========================
# /FUND PANEL
# =========================

@bot.tree.command(
    name="fund_panel",
    description="Create the gang fund tracking panel"
)
async def fund_panel(
    interaction: discord.Interaction
):

    if not is_admin(interaction):

        await interaction.response.send_message(
            "❌ You don't have permission.",
            ephemeral=True
        )

        return


    embed = create_fund_embed()

    await interaction.channel.send(
        embed=embed,
        view=FundView()
    )

    await interaction.response.send_message(
        "✅ Gang fund panel created!",
        ephemeral=True
    )


# =========================
# RUN BOT
# =========================

bot.run(TOKEN)
