import asyncio
import json
import httpx
import ollama
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
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
    "errors": 0
}

async def fetch_tickets():
    """Mock/Fetch tickets from the configured external API."""
    try:
        # In a real scenario, this would use the provided TICKETING_API_URL
        # For now, we simulate fetching some unprocessed tickets if the real API fails or isn't set up yet
        async with httpx.AsyncClient() as client:
            # We add a small timeout. If it fails, we yield mock data for demonstration.
            try:
                response = await client.get(settings.TICKETING_API_URL, timeout=3.0)
                if response.status_code == 200:
                    return response.json()
            except Exception:
                pass
                
        # Mock payload — uses FIXED IDs so they are processed ONCE then skipped.
        # Dynamic IDs (total_processed + N) caused an infinite loop where every
        # poll cycle generated unseen IDs, keeping Ollama running non-stop.
        return [
            {"id": "MOCK-001", "subject": "Server Down", "description": "The main database server is unreachable.", "comments": []},
            {"id": "MOCK-002", "subject": "Password Reset", "description": "I forgot my password and cannot log in.", "comments": []},
            {"id": "MOCK-003", "subject": "VPN Not Connecting", "description": "Cannot connect to corporate VPN from home.", "comments": []},
        ]
    except Exception as e:
        print(f"Error fetching tickets: {e}")
        return []

async def analyze_ticket(ticket: dict):
    """Run Ollama locally to analyze the ticket."""
    client = ollama.Client(host=settings.OLLAMA_HOST)
    prompt = f"""You are an expert IT helpdesk analyst with deep knowledge of enterprise infrastructure, networking, and software systems. Your job is to analyze support tickets and extract structured intelligence to help the team prioritize and resolve issues faster.

## YOUR ANALYSIS RULES:

### 1. CATEGORIZATION
Classify the ticket into one of these domains. Be specific:
- Network: connectivity, VPN, DNS, firewall, VLAN, switch, Wi-Fi issues
- Hardware: physical device failures, printers, monitors, laptops, servers
- Access/Auth: login failures, password resets, MFA, Active Directory, permissions
- Database: slow queries, connectivity errors, backup/restore, replication
- Software/App: crashes, bugs, installation errors, performance issues in applications
- Cloud/Infra: VM issues, cloud services, storage, backups
- Security: suspicious activity, malware, policy violations, mass account lockouts
- General: anything that does not fit the above categories

### 2. PRIORITY RULES (apply strictly)
- CRITICAL: Production system down, multiple users affected, data loss risk, or security breach
- HIGH: Single department impacted, key system degraded, SLA breach risk
- MEDIUM: Single user impacted, workaround exists, non-urgent degradation
- LOW: Cosmetic issues, how-to questions, minor inconveniences

### 3. RESOLUTION KNOWLEDGE (use your expertise to suggest real solutions)
- Network issues: check physical layer first (cable/NIC), then addressing (IP/subnet/gateway), then firewall/ACL rules
- Access issues: check account lock status in AD, reset via admin console, check MFA device sync
- Database issues: check connection pool limits, query explain plans, disk space, and replication lag
- Hardware issues: run diagnostics, check event logs, escalate to vendor if device is under warranty
- Software issues: collect logs, check for patches/updates, reproduce in isolated environment

### 4. SENTIMENT DETECTION
- Frustrated: words like "again", "still", "unacceptable", "hours", or indicates this is a repeated issue
- Negative: problem is significant but user is calm
- Neutral: factual report, no strong emotional language
- Positive: polite, not urgent, simply asking for help

## OUTPUT FORMAT
Return ONLY a valid JSON object with NO markdown and NO backticks. Use exactly these fields:
- category: (string)
- priority: (string: "CRITICAL", "HIGH", "MEDIUM", or "LOW")
- resolution_summary: (string: 1-2 sentence actionable resolution using expert knowledge)
- escalate_to: (string: "L1 Support", "L2 Support", "L3/Engineering", or "Security Team")
- time_to_resolve_estimate: (string: e.g., "15 mins", "2 hours", "1 day")
- sentiment: (string: "Positive", "Neutral", "Negative", or "Frustrated")
- key_symptoms: (array of 2-3 short strings identifying core symptoms)

## TICKET TO ANALYZE:
Ticket ID: {ticket.get('id')}
Subject: {ticket.get('subject')}
Description: {ticket.get('description')}
Comments: {ticket.get('comments', 'None')}
"""
    try:
        response = client.chat(
            model=settings.OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.1},
            format="json"
        )
        return json.loads(response["message"]["content"])
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

async def agent_worker():
    """Background task that polls the ticketing API and processes data."""
    print("Agent Worker Started.")
    while True:
        agent_state["status"] = "polling"
        agent_state["last_check"] = datetime.utcnow().isoformat()
        agent_state["current_ticket"] = None
        
        tickets = await fetch_tickets()
        
        if tickets:
            agent_state["status"] = "processing"
            
            with SessionLocal() as db:
                for t in tickets:
                    # Skip if already exists
                    if db.query(TicketAnalytics).filter(TicketAnalytics.ticket_id == t["id"]).first():
                        continue
                        
                    agent_state["current_ticket"] = t["id"]
                    await asyncio.sleep(1) # Simulate think time visually
                    
                    analysis = await analyze_ticket(t)
                    
                    record = TicketAnalytics(
                        ticket_id=t["id"],
                        category=analysis.get("category", "Unknown"),
                        priority=analysis.get("priority", "MEDIUM"),
                        resolution_summary=analysis.get("resolution_summary", ""),
                        escalate_to=analysis.get("escalate_to", "L1 Support"),
                        time_to_resolve_estimate=analysis.get("time_to_resolve_estimate", ""),
                        sentiment=analysis.get("sentiment", "Neutral"),
                        key_symptoms=analysis.get("key_symptoms", []),
                        raw_context=t
                    )
                    db.add(record)
                    db.commit()
                    
                    # Post the processed data back to the ticketing dashboard
                    await push_to_ticketing_api(t["id"], analysis)
                    
                    agent_state["total_processed"] += 1
                    
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
    return agent_state

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
        categories[r.category] = categories.get(r.category, 0) + 1
        sentiments[r.sentiment] = sentiments.get(r.sentiment, 0) + 1
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

@app.post("/api/chat")
def chat_with_agent(payload: ChatMessage, db: Session = Depends(get_db)):
    """Chat with the agent. Injects real ticket DB context into the prompt so the agent
    can answer questions about what it has learned and analyzed."""
    # Build context from the most recent 20 analyzed tickets
    recent = db.query(TicketAnalytics).order_by(TicketAnalytics.created_at.desc()).limit(20).all()
    total = db.query(TicketAnalytics).count()

    # Summarize the data for context injection
    categories = {}
    sentiments = {}
    priorities = {}
    for r in recent:
        categories[r.category] = categories.get(r.category, 0) + 1
        sentiments[r.sentiment] = sentiments.get(r.sentiment, 0) + 1
        if r.priority:
            priorities[r.priority] = priorities.get(r.priority, 0) + 1

    ticket_list = "\n".join([
        f"- [{r.priority or 'N/A'}] {r.ticket_id}: [{r.category}] {r.resolution_summary or 'No summary'} (Sentiment: {r.sentiment}, Escalate: {r.escalate_to or 'N/A'})"
        for r in recent
    ]) or "No tickets analyzed yet."

    system_prompt = f"""You are an expert IT helpdesk AI analyst embedded in a live monitoring dashboard. 
You have access to real-time data from the ticket analysis database.
Answer questions about ticket patterns, agent performance, and resolutions based on this data.
Be concise, insightful, and specific — reference actual ticket data when relevant.

## LIVE DATABASE SNAPSHOT:
- Total tickets analyzed so far: {total}
- Category breakdown: {categories}
- Sentiment breakdown: {sentiments}
- Priority breakdown: {priorities}

## MOST RECENT {len(recent)} ANALYZED TICKETS:
{ticket_list}

If the user asks you to verify the agent is working, explain the analysis patterns you see.
If the user asks about a specific ticket ID, look it up in the list above.
If no tickets exist yet, tell the user the agent is waiting for incoming tickets from the ticketing API."""

    client = ollama.Client(host=settings.OLLAMA_HOST)
    try:
        response = client.chat(
            model=settings.OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload.message}
            ],
            options={"temperature": 0.4, "num_predict": 512}
        )
        reply = response["message"]["content"].strip()
    except Exception as e:
        reply = f"⚠️ Could not reach Ollama: {str(e)}. Make sure Ollama is running."

    return {"reply": reply}

import os

# Mount the dashboard UI
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
os.makedirs(dashboard_path, exist_ok=True)
app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
