import json
import ollama
from .config import settings
from .schemas import TicketPayload, AnalysisResult

def perform_ticket_analysis(ticket: TicketPayload) -> AnalysisResult:
    client = ollama.Client(host=settings.OLLAMA_HOST)
    
    prompt = f"""
You are a Senior IT Systems Engineer analyzing a helpdesk ticket. 
Please review the following ticket details and provide a structured analysis in JSON format.

Ticket ID: {ticket.id}
Subject: {ticket.subject}
Description: {ticket.description}
Comments: {json.dumps(ticket.comments)}
Metadata: {json.dumps(ticket.metadata)}

You MUST return ONLY a raw JSON object with the following schema:
{{
  "headline": "A short, 1-sentence summary of the core issue",
  "risk_signals": ["risk 1", "risk 2"],
  "priority": "Low | Medium | High | Critical"
}}
"""
    
    response = client.chat(
        model=settings.OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0.2},
        format="json"
    )
    
    raw_output = response["message"]["content"]
    
    try:
        parsed = json.loads(raw_output)
        return AnalysisResult(**parsed), raw_output
    except Exception as e:
        # Fallback if the model doesn't strictly follow JSON or parsing fails
        return AnalysisResult(
            headline="Failed to parse model output",
            risk_signals=[],
            priority="Unknown"
        ), raw_output
