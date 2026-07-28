import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import re
import asyncio


# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
ADMIN_ROLE_ID = os.getenv("ADMIN_ROLE_ID")


if not TOKEN:
    raise ValueError(
        "TOKEN environment variable is missing!"
    )

if not GUILD_ID:
    raise ValueError(
        "GUILD_ID environment variable is missing!"
    )

if not ADMIN_ROLE_ID:
    raise ValueError(
        "ADMIN_ROLE_ID environment variable is missing!"
    )


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


def save_data():

    try:

        temp_file = DATA_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4,
                ensure_ascii=False
            )


        os.replace(
            temp_file,
            DATA_FILE
        )


    except Exception as e:

        print(
            f"[DATA ERROR] Could not save data: {e}"
        )


def load_data():

    if not os.path.exists(DATA_FILE):

        new_data = default_data()

        try:

            with open(
                DATA_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    new_data,
                    file,
                    indent=4
                )

        except Exception as e:

            print(
                f"[DATA ERROR] Could not create data.json: {e}"
            )

        return new_data


    try:

        with open(
            DATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            loaded = json.load(file)


        if not isinstance(
            loaded,
            dict
        ):

            return default_data()


        if "amount" not in loaded:

            loaded["amount"] = 0


        if "members" not in loaded:

            loaded["members"] = {}


        return loaded


    except Exception as e:

        print(
            f"[DATA ERROR] Could not load data.json: {e}"
        )

        return default_data()


data = load_data()


# ============================================================
# CONVERT OLD DATA TO DISCORD IDS
# ============================================================

def convert_old_member_ids():

    members = data.get(
        "members",
        {}
    )


    converted = {}

    changed = False


    for key, paid in members.items():

        key = str(
            key
        )


        # Already a normal Discord ID
        if key.isdigit():

            converted[key] = bool(
                paid
            )

            continue


        # Convert:
        # <@123456789>
        # <@!123456789>

        match = re.fullmatch(

            r"<@!?(\d+)>",

            key

        )


        if match:

            user_id = match.group(1)

            converted[user_id] = bool(
                paid
            )

            changed = True

        else:

            # Keep unknown old data
            converted[key] = bool(
                paid
            )


    if changed:

        data["members"] = converted

        save_data()

        print(
            "[DATA] Converted old Discord mentions to IDs."
        )


convert_old_member_ids()


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()

intents.members = True


class GangFundBot(
    commands.Bot
):


    def __init__(self):

        super().__init__(

            command_prefix="!",

            intents=intents

        )


        self.synced = False

        self.views_added = False


bot = GangFundBot()


# ============================================================
# SAFE INTERACTION HELPERS
# ============================================================

async def safe_defer(
    interaction: discord.Interaction,
    ephemeral=False
):

    try:

        if not interaction.response.is_done():

            await interaction.response.defer(

                ephemeral=ephemeral

            )

            return True


    except discord.NotFound:

        print(
            "[INTERACTION] Interaction expired "
            "before defer."
        )

        return False


    except discord.HTTPException as e:

        print(
            f"[INTERACTION] Defer failed: {e}"
        )

        return False


    return True


async def safe_followup(
    interaction: discord.Interaction,
    content=None,
    embed=None,
    view=None,
    ephemeral=False
):

    try:

        return await interaction.followup.send(

            content=content,

            embed=embed,

            view=view,

            ephemeral=ephemeral

        )


    except discord.NotFound:

        print(
            "[INTERACTION] Interaction expired "
            "before followup."
        )

        return None


    except discord.HTTPException as e:

        print(
            f"[INTERACTION] Followup failed: {e}"
        )

        return None


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(
    interaction: discord.Interaction
):

    if not interaction.guild:

        return False


    if interaction.user.guild_permissions.administrator:

        return True


    role = interaction.guild.get_role(

        ADMIN_ROLE_ID

    )


    if role and role in interaction.user.roles:

        return True


    return False


# ============================================================
# GET MEMBER
# ============================================================

async def get_member(
    guild: discord.Guild,
    user_id
):

    try:

        user_id = int(
            user_id
        )

    except:

        return None


    member = guild.get_member(

        user_id

    )


    if member:

        return member


    try:

        return await guild.fetch_member(

            user_id

        )

    except:

        return None


# ============================================================
# GET DISPLAY NAME
# ============================================================

async def get_display_name(
    guild: discord.Guild,
    user_id
):

    member = await get_member(

        guild,

        user_id

    )


    if member:

        return member.display_name


    return f"Unknown User ({user_id})"


# ============================================================
# CREATE PLAYER OPTIONS
# ============================================================

async def create_player_options(
    guild: discord.Guild
):

    options = []


    for user_id in data["members"]:

        member = await get_member(

            guild,

            user_id

        )


        if member:

            display_name = member.display_name

            description = (

                f"@{member.name}"

            )[:100]

        else:

            display_name = (

                f"Unknown User ({user_id})"

            )

            description = (

                "User is no longer "
                "in this server"

            )


        options.append(

            discord.SelectOption(

                label=display_name[:100],

                value=str(
                    user_id
                ),

                description=description[:100]

            )

        )


    return options


# ============================================================
# CREATE FUND EMBED
# ============================================================

async def create_fund_embed(
    guild: discord.Guild
):

    amount = int(

        data.get(
            "amount",
            0
        )

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

        description=(

            "Gang fund payment tracker\n\n"

            "Use the buttons below to "
            "mark members as paid or unpaid."

        ),

        color=discord.Color.green()

    )


    embed.add_field(

        name="💵 Fund Per Player",

        value=(

            f"${amount:,}"

        ),

        inline=True

    )


    embed.add_field(

        name="👥 Members",

        value=(

            str(
                total_members
            )

        ),

        inline=True

    )


    embed.add_field(

        name="💰 Collected",

        value=(

            f"${collected:,} / "
            f"${required:,}"

        ),

        inline=True

    )


    embed.add_field(

        name="✅ Paid",

        value=(

            str(
                paid_members
            )

        ),

        inline=True

    )


    embed.add_field(

        name="❌ Unpaid",

        value=(

            str(
                unpaid_members
            )

        ),

        inline=True

    )


    # ========================================================
    # MEMBER LIST
    # ========================================================

    if members:

        member_lines = []


        for user_id, paid in members.items():

            player_name = (

                await get_display_name(

                    guild,

                    user_id

                )

            )


            if paid is True:

                member_lines.append(

                    f"✅ **{player_name}** — Paid"

                )

            else:

                member_lines.append(

                    f"❌ **{player_name}** — Unpaid"

                )


        chunks = []

        current = ""


        for line in member_lines:

            if (

                len(current)
                + len(line)
                + 1

                > 1000

            ):

                chunks.append(

                    current

                )

                current = line

            else:

                if current:

                    current += "\n"

                current += line


        if current:

            chunks.append(

                current

            )


        for index, chunk in enumerate(

            chunks

        ):

            if index == 0:

                name = (

                    "📋 Member List"

                )

            else:

                name = (

                    "📋 Member List "
                    "(Continued)"

                )


            embed.add_field(

                name=name,

                value=chunk,

                inline=False

            )


    else:

        embed.add_field(

            name="📋 Member List",

            value=(

                "No members added yet."

            ),

            inline=False

        )


    embed.set_footer(

        text=(

            "Gang Fund System"

        )

    )


    return embed


# ============================================================
# UPDATE PANEL
# ============================================================

async def update_panel_from_interaction(
    interaction: discord.Interaction
):

    try:

        if not interaction.message:

            return


        embed = await create_fund_embed(

            interaction.guild

        )


        await interaction.message.edit(

            embed=embed,

            view=FundView()

        )


    except discord.NotFound:

        print(

            "[PANEL] Panel message no longer exists."

        )


    except discord.HTTPException as e:

        print(

            f"[PANEL] Could not update panel: {e}"

        )


# ============================================================
# PAID SELECT
# ============================================================

class PaidSelect(

    discord.ui.Select

):


    def __init__(

        self,

        options

    ):

        super().__init__(

            placeholder=(

                "Choose a player..."

            ),

            min_values=1,

            max_values=1,

            options=options

        )


    async def callback(

        self,

        interaction: discord.Interaction

    ):

        user_id = self.values[0]


        if user_id not in data["members"]:

            await safe_defer(

                interaction,

                ephemeral=True

            )


            await safe_followup(

                interaction,

                content=(

                    "❌ This player is no longer "
                    "in the gang fund."

                ),

                ephemeral=True

            )

            return


        data["members"][user_id] = True


        save_data()


        player_name = (

            await get_display_name(

                interaction.guild,

                user_id

            )

        )


        # Acknowledge dropdown immediately

        success = await safe_defer(

            interaction,

            ephemeral=True

        )


        if not success:

            return


        await safe_followup(

            interaction,

            content=(

                f"✅ **{player_name}** "
                "has been marked as **PAID**."

            ),

            ephemeral=True

        )


        # Update original panel

        await update_panel_from_interaction(

            interaction

        )


# ============================================================
# UNPAID SELECT
# ============================================================

class UnpaidSelect(

    discord.ui.Select

):


    def __init__(

        self,

        options

    ):

        super().__init__(

            placeholder=(

                "Choose a player..."

            ),

            min_values=1,

            max_values=1,

            options=options

        )


    async def callback(

        self,

        interaction: discord.Interaction

    ):

        user_id = self.values[0]


        if user_id not in data["members"]:

            await safe_defer(

                interaction,

                ephemeral=True

            )


            await safe_followup(

                interaction,

                content=(

                    "❌ This player is no longer "
                    "in the gang fund."

                ),

                ephemeral=True

            )

            return


        data["members"][user_id] = False


        save_data()


        player_name = (

            await get_display_name(

                interaction.guild,

                user_id

            )

        )


        success = await safe_defer(

            interaction,

            ephemeral=True

        )


        if not success:

            return


        await safe_followup(

            interaction,

            content=(

                f"❌ **{player_name}** "
                "has been marked as **UNPAID**."

            ),

            ephemeral=True

        )


        await update_panel_from_interaction(

            interaction

        )


# ============================================================
# FUND PANEL BUTTONS
# ============================================================

class FundView(

    discord.ui.View

):


    def __init__(self):

        super().__init__(

            timeout=None

        )


    # ========================================================
    # MARK PAID
    # ========================================================

    @discord.ui.button(

        label="Mark Paid",

        style=discord.ButtonStyle.success,

        emoji="✅",

        custom_id=(

            "gang_fund_mark_paid"

        )

    )
    async def mark_paid(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        # Acknowledge FIRST

        success = await safe_defer(

            interaction,

            ephemeral=True

        )


        if not success:

            return


        if not is_admin(

            interaction

        ):

            await safe_followup(

                interaction,

                content=(

                    "❌ You don't have permission "
                    "to manage the gang fund."

                ),

                ephemeral=True

            )

            return


        if not data["members"]:

            await safe_followup(

                interaction,

                content=(

                    "❌ No players have been "
                    "added yet."

                ),

                ephemeral=True

            )

            return


        options = (

            await create_player_options(

                interaction.guild

            )

        )


        if len(options) > 25:

            await safe_followup(

                interaction,

                content=(

                    "❌ There are more than "
                    "25 players.\n\n"
                    "Use `/fund_paid` instead."

                ),

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


        await safe_followup(

            interaction,

            content=(

                "Select the player who paid:"

            ),

            view=view,

            ephemeral=True

        )


    # ========================================================
    # MARK UNPAID
    # ========================================================

    @discord.ui.button(

        label="Mark Unpaid",

        style=discord.ButtonStyle.danger,

        emoji="❌",

        custom_id=(

            "gang_fund_mark_unpaid"

        )

    )
    async def mark_unpaid(

        self,

        interaction: discord.Interaction,

        button: discord.ui.Button

    ):

        success = await safe_defer(

            interaction,

            ephemeral=True

        )


        if not success:

            return


        if not is_admin(

            interaction

        ):

            await safe_followup(

                interaction,

                content=(

                    "❌ You don't have permission "
                    "to manage the gang fund."

                ),

                ephemeral=True

            )

            return


        if not data["members"]:

            await safe_followup(

                interaction,

                content=(

                    "❌ No players have been "
                    "added yet."

                ),

                ephemeral=True

            )

            return


        options = (

            await create_player_options(

                interaction.guild

            )

        )


        if len(options) > 25:

            await safe_followup(

                interaction,

                content=(

                    "❌ There are more than "
                    "25 players.\n\n"
                    "Use `/fund_unpaid` instead."

                ),

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


        await safe_followup(

            interaction,

            content=(

                "Select the player who is unpaid:"

            ),

            view=view,

            ephemeral=True

        )


# ============================================================
# BOT READY
# ============================================================

@bot.event
async def on_ready():

    print(
        "========================================"
    )

    print(
        f"Logged in as: {bot.user}"
    )

    print(
        f"Bot ID: {bot.user.id}"
    )

    print(
        "========================================"
    )


    # Add persistent buttons ONLY ONCE

    if not bot.views_added:

        bot.add_view(

            FundView()

        )

        bot.views_added = True


    # Sync commands ONLY ONCE

    if not bot.synced:

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


            bot.synced = True


            print(

                f"Successfully synced "
                f"{len(synced)} slash commands."

            )


        except Exception as e:

            print(

                f"[SYNC ERROR] {e}"

            )


    print(

        "Bot is ready!"

    )


# ============================================================
# /FUND_ADD
# ============================================================

@bot.tree.command(

    name="fund_add",

    description=(

        "Add a Discord member "
        "to the gang fund"

    )

)
@app_commands.describe(

    player=(

        "Select the Discord member"

    )

)
async def fund_add(

    interaction: discord.Interaction,

    player: discord.Member

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    user_id = str(

        player.id

    )


    if user_id in data["members"]:

        await safe_followup(

            interaction,

            content=(

                f"❌ **{player.display_name}** "
                "is already in the fund."

            ),

            ephemeral=True

        )

        return


    # SAVE ONLY DISCORD ID

    data["members"][user_id] = False


    save_data()


    await safe_followup(

        interaction,

        content=(

            f"✅ Added **{player.display_name}** "
            "to the gang fund."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_REMOVE
# ============================================================

@bot.tree.command(

    name="fund_remove",

    description=(

        "Remove a Discord member "
        "from the gang fund"

    )

)
@app_commands.describe(

    player=(

        "Select the Discord member"

    )

)
async def fund_remove(

    interaction: discord.Interaction,

    player: discord.Member

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    user_id = str(

        player.id

    )


    if user_id not in data["members"]:

        await safe_followup(

            interaction,

            content=(

                f"❌ **{player.display_name}** "
                "is not in the fund."

            ),

            ephemeral=True

        )

        return


    del data["members"][user_id]


    save_data()


    await safe_followup(

        interaction,

        content=(

            f"🗑️ Removed **{player.display_name}** "
            "from the gang fund."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_PAID
# ============================================================

@bot.tree.command(

    name="fund_paid",

    description=(

        "Mark a Discord member as paid"

    )

)
@app_commands.describe(

    player=(

        "Select the Discord member"

    )

)
async def fund_paid(

    interaction: discord.Interaction,

    player: discord.Member

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    user_id = str(

        player.id

    )


    if user_id not in data["members"]:

        await safe_followup(

            interaction,

            content=(

                f"❌ **{player.display_name}** "
                "is not in the fund."

            ),

            ephemeral=True

        )

        return


    data["members"][user_id] = True


    save_data()


    await safe_followup(

        interaction,

        content=(

            f"✅ **{player.display_name}** "
            "has been marked as paid."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_UNPAID
# ============================================================

@bot.tree.command(

    name="fund_unpaid",

    description=(

        "Mark a Discord member as unpaid"

    )

)
@app_commands.describe(

    player=(

        "Select the Discord member"

    )

)
async def fund_unpaid(

    interaction: discord.Interaction,

    player: discord.Member

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    user_id = str(

        player.id

    )


    if user_id not in data["members"]:

        await safe_followup(

            interaction,

            content=(

                f"❌ **{player.display_name}** "
                "is not in the fund."

            ),

            ephemeral=True

        )

        return


    data["members"][user_id] = False


    save_data()


    await safe_followup(

        interaction,

        content=(

            f"❌ **{player.display_name}** "
            "has been marked as unpaid."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_AMOUNT
# ============================================================

@bot.tree.command(

    name="fund_amount",

    description=(

        "Set the required gang fund amount"

    )

)
@app_commands.describe(

    amount=(

        "Amount required from each player"

    )

)
async def fund_amount(

    interaction: discord.Interaction,

    amount: int

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    if amount < 0:

        await safe_followup(

            interaction,

            content=(

                "❌ Amount cannot be negative."

            ),

            ephemeral=True

        )

        return


    data["amount"] = amount


    save_data()


    await safe_followup(

        interaction,

        content=(

            f"💰 Gang fund amount set to "
            f"**${amount:,}** per player."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_LIST
# ============================================================

@bot.tree.command(

    name="fund_list",

    description=(

        "Show the gang fund list"

    )

)
async def fund_list(

    interaction: discord.Interaction

):

    success = await safe_defer(

        interaction,

        ephemeral=False

    )


    if not success:

        return


    embed = await create_fund_embed(

        interaction.guild

    )


    await safe_followup(

        interaction,

        embed=embed,

        view=FundView()

    )


# ============================================================
# /FUND_RESET
# ============================================================

@bot.tree.command(

    name="fund_reset",

    description=(

        "Reset all players to unpaid"

    )

)
async def fund_reset(

    interaction: discord.Interaction

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    for user_id in data["members"]:

        data["members"][user_id] = False


    save_data()


    await safe_followup(

        interaction,

        content=(

            "🔄 All players have been "
            "**reset to UNPAID**."

        ),

        ephemeral=True

    )


# ============================================================
# /FUND_PANEL
# ============================================================

@bot.tree.command(

    name="fund_panel",

    description=(

        "Create the gang fund tracking panel"

    )

)
async def fund_panel(

    interaction: discord.Interaction

):

    success = await safe_defer(

        interaction,

        ephemeral=True

    )


    if not success:

        return


    if not is_admin(

        interaction

    ):

        await safe_followup(

            interaction,

            content=(

                "❌ You don't have permission."

            ),

            ephemeral=True

        )

        return


    embed = await create_fund_embed(

        interaction.guild

    )


    try:

        await interaction.channel.send(

            embed=embed,

            view=FundView()

        )


    except discord.HTTPException as e:

        print(

            f"[PANEL ERROR] {e}"

        )

        await safe_followup(

            interaction,

            content=(

                "❌ Could not create "
                "the fund panel."

            ),

            ephemeral=True

        )

        return


    await safe_followup(

        interaction,

        content=(

            "✅ Gang fund panel created!"

        ),

        ephemeral=True

    )


# ============================================================
# GLOBAL ERROR HANDLER
# ============================================================

@bot.tree.error
async def on_app_command_error(

    interaction: discord.Interaction,

    error: app_commands.AppCommandError

):

    print(

        f"[COMMAND ERROR] {error}"

    )


    if isinstance(

        error,

        app_commands.CommandOnCooldown

    ):

        return


    try:

        if interaction.response.is_done():

            await interaction.followup.send(

                "❌ An error occurred "
                "while running this command.",

                ephemeral=True

            )

        else:

            await interaction.response.send_message(

                "❌ An error occurred "
                "while running this command.",

                ephemeral=True

            )


    except:

        pass


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    print(

        "Starting GTA RP Gang Fund Bot..."

    )


    try:

        bot.run(

            TOKEN

        )


    except KeyboardInterrupt:

        print(

            "Bot stopped."

        )


    except Exception as e:

        print(

            "========================================"

        )

        print(

            "BOT FAILED TO START"

        )

        print(

            f"Error: {e}"

        )

        print(

            "========================================"

        )
