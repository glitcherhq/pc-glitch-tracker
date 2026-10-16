import asyncio
import os
import sqlite3
import urllib.parse
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import tasks

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()
CJ_WRAPPER = os.getenv("CJ_WRAPPER", "").strip()
HUMBLE_WRAPPER = os.getenv("HUMBLE_WRAPPER", "").strip()
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip()
WEB_RADAR_URL = "https://glitcherhq.github.io/pc-glitch-tracker/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

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

def wrap_affiliate_link(deal_id: str, store_id: str) -> str:
    base_url = f"https://www.cheapshark.com/redirect?dealID={deal_id}"
    if store_id == "21" and HUMBLE_WRAPPER:
        return HUMBLE_WRAPPER + urllib.parse.quote(base_url, safe="")
    if store_id in ("15", "2") and CJ_WRAPPER:
        return CJ_WRAPPER + urllib.parse.quote(base_url, safe="")
    return base_url

def pick_best_channel(guild: discord.Guild):
    keywords = ("free", "deal", "glitch", "giveaway", "game", "alert", "general", "chat")
    me = guild.me
    for kw in keywords:
        for ch in guild.text_channels:
            if kw in ch.name.lower() and ch.permissions_for(me).send_messages and ch.permissions_for(me).embed_links:
                return ch
    for ch in guild.text_channels:
        if ch.permissions_for(me).send_messages and ch.permissions_for(me).embed_links:
            return ch
    return None

def get_target_channels():
    targets = []
    for guild in bot.guilds:
        cursor.execute("SELECT channel_id FROM channels WHERE guild_id = ?", (guild.id,))
        row = cursor.fetchone()
        ch = guild.get_channel(row[0]) if row else None
        if not ch:
            ch = pick_best_channel(guild)
            if ch:
                cursor.execute("INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)", (guild.id, ch.id))
                conn.commit()
        if ch:
            targets.append(ch)
    return targets

class DealButtons(discord.ui.View):
    def __init__(self, primary_label: str, primary_url: str):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=primary_label, url=primary_url, style=discord.ButtonStyle.link, emoji="🔥"))
        self.add_item(discord.ui.Button(label="Live Web Radar", url=WEB_RADAR_URL, style=discord.ButtonStyle.link, emoji="⚡"))

async def handle_health(request):
    return web.Response(text="Steam Freebies & Glitch Radar Bot is live 24/7!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Web port open and listening on 0.0.0.0:{port}", flush=True)
    if RENDER_URL:
        print(f"🔗 YOUR RENDER URL IS: {RENDER_URL}", flush=True)

class GlitchRadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = GlitchRadarBot()

@bot.event
async def on_ready():
    print(f"🚀 24/7 CLOUD BOT ONLINE as {bot.user} across {len(bot.guilds)} server(s)!", flush=True)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="for 100% Free Games & Glitches"))
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()
    if not check_free_games.is_running():
        check_free_games.start()
    if not check_price_glitches.is_running():
        check_price_glitches.start()

@tasks.loop(minutes=10)
async def keep_alive_ping():
    if RENDER_URL:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    print(f"💓 Self-ping keep-alive status: {resp.status}", flush=True)
        except Exception:
            pass

@bot.event
async def on_guild_join(guild: discord.Guild):
    ch = pick_best_channel(guild)
    if ch:
        cursor.execute("INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)", (guild.id, ch.id))
        conn.commit()
        await send_sample_drops(ch.send)

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

async def send_sample_drops(send_func):
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        try:
            async with session.get("https://www.gamerpower.com/api/giveaways?platform=pc&type=game") as r1:
                if r1.status == 200:
                    freebies = await r1.json()
                    if freebies:
                        e1, v1 = format_freebie_embed(freebies[0])
                        await send_func(embed=e1, view=v1)
        except Exception as e:
            print(f"Freebie fetch error: {e}", flush=True)

        try:
            async with session.get("https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=5&sortBy=Savings") as r2:
                if r2.status == 200:
                    deals = await r2.json()
                    if deals:
                        e2, v2 = format_glitch_embed(deals[0])
                        await send_func(embed=e2, view=v2)
        except Exception as e:
            print(f"CheapShark fetch error: {e}", flush=True)

@bot.tree.command(name="setchannel", description="Activate live 100% Free PC Games and 75%+ Price Glitch alerts.")
async def setchannel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🚀 **Steam Freebies & Glitch Radar Connected!** Fetching 1 live **100% Free Game** and 1 **Flash Price Glitch** right now..."
    )
    cursor.execute("INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)", (interaction.guild_id, interaction.channel_id))
    conn.commit()
    await send_sample_drops(interaction.followup.send)

@tasks.loop(minutes=30)
async def check_free_games():
    channels = get_target_channels()
    if not channels:
        return
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get("https://www.gamerpower.com/api/giveaways?platform=pc&type=game") as resp:
            if resp.status != 200:
                return
            giveaways = await resp.json()
    cursor.execute("SELECT COUNT(*) FROM posted_items WHERE item_id LIKE 'free_%'")
    is_first_boot = cursor.fetchone()[0] == 0
    for idx, item in enumerate(giveaways[:5]):
        item_id = f"free_{item['id']}"
        cursor.execute("SELECT 1 FROM posted_items WHERE item_id = ?", (item_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO posted_items (item_id) VALUES (?)", (item_id,))
            conn.commit()
            if not is_first_boot or idx == 0:
                embed, view = format_freebie_embed(item)
                for ch in channels:
                    try:
                        await ch.send(embed=embed, view=view)
                    except Exception:
                        pass

@tasks.loop(minutes=15)
async def check_price_glitches():
    channels = get_target_channels()
    if not channels:
        return
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get("https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=10&sortBy=Savings") as resp:
            if resp.status != 200:
                return
            deals = await resp.json()
    cursor.execute("SELECT COUNT(*) FROM posted_items WHERE item_id LIKE 'deal_%'")
    is_first_boot = cursor.fetchone()[0] == 0
    for idx, deal in enumerate(deals):
        if round(float(deal.get("savings", 0))) < 75:
            continue
        item_id = f"deal_{deal['dealID']}"
        cursor.execute("SELECT 1 FROM posted_items WHERE item_id = ?", (item_id,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO posted_items (item_id) VALUES (?)", (item_id,))
            conn.commit()
            if not is_first_boot or idx == 0:
                embed, view = format_glitch_embed(deal)
                for ch in channels:
                    try:
                        await ch.send(embed=embed, view=view)
                    except Exception:
                        pass

async def main():
    await start_web_server()
    await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
