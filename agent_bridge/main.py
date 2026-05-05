from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager

from .config import settings
from .database import init_db, get_db, StoredAnalysis
from .schemas import TicketPayload, AnalysisResult
from .auth import verify_auth
from .agent_logic import perform_ticket_analysis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB on startup
    init_db()
    yield

app = FastAPI(title="Agent Bridge", lifespan=lifespan)

@app.post("/api/tickets/{ticket_id}/agent-analysis", response_model=AnalysisResult, dependencies=[Depends(verify_auth)])
async def analyze_ticket(ticket_id: str, ticket: TicketPayload, db: Session = Depends(get_db)):
    if ticket.id != ticket_id:
        raise HTTPException(status_code=400, detail="Ticket ID in URL does not match payload")
        
    # Analyze ticket via Ollama
    analysis, raw_output = perform_ticket_analysis(ticket)
    
    # Persist if enabled
    if settings.AGENT_BRIDGE_PERSIST_ANALYSIS:
        existing = db.query(StoredAnalysis).filter(StoredAnalysis.ticket_id == ticket_id).first()
        if existing:
            existing.headline = analysis.headline
            existing.risk_signals = analysis.risk_signals
            existing.priority = analysis.priority
            existing.raw_llm_output = raw_output
        else:
            new_record = StoredAnalysis(
                ticket_id=ticket_id,
                headline=analysis.headline,
                risk_signals=analysis.risk_signals,
                priority=analysis.priority,
                raw_llm_output=raw_output
            )
            db.add(new_record)
        db.commit()
        
    return analysis

@app.get("/v1/stored-analyses/ticket/{ticket_id}")
async def get_stored_analysis(ticket_id: str, db: Session = Depends(get_db)):
    record = db.query(StoredAnalysis).filter(StoredAnalysis.ticket_id == ticket_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found")
        
    return {
        "ticket_id": record.ticket_id,
        "headline": record.headline,
        "risk_signals": record.risk_signals,
        "priority": record.priority,
        "timestamp": record.timestamp
    }
