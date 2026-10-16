import os
import sqlite3
import urllib.parse
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

# =====================================================================
# CONFIGURATION
# =====================================================================
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Leave these two empty for now! Once approved later, paste your prefixes here:
CJ_WRAPPER = os.getenv("CJ_WRAPPER", "")
HUMBLE_WRAPPER = os.getenv("HUMBLE_WRAPPER", "")

WEB_RADAR_URL = "https://glitcherhq.github.io/pc-glitch-tracker/"

STORE_INFO = {
    "15": {"name": "Fanatical", "color": 0xF97316},
    "21": {"name": "Humble Store", "color": 0xEF4444},
    "2":  {"name": "Green Man Gaming", "color": 0x84CC16},
}

# =====================================================================
# DATABASE SETUP (Automatically creates bot_data.db)
# =====================================================================
conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS channels (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS posted_items (item_id TEXT PRIMARY KEY)")
conn.commit()


def is_posted(item_id: str) -> bool:
    cursor.execute("SELECT 1 FROM posted_items WHERE item_id = ?", (item_id,))
    return cursor.fetchone() is not None


def mark_posted(item_id: str):
    cursor.execute("INSERT OR IGNORE INTO posted_items (item_id) VALUES (?)", (item_id,))
    conn.commit()


def wrap_affiliate_link(deal_id: str, store_id: str) -> str:
    base_url = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
    if store_id == "21" and HUMBLE_WRAPPER:
        return HUMBLE_WRAPPER + urllib.parse.quote(base_url, safe="")
    if store_id in ("15", "2") and CJ_WRAPPER:
        return CJ_WRAPPER + urllib.parse.quote(base_url, safe="")
    return base_url


# =====================================================================
# CLICKABLE BUTTONS FOR DISCORD ALERTS
# =====================================================================
class DealButtons(discord.ui.View):
    def __init__(self, primary_label: str, primary_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=primary_label, url=primary_url, style=discord.ButtonStyle.link, emoji="🔥"))
        self.add_item(discord.ui.Button(label="Live Web Radar", url=WEB_RADAR_URL, style=discord.ButtonStyle.link, emoji="⚡"))


# =====================================================================
# DISCORD BOT SETUP
# =====================================================================
class GlitchRadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        check_free_games.start()
        check_price_glitches.start()


bot = GlitchRadarBot()


@bot.event
async def on_ready():
    print(f"✅ Bot is online as {bot.user} across {len(bot.guilds)} server(s)!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for 100% Free Games & Price Glitches"))


# =====================================================================
# SLASH COMMAND: /setchannel
# =====================================================================
@bot.tree.command(name="setchannel", description="Set this channel to receive 100% Free PC Games and 75%+ Price Glitch alerts.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel(interaction: discord.Interaction):
    cursor.execute(
        "INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)",
        (interaction.guild_id, interaction.channel_id)
    )
    conn.commit()
    await interaction.response.send_message(
        "✅ ** Steam Freebies & Glitch Radar Activated!**\n"
        "This channel will now automatically receive **100% Free Game Giveaways** and **75%+ Off Flash Price Glitches**. "
        "Fetching a live sample deal for you right now...",
        ephemeral=False
    )
    await send_instant_sample(interaction.channel)


async def send_instant_sample(channel: discord.abc.Messageable):
    """Fetches 1 live deal immediately when a server runs /setchannel so they see it work right away."""
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=5&sortBy=Savings"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                deals = await resp.json()
                if deals:
                    embed, view = format_glitch_embed(deals[0])
                    await channel.send(embed=embed, view=view)


def format_glitch_embed(deal: dict):
    savings = round(float(deal.get("savings", 0)))
    store_id = str(deal.get("storeID", "15"))
    store = STORE_INFO.get(store_id, {"name": "Official Store", "color": 0x10B981})
    deal_url = wrap_affiliate_link(deal["dealID"], store_id)

    embed = discord.Embed(
        title=f"⚡ -{savings}% PRICE DROP: {deal['title']}",
        description=(
            f"Verified official Steam key discount spotted on **{store['name']}**.\n\n"
            f"💰 **Sale Price:** `${deal['salePrice']}` ~~${deal['normalPrice']}~~ (**{savings}% OFF**)\n"
            f"⭐ **Steam Rating:** `{deal.get('steamRatingPercent', 'Verified')}%`"
        ),
        color=store["color"]
    )
    if deal.get("thumb"):
        embed.set_thumbnail(url=deal["thumb"])
    embed.set_footer(text="PC Glitch & Low Radar • Official Authorized Key Retailers Only")
    view = DealButtons(primary_label=f"Grab Deal (${deal['salePrice']}) →", primary_url=deal_url)
    return embed, view


def format_freebie_embed(item: dict):
    embed = discord.Embed(
        title=f"🎁 100% FREE GAME: {item['title']}",
        description=(
            f"{item.get('description', 'Claim this game for free before the giveaway expires!')}\n\n"
            f"💵 **Normal Price:** ~~{item.get('worth', 'Paid')}~~ → **FREE ($0.00)**\n"
            f"🖥️ **Platform:** `{item.get('platforms', 'PC')}`\n"
            f"⏳ **Ends:** `{item.get('end_date', 'Limited Time')}`"
        ),
        color=0x10B981
    )
    if item.get("image"):
        embed.set_image(url=item["image"])
    embed.set_footer(text="PC Glitch & Low Radar • 100% Free Game Alert")
    view = DealButtons(primary_label="Claim Free Game ($0.00) →", primary_url=item["open_giveaway_url"])
    return embed, view


async def broadcast_to_servers(embed: discord.Embed, view: discord.ui.View):
    cursor.execute("SELECT guild_id, channel_id FROM channels")
    rows = cursor.fetchall()
    for guild_id, channel_id in rows:
        channel = bot.get_channel(channel_id)
        if channel:
            try:
                await channel.send(embed=embed, view=view)
            except Exception:
                pass


# =====================================================================
# LOOP 1: 100% FREE PC GAMES (Runs every 30 minutes)
# =====================================================================
@tasks.loop(minutes=30)
async def check_free_games():
    url = "https://www.gamerpower.com/api/giveaways?platform=pc&type=game"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                giveaways = await resp.json()

        # Check if database is brand new so we don't spam 30 old giveaways at once
        cursor.execute("SELECT COUNT(*) FROM posted_items WHERE item_id LIKE 'free_%'")
        is_first_run = cursor.fetchone()[0] == 0

        for idx, item in enumerate(giveaways[:10]):
            item_id = f"free_{item['id']}"
            if not is_posted(item_id):
                mark_posted(item_id)
                if not is_first_run or idx == 0:
                    embed, view = format_freebie_embed(item)
                    await broadcast_to_servers(embed, view)
    except Exception as e:
        print(f"Freebie loop error: {e}")


# =====================================================================
# LOOP 2: 75%+ FLASH PRICE GLITCHES (Runs every 15 minutes)
# =====================================================================
@tasks.loop(minutes=15)
async def check_price_glitches():
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=15&sortBy=Savings"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return
                deals = await resp.json()

        cursor.execute("SELECT COUNT(*) FROM posted_items WHERE item_id LIKE 'deal_%'")
        is_first_run = cursor.fetchone()[0] == 0

        for idx, deal in enumerate(deals):
            savings = round(float(deal.get("savings", 0)))
            if savings < 75:
                continue
            item_id = f"deal_{deal['dealID']}"
            if not is_posted(item_id):
                mark_posted(item_id)
                if not is_first_run or idx == 0:
                    embed, view = format_glitch_embed(deal)
                    await broadcast_to_servers(embed, view)
    except Exception as e:
        print(f"Deal loop error: {e}")


if __name__ == "__main__":
    bot.run(BOT_TOKEN)
