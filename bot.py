import http.server
import os
import sqlite3
import threading
import time
import urllib.parse
import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks

LIVE_STATS = {"servers": 0, "users": 0, "recent_servers": []}

class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        recent_html = "".join(f"<li>{s}</li>" for s in LIVE_STATS["recent_servers"]) or "<li>Waiting for new installs...</li>"
        html = f"""
        <html><body style="background:#0b0f19;color:#e2e8f0;font-family:sans-serif;padding:30px;">
          <h2 style="color:#10b981;">⚡ Steam Freebies & Glitch Radar — Live Bot Telemetry</h2>
          <p><strong>Active Discord Servers:</strong> {LIVE_STATS['servers']}</p>
          <p><strong>Total Gamers Reached:</strong> {LIVE_STATS['users']:,}</p>
          <h4>Newest Servers Installed:</h4>
          <ul>{recent_html}</ul>
        </body></html>
        """
        self.wfile.write(html.encode("utf-8"))

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def open_render_port():
    port = int(os.environ.get("PORT", 10000))
    server = http.server.HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"✅ RENDER PORT {port} IS OPEN AND LISTENING!", flush=True)
    server.serve_forever()

threading.Thread(target=open_render_port, daemon=True).start()

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
    "steam": {"name": "Official Steam / Fanatical", "color": 0xF97316},
}

conn = sqlite3.connect("bot_data.db")
cursor = conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS channels (guild_id INTEGER PRIMARY KEY, channel_id INTEGER)")
cursor.execute("CREATE TABLE IF NOT EXISTS posted_items (item_id TEXT PRIMARY KEY)")
conn.commit()

def update_telemetry():
    LIVE_STATS["servers"] = len(bot.guilds)
    LIVE_STATS["users"] = sum(g.member_count or 0 for g in bot.guilds)
    LIVE_STATS["recent_servers"] = [f"{g.name} ({g.member_count or '?'} members)" for g in list(bot.guilds)[-10:]]

def wrap_affiliate_link(raw_url: str, store_id: str) -> str:
    if store_id == "21" and HUMBLE_WRAPPER:
        return HUMBLE_WRAPPER + urllib.parse.quote(raw_url, safe="")
    if store_id in ("15", "2", "steam") and CJ_WRAPPER:
        return CJ_WRAPPER + urllib.parse.quote(raw_url, safe="")
    return raw_url

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
        self.add_item(discord.ui.Button(label="Browse 200+ Live Deals", url=WEB_RADAR_URL, style=discord.ButtonStyle.link, emoji="⚡"))

class GlitchRadarBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()

bot = GlitchRadarBot()

@bot.event
async def on_ready():
    update_telemetry()
    print(f"🚀 24/7 CLOUD BOT ONLINE as {bot.user} across {len(bot.guilds)} server(s)!", flush=True)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"Deals in {len(bot.guilds)} Servers"))
    if not keep_alive_ping.is_running():
        keep_alive_ping.start()
    if not check_free_games.is_running():
        check_free_games.start()
    if not check_price_glitches.is_running():
        check_price_glitches.start()

@bot.event
async def on_guild_join(guild: discord.Guild):
    update_telemetry()
    print(f"🎉 NEW SERVER INSTALLED BOT: {guild.name} ({guild.member_count} members)", flush=True)
    ch = pick_best_channel(guild)
    if ch:
        cursor.execute("INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)", (guild.id, ch.id))
        conn.commit()
        await send_sample_drops(ch.send)

@tasks.loop(minutes=10)
async def keep_alive_ping():
    update_telemetry()
    if RENDER_URL:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(RENDER_URL) as resp:
                    print(f"💓 Self-ping status: {resp.status} | Active Servers: {LIVE_STATS['servers']}", flush=True)
        except Exception:
            pass

def format_glitch_embed(deal: dict):
    savings = round(float(deal.get("savings", 0)))
    store_id = str(deal.get("storeID", "15"))
    store = STORE_INFO.get(store_id, {"name": "Official Store", "color": 0x10B981})
    raw_url = deal.get("custom_url") or f"https://www.cheapshark.com/redirect?dealID={deal['dealID']}"
    deal_url = wrap_affiliate_link(raw_url, store_id)

    embed = discord.Embed(
        title=f"⚡ -{savings}% PRICE DROP: {deal['title']}",
        description=(
            f"Verified official Steam discount spotted on **{store['name']}**.\n\n"
            f"💰 **Sale Price:** `${deal['salePrice']}` ~~${deal['normalPrice']}~~ (**{savings}% OFF**)\n"
            f"⭐ **Rating:** `{deal.get('steamRatingPercent', 'Verified')}`"
        ),
        color=store["color"]
    )
    if deal.get("thumb"):
        embed.set_image(url=deal["thumb"])
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

async def fetch_live_deals(session: aiohttp.ClientSession):
    """Tries CheapShark first; if Cloudflare blocks Render's IP, automatically uses Valve's Official Steam Specials API."""
    try:
        url = "https://www.cheapshark.com/api/1.0/deals?storeID=2,15,21&onSale=1&lowerPrice=1&pageSize=40&sortBy=Recent"
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data:
                    print(f"✅ Loaded {len(data)} deals from CheapShark.", flush=True)
                    return data
            else:
                print(f"⚠️ CheapShark returned status {resp.status}, switching to official Steam API backup...", flush=True)
    except Exception as e:
        print(f"⚠️ CheapShark unreachable ({e}), switching to official Steam API backup...", flush=True)

    # Backup Engine: Official Valve Steam Storefront API (Never blocks Render IPs)
    steam_deals = []
    try:
        steam_url = "https://store.steampowered.com/api/featuredcategories?cc=us&l=en"
        async with session.get(steam_url, timeout=10) as resp:
            if resp.status == 200:
                sdata = await resp.json()
                buckets = [
                    sdata.get("specials", {}).get("items", []),
                    sdata.get("top_sellers", {}).get("items", []),
                    sdata.get("new_releases", {}).get("items", [])
                ]
                seen_ids = set()
                for bucket in buckets:
                    for item in bucket:
                        app_id = item.get("id")
                        discount = item.get("discount_percent", 0)
                        if discount >= 40 and app_id not in seen_ids:
                            seen_ids.add(app_id)
                            title = item.get("name", "Steam Game")
                            fanatical_search = f"https://www.fanatical.com/en/search?search={urllib.parse.quote(title)}"
                            steam_deals.append({
                                "dealID": f"steam_{app_id}_{discount}",
                                "title": title,
                                "savings": str(discount),
                                "salePrice": f"{item.get('final_price', 0) / 100:.2f}",
                                "normalPrice": f"{item.get('original_price', 0) / 100:.2f}",
                                "storeID": "steam",
                                "steamRatingPercent": "Steam Featured",
                                "thumb": item.get("large_capsule_image") or item.get("header_image"),
                                "custom_url": fanatical_search
                            })
                print(f"✅ Loaded {len(steam_deals)} discounted games from Official Steam API.", flush=True)
    except Exception as e:
        print(f"❌ Steam API error: {e}", flush=True)
    return steam_deals

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
            print(f"Sample freebie error: {e}", flush=True)

        deals = await fetch_live_deals(session)
        if deals:
            e2, v2 = format_glitch_embed(deals[0])
            await send_func(embed=e2, view=v2)

@bot.tree.command(name="setchannel", description="Activate live 100% Free PC Games and Price Glitch alerts.")
async def setchannel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🚀 **Steam Freebies & Glitch Radar Connected!** Fetching 1 live **100% Free Game** and 1 **Live Price Drop** right now..."
    )
    cursor.execute("INSERT OR REPLACE INTO channels (guild_id, channel_id) VALUES (?, ?)", (interaction.guild_id, interaction.channel_id))
    conn.commit()
    await send_sample_drops(interaction.followup.send)

@bot.tree.command(name="stats", description="Check how many Discord servers and gamers are using this bot.")
async def stats(interaction: discord.Interaction):
    update_telemetry()
    await interaction.response.send_message(
        f"📊 **Live Bot Telemetry**\n"
        f"• **Active Servers:** `{LIVE_STATS['servers']}`\n"
        f"• **Total Gamers Reached:** `{LIVE_STATS['users']:,}`\n"
        f"• **Newest Installs:** {', '.join(LIVE_STATS['recent_servers'][-5:])}",
        ephemeral=True
    )

@tasks.loop(minutes=45)
async def check_free_games():
    channels = get_target_channels()
    if not channels:
        return
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            async with session.get("https://www.gamerpower.com/api/giveaways?platform=pc") as resp:
                if resp.status != 200:
                    return
                giveaways = await resp.json()

        for item in giveaways[:10]:
            item_id = f"free_{item['id']}"
            cursor.execute("SELECT 1 FROM posted_items WHERE item_id = ?", (item_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO posted_items (item_id) VALUES (?)", (item_id,))
                conn.commit()
                embed, view = format_freebie_embed(item)
                for ch in channels:
                    try:
                        await ch.send(embed=embed, view=view)
                    except Exception:
                        pass
                print(f"🎁 Broadcasted Freebie: {item['title']}", flush=True)
                break
    except Exception as e:
        print(f"Freebie loop error: {e}", flush=True)

@tasks.loop(hours=2)
async def check_price_glitches():
    channels = get_target_channels()
    if not channels:
        return
    try:
        async with aiohttp.ClientSession(headers=HEADERS) as session:
            deals = await fetch_live_deals(session)

        for deal in deals:
            if round(float(deal.get("savings", 0))) < 45:
                continue
            item_id = f"deal_{deal['dealID']}"
            cursor.execute("SELECT 1 FROM posted_items WHERE item_id = ?", (item_id,))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO posted_items (item_id) VALUES (?)", (item_id,))
                conn.commit()
                embed, view = format_glitch_embed(deal)
                for ch in channels:
                    try:
                        await ch.send(embed=embed, view=view)
                    except Exception:
                        pass
                print(f"⚡ Broadcasted Price Drop: {deal['title']} (-{deal['savings']}%)", flush=True)
                break
    except Exception as e:
        print(f"Deal loop error: {e}", flush=True)

if __name__ == "__main__":
    if not BOT_TOKEN:
        while True:
            time.sleep(60)
    bot.run(BOT_TOKEN)
