from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from datetime import datetime
from .database import Base

class TicketAnalytics(Base):
    __tablename__ = "ticket_analytics"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(String, unique=True, index=True, nullable=False)

    # Analysis fields
    category = Column(String, nullable=True)
    priority = Column(String, nullable=True)           # CRITICAL / HIGH / MEDIUM / LOW
    resolution_summary = Column(Text, nullable=True)   # AI-generated summary
    resolved_methods = Column(Text, nullable=True)     # Real-world resolution from the source API
    escalate_to = Column(String, nullable=True)        # L1 / L2 / L3 / Security Team
    time_to_resolve_estimate = Column(String, nullable=True)
    sentiment = Column(String, nullable=True)
    key_symptoms = Column(JSON, nullable=True)         # list of strings

    # Raw data for audit
    raw_context = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
