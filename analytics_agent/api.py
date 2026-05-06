import asyncio
import json
import os
import secrets
import httpx
import ollama
from urllib.parse import urlparse
from datetime import datetime
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from typing import Optional
from pydantic import BaseModel
from dotenv import set_key
from sqlalchemy import func

from .config import settings
from .database import init_db, get_db, SessionLocal
from .models import TicketAnalytics, AgentSecret

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

# Last ticket sample from the most recent successful ticketing pull (for diagnostics).
ticket_diagnostics_state = {
    "updated_at": None,
    "fetch_page": None,
    "tickets_in_batch": 0,
    "sample_index": 0,
    "raw_ticket": None,
}

# Integration telemetry for proving upstream ticketing connectivity at runtime.
integration_state = {
    "ticketing_api_url": settings.TICKETING_API_URL,
    "ticketing_update_url": settings.TICKETING_UPDATE_URL,
    "using_mock_source": False,
    "api_key_configured": bool(settings.TICKETING_API_KEY),
    "last_fetch_at": None,
    "last_fetch_page": None,
    "last_fetch_status_code": None,
    "last_fetch_count": 0,
    "last_fetch_error": None,
    "last_push_at": None,
    "last_push_ticket_id": None,
    "last_push_status_code": None,
    "last_push_error": None,
    "total_fetched_tickets": 0,
    "total_push_attempts": 0,
    "total_push_success": 0,
    "total_push_failed": 0,
    "total_invalid_tickets_skipped": 0,
    "last_invalid_ticket_reason": None,
    "last_fetch_response_preview": "",
    "last_fetch_parse_hint": None,
}

# Runtime secret cache (DB-backed for AGENT_INTEGRATION_KEY).
runtime_secrets = {
    "agent_integration_key": "",
}

# Chat system prompt cache (avoids rebuilding heavy context on every request)
chat_context_cache = {
    "prompt": "",
    "generated_at": None,
    "fast_mode": None,
}

# DB health cache (read/write probe) to avoid probing on every UI poll.
db_health_cache = {
    "checked_at": None,
    "read_ok": None,
    "write_ok": None,
    "error": None,
}


def _is_placeholder_secret(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return True
    return ("your_generated_key" in v) or ("changeme" in v) or ("<" in v and ">" in v)


def _is_mock_url(url: str) -> bool:
    lowered = (url or "").lower()
    return (
        "mock" in lowered
        or "localhost" in lowered
        or "127.0.0.1" in lowered
    )


integration_state["using_mock_source"] = _is_mock_url(settings.TICKETING_API_URL)
integration_state["api_key_configured"] = bool(
    settings.TICKETING_API_KEY and not _is_placeholder_secret(settings.TICKETING_API_KEY)
)
STRICT_PRODUCTION_INTEGRATION = (os.getenv("STRICT_PRODUCTION_INTEGRATION", "false").lower() == "true")
EXPECTED_TICKET_COUNT = int(os.getenv("EXPECTED_TICKET_COUNT", "1080"))
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
AUTO_CLEAN_MOCK_ON_STARTUP = (os.getenv("AUTO_CLEAN_MOCK_ON_STARTUP", "true").lower() == "true")
TICKETING_HTTP_TIMEOUT_SECONDS = float(os.getenv("TICKETING_HTTP_TIMEOUT_SECONDS", "45"))
TICKETING_FETCH_RETRIES = int(os.getenv("TICKETING_FETCH_RETRIES", "2"))

# ── Brain Files (Use/ directory) ─────────────────────────────────────────
# Resolve relative to project root (two levels up from this file).
USE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Use")
os.makedirs(USE_DIR, exist_ok=True)


def _load_brain_files() -> str:
    """Read all .md files from Use/ and concatenate into a single context block."""
    sections = []
    if not os.path.isdir(USE_DIR):
        return ""
    for fname in sorted(os.listdir(USE_DIR)):
        if not fname.lower().endswith(".md"):
            continue
        fpath = os.path.join(USE_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                label = fname.replace(".md", "").upper()
                sections.append(f"## [{label}]\n{content}")
        except Exception:
            pass
    return "\n\n".join(sections)


def _load_brain_section(*filenames: str) -> str:
    """Load specific .md files from Use/ (e.g. 'skill.md', 'rules.md')."""
    parts = []
    for fname in filenames:
        fpath = os.path.join(USE_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                label = fname.replace(".md", "").upper()
                parts.append(f"## [{label}]\n{content}")
        except Exception:
            pass
    return "\n\n".join(parts)


def _build_ticketing_headers() -> dict:
    headers = {}
    if settings.TICKETING_API_KEY and not _is_placeholder_secret(settings.TICKETING_API_KEY):
        key = settings.TICKETING_API_KEY
        headers["Authorization"] = f"Bearer {key}"
        headers["x-api-key"] = key
        headers["x-ticketing-api-key"] = key
        headers["api-key"] = key
    if runtime_secrets["agent_integration_key"]:
        akey = runtime_secrets["agent_integration_key"]
        headers["x-agent-integration-key"] = akey
        headers["x-integration-key"] = akey
        headers["Agent-Integration-Key"] = akey
    return headers


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) > 4:
        return "****" + value[-4:]
    return "****"


def _get_db_health_status() -> dict:
    """Return DB read/write connectivity status with a short cache."""
    now = datetime.utcnow()
    checked_at = db_health_cache.get("checked_at")
    if isinstance(checked_at, datetime) and (now - checked_at).total_seconds() < 15:
        return {
            "db_read_ok": db_health_cache.get("read_ok"),
            "db_write_ok": db_health_cache.get("write_ok"),
            "db_error": db_health_cache.get("error"),
            "db_checked_at": checked_at.isoformat(),
        }

    read_ok = False
    write_ok = False
    err = None
    probe_key = "__DB_HEALTHCHECK__"
    try:
        with SessionLocal() as probe_db:
            # Read path: DB -> Agent
            _ = probe_db.query(func.count(TicketAnalytics.id)).scalar()
            read_ok = True

            # Write path: Agent -> DB (rolled back; no persistent side effects)
            txn = probe_db.begin_nested()
            try:
                existing = probe_db.query(AgentSecret).filter(AgentSecret.key_name == probe_key).first()
                if existing:
                    probe_db.delete(existing)
                    probe_db.flush()
                probe_db.add(AgentSecret(key_name=probe_key, secret_value=now.isoformat()))
                probe_db.flush()
                write_ok = True
            finally:
                txn.rollback()
    except Exception as e:
        err = repr(e)

    db_health_cache["checked_at"] = now
    db_health_cache["read_ok"] = read_ok
    db_health_cache["write_ok"] = write_ok
    db_health_cache["error"] = err
    return {
        "db_read_ok": read_ok,
        "db_write_ok": write_ok,
        "db_error": err,
        "db_checked_at": now.isoformat(),
    }


def _load_agent_integration_key_from_db(db: Session) -> str:
    row = db.query(AgentSecret).filter(AgentSecret.key_name == "AGENT_INTEGRATION_KEY").first()
    return row.secret_value if row else ""


def _upsert_agent_integration_key(db: Session, value: str):
    row = db.query(AgentSecret).filter(AgentSecret.key_name == "AGENT_INTEGRATION_KEY").first()
    if row:
        row.secret_value = value
    else:
        row = AgentSecret(key_name="AGENT_INTEGRATION_KEY", secret_value=value)
        db.add(row)
    db.commit()


def _delete_agent_integration_key(db: Session) -> bool:
    row = db.query(AgentSecret).filter(AgentSecret.key_name == "AGENT_INTEGRATION_KEY").first()
    if row:
        db.delete(row)
        db.commit()
        return True
    return False


def _extract_tickets(data: object, depth: int = 0) -> list:
    """Normalize ticketing API JSON into a list of ticket-shaped dicts.

    Supports common envelopes: { data: [...] }, { data: { tickets: [...] } },
    { payload: ... }, { results: [...] }, etc. Optional TICKETING_RESPONSE_LIST_KEY
    forces which top-level key holds the array.
    """
    if depth > 10:
        return []

    list_key = (settings.TICKETING_RESPONSE_LIST_KEY or "").strip()
    if list_key and isinstance(data, dict) and list_key in data:
        node = data.get(list_key)
        if isinstance(node, list):
            return [x for x in node if isinstance(x, dict)]

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    if not isinstance(data, dict):
        return []

    for key in (
        "tickets",
        "results",
        "items",
        "records",
        "rows",
        "ticketList",
        "ticket_list",
        "unprocessedTickets",
        "unprocessed_tickets",
        "pendingTickets",
        "PendingTickets",
    ):
        node = data.get(key)
        if isinstance(node, list) and node and isinstance(node[0], dict):
            return node

    data_node = data.get("data")
    if isinstance(data_node, list) and data_node and isinstance(data_node[0], dict):
        return data_node
    if isinstance(data_node, dict):
        inner = _extract_tickets(data_node, depth + 1)
        if inner:
            return inner

    for wrap in ("response", "payload", "result", "body", "content", "message"):
        node = data.get(wrap)
        if isinstance(node, dict):
            inner = _extract_tickets(node, depth + 1)
            if inner:
                return inner
        elif isinstance(node, list) and node and isinstance(node[0], dict):
            return node

    # Legacy flat fallbacks
    for key in ("tickets", "results", "items", "data"):
        node = data.get(key)
        if isinstance(node, list):
            dicts = [x for x in node if isinstance(x, dict)]
            if dicts:
                return dicts

    return []


def _candidate_ticket_urls(base_url: str) -> list[str]:
    """Return candidate pull URLs to handle canonical/alias API paths."""
    if not base_url:
        return []

    candidates = [base_url]
    parsed = urlparse(base_url)
    path = parsed.path or ""
    if "/api/agent-integration/tickets" in path:
        candidates.append(base_url.replace("/api/agent-integration/tickets", "/api/tickets/unprocessed"))
    elif "/api/tickets/unprocessed" in path:
        candidates.append(base_url.replace("/api/tickets/unprocessed", "/api/agent-integration/tickets"))
    return list(dict.fromkeys(candidates))


def _candidate_update_urls(base_url: str) -> list[str]:
    if not base_url:
        return []
    candidates = [base_url]
    path = (urlparse(base_url).path or "")
    if "/api/agent-integration/dashboard-payload" in path:
        candidates.append(base_url.replace("/api/agent-integration/dashboard-payload", "/api/tickets/update"))
    elif "/api/tickets/update" in path:
        candidates.append(base_url.replace("/api/tickets/update", "/api/agent-integration/dashboard-payload"))
    return list(dict.fromkeys(candidates))


# ── Ticket field normalization (single source of truth for ingest + diagnostics) ──

_TICKET_ID_KEYS = (
    "id",
    "ticket_id",
    "ID",
    "ticketNumber",
    "TicketNumber",
    "ticketNo",
    "ticket_no",
    "reference",
    "uuid",
)
_TITLE_KEYS = (
    "title",
    "subject",
    "issue",
    "problem",
    "summary",
    "name",
    "ticketTitle",
    "issueTitle",
    "ticket_subject",
    "TicketSubject",
)
_DESCRIPTION_KEYS = (
    "description",
    "details",
    "body",
    "message",
    "issueDescription",
    "issue_description",
    "fullDescription",
    "content",
)


def _coalesce_ticket_id(ticket: dict) -> tuple[Optional[str], Optional[str]]:
    for k in _TICKET_ID_KEYS:
        if k not in ticket:
            continue
        v = ticket.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s, k
    return None, None


def _coalesce_text_field(ticket: dict, keys: tuple[str, ...]) -> tuple[Optional[str], Optional[str]]:
    for k in keys:
        if k not in ticket:
            continue
        v = ticket.get(k)
        if v is None:
            continue
        if isinstance(v, (dict, list)):
            continue
        s = str(v).strip()
        if s:
            return s, k
    return None, None


def _coalesce_optional_raw(ticket: dict, keys: tuple[str, ...]) -> tuple[Optional[object], Optional[str]]:
    """Return first present value (any JSON-serializable type) and its key."""
    for k in keys:
        if k not in ticket:
            continue
        v = ticket.get(k)
        if v is not None:
            return v, k
    return None, None


def build_normalized_ticket_mapping(ticket: dict) -> dict:
    """Exact normalized mapping used by validation and analyze_ticket — plus source keys."""
    tid_v, tid_k = _coalesce_ticket_id(ticket)
    title_v, title_k = _coalesce_text_field(ticket, _TITLE_KEYS)
    desc_v, desc_k = _coalesce_text_field(ticket, _DESCRIPTION_KEYS)
    if desc_v is None and title_v is not None:
        desc_v, desc_k = title_v, title_k
    rm_v, rm_k = _coalesce_optional_raw(ticket, ("resolvedMethods", "resolved_methods", "resolution"))
    br_v, br_k = _coalesce_optional_raw(ticket, ("branch", "branchName", "location"))
    comm_v, comm_k = _coalesce_optional_raw(ticket, ("comments", "comment", "notes"))

    # Mirrors analyze_ticket() string assembly
    analyze_tid = tid_v or ticket.get("ticketNumber")
    if analyze_tid is not None:
        analyze_tid = str(analyze_tid).strip()
    analyze_subj = title_v if title_v is not None else ""
    analyze_desc = desc_v if desc_v is not None else ""
    analyze_res_m = ticket.get("resolvedMethods") or "None provided"
    analyze_br = ticket.get("branch") or "Unknown"
    analyze_comm = ticket.get("comments") or "None"

    def field(val, src):
        return {"value": val, "source_key": src}

    normalized = {
        "ticket_id": field(tid_v, tid_k),
        "title": field(title_v, title_k),
        "description": field(desc_v, desc_k),
        "resolved_methods": field(rm_v, rm_k),
        "branch": field(br_v, br_k),
        "comments": field(comm_v, comm_k),
    }

    return {
        "normalized": normalized,
        "analyze_ticket_preview": {
            "tid": analyze_tid,
            "subject": analyze_subj if isinstance(analyze_subj, str) else str(analyze_subj),
            "description": analyze_desc if isinstance(analyze_desc, str) else str(analyze_desc),
            "historical_resolution": analyze_res_m,
            "branch": analyze_br,
            "comments": analyze_comm,
        },
    }


def _validate_ticket_payload(ticket: dict) -> tuple[bool, str]:
    if not isinstance(ticket, dict):
        return False, "Ticket payload is not an object"

    tid, _ = _coalesce_ticket_id(ticket)
    if not tid:
        return False, "Missing ticket id (id/ticket_id/ID/ticketNumber)"

    title, _ = _coalesce_text_field(ticket, _TITLE_KEYS)
    description, _ = _coalesce_text_field(ticket, _DESCRIPTION_KEYS)
    if title is None:
        return False, f"Ticket {tid} missing required title"
    # Some ticketing APIs only send a subject/summary line — reuse as description for analysis.
    if description is None:
        description = title

    return True, ""

async def fetch_tickets_page(page: int) -> list:
    """Fetch a single page of tickets from the ticketing API.
    Returns an empty list when there are no more pages or the API is unreachable.
    """
    try:
        headers = _build_ticketing_headers()

        page_param = settings.TICKETING_PAGE_PARAM
        per_page_param = settings.TICKETING_PER_PAGE_PARAM
        per_page = settings.TICKETS_PER_PAGE
        # Support both page/per_page and limit/offset style pagination.
        page_value = page
        if page_param.lower() == "offset":
            page_value = max((page - 1) * per_page, 0)
        params = {
            page_param: page_value,
            per_page_param: per_page,
        }

        async with httpx.AsyncClient() as client:
            urls = _candidate_ticket_urls(settings.TICKETING_API_URL)
            last_error = ""
            for attempt in range(1, TICKETING_FETCH_RETRIES + 1):
                for url in urls:
                    # Debug: Log the exact URL and params being sent
                    print(f"[Agent] Calling: {url} with params {params} (attempt {attempt})")
                    integration_state["last_fetch_at"] = datetime.utcnow().isoformat()
                    integration_state["last_fetch_page"] = page
                    try:
                        response = await client.get(url, params=params, headers=headers, timeout=TICKETING_HTTP_TIMEOUT_SECONDS)
                        if (
                            response.status_code in (401, 403)
                            and settings.TICKETING_API_KEY
                            and not _is_placeholder_secret(settings.TICKETING_API_KEY)
                        ):
                            # Some ticketing gateways only accept api_key as query param.
                            retry_params = dict(params)
                            retry_params["api_key"] = settings.TICKETING_API_KEY
                            response = await client.get(url, params=retry_params, headers=headers, timeout=TICKETING_HTTP_TIMEOUT_SECONDS)

                        integration_state["last_fetch_status_code"] = response.status_code
                        integration_state["last_fetch_response_preview"] = (response.text or "")[:220]
                        if response.status_code == 200:
                            data = response.json()
                            tickets = _extract_tickets(data)
                            integration_state["last_fetch_count"] = len(tickets)
                            integration_state["last_fetch_error"] = ""
                            if not tickets:
                                top = list(data.keys()) if isinstance(data, dict) else type(data).__name__
                                pk = settings.TICKETING_RESPONSE_LIST_KEY or "(not set)"
                                integration_state["last_fetch_parse_hint"] = (
                                    f"HTTP 200 but extracted 0 ticket objects; JSON top-level keys={top}. "
                                    f"If tickets live under a specific array key, set TICKETING_RESPONSE_LIST_KEY "
                                    f"(current={pk!r}). See GET /api/diagnostics/last-fetched-ticket after a fetch."
                                )
                                print(f"[Agent] {integration_state['last_fetch_parse_hint']}")
                            else:
                                integration_state["last_fetch_parse_hint"] = None
                            integration_state["total_fetched_tickets"] += len(tickets)
                            agent_state["backfill_total_fetched"] = integration_state["total_fetched_tickets"]
                            if tickets:
                                sample = tickets[0]
                                if isinstance(sample, dict):
                                    ticket_diagnostics_state["updated_at"] = datetime.utcnow().isoformat()
                                    ticket_diagnostics_state["fetch_page"] = page
                                    ticket_diagnostics_state["tickets_in_batch"] = len(tickets)
                                    ticket_diagnostics_state["sample_index"] = 0
                                    ticket_diagnostics_state["raw_ticket"] = sample
                                else:
                                    ticket_diagnostics_state["updated_at"] = datetime.utcnow().isoformat()
                                    ticket_diagnostics_state["fetch_page"] = page
                                    ticket_diagnostics_state["tickets_in_batch"] = len(tickets)
                                    ticket_diagnostics_state["sample_index"] = 0
                                    ticket_diagnostics_state["raw_ticket"] = {
                                        "_non_object_sample": True,
                                        "python_type": type(sample).__name__,
                                    }
                            return tickets

                        last_error = f"HTTP {response.status_code}"
                        integration_state["last_fetch_count"] = 0
                        integration_state["last_fetch_error"] = last_error
                    except Exception as inner_e:
                        last_error = repr(inner_e)
                        integration_state["last_fetch_status_code"] = 0
                        integration_state["last_fetch_error"] = last_error
                        integration_state["last_fetch_count"] = 0

                if attempt < TICKETING_FETCH_RETRIES:
                    await asyncio.sleep(1)

            print(f"[Agent] Ticketing API fetch failed after retries on page {page}: {last_error}")
    except Exception as e:
        print(f"[Agent] Could not reach ticketing API (page {page}): {e}")
        print("[Agent] → Make sure TICKETING_API_URL and TICKETING_API_KEY are set correctly in .env")
        integration_state["last_fetch_status_code"] = 0
        integration_state["last_fetch_error"] = repr(e)
        integration_state["last_fetch_count"] = 0

    return []


async def analyze_ticket(ticket: dict):
    """Run Ollama locally to analyze the ticket."""
    client = ollama.Client(host=settings.OLLAMA_HOST)
    preview = build_normalized_ticket_mapping(ticket)["analyze_ticket_preview"]
    tid = preview["tid"]
    subj = preview["subject"]
    desc = preview["description"]
    res_m = preview["historical_resolution"]
    br = preview["branch"]
    comm = preview["comments"]

    # Load brain context for analysis (skill patterns + rules + thinking framework)
    brain_context = _load_brain_section("skill.md", "rules.md", "thinking.md")
    brain_block = f"\n\n## AGENT KNOWLEDGE (from brain files):\n{brain_context}" if brain_context else ""

    prompt = f"""You are an expert IT helpdesk analyst for a banking and financial services organization.
You have studied the organization's full ticket history of 1000+ tickets.
Your job is to analyze support tickets and classify them into the EXACT categories this organization uses.
{brain_block}

## ORGANIZATION CONTEXT:
- This is a banking/financial institution with multiple branches: {br}
- Staff use Windows PCs, MS Office, passbook printers, laser printers, Canon printers, and banking software
- Common recurring issues include: printer jams, password resets, site/internet access, antivirus alerts, and Office software problems

## CATEGORY RULES — use THESE exact categories:
Printer & Hardware, Password & Access, Network & Connectivity, Security & Vulnerability, Software & Applications, Banking System, Email & Communication, Server & Infrastructure.

## YOUR TASK:
Study the provided ticket details AND the 'Historical Resolution' (if provided).
Use this to generate a concise 'resolution_summary' that we can use to train other agents.

## TICKET TO ANALYZE:
Ticket ID: {tid}
Subject: {subj}
Description: {desc}
Historical Resolution: {res_m}
Comments: {comm}

## OUTPUT FORMAT
Return ONLY a valid JSON object with NO markdown and NO backticks. Use exactly these fields:
- category: (string)
- priority: (string: "CRITICAL", "HIGH", "MEDIUM", or "LOW")
- resolution_summary: (string: 1-2 sentence actionable resolution using your expert knowledge + the historical resolution)
- escalate_to: (string: "L1 Support", "L2 Support", "L3/Engineering", or "Security Team")
- time_to_resolve_estimate: (string: e.g., "15 mins", "2 hours", "1 day")
- sentiment: (string: "Positive", "Neutral", "Negative", or "Frustrated")
- key_symptoms: (array of 2-3 short strings)
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
    if not settings.TICKETING_API_KEY or _is_placeholder_secret(settings.TICKETING_API_KEY):
        integration_state["last_push_at"] = datetime.utcnow().isoformat()
        integration_state["last_push_ticket_id"] = ticket_id
        integration_state["last_push_error"] = "Skipped push: TICKETING_API_KEY not configured"
        return
        
    try:
        integration_state["total_push_attempts"] += 1
        async with httpx.AsyncClient() as client:
            headers = _build_ticketing_headers()
            headers["Content-Type"] = "application/json"
            payload = {
                "ticket_id": ticket_id,
                **analysis
            }
            urls = _candidate_update_urls(settings.TICKETING_UPDATE_URL)
            last_error = None
            success = False
            for url in urls:
                response = await client.post(url, json=payload, headers=headers, timeout=10.0)
                integration_state["last_push_at"] = datetime.utcnow().isoformat()
                integration_state["last_push_ticket_id"] = ticket_id
                integration_state["last_push_status_code"] = response.status_code
                if 200 <= response.status_code < 300:
                    integration_state["total_push_success"] += 1
                    integration_state["last_push_error"] = None
                    success = True
                    break
                last_error = f"HTTP {response.status_code}"
            if not success:
                integration_state["total_push_failed"] += 1
                integration_state["last_push_error"] = last_error or "Push failed"
    except Exception as e:
        print(f"Failed to push analysis to ticketing API for {ticket_id}: {e}")
        integration_state["last_push_at"] = datetime.utcnow().isoformat()
        integration_state["last_push_ticket_id"] = ticket_id
        integration_state["total_push_failed"] += 1
        integration_state["last_push_error"] = str(e)

async def process_ticket_batch(tickets: list, db_session):
    """Analyze and store a batch of tickets. Skips already-processed ones.
    Returns the count of newly processed tickets.
    """
    new_count = 0
    for t in tickets:
        # Debug: Print the structure of the first ticket in the batch
        if new_count == 0:
            print(f"[Agent] First ticket fields: {list(t.keys())}")

        valid, reason = _validate_ticket_payload(t)
        if not valid:
            integration_state["total_invalid_tickets_skipped"] += 1
            integration_state["last_invalid_ticket_reason"] = reason
            print(f"[Agent] Skipping invalid ticket: {reason}")
            continue

        tid, _ = _coalesce_ticket_id(t)
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
            resolved_methods=t.get("resolvedMethods") or "",  # Store the raw historical resolution
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
            # Be more patient — wait for 5 consecutive empty pages before stopping backfill
            consecutive_empty_pages += 1
            if consecutive_empty_pages >= 5:
                print(f"[Agent] Backfill complete. Total processed so far: {agent_state['total_processed']}")
                break
        else:
            consecutive_empty_pages = 0
            # If we got fewer tickets than requested, it might be the last page, but we keep going
            # until we hit the empty page limit.
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
    if STRICT_PRODUCTION_INTEGRATION and _is_mock_url(settings.TICKETING_API_URL):
        raise RuntimeError(
            "STRICT_PRODUCTION_INTEGRATION=true but TICKETING_API_URL points to mock/local endpoint. "
            "Set a production ticketing URL before startup."
        )

    if _is_mock_url(settings.TICKETING_API_URL):
        print("[Agent] WARNING: TICKETING_API_URL appears to be mock/local.")

    # Initialize total processed counter from DB
    with SessionLocal() as db:
        # Load DB-backed agent integration key into runtime cache.
        runtime_secrets["agent_integration_key"] = _load_agent_integration_key_from_db(db)
        # Backward compatibility: if key exists only in env, migrate once to DB.
        if not runtime_secrets["agent_integration_key"] and settings.AGENT_INTEGRATION_KEY:
            _upsert_agent_integration_key(db, settings.AGENT_INTEGRATION_KEY)
            runtime_secrets["agent_integration_key"] = settings.AGENT_INTEGRATION_KEY

        if AUTO_CLEAN_MOCK_ON_STARTUP:
            deleted = db.query(TicketAnalytics).filter(TicketAnalytics.ticket_id.like("MOCK-%")).delete(synchronize_session=False)
            if deleted:
                print(f"[Agent] Startup cleanup: removed {deleted} mock ticket(s).")
                db.commit()
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

@app.get("/api/integration-status")
def get_integration_status():
    status = integration_state.copy()
    last_code = integration_state.get("last_fetch_status_code")
    last_err = integration_state.get("last_fetch_error")
    upstream_ok = bool(last_code and isinstance(last_code, int) and 200 <= last_code < 300 and not last_err)
    status.update({
        "ticketing_api_url": settings.TICKETING_API_URL,
        "ticketing_update_url": settings.TICKETING_UPDATE_URL,
        "using_mock_source": _is_mock_url(settings.TICKETING_API_URL),
        "api_key_configured": bool(settings.TICKETING_API_KEY and not _is_placeholder_secret(settings.TICKETING_API_KEY)),
        "api_key_masked": _mask_secret(settings.TICKETING_API_KEY),
        "agent_integration_key_configured": bool(runtime_secrets["agent_integration_key"]),
        "agent_integration_key_masked": _mask_secret(runtime_secrets["agent_integration_key"]),
        "agent_mode": agent_state.get("mode"),
        "agent_status": agent_state.get("status"),
        # IMPORTANT: /api/integration-status returning HTTP 200 means this dashboard API is alive.
        # Use this flag to know whether the upstream ticketing server itself is reachable.
        "upstream_ticketing_reachable": upstream_ok,
        "upstream_failure_reason": None if upstream_ok else (last_err or f"last_fetch_status_code={last_code}"),
    })
    status.update(_get_db_health_status())
    return status


@app.get("/api/diagnostics/last-fetched-ticket")
def get_last_fetched_ticket_diagnostics():
    """Normalized field mapping for the first ticket in the last successful HTTP 200 pull.

    Helps debug schema mismatches without guessing which upstream keys map to id/title/description.
    """
    raw = ticket_diagnostics_state.get("raw_ticket")
    if not raw:
        return {
            "has_sample": False,
            "message": "No ticket captured yet. Wait for a successful ticketing fetch (HTTP 200 with at least one item).",
            "meta": {
                "updated_at": ticket_diagnostics_state.get("updated_at"),
                "fetch_page": ticket_diagnostics_state.get("fetch_page"),
                "tickets_in_batch": ticket_diagnostics_state.get("tickets_in_batch"),
            },
            "mapping_rules": {
                "ticket_id": list(_TICKET_ID_KEYS),
                "title": list(_TITLE_KEYS),
                "description": list(_DESCRIPTION_KEYS),
                "resolved_methods": ["resolvedMethods", "resolved_methods", "resolution"],
                "branch": ["branch", "branchName", "location"],
                "comments": ["comments", "comment", "notes"],
            },
        }

    if not isinstance(raw, dict):
        return {
            "has_sample": False,
            "message": "Last batch first element was not a JSON object.",
            "meta": raw,
            "mapping_rules": {
                "ticket_id": list(_TICKET_ID_KEYS),
                "title": list(_TITLE_KEYS),
                "description": list(_DESCRIPTION_KEYS),
            },
        }

    mapping = build_normalized_ticket_mapping(raw)
    valid, reason = _validate_ticket_payload(raw)
    return {
        "has_sample": True,
        "updated_at": ticket_diagnostics_state.get("updated_at"),
        "fetch_page": ticket_diagnostics_state.get("fetch_page"),
        "tickets_in_batch": ticket_diagnostics_state.get("tickets_in_batch"),
        "sample_index": ticket_diagnostics_state.get("sample_index"),
        "raw_ticket_keys": list(raw.keys()),
        "raw_ticket": raw,
        **mapping,
        "validation": {"valid": valid, "reason": reason},
        "mapping_rules": {
            "ticket_id": list(_TICKET_ID_KEYS),
            "title": list(_TITLE_KEYS),
            "description": list(_DESCRIPTION_KEYS),
            "resolved_methods": ["resolvedMethods", "resolved_methods", "resolution"],
            "branch": ["branch", "branchName", "location"],
            "comments": ["comments", "comment", "notes"],
        },
    }


class SettingsUpdate(BaseModel):
    ticketing_api_key: str


class AdminCleanupRequest(BaseModel):
    admin_api_key: Optional[str] = None

@app.get("/api/settings")
def get_settings():
    return {
        "has_key": bool(settings.TICKETING_API_KEY),
        "masked_key": _mask_secret(settings.TICKETING_API_KEY),
        "has_agent_integration_key": bool(runtime_secrets["agent_integration_key"]),
        "masked_agent_integration_key": _mask_secret(runtime_secrets["agent_integration_key"]),
        "agent_key_persisted_in_db": bool(runtime_secrets["agent_integration_key"]),
    }

@app.post("/api/settings")
def update_settings(update: SettingsUpdate):
    settings.TICKETING_API_KEY = update.ticketing_api_key
    integration_state["api_key_configured"] = bool(
        update.ticketing_api_key and not _is_placeholder_secret(update.ticketing_api_key)
    )
    # Try to persist to .env file in the root
    try:
        set_key(".env", "TICKETING_API_KEY", update.ticketing_api_key)
    except Exception as e:
        print(f"Failed to persist API key to .env: {e}")
    return {"status": "success"}


@app.post("/api/settings/agent-key/generate")
def generate_agent_integration_key(db: Session = Depends(get_db)):
    generated = secrets.token_hex(32)
    _upsert_agent_integration_key(db, generated)
    runtime_secrets["agent_integration_key"] = generated
    return {
        "status": "success",
        "agent_integration_key": generated,  # shown only at generation time
        "masked_agent_integration_key": _mask_secret(generated),
    }


@app.post("/api/settings/agent-key/revoke")
def revoke_agent_integration_key(db: Session = Depends(get_db)):
    deleted = _delete_agent_integration_key(db)
    runtime_secrets["agent_integration_key"] = ""
    return {"status": "success", "deleted_from_db": deleted}

@app.get("/api/stats")
def get_stats(db: Session = Depends(get_db)):
    # Exclude mock rows from dashboard stats so counts reflect production tickets only.
    base_query = db.query(TicketAnalytics).filter(~TicketAnalytics.ticket_id.like("MOCK-%"))
    total = base_query.count()
    recent = base_query.order_by(TicketAnalytics.created_at.desc()).limit(15).all()
    all_records = base_query.all()

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


@app.post("/api/admin/cleanup-mock")
def cleanup_mock_data(payload: AdminCleanupRequest, db: Session = Depends(get_db)):
    # Optional guard: if ADMIN_API_KEY is configured, require it.
    if ADMIN_API_KEY and payload.admin_api_key != ADMIN_API_KEY:
        return {"status": "error", "message": "Invalid admin API key"}

    before_total = db.query(func.count(TicketAnalytics.id)).scalar() or 0
    mock_rows = db.query(TicketAnalytics).filter(TicketAnalytics.ticket_id.like("MOCK-%"))
    deleted = mock_rows.count()
    mock_rows.delete(synchronize_session=False)
    db.commit()
    after_total = db.query(func.count(TicketAnalytics.id)).scalar() or 0

    # Keep runtime counters in sync after cleanup.
    agent_state["total_processed"] = after_total

    return {
        "status": "success",
        "deleted_mock_rows": deleted,
        "total_before": before_total,
        "total_after": after_total,
    }


@app.get("/api/admin/processing-target")
def processing_target_status(db: Session = Depends(get_db)):
    total = db.query(func.count(TicketAnalytics.id)).scalar() or 0
    non_mock = db.query(func.count(TicketAnalytics.id)).filter(~TicketAnalytics.ticket_id.like("MOCK-%")).scalar() or 0
    mock_count = db.query(func.count(TicketAnalytics.id)).filter(TicketAnalytics.ticket_id.like("MOCK-%")).scalar() or 0
    return {
        "expected_ticket_count": EXPECTED_TICKET_COUNT,
        "total_analyzed": total,
        "non_mock_analyzed": non_mock,
        "mock_count": mock_count,
        "remaining_to_target": max(EXPECTED_TICKET_COUNT - non_mock, 0),
        "target_met": non_mock >= EXPECTED_TICKET_COUNT,
    }


@app.get("/api/admin/connectivity-check")
async def connectivity_check():
    headers = _build_ticketing_headers()
    pull_urls = _candidate_ticket_urls(settings.TICKETING_API_URL)
    push_urls = _candidate_update_urls(settings.TICKETING_UPDATE_URL)
    report = {"pull": [], "push": []}

    async with httpx.AsyncClient() as client:
        for u in pull_urls:
            try:
                r = await client.get(u, params={settings.TICKETING_PER_PAGE_PARAM: 1, settings.TICKETING_PAGE_PARAM: 0}, headers=headers, timeout=8.0)
                report["pull"].append({"url": u, "status": r.status_code, "ok": r.status_code < 500})
            except Exception as e:
                report["pull"].append({"url": u, "status": 0, "ok": False, "error": repr(e)})
        for u in push_urls:
            try:
                r = await client.post(u, json={"status": {"message": "connectivity-check"}}, headers=headers, timeout=8.0)
                report["push"].append({"url": u, "status": r.status_code, "ok": r.status_code < 500})
            except Exception as e:
                report["push"].append({"url": u, "status": 0, "ok": False, "error": repr(e)})

    return report

class ChatMessage(BaseModel):
    message: str

def _build_chat_context(db: Session, fast_mode: bool = False):
    """Build system prompt from DB stats. Uses SQL aggregation (no full-table Python scans)."""
    non_mock = ~TicketAnalytics.ticket_id.like("MOCK-%")
    total = db.query(func.count(TicketAnalytics.id)).filter(non_mock).scalar() or 0

    cat_rows = (
        db.query(TicketAnalytics.category, func.count(TicketAnalytics.id))
        .filter(non_mock)
        .group_by(TicketAnalytics.category)
        .all()
    )
    categories = {(c or "Unknown"): n for c, n in cat_rows}

    sen_rows = (
        db.query(TicketAnalytics.sentiment, func.count(TicketAnalytics.id))
        .filter(non_mock)
        .group_by(TicketAnalytics.sentiment)
        .all()
    )
    sentiments = {(s or "Neutral"): n for s, n in sen_rows}

    pri_rows = (
        db.query(TicketAnalytics.priority, func.count(TicketAnalytics.id))
        .filter(non_mock)
        .filter(TicketAnalytics.priority.isnot(None), TicketAnalytics.priority != "")
        .group_by(TicketAnalytics.priority)
        .all()
    )
    priorities = {p: n for p, n in pri_rows}

    recent_limit = 3 if fast_mode else 5
    recent = (
        db.query(TicketAnalytics)
        .filter(non_mock)
        .order_by(TicketAnalytics.created_at.desc())
        .limit(recent_limit)
        .all()
    )
    ticket_lines = "\n".join([
        f"ID:{r.ticket_id}|CAT:{r.category}|SOLVED_BY:{r.resolved_methods or r.resolution_summary}"
        for r in recent
    ]) or "none"

    # In fast mode, skip large brain context injection for lower latency.
    brain_block = ""
    if not fast_mode:
        brain_context = _load_brain_files()
        brain_block = f"\n\nAGENT BRAIN CONTEXT:\n{brain_context}" if brain_context else ""
    
    system_prompt = (
        "You are an IT helpdesk AI analyst. You have been trained on real historical resolutions.\n"
        f"STATS: total={total}, categories={categories}, sentiments={sentiments}, priorities={priorities}\n"
        f"HISTORICAL KNOWLEDGE (id|category|resolution):\n{ticket_lines}\n"
        "RULES: If a user asks how to resolve an issue, check the HISTORICAL KNOWLEDGE for similar cases. "
        "Answer concisely and accurately; cite ticket IDs when relevant. "
        "Prefer direct, actionable bullet points."
        f"{brain_block}"
    )
    return system_prompt


def _get_chat_system_prompt(db: Session) -> str:
    """Get cached chat system prompt with short TTL."""
    now = datetime.utcnow()
    ttl_seconds = max(int(settings.CHAT_CONTEXT_CACHE_SECONDS), 0)
    fast_mode = bool(settings.FAST_CHAT_MODE)
    generated_at = chat_context_cache.get("generated_at")

    if (
        chat_context_cache.get("prompt")
        and isinstance(generated_at, datetime)
        and chat_context_cache.get("fast_mode") == fast_mode
        and (now - generated_at).total_seconds() <= ttl_seconds
    ):
        return chat_context_cache["prompt"]

    prompt = _build_chat_context(db, fast_mode=fast_mode)
    chat_context_cache["prompt"] = prompt
    chat_context_cache["generated_at"] = now
    chat_context_cache["fast_mode"] = fast_mode
    return prompt


@app.get("/api/health")
async def get_health():
    """System health snapshot (Safe version - no psutil needed)."""
    return {
        "cpu": "—",
        "ram": "—",
        "disk": "—",
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }


@app.post("/api/chat")
async def chat_with_agent(payload: ChatMessage, db: Session = Depends(get_db)):
    """Streaming chat — SSE tokens; tuned for full answers without premature cutoffs."""
    system_prompt = _get_chat_system_prompt(db)
    fast_mode = bool(settings.FAST_CHAT_MODE)

    async def token_stream():
        yielded_any = False
        truncated = False
        try:
            client = ollama.AsyncClient(host=settings.OLLAMA_HOST)

            response_stream = await asyncio.wait_for(
                client.chat(
                    model=settings.OLLAMA_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": payload.message},
                    ],
                    stream=True,
                    options={
                        "temperature": settings.FAST_CHAT_TEMPERATURE if fast_mode else settings.CHAT_TEMPERATURE,
                        "num_predict": settings.FAST_CHAT_NUM_PREDICT if fast_mode else settings.CHAT_NUM_PREDICT,
                        "num_ctx": settings.FAST_CHAT_NUM_CTX if fast_mode else settings.CHAT_NUM_CTX,
                        "num_thread": settings.OLLAMA_NUM_THREADS,
                        "keep_alive": -1,
                    },
                ),
                timeout=settings.CHAT_STREAM_CONNECT_SECONDS,
            )
            started_at = datetime.utcnow()
            stream_iter = response_stream.__aiter__()
            while True:
                elapsed = (datetime.utcnow() - started_at).total_seconds()
                if elapsed >= settings.CHAT_MAX_STREAM_SECONDS:
                    truncated = True
                    break
                try:
                    chunk = await asyncio.wait_for(
                        stream_iter.__anext__(),
                        timeout=settings.CHAT_TOKEN_IDLE_SECONDS,
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    truncated = True
                    break

                msg = chunk.get("message") or {}
                token = msg.get("content") or ""
                if token:
                    yielded_any = True
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    break

            if not yielded_any:
                yield f"data: {json.dumps({'token': 'No response from the model. Check that Ollama is running, the model is pulled, and OLLAMA_URL/OLLAMA_HOST points to the correct host.'})}\n\n"
            elif truncated:
                yield f"data: {json.dumps({'token': ' [truncated: increase CHAT_MAX_STREAM_SECONDS or CHAT_TOKEN_IDLE_SECONDS if needed]'})}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'token': 'The model did not start streaming in time. Check Ollama connectivity and CHAT_STREAM_CONNECT_SECONDS in .env.'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'token': f'Error: {str(e)}'})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        token_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── Brain Files API ──────────────────────────────────────────────────────

class BrainFileUpdate(BaseModel):
    content: str


@app.get("/api/brain-files")
def list_brain_files():
    """List all .md files in the Use/ directory."""
    files = []
    if not os.path.isdir(USE_DIR):
        return {"files": []}
    for fname in sorted(os.listdir(USE_DIR)):
        if not fname.lower().endswith(".md"):
            continue
        fpath = os.path.join(USE_DIR, fname)
        try:
            stat = os.stat(fpath)
            files.append({
                "name": fname,
                "size_bytes": stat.st_size,
                "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            files.append({"name": fname, "size_bytes": 0, "modified_at": None})
    return {"files": files, "directory": USE_DIR}


@app.get("/api/brain-files/{filename}")
def read_brain_file(filename: str):
    """Read full content of a specific .md file from Use/."""
    if not filename.endswith(".md"):
        return {"error": "Only .md files are supported"}
    # Prevent path traversal
    safe_name = os.path.basename(filename)
    fpath = os.path.join(USE_DIR, safe_name)
    if not os.path.isfile(fpath):
        return {"error": f"File '{safe_name}' not found", "content": ""}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        stat = os.stat(fpath)
        return {
            "name": safe_name,
            "content": content,
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        }
    except Exception as e:
        return {"error": str(e), "content": ""}


@app.put("/api/brain-files/{filename}")
def write_brain_file(filename: str, payload: BrainFileUpdate):
    """Write/update content of a .md file in Use/."""
    if not filename.endswith(".md"):
        return {"error": "Only .md files are supported"}
    safe_name = os.path.basename(filename)
    fpath = os.path.join(USE_DIR, safe_name)
    try:
        os.makedirs(USE_DIR, exist_ok=True)
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(payload.content)
        stat = os.stat(fpath)
        return {
            "status": "success",
            "name": safe_name,
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


# Mount the dashboard UI
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
os.makedirs(dashboard_path, exist_ok=True)
app.mount("/", StaticFiles(directory=dashboard_path, html=True), name="dashboard")
