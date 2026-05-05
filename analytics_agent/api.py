import asyncio
import json
import httpx
import ollama
import psutil
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from pydantic import BaseModel
from dotenv import set_key

from .config import settings
from .database import init_db, get_db, SessionLocal
from .models import TicketAnalytics

# Global state for live tracking
agent_state = {
    "status": "idle",
    "last_check": None,
    "current_ticket": None,
    "total_processed": 0,
    "errors": 0,
    # Backfill tracking
    "mode": "starting",          # 'backfilling' | 'live'
    "backfill_page": 0,
    "backfill_total_fetched": 0,
}

async def fetch_tickets_page(page: int) -> list:
    """Fetch a single page of tickets from the ticketing API.
    Returns an empty list when there are no more pages or the API is unreachable.
    """
    try:
        headers = {}
        if settings.TICKETING_API_KEY:
            headers["Authorization"] = f"Bearer {settings.TICKETING_API_KEY}"
            headers["x-api-key"] = settings.TICKETING_API_KEY

        params = {
            settings.TICKETING_PAGE_PARAM: page,
            settings.TICKETING_PER_PAGE_PARAM: settings.TICKETS_PER_PAGE,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                settings.TICKETING_API_URL,
                params=params,
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 200:
                data = response.json()
                # Support both { tickets: [...] } and plain [...] response formats
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("tickets") or data.get("data") or data.get("results") or []
            else:
                print(f"[Agent] Ticketing API returned HTTP {response.status_code} on page {page}")
    except Exception as e:
        print(f"[Agent] Could not reach ticketing API (page {page}): {e}")
        print("[Agent] → Make sure TICKETING_API_URL and TICKETING_API_KEY are set correctly in .env")

    return []


async def analyze_ticket(ticket: dict):
    """Run Ollama locally to analyze the ticket."""
    client = ollama.Client(host=settings.OLLAMA_HOST)
    # Robust field extraction to handle different API schemas
    tid = ticket.get('id') or ticket.get('ticket_id') or ticket.get('ID')
    subj = ticket.get('subject') or ticket.get('title') or ticket.get('Subject') or ticket.get('name')
    desc = ticket.get('description') or ticket.get('body') or ticket.get('Description') or ticket.get('content')
    comm = ticket.get('comments') or ticket.get('Comments') or 'None'

    prompt = f"""You are an expert IT helpdesk analyst for a banking and financial services organization.
You have studied the organization's full ticket history of 1000+ tickets.
Your job is to analyze support tickets and classify them into the EXACT categories this organization uses.

## ORGANIZATION CONTEXT:
- This is a banking/financial institution with multiple branches: Head Office (HO), Ladies Branch, Town Branch, and remote sites
- Staff use Windows PCs, MS Office, passbook printers, laser printers, Canon printers, and banking software
- Common recurring issues include: printer jams, password resets, site/internet access, antivirus alerts, and Office software problems
- Ticket prefixes like KCUB refer to internal system hostnames

## CATEGORY RULES — use THESE exact categories:

### Printer & Hardware
Use when: printer issue, printer jam, Canon printer, passbook printer, printer not working, toner, scanner, monitor, mouse, keyboard, UPS, projector, hardware failure
Examples: "Printer issue", "Cannon printer issue", "Passbook printer issue", "printer jam"

### Password & Access
Use when: password reset, login failure, account locked, forgot password, can't login, access denied, new user account, user creation
Examples: "password reset", "login issue", "new employee account"

### Network & Connectivity
Use when: internet not working, site not loading, site whitelist, network down, slow internet, VPN, WiFi, IP, DNS, firewall, port blocked
Examples: "site working issue", "site whitelist", "internet not working", "network issue"

### Security & Vulnerability
Use when: virus detected, CVE, vulnerability, malware, antivirus alert, threat detected, suspicious activity, security patch
Examples: "Vulnerability detected in 10.50.53.10: CVE-2020-1112", "Antivirus threat detected"

### Software & Applications
Use when: MS Office, Excel, Word, Outlook, software crash, installation, application error, software not opening, folder issue, file issue
Examples: "excel issue", "MS office installation", "folder opening issue", "application not responding"

### Banking System
Use when: core banking, CBS, Finacle, banking software, transaction error, account processing, banking portal, system KCUB
Examples: "KCUB: Stale Status Report on system kcub-07-005", "core banking issue"

### Email & Communication
Use when: email not working, Outlook, mail not sending, Teams, communication tools

### Server & Infrastructure
Use when: server down, server unreachable, database, backup failure, disk space, system performance, domain issue

## PRIORITY RULES
- CRITICAL: Multiple users/branches affected, banking system down, security breach with active CVE, data loss risk
- HIGH: Single branch impacted, printer down in a busy branch, security vulnerability detected, SLA breach likely
- MEDIUM: Single user affected, workaround exists, password reset, software install
- LOW: Minor inconvenience, how-to question, non-urgent request

## OUTPUT FORMAT
Return ONLY a valid JSON object with NO markdown and NO backticks. Use exactly these fields:
- category: (string)
- priority: (string: "CRITICAL", "HIGH", "MEDIUM", or "LOW")
- resolution_summary: (string: 1-2 sentence actionable resolution using expert knowledge)
- escalate_to: (string: "L1 Support", "L2 Support", "L3/Engineering", or "Security Team")
- time_to_resolve_estimate: (string: e.g., "15 mins", "2 hours", "1 day")
- sentiment: (string: "Positive", "Neutral", "Negative", or "Frustrated")
- key_symptoms: (array of 2-3 short strings)

## TICKET TO ANALYZE:
Ticket ID: {tid}
Subject: {subj}
Description: {desc}
Comments: {comm}
"""
    try:
        response = client.chat(
            model=settings.OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "temperature": 0.1,
                "num_predict": 512,
                "num_ctx": 1024,
                "num_thread": settings.OLLAMA_NUM_THREADS,
            },
            format="json"
        )
        content = response["message"]["content"]
        # Robust JSON cleaning: remove markdown backticks if present
        if content.startswith("```"):
            content = content.strip("```").strip("json").strip()
        return json.loads(content)
    except Exception as e:
        print(f"Ollama error on ticket {ticket.get('id')}: {e}")
        return {
            "category": "Unknown",
            "resolution_summary": "Failed to analyze",
            "time_to_resolve_estimate": "Unknown",
            "sentiment": "Neutral"
        }

async def push_to_ticketing_api(ticket_id: str, analysis: dict):
    """Push the analyzed intelligence back to the Ticketing System dashboard."""
    if not settings.TICKETING_API_KEY:
        return
        
    try:
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {settings.TICKETING_API_KEY}", 
                "Content-Type": "application/json",
                "x-api-key": settings.TICKETING_API_KEY # Some systems use this instead
            }
            payload = {
                "ticket_id": ticket_id,
                "agent_analysis": analysis
            }
            await client.post(settings.TICKETING_UPDATE_URL, json=payload, headers=headers, timeout=5.0)
    except Exception as e:
        print(f"Failed to push analysis to ticketing API for {ticket_id}: {e}")

async def process_ticket_batch(tickets: list, db_session):
    """Analyze and store a batch of tickets. Skips already-processed ones.
    Returns the count of newly processed tickets.
    """
    new_count = 0
    for t in tickets:
        # Debug: Print the structure of the first ticket in the batch
        if new_count == 0:
            print(f"[Agent] First ticket fields: {list(t.keys())}")

        tid = t.get("id") or t.get("ticket_id") or t.get("ID")
        if not tid:
            continue

        # Skip if already in DB
        if db_session.query(TicketAnalytics).filter(TicketAnalytics.ticket_id == str(tid)).first():
            continue

        agent_state["current_ticket"] = str(tid)
        agent_state["status"] = "processing"

        analysis = await analyze_ticket(t)

        record = TicketAnalytics(
            ticket_id=str(tid),
            category=analysis.get("category", "Unknown"),
            priority=analysis.get("priority", "MEDIUM"),
            resolution_summary=analysis.get("resolution_summary", ""),
            escalate_to=analysis.get("escalate_to", "L1 Support"),
            time_to_resolve_estimate=analysis.get("time_to_resolve_estimate", ""),
            sentiment=analysis.get("sentiment", "Neutral"),
            key_symptoms=analysis.get("key_symptoms", []),
            raw_context=t
        )
        db_session.add(record)
        db_session.commit()

        await push_to_ticketing_api(str(tid), analysis)
        agent_state["total_processed"] += 1
        new_count += 1

        # Throttle to protect CPU between tickets
        await asyncio.sleep(settings.BACKFILL_DELAY_SECONDS)

    return new_count


async def agent_worker():
    """Background worker: two-phase operation.

    Phase 1 — BACKFILL: Reads ALL tickets from page 1 to the last page.
               Skips tickets already in the DB. This runs once on startup
               and ensures every historical ticket is analyzed.

    Phase 2 — LIVE: Polls page 1 every POLL_INTERVAL_SECONDS to catch
               newly created tickets in real time. Runs 24/7 indefinitely.
    """
    print("[Agent] Worker started.")

    # ── Phase 1: Backfill ────────────────────────────────────────────
    print("[Agent] Phase 1 — Starting historical backfill from page 1...")
    agent_state["mode"] = "backfilling"
    page = 1
    consecutive_empty_pages = 0

    while True:
        agent_state["status"] = "polling"
        agent_state["backfill_page"] = page
        agent_state["last_check"] = datetime.utcnow().isoformat()

        tickets = await fetch_tickets_page(page)

        if not tickets:
            # Two consecutive empty pages = we've reached the end
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 2:
                print(f"[Agent] Backfill complete. Total processed so far: {agent_state['total_processed']}")
                break
        else:
            consecutive_empty_pages = 0
            agent_state["backfill_total_fetched"] += len(tickets)
            agent_state["status"] = "processing"

            with SessionLocal() as db:
                await process_ticket_batch(tickets, db)

        page += 1
        # Brief pause between pages to avoid hammering the API or Ollama
        await asyncio.sleep(1)

    # ── Phase 2: Live polling ────────────────────────────────────────
    print("[Agent] Phase 2 — Switching to live polling mode.")
    agent_state["mode"] = "live"

    while True:
        agent_state["status"] = "polling"
        agent_state["last_check"] = datetime.utcnow().isoformat()
        agent_state["current_ticket"] = None

        # Only check the first page for new tickets
        tickets = await fetch_tickets_page(1)

        if tickets:
            agent_state["status"] = "processing"
            with SessionLocal() as db:
                new = await process_ticket_batch(tickets, db)
                if new > 0:
                    print(f"[Agent] Live: processed {new} new ticket(s).")

        agent_state["status"] = "sleeping"
        agent_state["current_ticket"] = None
        await asyncio.sleep(settings.POLL_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Initialize total processed counter from DB
    with SessionLocal() as db:
        count = db.query(TicketAnalytics).count()
        agent_state["total_processed"] = count

    # Warm up Ollama — load the model into memory NOW so the first chat
    # request doesn't pay the cold-start penalty (can be 20-40s on CPU).
    print(f"[Agent] Warming up model {settings.OLLAMA_MODEL}...")
    try:
        _warmup_client = ollama.Client(host=settings.OLLAMA_HOST)
        _warmup_client.chat(
            model=settings.OLLAMA_MODEL,
            messages=[{"role": "user", "content": "hi"}],
            options={
                "num_predict": 1,         # Generate just 1 token — enough to load the model
                "num_ctx": 256,
                "num_thread": settings.OLLAMA_NUM_THREADS,
                "keep_alive": -1,         # Keep model in memory indefinitely
            }
        )
        print(f"[Agent] Model warm. Ready for chat requests.")
    except Exception as e:
        print(f"[Agent] Warmup warning: {e}")

    task = asyncio.create_task(agent_worker())
    yield
    task.cancel()

app = FastAPI(title="Offline Agent Dashboard", lifespan=lifespan)

# Allow all origins for the dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/live-status")
def get_live_status():
    # Append system health
    status = agent_state.copy()
    try:
        status["system_health"] = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
    except Exception:
        pass
    return status

class SettingsUpdate(BaseModel):
    ticketing_api_key: str

@app.get("/api/settings")
def get_settings():
    has_key = bool(settings.TICKETING_API_KEY)
    masked_key = ""
    if has_key:
        key_len = len(settings.TICKETING_API_KEY)
        if key_len > 4:
            masked_key = "****" + settings.TICKETING_API_KEY[-4:]
        else:
            masked_key = "****"
    return {"has_key": has_key, "masked_key": masked_key}

@app.post("/api/settings")
def update_settings(update: SettingsUpdate):
    settings.TICKETING_API_KEY = update.ticketing_api_key
    # Try to persist to .env file in the root
    try:
        set_key(".env", "TICKETING_API_KEY", update.ticketing_api_key)
    except Exception as e:
        print(f"Failed to persist API key to .env: {e}")
    return {"status": "success"}

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(TicketAnalytics).count()
    recent = db.query(TicketAnalytics).order_by(TicketAnalytics.created_at.desc()).limit(15).all()
    all_records = db.query(TicketAnalytics).all()

    # Aggregations
    categories = {}
    sentiments = {}
    priorities = {}
    escalations = {}
    for r in all_records:
        # Guard against None/empty values to prevent 'undefined' in charts
        cat = r.category or "Unknown"
        sen = r.sentiment or "Neutral"
        categories[cat] = categories.get(cat, 0) + 1
        sentiments[sen] = sentiments.get(sen, 0) + 1
        if r.priority:
            priorities[r.priority] = priorities.get(r.priority, 0) + 1
        if r.escalate_to:
            escalations[r.escalate_to] = escalations.get(r.escalate_to, 0) + 1


    return {
        "total_analyzed": total,
        "categories": categories,
        "sentiments": sentiments,
        "priorities": priorities,
        "escalations": escalations,
        "recent_tickets": [
            {
                "ticket_id": r.ticket_id,
                "category": r.category,
                "priority": r.priority,
                "sentiment": r.sentiment,
                "escalate_to": r.escalate_to,
                "resolution_summary": r.resolution_summary,
                "time_to_resolve_estimate": r.time_to_resolve_estimate,
                "key_symptoms": r.key_symptoms or [],
                "created_at": r.created_at.isoformat()
            } for r in recent
        ]
    }

class ChatMessage(BaseModel):
    message: str

def _build_chat_context(db: Session):
    """Build a compact system prompt from the DB. Kept small to reduce token count
    and lower time-to-first-token during inference."""
    total = db.query(TicketAnalytics).count()
    # Only use top-5 recent tickets — enough context, far fewer tokens
    recent = db.query(TicketAnalytics).order_by(TicketAnalytics.created_at.desc()).limit(5).all()

    categories: dict = {}
    sentiments: dict = {}
    priorities: dict = {}
    # Use ALL records for accurate breakdowns but only query needed columns to avoid pulling massive JSONs
    for r in db.query(TicketAnalytics.category, TicketAnalytics.sentiment, TicketAnalytics.priority).all():
        cat = r.category or "Unknown"
        sen = r.sentiment or "Neutral"
        categories[cat] = categories.get(cat, 0) + 1
        sentiments[sen] = sentiments.get(sen, 0) + 1
        if r.priority:
            priorities[r.priority] = priorities.get(r.priority, 0) + 1

    ticket_lines = "\n".join([
        f"{r.ticket_id}|{r.priority or '?'}|{r.category or '?'}|{r.sentiment or '?'}|{r.escalate_to or '?'}"
        for r in recent
    ]) or "none"

    system_prompt = (
        f"You are an IT helpdesk AI analyst. Answer questions about ticket data concisely.\n"
        f"STATS: total={total}, categories={categories}, sentiments={sentiments}, priorities={priorities}\n"
        f"RECENT TICKETS (id|priority|category|sentiment|escalate):\n{ticket_lines}\n"
        f"Rules: Be brief. Reference real data. If asked if working, confirm and summarize stats."
    )
    return system_prompt


@app.post("/api/chat")
async def chat_with_agent(payload: ChatMessage, db: Session = Depends(get_db)):
    """Streaming chat — tokens are sent word-by-word via SSE so the UI
    updates immediately without waiting for the full response."""
    system_prompt = _build_chat_context(db)
    
    async def token_stream():
        try:
            client = ollama.AsyncClient(host=settings.OLLAMA_HOST)
            # await the chat call, then async iterate over the stream
            response_stream = await client.chat(
                model=settings.OLLAMA_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": payload.message}
                ],
                stream=True,
                options={
                    "temperature": 0.2,        # Lower = more focused, faster convergence
                    "num_predict": 300,        # Short answers only
                    "num_ctx": 512,            # Smallest viable context window
                    "num_thread": settings.OLLAMA_NUM_THREADS,
                    "keep_alive": -1,          # Keep model hot between requests
                }
            )
            async for chunk in response_stream:
                token = chunk["message"]["content"]
                # SSE format: data: <json>\n\n
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            yield f"data: {json.dumps({'token': error_msg})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(token_stream(), media_type="text/event-stream")

import os

# Mount the dashboard UI
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
os.makedirs(dashboard_path, exist_ok=True)
app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
