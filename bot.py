import asyncio
import aiohttp
import random
import os
import time
from threading import Thread
from dhooks import Webhook, Embed
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ---------- CONFIGURATION ----------
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1367791217651220500/eWvP-ncpHXpEaB8smp-MvNakQGB1TjAXLQOmuWyZLL_7hE9NCEaby5v2lpHKkWIlrZ5j"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", DEFAULT_WEBHOOK)
ID_MIN = int(os.environ.get("ID_MIN", "1000000"))
ID_MAX = int(os.environ.get("ID_MAX", "1150000"))
CONCURRENCY = int(os.environ.get("CONCURRENCY", "200"))
API_PORT = int(os.environ.get("PORT", "8000"))

hits_store = []
MAX_HITS_STORED = 100
webhook = Webhook(WEBHOOK_URL)

# ---------- FASTAPI ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/api/hits")
async def get_hits():
    return {"hits": hits_store[-50:]}

@app.get("/api/status")
async def get_status():
    return {
        "status": "running",
        "id_range": f"{ID_MIN}–{ID_MAX}",
        "concurrency": CONCURRENCY,
        "total_hits": len(hits_store)
    }

def run_api():
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)

# ---------- THUMBNAIL ----------
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

# ---------- DISCORD EMBED (with credits) ----------
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

    # Footer with disclaimer AND credits
    embed.set_footer(text="🔔 Informational only – No automated actions | Credits: McClaimer")

    thumb = await get_community_thumbnail(webhook._session, group_id) if hasattr(webhook, '_session') else None
    if thumb:
        embed.set_thumbnail(thumb)

    try:
        await asyncio.to_thread(webhook.send, embed)
    except Exception as e:
        print(f"Webhook error: {e}")

# ---------- CHECK COMMUNITY ----------
async def check_community(session, group_id, semaphore):
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

# ---------- SCANNER WORKER ----------
async def scanner_worker():
    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=0, ttl_dns_cache=300)
    async with aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    ) as session:
        webhook._session = session
        tasks = []
        while True:
            group_id = random.randint(ID_MIN, ID_MAX)
            task = asyncio.create_task(check_community(session, group_id, semaphore))
            tasks.append(task)
            if len(tasks) > CONCURRENCY * 2:
                done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

# ---------- MAIN (with credits in console) ----------
async def main():
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
    api_thread = Thread(target=run_api, daemon=True)
    api_thread.start()
    asyncio.run(main())
