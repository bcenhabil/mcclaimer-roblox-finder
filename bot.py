import asyncio
import aiohttp
import random
import os
import time
import sqlite3
import logging
from datetime import timedelta
from collections import deque
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
import uvicorn

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- SCAN LOG (every group checked) ----------
scan_log = deque(maxlen=250)          # last 250 scans for dashboard
check_timestamps = deque(maxlen=10000) # for CPM calculation

def add_scan_log(group_id, result, details=""):
    entry = {"time": time.time(), "group_id": group_id, "result": result, "details": details}
    scan_log.appendleft(entry)
    check_timestamps.append(time.time())

def get_cpm():
    now = time.time()
    cutoff = now - 60
    return sum(1 for ts in check_timestamps if ts > cutoff)

# ---------- ACTIVITY LOG (important events) ----------
activity_log = deque(maxlen=200)
def add_activity(entry_type, message, group_id=None):
    activity_log.appendleft({"time": time.time(), "type": entry_type, "message": message, "group_id": group_id})
    logger.info(message)

# ---------- CONFIGURATION ----------
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j")
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "500"))   # high for speed
PORT = int(os.environ.get("PORT", "8000"))
USE_PROXY = os.environ.get("USE_PROXY", "true").lower() == "true"
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "3600"))

# Multi‑source proxy URLs (free, frequently updated lists)
PROXY_SOURCES = [
    "https://api.proxycrash.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://raw.githubusercontent.com/vuong1330-create/proxy-ditmexm/refs/heads/main/proxy.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt",
    "https://api.proxycrash.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=ipport&format=text&protocol=http&anonymity=elite",
]

# ---------- MULTI-SOURCE PROXY MANAGER ----------
class ProxyManager:
    def __init__(self, sources):
        self.sources = sources
        self.proxies = []
        self.index = 0
        self.lock = asyncio.Lock()
        self.last_refresh = 0
        self.refresh_interval = 600  # 10 minutes

    async def fetch_single_source(self, session, url):
        try:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    lines = [line.strip() for line in text.split('\n') if line.strip() and ':' in line]
                    # ensure http:// prefix
                    proxies = [f"http://{line}" if not line.startswith('http') else line for line in lines]
                    return proxies
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
        return []

    async def fetch_all_sources(self):
        all_proxies = set()
        async with aiohttp.ClientSession() as session:
            tasks = [self.fetch_single_source(session, url) for url in self.sources]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for proxies in results:
                if isinstance(proxies, list):
                    all_proxies.update(proxies)
        # Remove malformed
        valid = [p for p in all_proxies if ':' in p and len(p) < 100]
        return list(valid)

    async def test_proxy(self, proxy):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://httpbin.org/ip", proxy=proxy, timeout=5) as resp:
                    return resp.status == 200
        except:
            return False

    async def refresh(self):
        add_activity("info", f"Fetching proxies from {len(self.sources)} sources...")
        raw_proxies = await self.fetch_all_sources()
        if not raw_proxies:
            add_activity("error", "No proxies fetched, keeping old list")
            return len(self.proxies)

        # Test first 100 proxies for speed (limit testing)
        working = []
        for p in raw_proxies[:100]:
            if await self.test_proxy(p):
                working.append(p)
        # If we have few working, fallback to untested but deduplicated
        if len(working) < 10:
            working = raw_proxies[:500]

        async with self.lock:
            self.proxies = working
            self.index = 0

        # Write to file for persistence
        with open("proxies.txt", "w") as f:
            f.write("\n".join(self.proxies))

        add_activity("info", f"Loaded {len(self.proxies)} working proxies from {len(self.sources)} sources")
        return len(self.proxies)

    async def next(self):
        async with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            return p

    async def ensure_refresh(self):
        if time.time() - self.last_refresh > self.refresh_interval:
            self.last_refresh = time.time()
            return await self.refresh()
        return len(self.proxies)

proxy_manager = ProxyManager(PROXY_SOURCES) if USE_PROXY else None

# ---------- DATABASE (SQLite) ----------
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
    add_activity("hit", f"Found joinable: {details['name']} (ID: {group_id})", group_id)

def get_hits_from_db(limit=50, offset=0):
    cursor.execute("SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
    return [{"id": r[0], "name": r[1], "members": r[2], "created": r[3], "timestamp": r[4], "description": r[5]} for r in cursor.fetchall()]

def get_total_hits_count():
    cursor.execute("SELECT COUNT(*) FROM hits")
    return cursor.fetchone()[0]

# ---------- USER AGENT ROTATION ----------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
def random_ua():
    return random.choice(USER_AGENTS)

# ---------- FASTAPI APP ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- HTML DASHBOARD (CPM + scan log + responsive) ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Roblox Community Finder | Ultra Fast</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, -apple-system, 'Segoe UI', monospace;
            background: linear-gradient(145deg, #0a0f1f, #0d1b2a);
            padding: 1rem;
            color: #eef;
        }
        .container { max-width: 1600px; margin: auto; }
        h1 { font-size: clamp(1.6rem, 5vw, 2.2rem); background: linear-gradient(135deg, #00ff9d, #00d4ff); -webkit-background-clip: text; background-clip: text; color: transparent; }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
            gap: 1rem;
            margin: 1.5rem 0;
        }
        .stat-card {
            background: rgba(15,25,45,0.7);
            backdrop-filter: blur(8px);
            border-radius: 24px;
            padding: 1rem;
            text-align: center;
            border: 1px solid rgba(0,255,157,0.2);
            transition: transform 0.2s;
        }
        .stat-card:hover { transform: translateY(-3px); border-color: #00ff9d; }
        .stat-value {
            font-size: 1.8rem;
            font-weight: 800;
            color: #00ff9d;
        }
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 0.8rem;
            margin: 1rem 0;
        }
        input, button {
            background: #1e2a3e;
            border: none;
            padding: 0.6rem 1rem;
            border-radius: 60px;
            color: white;
            font-size: 0.9rem;
        }
        button {
            background: linear-gradient(95deg, #00ff9d, #00d4ff);
            color: #000;
            font-weight: bold;
            cursor: pointer;
            transition: 0.1s;
        }
        button:active { transform: scale(0.97); }
        .two-columns {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
        }
        .panel {
            flex: 1;
            background: rgba(10,18,30,0.6);
            backdrop-filter: blur(8px);
            border-radius: 28px;
            padding: 1rem;
            overflow-x: auto;
        }
        .log-panel {
            max-height: 550px;
            overflow-y: auto;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.8rem;
        }
        th, td {
            padding: 0.5rem;
            text-align: left;
            border-bottom: 1px solid rgba(0,255,157,0.2);
        }
        th { color: #00ff9d; }
        .scan-entry {
            font-size: 0.7rem;
            padding: 0.3rem;
            border-left: 3px solid;
            margin-bottom: 0.3rem;
            background: rgba(0,0,0,0.2);
            border-radius: 8px;
        }
        .result-joinable { border-left-color: #0f0; }
        .result-owned { border-left-color: #fa0; }
        .result-locked { border-left-color: #f66; }
        .result-no_entry { border-left-color: #888; }
        .result-error { border-left-color: #f66; }
        .result-rate_limit { border-left-color: #ff9900; }
        .footer {
            text-align: center;
            margin-top: 2rem;
            font-size: 0.7rem;
            color: #aaa;
        }
        a { color: #00ff9d; text-decoration: none; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #1e2a3e; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #00ff9d; border-radius: 10px; }
    </style>
</head>
<body>
<div class="container">
    <h1>⚡ Roblox Community Finder <span style="background:#ff3366; padding:0 0.6rem; border-radius:40px; font-size:0.7rem;">ULTRA FAST</span></h1>
    <div class="stats-grid" id="statsGrid"></div>
    <div class="controls">
        <input type="text" id="searchInput" placeholder="🔍 Search by name">
        <input type="number" id="minMembers" placeholder="Min members">
        <button id="filterBtn">Apply</button>
        <button id="exportBtn">📥 CSV</button>
        <button id="testWebhookBtn">📢 Test Webhook</button>
    </div>
    <div class="two-columns">
        <div class="panel">
            <h3>📌 Joinable Communities</h3>
            <div class="table-wrapper">
                <table id="hitsTable">
                    <thead><tr><th>Time</th><th>ID</th><th>Name</th><th>Members</th></tr></thead>
                    <tbody id="hitsBody"><tr><td colspan="4">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
        <div class="panel log-panel">
            <h3>🔄 Scan Log (every group checked)</h3>
            <div id="scanLogContainer"></div>
        </div>
    </div>
    <div class="footer">✅ ToS compliant – discovery only | Multi‑source proxies | CPM: <span id="cpmValue">0</span> checks/min | Developed by McClaimer</div>
</div>
<script>
    let lastHitCount = 0;
    async function loadStats() {
        let res = await fetch('/api/status');
        let d = await res.json();
        document.getElementById('statsGrid').innerHTML = `
            <div class="stat-card"><div class="stat-value">${d.total_hits}</div><div>Total Hits</div></div>
            <div class="stat-card"><div class="stat-value">${d.id_range}</div><div>ID Range</div></div>
            <div class="stat-card"><div class="stat-value">${d.concurrency}</div><div>Concurrency</div></div>
            <div class="stat-card"><div class="stat-value">${d.proxy_enabled ? '✅' : '❌'}</div><div>Proxy Mode</div></div>
        `;
        let cpmRes = await fetch('/api/cpm');
        let cpmData = await cpmRes.json();
        document.getElementById('cpmValue').innerText = cpmData.cpm;
    }
    async function loadHits() {
        let search = document.getElementById('searchInput').value;
        let minMem = document.getElementById('minMembers').value;
        let res = await fetch(`/api/hits?search=${encodeURIComponent(search)}&min_members=${minMem}`);
        let data = await res.json();
        let tbody = document.getElementById('hitsBody');
        if (!data.hits.length) { tbody.innerHTML = '<tr><td colspan="4">✨ No joinable communities yet ✨</td></tr>'; return; }
        let html = '';
        for (let h of data.hits) {
            let time = new Date(h.timestamp * 1000).toLocaleString();
            html += `<tr>
                <td>${time}</td>
                <td><a href="https://www.roblox.com/groups/group.aspx?gid=${h.id}" target="_blank">${h.id}</a></td>
                <td>${escapeHtml(h.name)}</td>
                <td>${h.members.toLocaleString()}</td>
            </tr>`;
        }
        tbody.innerHTML = html;
    }
    async function loadScanLog() {
        let res = await fetch('/api/scanlog');
        let logs = await res.json();
        let container = document.getElementById('scanLogContainer');
        if (!logs.length) { container.innerHTML = '<div>💤 Waiting for first scans...</div>'; return; }
        let html = '';
        for (let log of logs) {
            let time = new Date(log.time * 1000).toLocaleTimeString();
            let resultText = '';
            switch(log.result) {
                case 'joinable': resultText = '✅ JOINABLE'; break;
                case 'owned': resultText = '👑 Owned'; break;
                case 'locked': resultText = '🔒 Locked'; break;
                case 'no_entry': resultText = '🚫 No entry'; break;
                case 'error': resultText = '⚠️ Error'; break;
                case 'rate_limit': resultText = '⏱️ Rate limit'; break;
                default: resultText = log.result;
            }
            html += `<div class="scan-entry result-${log.result}">[${time}] ID ${log.group_id} → ${resultText} ${log.details ? `(${log.details})` : ''}</div>`;
        }
        container.innerHTML = html;
    }
    async function exportCSV() { window.location.href = '/api/export-csv'; }
    async function testWebhook() {
        let res = await fetch('/api/test-webhook');
        let data = await res.json();
        alert(data.message);
    }
    function escapeHtml(s) { return String(s).replace(/[&<>]/g, m => m==='&'?'&amp;':m==='<'?'&lt;':'&gt;'); }
    document.getElementById('filterBtn').onclick = () => loadHits();
    document.getElementById('exportBtn').onclick = exportCSV;
    document.getElementById('testWebhookBtn').onclick = testWebhook;
    loadStats(); loadHits(); loadScanLog();
    setInterval(() => { loadStats(); loadHits(); loadScanLog(); }, 3000);
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=HTML_PAGE)

@app.get("/api/hits")
async def api_hits(search: str = "", min_members: int = 0):
    query = "SELECT id, name, member_count, created, timestamp, description FROM hits WHERE 1=1"
    params = []
    if search:
        query += " AND name LIKE ?"
        params.append(f"%{search}%")
    if min_members > 0:
        query += " AND member_count >= ?"
        params.append(min_members)
    query += " ORDER BY timestamp DESC LIMIT 100"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    return {"hits": [{"id":r[0],"name":r[1],"members":r[2],"created":r[3],"timestamp":r[4],"description":r[5]} for r in rows]}

@app.get("/api/scanlog")
async def api_scanlog():
    return list(scan_log)

@app.get("/api/cpm")
async def api_cpm():
    return {"cpm": get_cpm()}

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
        embed = Embed(title="✅ Webhook Test", description="Multi‑source proxy mode is active and scanning!", color=0x00ff9d)
        embed.set_footer(text="Manual actions only | McClaimer")
        await asyncio.to_thread(webhook.send, embed=embed)
        add_activity("info", "Test webhook sent")
        return {"message": "Test webhook sent! Check Discord."}
    except Exception as e:
        add_activity("error", f"Test failed: {e}")
        return {"error": str(e)}

@app.get("/api/export-csv")
async def export_csv():
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID","Name","Members","Created","Timestamp","Description"])
    cursor.execute("SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC")
    writer.writerows(cursor.fetchall())
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=hits.csv"})

# ---------- DISCORD & SCANNER ----------
webhook = Webhook(WEBHOOK_URL)
start_time = time.time()

async def send_heartbeat():
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            embed = Embed(title="💓 Bot Heartbeat", color=0x00ff9d, timestamp="now")
            embed.add_field(name="Uptime", value=str(timedelta(seconds=int(time.time()-start_time))), inline=True)
            embed.add_field(name="Total Hits", value=str(get_total_hits_count()), inline=True)
            embed.add_field(name="Current CPM", value=str(get_cpm()), inline=True)
            embed.set_footer(text="Multi‑source proxies | McClaimer")
            await asyncio.to_thread(webhook.send, embed=embed)
        except: pass

async def get_thumbnail(session, gid):
    try:
        async with session.get(f"https://thumbnails.roblox.com/v1/groups/icon?groupId={gid}&size=420x420&format=Png", timeout=5) as r:
            if r.status == 200:
                data = await r.json()
                if data.get("data") and data["data"]:
                    return data["data"][0].get("imageUrl")
    except: pass
    return None

async def send_discord(group_id, details):
    try:
        embed = Embed(title=f"🎯 JOINABLE: {details['name']}", url=f"https://www.roblox.com/groups/group.aspx?gid={group_id}", color=0x00ff9d, timestamp="now")
        embed.add_field(name="ID", value=str(group_id), inline=True)
        embed.add_field(name="Members", value=details["memberCount"], inline=True)
        embed.add_field(name="Public Entry", value=details["publicEntryAllowed"], inline=True)
        embed.set_footer(text="Manual join only – ToS compliant | McClaimer")
        thumb = await get_thumbnail(webhook._session, group_id) if hasattr(webhook,'_session') else None
        if thumb:
            embed.set_thumbnail(thumb)
        await asyncio.to_thread(webhook.send, embed)
    except Exception as e:
        add_activity("error", f"Discord send fail: {e}")

async def check_group(session, gid, sem, retry=0):
    async with sem:
        try:
            proxy = await proxy_manager.next() if USE_PROXY else None
            headers = {"User-Agent": random_ua()}
            async with session.get(f"https://groups.roblox.com/v1/groups/{gid}", headers=headers, timeout=10, proxy=proxy) as r:
                if r.status == 429:
                    add_scan_log(gid, "rate_limit", f"retry {retry}")
                    wait = min(2**retry, 30)
                    await asyncio.sleep(wait)
                    if retry < 3:
                        return await check_group(session, gid, sem, retry+1)
                    return
                if r.status != 200:
                    add_scan_log(gid, "error", f"HTTP {r.status}")
                    return
                data = await r.json()
                if 'errors' in data:
                    add_scan_log(gid, "error", "API error")
                    return
                if data.get('owner'):
                    owner_name = data['owner']['name'] if data['owner'] else 'unknown'
                    add_scan_log(gid, "owned", f"owner: {owner_name[:20]}")
                    return
                if data.get('isLocked'):
                    add_scan_log(gid, "locked", "locked")
                    return
                if data.get('publicEntryAllowed') is True:
                    details = {
                        "name": data.get("name", "Unknown"),
                        "memberCount": data.get("memberCount", 0),
                        "publicEntryAllowed": True,
                        "description": data.get("description", ""),
                        "created": data.get("created", "")
                    }
                    add_scan_log(gid, "joinable", details['name'])
                    add_activity("hit", f"Found: {details['name']} (ID: {gid})", gid)
                    save_hit_to_db(gid, details)
                    await send_discord(gid, details)
                else:
                    add_scan_log(gid, "no_entry", "publicEntryAllowed false")
        except asyncio.TimeoutError:
            add_scan_log(gid, "error", "timeout")
        except Exception as e:
            add_scan_log(gid, "error", str(e)[:40])

async def scanner():
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=500, ttl_dns_cache=300)
    async with aiohttp.ClientSession(connector=connector) as session:
        webhook._session = session
        if USE_PROXY:
            await proxy_manager.refresh()
            asyncio.create_task(proxy_manager.ensure_refresh())
        tasks = []
        while True:
            gid = random.randint(ID_MIN, ID_MAX)
            tasks.append(asyncio.create_task(check_group(session, gid, sem)))
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

async def main():
    add_activity("info", f"🚀 Ultra‑fast mode with multi‑source proxies. Range {ID_MIN}–{ID_MAX}, concurrency {CONCURRENCY}")
    embed = Embed(title="✅ Bot Started – Multi‑Source Proxy Mode", description=f"Scanning {ID_MIN}–{ID_MAX} with {CONCURRENCY} concurrent requests\nProxies fetched from {len(PROXY_SOURCES)} sources.", color=0x00ff9d)
    embed.set_footer(text="CPM and scan log active | McClaimer")
    await asyncio.to_thread(webhook.send, embed=embed)
    asyncio.create_task(send_heartbeat())
    await scanner()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
