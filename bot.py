import os
import sqlite3
import urllib.parse
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

# Automatically pulls your secret token from GitHub's secure vault
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")

CJ_WRAPPER = os.getenv("CJ_WRAPPER", "")
HUMBLE_WRAPPER = os.getenv("HUMBLE_WRAPPER", "")
WEB_RADAR_URL = "https://glitcherhq.github.io/pc-glitch-tracker/"

STORE_INFO = {
    "15": {"name": "Fanatical", "color": 0xF97316},
    "21": {"name": "Humble Store", "color": 0xEF4444},
    "2":  {"name": "Green Man Gaming", "color": 0x84CC16},
}

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

class DealButtons(discord.ui.View):
    def __init__(self, primary_label: str, primary_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=primary_label, url=primary_url, style=discord.ButtonStyle.link, emoji="🔥"))
        self.add_item(discord.ui.Button(label="Live Web Radar", url=WEB_RADAR_URL, style=discord.ButtonStyle.link, emoji="⚡"))

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
    print(f"✅ Bot is online as {bot.user}!")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for Free Games & Price Glitches"))

@bot.tree.command(name="setchannel", description="Set this channel to receive 100% Free PC Games and 75%+ Price Glitch alerts.")
@app_commands.checks.has_permissions(manage_channels=True)
async def setchannel(interaction: discord.Interaction):
    cursor.execute(
        "INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)",
        (interaction.guild_id, interaction.channel_id)
    )
    conn.commit()
    await interaction.response.send_message(
        "✅ **Steam Freebies & Glitch Radar Activated!**\n"
        "This channel will now automatically receive daily giveaways and deep price drops.",
        ephemeral=False
    )
    url = "https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=1&sortBy=Savings"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                deals = await resp.json()
                if deals:
                    deal = deals[0]
                    savings = round(float(deal.get("savings", 0)))
                    store = STORE_INFO.get(str(deal.get("storeID", "15")), {"name": "Official Store", "color": 0x10B981})
                    embed = discord.Embed(
                        title=f"⚡ -{savings}% PRICE DROP: {deal['title']}",
                        description=f"💰 **Sale Price:** `${deal['salePrice']}` ~~${deal['normalPrice']}~~ (**{savings}% OFF**)",
                        color=store["color"]
                    )
                    if deal.get("thumb"):
                        embed.set_thumbnail(url=deal["thumb"])
                    await interaction.channel.send(embed=embed, view=DealButtons(f"Grab Deal (${deal['salePrice']}) →", wrap_affiliate_link(deal["dealID"], str(deal.get("storeID", "15")))))

@tasks.loop(minutes=30)
async def check_free_games():
    pass

@tasks.loop(minutes=15)
async def check_price_glitches():
    pass

if __name__ == "__main__":
    bot.run(BOT_TOKEN)
