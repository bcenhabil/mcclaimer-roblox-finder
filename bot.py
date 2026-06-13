import asyncio
import aiohttp
import random
import os
import time
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn

# ---------- CONFIGURATION ----------
# Use environment variables or defaults
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j")
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
PORT = int(os.environ.get("PORT", "8000"))
USE_PROXY = os.environ.get("USE_PROXY", "false").lower() == "true"   # disable proxy by default for stability

# In‑memory store for recent hits
hits_store = []
MAX_HITS = 100
webhook = Webhook(WEBHOOK_URL)

# ---------- FASTAPI APP ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- HTML DASHBOARD (embedded) ----------
HTML_PAGE = """
<!DOCTYPE html>
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
        .live-badge { background: #ff3366; display: inline-block; padding: 0.2rem 0.8rem; border-radius: 20px; font-size: 0.7rem; margin-left: 10px; animation: pulse 1.5s infinite; }
        @keyframes pulse { 0% { opacity: 0.6; } 50% { opacity: 1; } 100% { opacity: 0.6; } }
        table { width: 100%; border-collapse: collapse; background: #16213e; border-radius: 16px; overflow: hidden; }
        th, td { padding: 12px 15px; text-align: left; border-bottom: 1px solid #2a3a5a; }
        th { background: #0f3460; color: #00ff9d; }
        tr:hover { background: #1f2a48; }
        .community-link { color: #00ff9d; text-decoration: none; font-weight: bold; }
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
        <tbody id="hitsBody"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
    <div class="footer">🔔 Informational only – no automated joining.<br><span class="credits">Developed by McClaimer</span></div>
</div>
<script>
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
            if (!hits.length) {
                tbody.innerHTML = '<tr><td colspan="5">No hits yet. Waiting...</td></tr>';
                return;
            }
            let html = '';
            for (let hit of hits) {
                const timeStr = new Date(hit.timestamp * 1000).toLocaleTimeString();
                html += `<tr>
                    <td>${timeStr}</td>
                    <td><a href="https://www.roblox.com/groups/group.aspx?gid=${hit.id}" target="_blank" class="community-link">${hit.id}</a></td>
                    <td>${escapeHtml(hit.name)}</td>
                    <td>${hit.members.toLocaleString()}</td>
                    <td>${hit.created || 'Unknown'}</td>
                </tr>`;
            }
            tbody.innerHTML = html;
        } catch(e) { tbody.innerHTML = '<tr><td colspan="5">Error fetching hits</td></tr>'; }
    }
    function escapeHtml(str) {
        return str.replace(/[&<>]/g, function(m) {
            if (m === '&') return '&amp;';
            if (m === '<') return '&lt;';
            if (m === '>') return '&gt;';
            return m;
        });
    }
    fetchStatus(); fetchHits();
    setInterval(() => { fetchStatus(); fetchHits(); }, 3000);
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=HTML_PAGE)

@app.get("/api/hits")
async def api_hits():
    return {"hits": hits_store[-50:]}

@app.get("/api/status")
async def api_status():
    return {
        "status": "running",
        "id_range": f"{ID_MIN}–{ID_MAX}",
        "concurrency": CONCURRENCY,
        "total_hits": len(hits_store),
        "proxy_enabled": USE_PROXY
    }

# ---------- HELPER: GET GROUP THUMBNAIL ----------
async def get_thumbnail(session, group_id):
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

# ---------- SEND DISCORD EMBED ----------
async def send_discord(group_id, details):
    embed = Embed(
        title=f"🎯 JOINABLE COMMUNITY! {details['name']}",
        url=f"https://www.roblox.com/groups/group.aspx?gid={group_id}",
        color=0x00ff00,
        timestamp="now"
    )
    embed.add_field(name="ID", value=str(group_id), inline=True)
    embed.add_field(name="Members", value=details["memberCount"], inline=True)
    embed.add_field(name="Public Entry", value=details["publicEntryAllowed"], inline=True)
    embed.add_field(name="Owner", value="None (joinable)", inline=False)
    if details.get("description"):
        embed.add_field(name="Description", value=details["description"][:200], inline=False)
    embed.set_footer(text="🔔 Informational only – No automated actions | Credits: McClaimer")
    # Thumbnail if available
    if hasattr(webhook, '_session'):
        thumb = await get_thumbnail(webhook._session, group_id)
        if thumb:
            embed.set_thumbnail(thumb)
    try:
        await asyncio.to_thread(webhook.send, embed)
    except Exception as e:
        print(f"Webhook error: {e}")

# ---------- CHECK A SINGLE GROUP ----------
async def check_group(session, group_id, semaphore):
    async with semaphore:
        try:
            url = f"https://groups.roblox.com/v1/groups/{group_id}"
            async with session.get(url, timeout=10) as resp:
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
                        "description": data.get("description", "")
                    }
                    print(f"[+] HIT: {group_id} - {details['name']}")
                    # Store in memory
                    record = {
                        "id": group_id,
                        "name": details["name"],
                        "members": details["memberCount"],
                        "created": data.get("created", "Unknown")[:10] if data.get("created") else "Unknown",
                        "timestamp": time.time()
                    }
                    hits_store.insert(0, record)
                    if len(hits_store) > MAX_HITS:
                        hits_store.pop()
                    # Send Discord embed
                    await send_discord(group_id, details)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

# ---------- MAIN SCANNER WORKER ----------
async def scanner_worker():
    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=100, ttl_dns_cache=300)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    ) as session:
        # Share session with webhook for thumbnails
        webhook._session = session
        tasks = []
        while True:
            group_id = random.randint(ID_MIN, ID_MAX)
            task = asyncio.create_task(check_group(session, group_id, semaphore))
            tasks.append(task)
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

# ---------- STARTUP ----------
async def start_scanner():
    print("""
    ===================================================
       Roblox Community Finder - 24/7 Async Scanner
       Credits: McClaimer
    ===================================================
    """)
    await asyncio.to_thread(webhook.send, "🚀 24/7 Community Finder started (Credits: McClaimer)")
    print(f"Scanning IDs {ID_MIN}–{ID_MAX} with concurrency {CONCURRENCY}")
    await scanner_worker()

if __name__ == "__main__":
    # Run scanner in background and start API
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(start_scanner())
    # Start FastAPI server (blocking)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
