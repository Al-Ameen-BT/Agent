from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict

class TicketPayload(BaseModel):
    id: str
    subject: str
    description: str
    comments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class AnalysisResult(BaseModel):
    headline: str
    risk_signals: List[str]
    priority: str
