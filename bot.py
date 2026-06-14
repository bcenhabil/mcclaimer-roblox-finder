import asyncio
import aiohttp
import random
import os
import time
import sqlite3
import logging
from datetime import timedelta
from threading import Thread
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
import uvicorn

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("scanner.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ---------- CONFIGURATION (Proxy ON by default) ----------
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j")
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
PORT = int(os.environ.get("PORT", "8000"))
USE_PROXY = os.environ.get("USE_PROXY", "true").lower() == "true"   # <-- NOW ENABLED BY DEFAULT
PROXY_LIST_URL = os.environ.get("PROXY_LIST_URL", "https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/all.txt")
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "3600"))

# ---------- DATABASE ----------
conn = sqlite3.connect('hits.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS hits (
        id INTEGER PRIMARY KEY,
        name TEXT,
        member_count INTEGER,
        created TEXT,
        timestamp REAL,
        description TEXT
    )
''')
conn.commit()

def save_hit_to_db(group_id, details):
    cursor.execute('INSERT OR IGNORE INTO hits (id, name, member_count, created, timestamp, description) VALUES (?,?,?,?,?,?)',
                   (group_id, details['name'], details['memberCount'], details.get('created', ''), time.time(), details.get('description', '')))
    conn.commit()

def get_hits_from_db(limit=100, offset=0, search=None, min_members=None):
    query = "SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC"
    params = []
    conditions = []
    if search:
        conditions.append("name LIKE ?")
        params.append(f"%{search}%")
    if min_members:
        conditions.append("member_count >= ?")
        params.append(int(min_members))
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return [{"id": r[0], "name": r[1], "members": r[2], "created": r[3], "timestamp": r[4], "description": r[5]} for r in rows]

def get_total_hits_count():
    cursor.execute("SELECT COUNT(*) FROM hits")
    return cursor.fetchone()[0]

# ---------- PROXY MANAGER (with testing and rotation) ----------
class ProxyManager:
    def __init__(self, proxy_list_url):
        self.proxy_list_url = proxy_list_url
        self.proxies = []
        self.current_index = 0
        self.lock = asyncio.Lock()
        self.last_refresh = 0
        self.refresh_interval = 300  # 5 minutes

    async def test_proxy(self, proxy):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://httpbin.org/ip", proxy=proxy, timeout=5) as resp:
                    return resp.status == 200
        except:
            return False

    async def fetch_proxies(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.proxy_list_url) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        raw_proxies = [line.strip() for line in text.split('\n') if line.strip() and ':' in line]
                        working = []
                        # Test first 50 proxies for speed
                        for p in raw_proxies[:50]:
                            proxy_url = f"http://{p}"
                            if await self.test_proxy(proxy_url):
                                working.append(proxy_url)
                        async with self.lock:
                            self.proxies = working
                            self.current_index = 0
                        logger.info(f"Loaded {len(working)} working proxies")
                        return len(working)
        except Exception as e:
            logger.error(f"Proxy fetch failed: {e}")
            return 0

    async def get_next_proxy(self):
        async with self.lock:
            if not self.proxies:
                return None
            proxy = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            return proxy

    async def refresh_if_needed(self):
        if time.time() - self.last_refresh > self.refresh_interval:
            self.last_refresh = time.time()
            return await self.fetch_proxies()
        return len(self.proxies)

proxy_manager = ProxyManager(PROXY_LIST_URL) if USE_PROXY else None

# ---------- USER-AGENT ROTATION ----------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/119.0",
]
def get_random_ua():
    return random.choice(USER_AGENTS)

# ---------- FASTAPI ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# HTML Dashboard (same as before, abbreviated for brevity)
HTML_PAGE = """<!DOCTYPE html>
<html>
<head><title>Roblox Community Finder</title><style>
body{background:#0a0f1a;color:#eef;font-family:monospace;padding:2rem}
table{width:100%;background:#16213e;border-collapse:collapse}
th,td{padding:8px;border-bottom:1px solid #2a3a5a}
th{background:#0f3460;color:#0f0}
a{color:#0f0}
</style></head>
<body>
<h1>🤖 Roblox Community Finder <span style="background:#f36;padding:0 8px;border-radius:20px">LIVE</span></h1>
<div id="stats"></div>
<input id="search" placeholder="Search name" onkeyup="apply()">
<input id="minmem" placeholder="Min members" type="number" onchange="apply()">
<button onclick="exportCSV()">📥 CSV</button>
<table id="hits"><thead><tr><th>Time</th><th>ID</th><th>Name</th><th>Members</th></tr></thead><tbody></tbody></table>
<div id="pagination"></div>
<script>
let page=1,search='',minmem='';
async function load(){let u=`/api/hits?page=${page}&limit=50&search=${search}&min_members=${minmem}`;
let r=await fetch(u),d=await r.json();let tbody=document.querySelector('#hits tbody');
if(!d.hits.length){tbody.innerHTML='<tr><td colspan=4>None</tr>';return;}
tbody.innerHTML=d.hits.map(h=>`<tr><td>${new Date(h.timestamp*1000).toLocaleString()}</td><td><a href='https://www.roblox.com/groups/group.aspx?gid=${h.id}' target=_blank>${h.id}</a></td><td>${h.name}</td><td>${h.members}</td></tr>`).join('');
let pages='';for(let i=1;i<=Math.ceil(d.total/50);i++)pages+=`<button onclick="changePage(${i})">${i}</button>`;
document.getElementById('pagination').innerHTML=pages;}
async function loadStats(){let r=await fetch('/api/status'),d=await r.json();document.getElementById('stats').innerHTML=`<div>Hits:${d.total_hits} Range:${d.id_range} Concurrency:${d.concurrency} Proxy:${d.proxy_enabled?'ON':'OFF'}</div>`;}
function apply(){search=document.getElementById('search').value;minmem=document.getElementById('minmem').value;page=1;load();}
function changePage(p){page=p;load();}
function exportCSV(){window.location='/api/export-csv';}
loadStats();load();setInterval(loadStats,10000);
</script>
</body></html>"""

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=HTML_PAGE)

@app.get("/api/hits")
async def api_hits(page: int = 1, limit: int = 50, search: str = None, min_members: int = None):
    offset = (page - 1) * limit
    hits = get_hits_from_db(limit=limit, offset=offset, search=search, min_members=min_members)
    total = get_total_hits_count()
    return {"hits": hits, "total": total}

@app.get("/api/status")
async def api_status():
    return {"status": "running", "id_range": f"{ID_MIN}–{ID_MAX}", "concurrency": CONCURRENCY, "total_hits": get_total_hits_count(), "proxy_enabled": USE_PROXY}

@app.get("/api/export-csv")
async def export_csv():
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Members", "Created", "Timestamp", "Description"])
    cursor.execute("SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC")
    writer.writerows(cursor.fetchall())
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hits.csv"})

@app.get("/api/heartbeat")
async def heartbeat():
    return {"status": "alive", "timestamp": time.time(), "total_hits": get_total_hits_count()}

# ---------- DISCORD WEBHOOK & SCANNER ----------
webhook = Webhook(WEBHOOK_URL)
start_time = time.time()

async def send_heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        uptime = str(timedelta(seconds=int(time.time() - start_time)))
        embed = Embed(title="💓 Bot Heartbeat", color=0x00ff00, timestamp="now")
        embed.add_field(name="Uptime", value=uptime, inline=True)
        embed.add_field(name="Total Hits", value=str(get_total_hits_count()), inline=True)
        embed.add_field(name="Proxy", value="✅" if USE_PROXY else "❌", inline=True)
        embed.set_footer(text="24/7 Monitoring | Credits: McClaimer")
        await asyncio.to_thread(webhook.send, embed=embed)
        logger.info("Heartbeat sent")

async def get_thumbnail(session, group_id):
    try:
        url = f"https://thumbnails.roblox.com/v1/groups/icon?groupId={group_id}&size=420x420&format=Png"
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data") and data["data"]:
                    return data["data"][0].get("imageUrl")
    except:
        pass
    return None

async def send_discord(group_id, details):
    embed = Embed(title=f"🎯 JOINABLE COMMUNITY! {details['name']}", url=f"https://www.roblox.com/groups/group.aspx?gid={group_id}", color=0x00ff00, timestamp="now")
    embed.add_field(name="ID", value=str(group_id), inline=True)
    embed.add_field(name="Members", value=details["memberCount"], inline=True)
    embed.add_field(name="Public Entry", value=details["publicEntryAllowed"], inline=True)
    embed.add_field(name="Owner", value="None (joinable)", inline=False)
    if details.get("description"):
        embed.add_field(name="Description", value=details["description"][:200], inline=False)
    embed.set_footer(text="Informational only | Credits: McClaimer")
    if hasattr(webhook, '_session'):
        thumb = await get_thumbnail(webhook._session, group_id)
        if thumb:
            embed.set_thumbnail(thumb)
    await asyncio.to_thread(webhook.send, embed)

async def check_group(session, group_id, semaphore, retry=0):
    async with semaphore:
        try:
            proxy = await proxy_manager.get_next_proxy() if USE_PROXY else None
            headers = {"User-Agent": get_random_ua()}
            async with session.get(f"https://groups.roblox.com/v1/groups/{group_id}", headers=headers, timeout=10, proxy=proxy) as resp:
                if resp.status == 429:
                    wait = min(2 ** retry, 60)
                    logger.warning(f"Rate limit {group_id}, wait {wait}s")
                    await asyncio.sleep(wait)
                    if retry < 5:
                        return await check_group(session, group_id, semaphore, retry+1)
                    return
                if resp.status != 200:
                    return
                data = await resp.json()
                if 'errors' in data or data.get('owner') or data.get('isLocked'):
                    return
                if data.get('publicEntryAllowed') is True:
                    details = {
                        "name": data.get("name", "Unknown"),
                        "memberCount": data.get("memberCount", 0),
                        "publicEntryAllowed": True,
                        "description": data.get("description", ""),
                        "created": data.get("created", "")
                    }
                    logger.info(f"HIT: {group_id} - {details['name']}")
                    save_hit_to_db(group_id, details)
                    await send_discord(group_id, details)
        except:
            pass

async def scanner_worker():
    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        webhook._session = session
        if USE_PROXY:
            asyncio.create_task(proxy_manager.refresh_if_needed())
        tasks = []
        while True:
            gid = random.randint(ID_MIN, ID_MAX)
            tasks.append(asyncio.create_task(check_group(session, gid, semaphore)))
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

async def start_scanner():
    logger.info("""
    ===================================================
       Roblox Community Finder - Proxy Enabled
       Faster scanning, more hits to Discord
       Credits: McClaimer
    ===================================================
    """)
    embed = Embed(title="✅ Bot Started (Proxy Mode)", description=f"Scanning {ID_MIN}–{ID_MAX} with {CONCURRENCY} concurrent requests", color=0x00ff00)
    embed.add_field(name="Proxy", value="ON (rotating)", inline=True)
    embed.set_footer(text="Heartbeat every hour | McClaimer")
    await asyncio.to_thread(webhook.send, embed=embed)
    asyncio.create_task(send_heartbeat())
    await scanner_worker()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_scanner())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
