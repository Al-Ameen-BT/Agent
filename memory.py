"""
memory.py — Conversation memory for the IT agent

Keeps a rolling window of recent messages.
Older messages are summarized to preserve context without bloating the prompt.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json

from config import LOGS_PATH, PERSONA_NAME


@dataclass
class Turn:
    role: str        # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class ConversationMemory:
    def __init__(self, max_turns: int = 12):
        self.max_turns = max_turns
        self.turns: list[Turn] = []
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def add(self, role: str, content: str):
        self.turns.append(Turn(role=role, content=content))
        # Keep only the last N turns
        if len(self.turns) > self.max_turns * 2:
            self.turns = self.turns[-(self.max_turns * 2):]

    def get_messages(self) -> list[dict]:
        """Return messages in Ollama/OpenAI chat format."""
        return [
            {"role": t.role, "content": t.content}
            for t in self.turns
        ]

    def clear(self):
        self.turns = []

    def save_log(self):
        """Save session to logs/ for later use as training data."""
        if not self.turns:
            return

        Path(LOGS_PATH).mkdir(exist_ok=True)
        log_file = Path(LOGS_PATH) / f"session_{self.session_id}.json"

        data = {
            "session_id": self.session_id,
            "persona": PERSONA_NAME,
            "messages": [
                {
                    "role": "assistant" if t.role == "assistant" else "user",
                    "content": t.content,
                    "timestamp": t.timestamp
                }
                for t in self.turns
            ]
        }

        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(log_file)

    def get_summary_text(self) -> str:
        """Human-readable summary for debugging."""
        lines = []
        for t in self.turns:
            label = PERSONA_NAME if t.role == "assistant" else "User"
            preview = t.content[:80].replace("\n", " ")
            lines.append(f"  [{label}] {preview}{'…' if len(t.content) > 80 else ''}")
        return "\n".join(lines) if lines else "  (empty)"
