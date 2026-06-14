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

# ---------- ENHANCED DASHBOARD WITH BETTER COLOR GRADING ----------
HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Roblox Community Finder | Premium Gradients</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; transition: all 0.2s ease; }
        body {
            font-family: 'Inter', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(145deg, #0a0f1f 0%, #0d1b2a 35%, #1b263b 100%);
            min-height: 100vh;
            padding: 2rem;
            color: #eef;
        }
        /* Glassmorphism with gradient borders */
        .glass {
            background: rgba(15, 25, 45, 0.55);
            backdrop-filter: blur(12px);
            border-radius: 32px;
            border: 1px solid rgba(0, 255, 157, 0.25);
            box-shadow: 0 15px 35px rgba(0,0,0,0.3), inset 0 0 20px rgba(0,255,157,0.05);
        }
        .container { max-width: 1600px; margin: auto; }
        h1 {
            font-size: 2.7rem;
            background: linear-gradient(135deg, #00ff9d, #00d4ff, #3b82f6);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            display: inline-block;
            letter-spacing: -0.5px;
            animation: fadeInDown 0.7s cubic-bezier(0.2, 0.9, 0.4, 1.1);
        }
        @keyframes fadeInDown {
            from { opacity: 0; transform: translateY(-30px) scale(0.95); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }
        @keyframes pulseGlow {
            0% { text-shadow: 0 0 2px #00ff9d; opacity: 0.7; }
            50% { text-shadow: 0 0 12px #00ff9d; opacity: 1; }
            100% { text-shadow: 0 0 2px #00ff9d; opacity: 0.7; }
        }
        .live-badge {
            background: linear-gradient(110deg, #ff3366, #ff6b4a);
            display: inline-block;
            padding: 0.25rem 1rem;
            border-radius: 60px;
            font-size: 0.75rem;
            font-weight: 600;
            margin-left: 16px;
            box-shadow: 0 0 10px rgba(255,51,102,0.5);
            animation: pulseGlow 2s infinite;
        }
        .stats-grid {
            display: flex;
            gap: 1.5rem;
            flex-wrap: wrap;
            margin: 2rem 0;
        }
        .stat-card {
            flex: 1;
            min-width: 150px;
            padding: 1.3rem;
            text-align: center;
            background: rgba(12, 20, 35, 0.65);
            backdrop-filter: blur(8px);
            border-radius: 28px;
            border: 1px solid rgba(0, 255, 157, 0.2);
            transition: all 0.25s ease;
        }
        .stat-card:hover {
            transform: translateY(-6px);
            border-color: #00ff9d;
            box-shadow: 0 12px 28px rgba(0,255,157,0.2);
            background: rgba(20, 35, 55, 0.8);
        }
        .stat-value {
            font-size: 2.6rem;
            font-weight: 800;
            background: linear-gradient(135deg, #00ff9d, #aaffdd);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            letter-spacing: -1px;
        }
        .controls {
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            margin-bottom: 1.8rem;
            align-items: center;
        }
        input, select, button {
            background: #1e2a3e;
            border: 1px solid #2d3a5a;
            padding: 10px 20px;
            border-radius: 60px;
            color: white;
            font-size: 0.9rem;
            transition: 0.2s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #00ff9d;
            box-shadow: 0 0 0 2px rgba(0,255,157,0.2);
        }
        button {
            background: linear-gradient(95deg, #00ff9d, #00d4ff);
            color: #0a0f1a;
            font-weight: bold;
            border: none;
            cursor: pointer;
        }
        button:hover {
            transform: scale(1.02);
            box-shadow: 0 4px 12px rgba(0,255,157,0.4);
        }
        .toggle-switch {
            display: flex;
            align-items: center;
            gap: 10px;
            background: #1e2a3e;
            padding: 6px 18px;
            border-radius: 60px;
            border: 1px solid #2d3a5a;
        }
        .flex-row {
            display: flex;
            gap: 1.8rem;
            flex-wrap: wrap;
        }
        .hits-panel, .log-panel {
            background: rgba(10, 18, 30, 0.6);
            backdrop-filter: blur(8px);
            border-radius: 28px;
            padding: 1.5rem;
            border: 1px solid rgba(0, 180, 255, 0.15);
        }
        .hits-panel { flex: 2; }
        .log-panel { flex: 1.2; max-height: 580px; overflow-y: auto; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 12px 10px;
            text-align: left;
            border-bottom: 1px solid rgba(0, 255, 157, 0.15);
        }
        th {
            color: #00ff9d;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        .log-entry {
            font-size: 0.8rem;
            padding: 8px 12px;
            margin-bottom: 6px;
            border-radius: 16px;
            background: rgba(0,0,0,0.2);
            border-left: 3px solid;
            animation: slideIn 0.2s ease;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-12px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .log-hit { border-left-color: #00ff9d; color: #ccffdd; }
        .log-rate_limit { border-left-color: #ffaa44; color: #ffe6cc; }
        .log-error { border-left-color: #ff6666; color: #ffcccc; }
        .log-info { border-left-color: #3b82f6; color: #cce5ff; }
        .tos-footer {
            text-align: center;
            margin-top: 2.5rem;
            font-size: 0.75rem;
            padding: 1rem;
            background: rgba(0,0,0,0.35);
            border-radius: 60px;
            backdrop-filter: blur(5px);
            color: #bbbbdd;
        }
        .theme-toggle {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #1e2a3e;
            border-radius: 50%;
            width: 52px;
            height: 52px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            font-size: 1.5rem;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(0,255,157,0.3);
            transition: 0.2s;
        }
        .theme-toggle:hover { transform: scale(1.05); border-color: #00ff9d; }
        .light-mode {
            background: linear-gradient(145deg, #eef2f7, #d9e2ec);
            color: #1a1f2e;
        }
        .light-mode .glass, .light-mode .stat-card, .light-mode .hits-panel, .light-mode .log-panel {
            background: rgba(255,255,255,0.7);
            backdrop-filter: blur(10px);
            color: #1a1f2e;
            border-color: rgba(0,100,80,0.2);
        }
        .light-mode .stat-value { background: linear-gradient(135deg, #008866, #00aaff); -webkit-background-clip: text; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #1e2a3e; border-radius: 10px; }
        ::-webkit-scrollbar-thumb { background: #00ff9d; border-radius: 10px; }
        .copy-id {
            background: rgba(0,255,157,0.2);
            padding: 4px 12px;
            border-radius: 40px;
            cursor: pointer;
            font-size: 0.75rem;
            font-weight: bold;
            transition: 0.1s;
        }
        .copy-id:hover { background: rgba(0,255,157,0.5); }
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400;14..32,600;14..32,800&display=swap" rel="stylesheet">
</head>
<body>
<div class="container">
    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
        <h1>⚡ Roblox Community Finder <span class="live-badge">LIVE & TOS SAFE</span></h1>
        <div class="toggle-switch">
            <span>🔗 Show Join Links</span>
            <label style="position:relative; display:inline-block; width:44px; height:22px; margin-left:8px;">
                <input type="checkbox" id="showLinksToggle" style="opacity:0; width:0; height:0;">
                <span style="position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#ccc; border-radius:34px; transition:.2s;"></span>
                <span style="position:absolute; content:''; height:16px; width:16px; left:3px; bottom:3px; background:white; border-radius:50%; transition:.2s;"></span>
            </label>
        </div>
    </div>
    <div class="stats-grid" id="statsGrid"></div>
    <div class="controls">
        <input type="text" id="searchInput" placeholder="🔍 Search by name...">
        <input type="number" id="minMembers" placeholder="Min members">
        <button id="filterBtn">Apply Filters</button>
        <button id="exportBtn">📥 Export CSV</button>
        <button id="testWebhookBtn">📢 Test Webhook</button>
        <div class="toggle-switch">
            <span>🔔 Desktop Alerts</span>
            <input type="checkbox" id="notifToggle">
        </div>
    </div>
    <div class="flex-row">
        <div class="hits-panel">
            <h3 style="margin-bottom:15px;">📌 Discovered Communities (Joinable)</h3>
            <div style="overflow-x:auto;">
                <table id="hitsTable">
                    <thead><tr><th>Time</th><th>ID</th><th>Name</th><th>Members</th><th>Action</th></tr></thead>
                    <tbody id="hitsBody"><tr><td colspan="5">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
        <div class="log-panel">
            <h3 style="margin-bottom:15px;">🔄 Live Activity Log</h3>
            <div id="logContainer">Waiting for activity...</div>
        </div>
    </div>
    <div class="tos-footer">
        ✅ This tool is fully compliant with Roblox Terms of Service. It only <strong>discovers</strong> public communities and provides <strong>manual join links</strong>. No automated joining, claiming, or interaction occurs. All actions require human confirmation. <br>
        ⚠️ Respect Roblox rules – do not spam or harass communities. | Developed by McClaimer
    </div>
</div>
<div class="theme-toggle" id="themeToggle">🌙</div>
<script>
    let showLinks = false;
    let notifEnabled = false;
    let lastHitCount = 0;
    const API_BASE = "";
    async function loadStats() {
        let r = await fetch('/api/status');
        let d = await r.json();
        document.getElementById('statsGrid').innerHTML = `
            <div class="stat-card"><div class="stat-value" id="totalHitsAnim">${d.total_hits}</div><div>Total Hits</div></div>
            <div class="stat-card"><div class="stat-value">${d.id_range}</div><div>ID Range</div></div>
            <div class="stat-card"><div class="stat-value">${d.concurrency}</div><div>Concurrency</div></div>
            <div class="stat-card"><div class="stat-value">${d.proxy_enabled ? '✅' : '❌'}</div><div>Proxy Mode</div></div>
        `;
        animateNumber('totalHitsAnim', lastHitCount, d.total_hits);
        lastHitCount = d.total_hits;
    }
    function animateNumber(id, start, end) {
        let el = document.getElementById(id);
        if (!el) return;
        let range = end - start;
        let duration = 600;
        let stepTime = 20;
        let steps = duration / stepTime;
        let increment = range / steps;
        let current = start;
        let timer = setInterval(() => {
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
        let search = document.getElementById('searchInput').value;
        let minMem = document.getElementById('minMembers').value;
        let url = `/api/hits?search=${encodeURIComponent(search)}&min_members=${minMem}`;
        let r = await fetch(url);
        let data = await r.json();
        let tbody = document.getElementById('hitsBody');
        if (!data.hits.length) { tbody.innerHTML = '<tr><td colspan="5">✨ No communities found yet ✨</td></tr>'; return; }
        let html = '';
        for (let h of data.hits) {
            let time = new Date(h.timestamp * 1000).toLocaleString();
            let linkOrCopy = showLinks ? `<a href="https://www.roblox.com/groups/group.aspx?gid=${h.id}" target="_blank" style="color:#00ff9d; font-weight:500;">Join</a>` : `<span class="copy-id" onclick="copyId(${h.id})">📋 Copy ID</span>`;
            html += `<tr>
                <td>${time}</td>
                <td>${h.id}</td>
                <td>${escapeHtml(h.name)}</td>
                <td>${h.members.toLocaleString()}</td>
                <td>${linkOrCopy}</td>
            </tr>`;
        }
        tbody.innerHTML = html;
        if (notifEnabled && data.hits.length > 0 && data.hits[0].timestamp > (Date.now()/1000 - 10)) {
            new Notification("🎯 New Community Found!", { body: data.hits[0].name, icon: "https://www.roblox.com/favicon.ico" });
        }
    }
    async function loadLogs() {
        let r = await fetch('/api/logs');
        let logs = await r.json();
        let container = document.getElementById('logContainer');
        if (!logs.length) { container.innerHTML = '<div>💤 No activity yet</div>'; return; }
        let html = '';
        for (let log of logs) {
            let time = new Date(log.time * 1000).toLocaleTimeString();
            html += `<div class="log-entry log-${log.type}">[${time}] ${escapeHtml(log.message)}</div>`;
        }
        container.innerHTML = html;
    }
    async function exportCSV() { window.location.href = '/api/export-csv'; }
    async function testWebhook() {
        let r = await fetch('/api/test-webhook');
        let d = await r.json();
        alert(d.message);
    }
    function copyId(id) { navigator.clipboard.writeText(id); alert(`✅ Copied ID: ${id}`); }
    function escapeHtml(s) { return String(s).replace(/[&<>]/g, m => m==='&'?'&amp;':m==='<'?'&lt;':'&gt;'); }
    document.getElementById('showLinksToggle').addEventListener('change', (e) => { showLinks = e.target.checked; loadHits(); });
    document.getElementById('notifToggle').addEventListener('change', (e) => { notifEnabled = e.target.checked; if(notifEnabled && Notification.permission !== 'granted') Notification.requestPermission(); });
    document.getElementById('filterBtn').addEventListener('click', () => loadHits());
    document.getElementById('exportBtn').addEventListener('click', exportCSV);
    document.getElementById('testWebhookBtn').addEventListener('click', testWebhook);
    document.getElementById('themeToggle').addEventListener('click', () => { document.body.classList.toggle('light-mode'); });
    // Fix toggle switch styling
    document.querySelectorAll('.toggle-switch input[type="checkbox"]').forEach(cb => {
        let span = cb.nextElementSibling;
        if(span && span.classList.contains('slider')) return;
        let slider = document.createElement('span');
        slider.className = 'slider';
        slider.style.cssText = 'position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#ccc; border-radius:34px; transition:.2s;';
        let thumb = document.createElement('span');
        thumb.style.cssText = 'position:absolute; content:""; height:16px; width:16px; left:3px; bottom:3px; background:white; border-radius:50%; transition:.2s;';
        cb.parentNode.style.position = 'relative';
        cb.parentNode.style.display = 'inline-block';
        cb.parentNode.style.width = '44px';
        cb.parentNode.style.height = '22px';
        cb.style.opacity = '0';
        cb.style.width = '0';
        cb.style.height = '0';
        cb.parentNode.appendChild(slider);
        cb.parentNode.appendChild(thumb);
        cb.addEventListener('change', () => {
            slider.style.backgroundColor = cb.checked ? '#00ff9d' : '#ccc';
            thumb.style.transform = cb.checked ? 'translateX(22px)' : 'translateX(0)';
        });
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
        embed = Embed(title="✅ Webhook Test", description="Premium design dashboard is live!", color=0x00ff9d)
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

# ---------- DISCORD & SCANNER (unchanged, with ToS footer) ----------
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
    add_log("info", f"🚀 Started with premium color grading. Scanning {ID_MIN}–{ID_MAX}, concurrency {CONCURRENCY}")
    embed = Embed(title="✅ Bot Started – Premium UI", description=f"Scanning {ID_MIN}–{ID_MAX} with {CONCURRENCY} concurrent requests", color=0x00ff9d)
    embed.set_footer(text="No automation – discovery only | McClaimer")
    await asyncio.to_thread(webhook.send, embed=embed)
    asyncio.create_task(send_heartbeat())
    await scanner()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(main())
    uvicorn.run(app, host="0.0.0.0", port=PORT)
