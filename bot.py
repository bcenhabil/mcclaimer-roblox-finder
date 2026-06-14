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

# ---------- ACTIVITY LOG ----------
activity_log = []
MAX_LOG_ENTRIES = 200

def add_log(entry_type, message, group_id=None):
    log_entry = {"time": time.time(), "type": entry_type, "message": message, "group_id": group_id}
    activity_log.insert(0, log_entry)
    if len(activity_log) > MAX_LOG_ENTRIES:
        activity_log.pop()
    logger.info(message)

# ---------- CONFIGURATION (Proxy ON by default) ----------
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j")
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
PORT = int(os.environ.get("PORT", "8000"))
USE_PROXY = os.environ.get("USE_PROXY", "true").lower() == "true"   # <-- ENABLED BY DEFAULT
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
    add_log("hit", f"Found joinable community: {details['name']} (ID: {group_id})", group_id)

def get_hits_from_db(limit=100, offset=0):
    cursor.execute("SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
    rows = cursor.fetchall()
    return [{"id": r[0], "name": r[1], "members": r[2], "created": r[3], "timestamp": r[4], "description": r[5]} for r in rows]

def get_total_hits_count():
    cursor.execute("SELECT COUNT(*) FROM hits")
    return cursor.fetchone()[0]

# ---------- PROXY MANAGER ----------
class ProxyManager:
    def __init__(self, proxy_list_url):
        self.proxy_list_url = proxy_list_url
        self.proxies = []
        self.current_index = 0
        self.lock = asyncio.Lock()
        self.last_refresh = 0
        self.refresh_interval = 300

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
                        for p in raw_proxies[:50]:
                            proxy_url = f"http://{p}"
                            if await self.test_proxy(proxy_url):
                                working.append(proxy_url)
                        async with self.lock:
                            self.proxies = working
                            self.current_index = 0
                        add_log("info", f"Loaded {len(working)} working proxies")
                        return len(working)
        except Exception as e:
            add_log("error", f"Proxy fetch failed: {e}")
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
]
def get_random_ua():
    return random.choice(USER_AGENTS)

# ---------- FASTAPI ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# HTML Dashboard (with activity log)
HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Community Finder - Fast Proxy Mode</title>
    <style>
        body { background: #0a0f1a; color: #eef; font-family: monospace; padding: 20px; }
        .container { max-width: 1400px; margin: auto; }
        .stats { display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 20px; }
        .stat-card { background: #16213e; padding: 15px; border-radius: 10px; }
        .stat-value { font-size: 2em; font-weight: bold; color: #0f0; }
        .flex { display: flex; gap: 20px; flex-wrap: wrap; }
        .hits-table, .log-panel { background: #16213e; border-radius: 10px; padding: 15px; flex: 1; }
        .log-panel { max-height: 500px; overflow-y: auto; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 8px; text-align: left; border-bottom: 1px solid #2a3a5a; }
        th { background: #0f3460; color: #0f0; }
        .log-entry { padding: 5px; border-bottom: 1px solid #2a3a5a; font-size: 12px; }
        .log-hit { color: #0f0; }
        .log-rate_limit { color: #ff9800; }
        .log-error { color: #f66; }
        .log-info { color: #aaa; }
        button { background: #0f3460; color: #0f0; border: none; padding: 8px 16px; border-radius: 5px; cursor: pointer; }
    </style>
</head>
<body>
<div class="container">
    <h1>⚡ Roblox Community Finder - Fast Proxy Mode</h1>
    <div class="stats" id="stats"></div>
    <div class="flex">
        <div class="hits-table">
            <h3>📌 Recent Hits</h3>
            <table id="hitsTable">
                <thead><tr><th>Time</th><th>ID</th><th>Name</th><th>Members</th></tr></thead>
                <tbody id="hitsBody"><tr><td colspan="4">Loading...<\/td><\/tr><\/tbody>
            <\/table>
        <\/div>
        <div class="log-panel">
            <h3>🔄 Live Activity Log (Proxy ON)</h3>
            <div id="logContainer"><\/div>
        <\/div>
    <\/div>
    <div style="margin-top: 20px;">
        <button onclick="testWebhook()">📢 Test Webhook</button>
        <button onclick="location.reload()">🔄 Refresh</button>
    <\/div>
<\/div>
<script>
    async function loadStats() {
        let res = await fetch('/api/status');
        let data = await res.json();
        document.getElementById('stats').innerHTML = `
            <div class="stat-card"><div class="stat-value">${data.total_hits}<\/div><div>Total Hits<\/div><\/div>
            <div class="stat-card"><div class="stat-value">${data.id_range}<\/div><div>ID Range<\/div><\/div>
            <div class="stat-card"><div class="stat-value">${data.concurrency}<\/div><div>Concurrency<\/div><\/div>
            <div class="stat-card"><div class="stat-value">${data.proxy_enabled ? '✅ ON' : '❌ OFF'}<\/div><div>Proxy<\/div><\/div>
        `;
    }
    async function loadHits() {
        let res = await fetch('/api/hits');
        let data = await res.json();
        let tbody = document.getElementById('hitsBody');
        if (!data.hits.length) { tbody.innerHTML = '<tr><td colspan="4">No hits yet<\/td><\/tr>'; return; }
        let html = '';
        for (let h of data.hits) {
            let time = new Date(h.timestamp * 1000).toLocaleString();
            html += `<tr><td>${time}<\/td><td><a href="https://www.roblox.com/groups/group.aspx?gid=${h.id}" target="_blank">${h.id}<\/a><\/td><td>${escapeHtml(h.name)}<\/td><td>${h.members}<\/td><\/tr>`;
        }
        tbody.innerHTML = html;
    }
    async function loadLogs() {
        let res = await fetch('/api/logs');
        let logs = await res.json();
        let container = document.getElementById('logContainer');
        if (!logs.length) { container.innerHTML = '<div>No activity yet<\/div>'; return; }
        let html = '';
        for (let log of logs) {
            let time = new Date(log.time * 1000).toLocaleTimeString();
            let cls = `log-${log.type}`;
            html += `<div class="log-entry ${cls}">[${time}] ${escapeHtml(log.message)}<\/div>`;
        }
        container.innerHTML = html;
    }
    async function testWebhook() {
        let res = await fetch('/api/test-webhook');
        let data = await res.json();
        alert(data.message);
    }
    function escapeHtml(str) { return str.replace(/[&<>]/g, function(m){ return m==='&'?'&amp;':m==='<'?'&lt;':'&gt;'; }); }
    loadStats(); loadHits(); loadLogs();
    setInterval(() => { loadStats(); loadHits(); loadLogs(); }, 3000);
<\/script>
<\/body>
<\/html>"""

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=HTML_PAGE)

@app.get("/api/hits")
async def api_hits():
    hits = get_hits_from_db(limit=100)
    return {"hits": hits}

@app.get("/api/logs")
async def api_logs():
    return activity_log[:100]

@app.get("/api/status")
async def api_status():
    return {
        "status": "running",
        "id_range": f"{ID_MIN}–{ID_MAX}",
        "concurrency": CONCURRENCY,
        "total_hits": get_total_hits_count(),
        "proxy_enabled": USE_PROXY
    }

@app.get("/api/test-webhook")
async def test_webhook():
    try:
        embed = Embed(title="✅ Webhook Test", description="Proxy mode is ON – this message proves it works!", color=0x00ff00)
        embed.set_footer(text="Credits: McClaimer")
        await asyncio.to_thread(webhook.send, embed=embed)
        add_log("info", "Test webhook sent successfully")
        return {"message": "Test webhook sent! Check Discord."}
    except Exception as e:
        add_log("error", f"Test webhook failed: {e}")
        return {"error": str(e)}

# ---------- DISCORD & SCANNER ----------
webhook = Webhook(WEBHOOK_URL)
start_time = time.time()

async def send_heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            uptime = str(timedelta(seconds=int(time.time() - start_time)))
            embed = Embed(title="💓 Bot Heartbeat (Proxy ON)", color=0x00ff00, timestamp="now")
            embed.add_field(name="Uptime", value=uptime, inline=True)
            embed.add_field(name="Total Hits", value=str(get_total_hits_count()), inline=True)
            embed.add_field(name="Proxy", value="Rotating", inline=True)
            embed.set_footer(text="Fast mode | Credits: McClaimer")
            await asyncio.to_thread(webhook.send, embed=embed)
            add_log("info", "Heartbeat sent")
        except Exception as e:
            add_log("error", f"Heartbeat failed: {e}")

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
    try:
        embed = Embed(title=f"🎯 JOINABLE! {details['name']}", url=f"https://www.roblox.com/groups/group.aspx?gid={group_id}", color=0x00ff00, timestamp="now")
        embed.add_field(name="ID", value=str(group_id), inline=True)
        embed.add_field(name="Members", value=details["memberCount"], inline=True)
        embed.add_field(name="Public Entry", value=details["publicEntryAllowed"], inline=True)
        embed.set_footer(text="Fast proxy mode | Credits: McClaimer")
        if hasattr(webhook, '_session'):
            thumb = await get_thumbnail(webhook._session, group_id)
            if thumb:
                embed.set_thumbnail(thumb)
        await asyncio.to_thread(webhook.send, embed)
        add_log("info", f"Discord sent for {group_id}")
    except Exception as e:
        add_log("error", f"Discord send failed: {e}")

async def check_group(session, group_id, semaphore, retry=0):
    async with semaphore:
        try:
            proxy = await proxy_manager.get_next_proxy() if USE_PROXY else None
            headers = {"User-Agent": get_random_ua()}
            async with session.get(f"https://groups.roblox.com/v1/groups/{group_id}", headers=headers, timeout=10, proxy=proxy) as resp:
                if resp.status == 429:
                    wait = min(2 ** retry, 60)
                    add_log("rate_limit", f"Rate limited on {group_id}, waiting {wait}s", group_id)
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
                    add_log("hit", f"FOUND: {details['name']} (ID: {group_id})", group_id)
                    save_hit_to_db(group_id, details)
                    await send_discord(group_id, details)
        except asyncio.TimeoutError:
            add_log("error", f"Timeout on {group_id}", group_id)
        except Exception as e:
            add_log("error", f"Error checking {group_id}: {e}", group_id)

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
    add_log("info", f"🚀 Bot started in FAST PROXY MODE – scanning {ID_MIN}–{ID_MAX} with concurrency {CONCURRENCY}")
    try:
        embed = Embed(title="✅ Bot Started (Fast Proxy Mode)", description=f"Scanning {ID_MIN}–{ID_MAX} with {CONCURRENCY} concurrent requests via rotating proxies.", color=0x00ff00)
        embed.add_field(name="Proxy", value="Enabled & Rotating", inline=True)
        await asyncio.to_thread(webhook.send, embed=embed)
        add_log("info", "Startup webhook sent")
    except Exception as e:
        add_log("error", f"Startup webhook failed: {e}")
    asyncio.create_task(send_heartbeat())
    await scanner_worker()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_scanner())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
