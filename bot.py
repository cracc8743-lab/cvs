import os
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
API_KEY = os.getenv("CVS_API_KEY")

BASE_URL = "https://puff-cvs-api-production.up.railway.app"
OWNER_ID = 1500626713065820273
ORDERS_CHANNEL_ID = 1551988175239647303
SHOP_CHANNEL_ID = 1545250548045975622
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


async def api_get(endpoint):
    headers = {
        "X-API-Key": API_KEY
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{BASE_URL}{endpoint}",
            headers=headers
        ) as response:
            return response.status, await response.json()


async def api_post(endpoint, data):
    headers = {
        "X-API-Key": API_KEY
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{BASE_URL}{endpoint}",
            headers=headers,
            json=data
        ) as response:
            return response.status, await response.json()


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


# --------------------
# /balance
# --------------------

@bot.tree.command(name="balance", description="Check API wallet balance")
async def balance(interaction: discord.Interaction):
    await interaction.response.defer()

    status, data = await api_get("/v1/balance")

    if status != 200:
        await interaction.followup.send(f"API Error: {data}")
        return

    await interaction.followup.send(
        f"💰 **API Balance: ${data['balance_usd']:.2f}**"
    )

# --------------------
# /stock
# --------------------

@bot.tree.command(name="stock", description="View available CVS stock")
async def stock(interaction: discord.Interaction):

    await interaction.response.defer()

    status, data = await api_get("/v1/stock")

    if status != 200:
        await interaction.followup.send(f"API Error: {data}")
        return

    if not data:
        await interaction.followup.send("No stock available.")
        return

    embed = discord.Embed(
        title="🛒 CVS Stock",
        description="Available ExtraCare tiers"
    )

    for tier in data:

        embed.add_field(
            name=tier["label"],
            value=(
                f"Price: **${((tier['min'] + tier['max']) / 2) * 0.50:.2f}**\n"
                f"Stock: **{tier['count_display']}**\n"
                f"`{tier['min']} - {tier['max']}`"
            ),
            inline=True
        )

    await interaction.followup.send(embed=embed)


# --------------------
# /buy
# --------------------

# --------------------
# NEW /buy SYSTEM
# --------------------

def customer_price(tier_min, tier_max):
    midpoint = (tier_min + tier_max) / 2
    return midpoint * 0.50
class ApprovalView(discord.ui.View):
    def __init__(self, buyer, tier_min, tier_max, tier_label, sell_price):
        super().__init__(timeout=600)
        self.buyer = buyer
        self.tier_min = tier_min
        self.tier_max = tier_max
        self.tier_label = tier_label
        self.sell_price = sell_price
        self.finished = False

    @discord.ui.button(
        label="Approve",
        style=discord.ButtonStyle.green,
        emoji="✅"
    )
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):

        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "Only the owner can approve orders.",
                ephemeral=True
            )
            return

        if self.finished:
            await interaction.response.send_message(
                "This order was already handled.",
                ephemeral=True
            )
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        status, data = await api_post(
            "/v1/purchase",
            {
                "tier_min": self.tier_min,
                "tier_max": self.tier_max
            }
        )

        if status != 200:
            self.finished = False

            if status == 402:
                error = "Not enough API balance."
            elif status == 409:
                error = "That tier is out of stock."
            elif status == 401:
                error = "API authentication failed."
            else:
                error = f"API error: {data}"

            await interaction.followup.send(
                f"❌ Purchase failed: {error}",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="✅ CVS Order",
            description="Your card is ready!"
        )

        embed.add_field(
            name="Tier",
            value=self.tier_label
        )

        embed.add_field(
            name="Card Balance",
            value=f"${data['total_bucks']:.2f}"
        )

        embed.add_field(
            name="ExtraCare Number",
            value=f"`{data['ec_number']}`",
            inline=False
        )

        embed.add_field(
            name="Offer Link",
            value=data["offer_link"],
            inline=False
        )

        embed.add_field(
            name="Apple Wallet",
            value=data["applepay_link"],
            inline=False
        )

        try:
            await self.buyer.send(embed=embed)
            await interaction.followup.send(
                "✅ Purchased and sent to the customer.",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "⚠️ Purchase succeeded, but I couldn't DM the customer.",
                ephemeral=True
            )
    @discord.ui.button(
        label="Decline",
        style=discord.ButtonStyle.red,
        emoji="❌"
    )
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "Only the owner can decline orders.",
                ephemeral=True
            )
            return

        if self.finished:
            await interaction.response.send_message(
                "This order was already handled.",
                ephemeral=True
            )
            return

        self.finished = True

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(view=self)

        try:
            await self.buyer.send(
                f"❌ Your **{self.tier_label}** CVS order was declined."
            )
        except discord.Forbidden:
            pass
class TierSelect(discord.ui.Select):
    def __init__(self, stock):
        options = []

        for tier in stock[:25]:
            price = customer_price(tier["min"], tier["max"])

            options.append(
                discord.SelectOption(
                    label=f"{tier['label']} — ${price:.2f}",
                    description=f"Stock: {tier['count_display']}",
                    value=f"{tier['min']}:{tier['max']}"
                )
            )

        super().__init__(
            placeholder="Choose a CVS tier...",
            min_values=1,
            max_values=1,
            options=options
        )

        self.stock = stock

    async def callback(self, interaction: discord.Interaction):
        tier_min, tier_max = map(int, self.values[0].split(":"))

        tier = next(
            (
                t for t in self.stock
                if t["min"] == tier_min and t["max"] == tier_max
            ),
            None
        )

        if tier is None:
            await interaction.response.send_message(
                "❌ That tier is no longer available.",
                ephemeral=True
            )
            return

        price = customer_price(tier_min, tier_max)

               # Tell the customer privately that the order is waiting
        await interaction.response.send_message(
            f"✅ **Order submitted!**\n\n"
            f"Tier: **{tier['label']}**\n"
            f"Price: **${price:.2f}**\n\n"
            f"Please complete your manual payment.\n"
            f"Your order will be delivered after payment is confirmed.",
            ephemeral=True
        )

        # Send approval request to private orders channel
        orders_channel = interaction.client.get_channel(ORDERS_CHANNEL_ID)

        if orders_channel is None:
            await interaction.followup.send(
                "❌ Orders channel could not be found. Contact the owner.",
                ephemeral=True
            )
            return

        await orders_channel.send(
            f"🧾 **NEW ORDER**\n\n"
            f"Buyer: {interaction.user.mention}\n"
            f"User ID: `{interaction.user.id}`\n"
            f"Tier: **{tier['label']}**\n"
            f"Customer Price: **${price:.2f}**\n\n"
            f"Confirm payment before approving.",
            view=ApprovalView(
                interaction.user,
                tier_min,
                tier_max,
                tier["label"],
                price
            )
        )



class TierView(discord.ui.View):
    def __init__(self, stock):
        super().__init__(timeout=300)
        self.add_item(TierSelect(stock))
class PublicShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Buy",
        style=discord.ButtonStyle.green,
        emoji="🛒",
        custom_id="cvs_public_buy"
    )
    async def buy_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer(ephemeral=True)

        status, stock = await api_get("/v1/stock")

        if status != 200 or not stock:
            await interaction.followup.send(
                "❌ No stock is currently available.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            "🛒 **Select the tier you want to purchase:**",
            view=TierView(stock),
            ephemeral=True
        )
@bot.tree.command(name="buy", description="Purchase a CVS card")
async def buy(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    status, stock = await api_get("/v1/stock")

    if status != 200:
        await interaction.followup.send(
            "❌ Couldn't load stock.",
            ephemeral=True
        )
        return

    if not stock:
        await interaction.followup.send(
            "❌ No stock is currently available.",
            ephemeral=True
        )
        return

    await interaction.followup.send(
        "🛒 **Select the tier you want to purchase:**",
        view=TierView(stock),
        ephemeral=True
    )
@bot.tree.command(name="postshop", description="Post the CVS shop")
async def postshop(interaction: discord.Interaction):
    # Only you can post the shop
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "❌ Only the owner can use this command.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    status, stock = await api_get("/v1/stock")

    if status != 200 or not stock:
        await interaction.followup.send(
            "❌ Couldn't load stock.",
            ephemeral=True
        )
        return

    shop_channel = interaction.client.get_channel(SHOP_CHANNEL_ID)

    if shop_channel is None:
        await interaction.followup.send(
            "❌ Shop channel could not be found.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🛒 CVS Shop",
        description="Choose a tier and click **Buy** to place an order."
    )

    for tier in stock:
        price = customer_price(tier["min"], tier["max"])

        embed.add_field(
            name=tier["label"],
            value=(
                f"💵 Price: **${price:.2f}**\n"
                f"📦 Stock: **{tier['count_display']}**"
            ),
            inline=True
        )

    embed.set_footer(
        text="Click Buy below to start your order."
    )

    await shop_channel.send(
        embed=embed,
        view=PublicShopView()
    )

    await interaction.followup.send(
        "✅ Shop posted!",
        ephemeral=True
    )
bot.run(DISCORD_TOKEN)