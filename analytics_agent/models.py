from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime
from .database import Base

class TicketAnalytics(Base):
    __tablename__ = "ticket_analytics"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String, unique=True, index=True, nullable=False)
    
    # Standard offline intelligence fields
    category = Column(String, nullable=True)
    resolution_summary = Column(Text, nullable=True)
    time_to_resolve_estimate = Column(String, nullable=True)
    sentiment = Column(String, nullable=True)
    
    # Store the raw LLM context or original ticket dump if needed for audit
    raw_context = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
