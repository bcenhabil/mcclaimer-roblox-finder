import asyncio
import aiohttp
import random
import os
import time
from threading import Thread
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
from urllib.parse import urlparse

# ---------- CONFIGURATION ----------
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", DEFAULT_WEBHOOK)
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
API_PORT = int(os.environ.get("PORT", "8000"))

# Proxy configuration
USE_PROXY = os.environ.get("USE_PROXY", "true").lower() == "true"
PROXY_LIST_URL = os.environ.get("PROXY_LIST_URL", "https://raw.githubusercontent.com/fyvri/fresh-proxy-list/archive/storage/classic/all.txt")
PROXY_REFRESH_INTERVAL = int(os.environ.get("PROXY_REFRESH_INTERVAL", "300"))  # 5 minutes

hits_store = []
MAX_HITS_STORED = 100
webhook = Webhook(WEBHOOK_URL)

# ---------- PROXY MANAGER ----------
class ProxyManager:
    def __init__(self, proxy_list_url, refresh_interval=300):
        self.proxy_list_url = proxy_list_url
        self.refresh_interval = refresh_interval
        self.proxies = []
        self.current_index = 0
        self.last_refresh = 0
        self.lock = asyncio.Lock()
        
    async def fetch_proxies(self):
        """Fetch fresh proxy list from GitHub"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.proxy_list_url) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        proxies = [line.strip() for line in text.split('\n') if line.strip() and ':' in line]
                        # Assume HTTP proxies (most common)
                        http_proxies = [f"http://{p}" for p in proxies]
                        async with self.lock:
                            self.proxies = http_proxies
                            self.current_index = 0
                        print(f"[+] Loaded {len(self.proxies)} proxies")
                        return len(self.proxies)
        except Exception as e:
            print(f"[-] Failed to fetch proxies: {e}")
            return 0
    
    async def get_next_proxy(self):
        """Get next proxy in rotation (round-robin)"""
        async with self.lock:
            if not self.proxies:
                return None
            proxy = self.proxies[self.current_index % len(self.proxies)]
            self.current_index += 1
            return proxy
    
    async def refresh_if_needed(self):
        """Refresh proxy list if needed"""
        current_time = time.time()
        if current_time - self.last_refresh > self.refresh_interval:
            self.last_refresh = current_time
            return await self.fetch_proxies()
        return len(self.proxies)
    
    async def get_connector(self):
        """Get a connector for the current proxy (HTTP only)"""
        proxy = await self.get_next_proxy()
        if not proxy:
            return None, None
        # For HTTP proxies, we can use a standard TCPConnector
        # and pass the proxy to session via 'proxy' param later.
        # But aiohttp.ClientSession supports 'proxy' directly.
        return None, proxy

proxy_manager = ProxyManager(PROXY_LIST_URL, PROXY_REFRESH_INTERVAL)

# ---------- FASTAPI ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Embedded HTML Dashboard (abbreviated – full version from previous message)
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Roblox Community Finder – Live Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0a0f1a; color: #eef; padding: 2rem; }
        .container { max-width: 1300px; margin: auto; }
        h1 { text-align: center; background: linear-gradient(135deg, #00ff9d, #00b8ff); -webkit-background-clip: text; background-clip: text; color: transparent; margin-bottom: 0.5rem; }
        .sub { text-align: center; color: #aaa; margin-bottom: 2rem; }
        .stats-grid { display: flex; gap: 1rem; justify-content: center; margin-bottom: 2rem; flex-wrap: wrap; }
        .stat-card { background: #16213e; padding: 1rem 1.5rem; border-radius: 16px; text-align: center; flex: 1; min-width: 150px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .stat-value { font-size: 2rem; font-weight: bold; color: #00ff9d; }
        .stat-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 0.3rem; }
        .live-badge { background: #ff3366; display: inline-block; padding: 0.2rem 0.8rem; border-radius: 20px; font-size: 0.7rem; margin-left: 10px; vertical-align: middle; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
        table { width: 100%; border-collapse: collapse; background: #16213e; border-radius: 16px; overflow: hidden; box-shadow: 0 8px 20px rgba(0,0,0,0.3); }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #2a3a5a; }
        th { background: #0f3460; color: #00ff9d; font-weight: 600; }
        tr:hover { background: #1f2a48; }
        .community-link { color: #00ff9d; text-decoration: none; font-weight: bold; }
        .community-link:hover { text-decoration: underline; }
        .footer { text-align: center; margin-top: 2rem; color: #888; font-size: 0.8rem; }
        .refresh-note { text-align: right; font-size: 0.7rem; color: #aaa; margin-bottom: 0.5rem; }
        .credits { color: #00ff9d; font-weight: bold; }
    </style>
</head>
<body>
<div class="container">
    <h1>🤖 Roblox Community Finder <span class="live-badge">LIVE</span></h1>
    <div class="sub">Real‑time monitor of joinable communities | <span class="credits">Credits: McClaimer</span></div>
    <div class="stats-grid">
        <div class="stat-card"><div class="stat-value" id="totalHits">0</div><div class="stat-label">Total Hits</div></div>
        <div class="stat-card"><div class="stat-value" id="scanRange">—</div><div class="stat-label">ID Range</div></div>
        <div class="stat-card"><div class="stat-value" id="concurrency">—</div><div class="stat-label">Concurrency</div></div>
        <div class="stat-card"><div class="stat-value" id="botStatus">🟢</div><div class="stat-label">Bot Status</div></div>
    </div>
    <div class="refresh-note">↻ Auto‑refreshes every 3 seconds</div>
    <table>
        <thead><tr><th>Time</th><th>Community ID</th><th>Name</th><th>Members</th><th>Created</th></tr></thead>
        <tbody id="hitsBody"><tr><td colspan="5" style="text-align:center">Loading hits...</td></tr></tbody>
    </table>
    <div class="footer">
        🔔 Informational only – no automated joining.<br>
        <span class="credits">Developed by McClaimer</span>
    </div>
</div>
<script>
    const API_BASE = "";
    async function fetchStatus() {
        try {
            const res = await fetch("/api/status");
            const data = await res.json();
            document.getElementById('scanRange').innerText = data.id_range || '?';
            document.getElementById('concurrency').innerText = data.concurrency || '?';
            document.getElementById('botStatus').innerHTML = '🟢 Running';
            document.getElementById('totalHits').innerText = data.total_hits || 0;
        } catch(e) { document.getElementById('botStatus').innerHTML = '🔴 Offline'; }
    }
    async function fetchHits() {
        try {
            const res = await fetch("/api/hits");
            const data = await res.json();
            const hits = data.hits || [];
            const tbody = document.getElementById('hitsBody');
            if (!hits.length) { tbody.innerHTML = '<tr><td colspan="5">No hits yet...</td></tr>'; return; }
            let html = '';
            for (let hit of hits) {
                const timeStr = new Date(hit.timestamp * 1000).toLocaleTimeString();
                html += `<tr><td>${timeStr}</td><td><a href="https://www.roblox.com/groups/group.aspx?gid=${hit.id}" target="_blank" class="community-link">${hit.id}</a></td><td>${escapeHtml(hit.name)}</td><td>${hit.members.toLocaleString()}</td><td>${hit.created || 'Unknown'}</td></tr>`;
            }
            tbody.innerHTML = html;
        } catch(e) { tbody.innerHTML = '<tr><td colspan="5">Error fetching hits</td></tr>'; }
    }
    function escapeHtml(str) { return str.replace(/[&<>]/g, function(m){ return m==='&'?'&amp;':m==='<'?'&lt;':'&gt;'; }); }
    fetchStatus(); fetchHits();
    setInterval(() => { fetchStatus(); fetchHits(); }, 3000);
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)

@app.get("/api/hits")
async def get_hits():
    return {"hits": hits_store[-50:]}

@app.get("/api/status")
async def get_status():
    return {
        "status": "running",
        "id_range": f"{ID_MIN}–{ID_MAX}",
        "concurrency": CONCURRENCY,
        "total_hits": len(hits_store),
        "proxy_enabled": USE_PROXY,
        "proxy_count": len(proxy_manager.proxies) if USE_PROXY else 0
    }

# ---------- THUMBNAIL & DISCORD ----------
async def get_community_thumbnail(session, group_id):
    try:
        url = f"https://thumbnails.roblox.com/v1/groups/icon?groupId={group_id}&size=420x420&format=Png"
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data") and len(data["data"]) > 0:
                    return data["data"][0].get("imageUrl")
    except:
        pass
    return None

async def send_hit_embed(group_id, details):
    embed = Embed(
        title=f"🎯 JOINABLE COMMUNITY! {details.get('name', 'Unknown')}",
        url=f"https://www.roblox.com/groups/group.aspx?gid={group_id}",
        color=0x00ff00,
        timestamp="now"
    )
    embed.add_field(name="ID", value=str(group_id), inline=True)
    embed.add_field(name="Members", value=details.get("memberCount", "?"), inline=True)
    embed.add_field(name="Public Entry", value=details.get("publicEntryAllowed", False), inline=True)
    embed.add_field(name="Owner", value=details.get("owner", "None (joinable)"), inline=False)
    if details.get("description"):
        embed.add_field(name="Description", value=details["description"][:200], inline=False)
    if details.get("created"):
        embed.add_field(name="Created", value=details["created"][:10], inline=True)
    embed.set_footer(text="🔔 Informational only – No automated actions | Credits: McClaimer")
    thumb = await get_community_thumbnail(webhook._session, group_id) if hasattr(webhook, '_session') else None
    if thumb:
        embed.set_thumbnail(thumb)
    try:
        await asyncio.to_thread(webhook.send, embed)
    except Exception as e:
        print(f"Webhook error: {e}")

# ---------- CHECK A SINGLE COMMUNITY ----------
async def check_community(session, group_id, semaphore, proxy=None):
    async with semaphore:
        try:
            url = f"https://groups.roblox.com/v1/groups/{group_id}"
            # Use proxy if provided
            if proxy:
                async with session.get(url, timeout=10, proxy=proxy) as resp:
                    # ... same logic
                    pass
            else:
                async with session.get(url, timeout=10) as resp:
                    # ... same logic
                    pass
            # Actual logic (duplicated for brevity; same as before)
            # We'll rewrite cleanly below
        except:
            pass

# ---------- REVISED CHECK WITH PROXY SUPPORT ----------
async def check_community(session, group_id, semaphore, proxy):
    async with semaphore:
        try:
            url = f"https://groups.roblox.com/v1/groups/{group_id}"
            kwargs = {"timeout": 10}
            if proxy:
                kwargs["proxy"] = proxy
            async with session.get(url, **kwargs) as resp:
                if resp.status == 429:
                    print("[!] Rate limited – waiting 2s")
                    await asyncio.sleep(2)
                    return
                if resp.status != 200:
                    return
                data = await resp.json()
                if 'errors' in data or data.get('owner') is not None or data.get('isLocked', False):
                    return
                if data.get('publicEntryAllowed') is True:
                    details = {
                        "name": data.get("name", "Unknown"),
                        "memberCount": data.get("memberCount", 0),
                        "publicEntryAllowed": True,
                        "owner": "None (joinable)",
                        "description": data.get("description", ""),
                        "created": data.get("created", "Unknown")
                    }
                    print(f"[+] HIT: {group_id} - {details['name']}")
                    hit_record = {
                        "id": group_id,
                        "name": details["name"],
                        "members": details["memberCount"],
                        "created": details["created"][:10] if details["created"] else "Unknown",
                        "timestamp": time.time()
                    }
                    hits_store.insert(0, hit_record)
                    if len(hits_store) > MAX_HITS_STORED:
                        hits_store.pop()
                    await send_hit_embed(group_id, details)
        except Exception:
            pass

# ---------- SCANNER WORKER WITH PROXY ROTATION ----------
async def scanner_worker():
    semaphore = asyncio.Semaphore(CONCURRENCY)
    # Pre-fetch proxy list if enabled
    if USE_PROXY:
        await proxy_manager.fetch_proxies()
        print(f"[+] Proxy rotation enabled with {len(proxy_manager.proxies)} proxies")

    async def proxy_refresh_loop():
        while True:
            await asyncio.sleep(PROXY_REFRESH_INTERVAL)
            if USE_PROXY:
                count = await proxy_manager.refresh_if_needed()
                print(f"[+] Refreshed proxies: {count} active")

    asyncio.create_task(proxy_refresh_loop())

    # We'll use a single session with connection pooling (proxies are per-request)
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    ) as session:
        webhook._session = session  # for thumbnails
        tasks = []
        while True:
            group_id = random.randint(ID_MIN, ID_MAX)
            proxy = await proxy_manager.get_next_proxy() if USE_PROXY else None
            task = asyncio.create_task(check_community(session, group_id, semaphore, proxy))
            tasks.append(task)
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

# ---------- MAIN ----------
async def start_scanner():
    print("""
    ===================================================
       Roblox Community Finder - 24/7 Async Scanner
       Credits: McClaimer
       Proxy Rotation: ENABLED
    ===================================================
    """)
    await asyncio.to_thread(webhook.send, "🚀 24/7 Community Finder started with Proxy Rotation! (Credits: McClaimer)")
    print(f"Scanning IDs {ID_MIN}–{ID_MAX} with concurrency {CONCURRENCY}")
    await scanner_worker()

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)

if __name__ == "__main__":
    # Start the background scanner in the same event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_scanner())
    # Start API server (which runs the loop)
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
