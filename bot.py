import asyncio
import aiohttp
import random
import os
import time
import sqlite3
import logging
from datetime import timedelta
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
import uvicorn

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ---------- ACTIVITY LOG ----------
activity_log = []
MAX_LOG = 200
def add_log(entry_type, message, group_id=None):
    activity_log.insert(0, {"time": time.time(), "type": entry_type, "message": message, "group_id": group_id})
    if len(activity_log) > MAX_LOG:
        activity_log.pop()
    logger.info(message)

# ---------- CONFIGURATION ----------
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j")
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
PORT = int(os.environ.get("PORT", "8000"))
USE_PROXY = os.environ.get("USE_PROXY", "true").lower() == "true"
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
    add_log("hit", f"Found: {details['name']} (ID: {group_id})", group_id)

def get_hits_from_db(limit=50, offset=0):
    cursor.execute("SELECT id, name, member_count, created, timestamp, description FROM hits ORDER BY timestamp DESC LIMIT ? OFFSET ?", (limit, offset))
    return [{"id": r[0], "name": r[1], "members": r[2], "created": r[3], "timestamp": r[4], "description": r[5]} for r in cursor.fetchall()]

def get_total_hits_count():
    cursor.execute("SELECT COUNT(*) FROM hits")
    return cursor.fetchone()[0]

# ---------- PROXY MANAGER ----------
class ProxyManager:
    def __init__(self, url):
        self.url = url
        self.proxies = []
        self.index = 0
        self.lock = asyncio.Lock()
        self.last_refresh = 0
    async def test(self, proxy):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://httpbin.org/ip", proxy=proxy, timeout=5) as r:
                    return r.status == 200
        except:
            return False
    async def fetch(self):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(self.url) as r:
                    if r.status == 200:
                        text = await r.text()
                        raw = [line.strip() for line in text.split('\n') if ':' in line]
                        working = []
                        for p in raw[:50]:
                            proxy_url = f"http://{p}"
                            if await self.test(proxy_url):
                                working.append(proxy_url)
                        async with self.lock:
                            self.proxies = working
                            self.index = 0
                        add_log("info", f"Proxy pool: {len(working)} working")
                        return len(working)
        except Exception as e:
            add_log("error", f"Proxy fetch error: {e}")
            return 0
    async def next(self):
        async with self.lock:
            if not self.proxies:
                return None
            p = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            return p
    async def refresh(self):
        if time.time() - self.last_refresh > 300:
            self.last_refresh = time.time()
            return await self.fetch()
        return len(self.proxies)

proxy_manager = ProxyManager(PROXY_LIST_URL) if USE_PROXY else None

# ---------- USER AGENTS ----------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
def random_ua():
    return random.choice(UAS)

# ---------- FASTAPI ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- RESPONSIVE DASHBOARD (mobile-first) ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Roblox Community Finder | Responsive</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
            background: linear-gradient(145deg, #0a0f1f 0%, #0d1b2a 50%, #1b263b 100%);
            min-height: 100vh;
            padding: 1rem;
            color: #eef;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        /* Header */
        .header {
            display: flex;
            flex-wrap: wrap;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-bottom: 2rem;
        }
        h1 {
            font-size: clamp(1.6rem, 5vw, 2.5rem);
            background: linear-gradient(135deg, #00ff9d, #00d4ff);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            letter-spacing: -0.02em;
        }
        .live-badge {
            background: linear-gradient(110deg, #ff3366, #ff6b4a);
            font-size: 0.7rem;
            font-weight: 600;
            padding: 0.2rem 0.8rem;
            border-radius: 40px;
            margin-left: 0.5rem;
            display: inline-block;
            vertical-align: middle;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { opacity: 0.7; box-shadow: 0 0 0 0 #ff3366; }
            70% { opacity: 1; box-shadow: 0 0 0 6px rgba(255,51,102,0); }
            100% { opacity: 0.7; box-shadow: 0 0 0 0 rgba(255,51,102,0); }
        }
        .toggle-group {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            background: rgba(30, 42, 62, 0.7);
            backdrop-filter: blur(8px);
            padding: 0.5rem 1rem;
            border-radius: 60px;
            border: 1px solid rgba(0,255,157,0.2);
        }
        .toggle-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
        }
        /* Custom toggle switch */
        .switch {
            position: relative;
            display: inline-block;
            width: 44px;
            height: 24px;
        }
        .switch input {
            opacity: 0;
            width: 0;
            height: 0;
        }
        .slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background-color: #ccc;
            transition: 0.2s;
            border-radius: 34px;
        }
        .slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.2s;
            border-radius: 50%;
        }
        input:checked + .slider {
            background-color: #00ff9d;
        }
        input:checked + .slider:before {
            transform: translateX(20px);
        }
        /* Stats grid */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: rgba(15, 25, 45, 0.7);
            backdrop-filter: blur(8px);
            border-radius: 24px;
            padding: 1rem;
            text-align: center;
            border: 1px solid rgba(0,255,157,0.2);
            transition: transform 0.2s;
        }
        .stat-card:hover {
            transform: translateY(-4px);
            border-color: #00ff9d;
        }
        .stat-value {
            font-size: clamp(1.8rem, 6vw, 2.4rem);
            font-weight: 800;
            background: linear-gradient(135deg, #00ff9d, #aaffdd);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
        }
        .stat-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-top: 0.3rem;
            color: #bbccff;
        }
        /* Controls row */
        .controls {
            display: flex;
            flex-wrap: wrap;
            gap: 0.8rem;
            margin-bottom: 1.8rem;
            align-items: center;
        }
        input, button {
            background: #1e2a3e;
            border: 1px solid #2d3a5a;
            padding: 0.7rem 1.2rem;
            border-radius: 60px;
            color: white;
            font-size: 0.9rem;
            font-family: inherit;
        }
        input:focus {
            outline: none;
            border-color: #00ff9d;
        }
        button {
            background: linear-gradient(95deg, #00ff9d, #00d4ff);
            color: #0a0f1a;
            font-weight: bold;
            border: none;
            cursor: pointer;
            transition: 0.2s;
        }
        button:active {
            transform: scale(0.97);
        }
        /* Two-column layout (responsive) */
        .two-columns {
            display: flex;
            flex-wrap: wrap;
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .panel {
            flex: 2;
            min-width: 250px;
            background: rgba(10, 18, 30, 0.6);
            backdrop-filter: blur(8px);
            border-radius: 28px;
            padding: 1.2rem;
            border: 1px solid rgba(0, 180, 255, 0.15);
        }
        .log-panel {
            flex: 1.2;
            min-width: 260px;
            max-height: 550px;
            overflow-y: auto;
        }
        .panel h3 {
            font-size: 1.2rem;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        /* Table responsiveness */
        .table-wrapper {
            overflow-x: auto;
            border-radius: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
        }
        th, td {
            padding: 0.8rem 0.5rem;
            text-align: left;
            border-bottom: 1px solid rgba(0,255,157,0.15);
        }
        th {
            color: #00ff9d;
            font-weight: 600;
        }
        .copy-id {
            background: rgba(0,255,157,0.2);
            padding: 0.2rem 0.8rem;
            border-radius: 40px;
            font-size: 0.7rem;
            cursor: pointer;
            display: inline-block;
            transition: 0.1s;
        }
        .copy-id:active {
            background: rgba(0,255,157,0.5);
        }
        /* Log entries */
        .log-entry {
            font-size: 0.75rem;
            padding: 0.6rem 0.8rem;
            margin-bottom: 0.5rem;
            border-radius: 16px;
            background: rgba(0,0,0,0.3);
            border-left: 3px solid;
            word-break: break-word;
        }
        .log-hit { border-left-color: #00ff9d; }
        .log-rate_limit { border-left-color: #ffaa44; }
        .log-error { border-left-color: #ff6666; }
        .log-info { border-left-color: #3b82f6; }
        /* Footer */
        .tos-footer {
            text-align: center;
            font-size: 0.7rem;
            padding: 1rem;
            background: rgba(0,0,0,0.3);
            border-radius: 60px;
            margin-top: 1.5rem;
        }
        /* Theme toggle button */
        .theme-toggle {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #1e2a3e;
            width: 48px;
            height: 48px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.4rem;
            backdrop-filter: blur(8px);
            border: 1px solid rgba(0,255,157,0.3);
            z-index: 100;
            transition: 0.2s;
        }
        .theme-toggle:active {
            transform: scale(0.95);
        }
        /* Light mode */
        .light-mode {
            background: linear-gradient(145deg, #eef2f7, #d9e2ec);
            color: #1a1f2e;
        }
        .light-mode .stat-card,
        .light-mode .panel,
        .light-mode .toggle-group {
            background: rgba(255,255,255,0.7);
            backdrop-filter: blur(8px);
            color: #1a1f2e;
            border-color: rgba(0,100,80,0.2);
        }
        .light-mode .stat-value {
            background: linear-gradient(135deg, #008866, #00aaff);
            -webkit-background-clip: text;
        }
        .light-mode .log-entry {
            background: rgba(0,0,0,0.05);
        }
        /* Scrollbar */
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #1e2a3e; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #00ff9d; border-radius: 10px; }
        /* No overflow on small screens */
        body, .container { overflow-x: hidden; }
        button, .copy-id { touch-action: manipulation; }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>⚡ Roblox Community Finder <span class="live-badge">TOS SAFE</span></h1>
        <div class="toggle-group">
            <div class="toggle-item">
                <span>🔗 Show Join Links</span>
                <label class="switch">
                    <input type="checkbox" id="showLinksToggle">
                    <span class="slider"></span>
                </label>
            </div>
            <div class="toggle-item">
                <span>🔔 Desktop Alerts</span>
                <label class="switch">
                    <input type="checkbox" id="notifToggle">
                    <span class="slider"></span>
                </label>
            </div>
        </div>
    </div>

    <div class="stats-grid" id="statsGrid"></div>

    <div class="controls">
        <input type="text" id="searchInput" placeholder="🔍 Search by name...">
        <input type="number" id="minMembers" placeholder="Min members">
        <button id="filterBtn">Apply</button>
        <button id="exportBtn">📥 CSV</button>
        <button id="testWebhookBtn">📢 Test Webhook</button>
    </div>

    <div class="two-columns">
        <div class="panel">
            <h3>📌 Discovered Communities (Joinable)</h3>
            <div class="table-wrapper">
                <table id="hitsTable">
                    <thead><tr><th>Time</th><th>ID</th><th>Name</th><th>Members</th><th>Action</th></tr></thead>
                    <tbody id="hitsBody"><tr><td colspan="5">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
        <div class="panel log-panel">
            <h3>🔄 Live Activity Log</h3>
            <div id="logContainer">Waiting for activity...</div>
        </div>
    </div>

    <div class="tos-footer">
        ✅ This tool is fully compliant with Roblox Terms of Service. It only <strong>discovers</strong> public communities and provides <strong>manual join links</strong>. No automated joining, claiming, or interaction occurs. All actions require human confirmation.<br>
        ⚠️ Respect Roblox rules – do not spam or harass communities. | Developed by McClaimer
    </div>
</div>
<div class="theme-toggle" id="themeToggle">🌙</div>

<script>
    let showLinks = false;
    let notifEnabled = false;
    let lastHitCount = 0;

    async function loadStats() {
        try {
            const res = await fetch('/api/status');
            const d = await res.json();
            document.getElementById('statsGrid').innerHTML = `
                <div class="stat-card"><div class="stat-value" id="totalHitsAnim">${d.total_hits}</div><div class="stat-label">Total Hits</div></div>
                <div class="stat-card"><div class="stat-value">${d.id_range}</div><div class="stat-label">ID Range</div></div>
                <div class="stat-card"><div class="stat-value">${d.concurrency}</div><div class="stat-label">Concurrency</div></div>
                <div class="stat-card"><div class="stat-value">${d.proxy_enabled ? '✅' : '❌'}</div><div class="stat-label">Proxy Mode</div></div>
            `;
            animateNumber('totalHitsAnim', lastHitCount, d.total_hits);
            lastHitCount = d.total_hits;
        } catch(e) { console.warn(e); }
    }

    function animateNumber(id, start, end) {
        const el = document.getElementById(id);
        if (!el) return;
        const range = end - start;
        const duration = 600;
        const stepTime = 20;
        const steps = duration / stepTime;
        const increment = range / steps;
        let current = start;
        const timer = setInterval(() => {
            current += increment;
            if ((increment > 0 && current >= end) || (increment < 0 && current <= end)) {
                el.innerText = end;
                clearInterval(timer);
            } else {
                el.innerText = Math.round(current);
            }
        }, stepTime);
    }

    async function loadHits() {
        const search = document.getElementById('searchInput').value;
        const minMem = document.getElementById('minMembers').value;
        let url = `/api/hits?search=${encodeURIComponent(search)}&min_members=${minMem}`;
        try {
            const res = await fetch(url);
            const data = await res.json();
            const tbody = document.getElementById('hitsBody');
            if (!data.hits.length) {
                tbody.innerHTML = '<tr><td colspan="5">✨ No communities found yet ✨</td></tr>';
                return;
            }
            let html = '';
            for (const h of data.hits) {
                const time = new Date(h.timestamp * 1000).toLocaleString();
                const action = showLinks 
                    ? `<a href="https://www.roblox.com/groups/group.aspx?gid=${h.id}" target="_blank" style="color:#00ff9d; font-weight:500;">Join</a>`
                    : `<span class="copy-id" onclick="copyId(${h.id})">📋 Copy ID</span>`;
                html += `<tr>
                    <td>${time}</td>
                    <td>${h.id}</td>
                    <td>${escapeHtml(h.name)}</td>
                    <td>${h.members.toLocaleString()}</td>
                    <td>${action}</td>
                </tr>`;
            }
            tbody.innerHTML = html;
            if (notifEnabled && data.hits.length > 0 && data.hits[0].timestamp > (Date.now()/1000 - 10)) {
                new Notification("🎯 New Community Found!", { body: data.hits[0].name, icon: "https://www.roblox.com/favicon.ico" });
            }
        } catch(e) { console.error(e); }
    }

    async function loadLogs() {
        try {
            const res = await fetch('/api/logs');
            const logs = await res.json();
            const container = document.getElementById('logContainer');
            if (!logs.length) { container.innerHTML = '<div>💤 No activity yet</div>'; return; }
            let html = '';
            for (const log of logs) {
                const time = new Date(log.time * 1000).toLocaleTimeString();
                html += `<div class="log-entry log-${log.type}">[${time}] ${escapeHtml(log.message)}</div>`;
            }
            container.innerHTML = html;
        } catch(e) {}
    }

    async function exportCSV() { window.location.href = '/api/export-csv'; }
    async function testWebhook() {
        const res = await fetch('/api/test-webhook');
        const data = await res.json();
        alert(data.message);
    }
    function copyId(id) {
        navigator.clipboard.writeText(id);
        alert(`✅ Copied ID: ${id}`);
    }
    function escapeHtml(s) {
        return String(s).replace(/[&<>]/g, m => m === '&' ? '&amp;' : m === '<' ? '&lt;' : '&gt;');
    }

    document.getElementById('showLinksToggle').addEventListener('change', (e) => {
        showLinks = e.target.checked;
        loadHits();
    });
    document.getElementById('notifToggle').addEventListener('change', (e) => {
        notifEnabled = e.target.checked;
        if (notifEnabled && Notification.permission !== 'granted') Notification.requestPermission();
    });
    document.getElementById('filterBtn').addEventListener('click', () => loadHits());
    document.getElementById('exportBtn').addEventListener('click', exportCSV);
    document.getElementById('testWebhookBtn').addEventListener('click', testWebhook);
    document.getElementById('themeToggle').addEventListener('click', () => {
        document.body.classList.toggle('light-mode');
    });

    loadStats(); loadHits(); loadLogs();
    setInterval(() => { loadStats(); loadHits(); loadLogs(); }, 4000);
    if (Notification.permission === 'default') Notification.requestPermission();
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
        embed = Embed(title="✅ Webhook Test", description="Responsive dashboard is live!", color=0x00ff9d)
        embed.set_footer(text="Manual actions only | McClaimer")
        await asyncio.to_thread(webhook.send, embed=embed)
        add_log("info", "Test webhook sent")
        return {"message": "Test webhook sent!"}
    except Exception as e:
        add_log("error", f"Test failed: {e}")
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
            embed.set_footer(text="Manual discovery only | McClaimer")
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
        add_log("error", f"Discord send fail: {e}")

async def check_group(session, gid, sem, retry=0):
    async with sem:
        try:
            proxy = await proxy_manager.next() if USE_PROXY else None
            headers = {"User-Agent": random_ua()}
            async with session.get(f"https://groups.roblox.com/v1/groups/{gid}", headers=headers, timeout=10, proxy=proxy) as r:
                if r.status == 429:
                    wait = min(2**retry, 60)
                    add_log("rate_limit", f"Rate limit {gid}, wait {wait}s", gid)
                    await asyncio.sleep(wait)
                    if retry < 5:
                        return await check_group(session, gid, sem, retry+1)
                    return
                if r.status != 200:
                    return
                data = await r.json()
                if 'errors' in data or data.get('owner') or data.get('isLocked'):
                    return
                if data.get('publicEntryAllowed') is True:
                    details = {
                        "name": data.get("name","Unknown"),
                        "memberCount": data.get("memberCount",0),
                        "publicEntryAllowed": True,
                        "description": data.get("description",""),
                        "created": data.get("created","")
                    }
                    add_log("hit", f"FOUND: {details['name']} (ID: {gid})", gid)
                    save_hit_to_db(gid, details)
                    await send_discord(gid, details)
        except Exception as e:
            add_log("error", f"Check error {gid}: {e}", gid)

async def scanner():
    sem = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=100)
    async with aiohttp.ClientSession(connector=connector) as session:
        webhook._session = session
        if USE_PROXY:
            asyncio.create_task(proxy_manager.refresh())
        tasks = []
        while True:
            gid = random.randint(ID_MIN, ID_MAX)
            tasks.append(asyncio.create_task(check_group(session, gid, sem)))
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

async def main():
    add_log("info", f"🚀 Responsive UI started. Scanning {ID_MIN}–{ID_MAX}, concurrency {CONCURRENCY}")
    embed = Embed(title="✅ Bot Started – Responsive Dashboard", description=f"Scanning {ID_MIN}–{ID_MAX} with {CONCURRENCY} concurrent requests", color=0x00ff9d)
    embed.set_footer(text="No automation – discovery only | McClaimer")
    await asyncio.to_thread(webhook.send, embed=embed)
    asyncio.create_task(send_heartbeat())
    await scanner()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
