"""
prepare_data.py — Convert your raw chat logs into agent training data

Supports multiple raw formats and outputs clean JSON files
ready to drop into data/ and ingest.

Usage:
  python prepare_data.py                    # interactive guide
  python prepare_data.py whatsapp file.txt  # WhatsApp export
  python prepare_data.py telegram file.json # Telegram export
  python prepare_data.py discord  file.json # Discord export
  python prepare_data.py plain    file.txt  # plain "Name: message" format
  python prepare_data.py preview  file.json # preview a prepared file
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime


OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────
#  CONVERTERS — one per raw format
# ─────────────────────────────────────────────────────────────────────────

def convert_whatsapp(filepath: str, persona_name: str) -> list[dict]:
    """
    WhatsApp .txt export format:
    [DD/MM/YYYY, HH:MM:SS] Name: message
    or
    [MM/DD/YY, HH:MM AM] Name: message
    """
    pattern = re.compile(r"^\[.*?\]\s+(.+?):\s+(.+)$")
    messages = []
    current_name = None
    current_text = []

    def flush():
        if current_name and current_text:
            role = "assistant" if current_name.lower() == persona_name.lower() else "user"
            messages.append({"role": role, "content": " ".join(current_text).strip()})

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = pattern.match(line)
            if m:
                flush()
                current_name = m.group(1).strip()
                current_text = [m.group(2).strip()]
            elif current_text:
                # Continuation of previous message
                current_text.append(line)

    flush()
    return messages


def convert_telegram(filepath: str, persona_name: str) -> list[dict]:
    """
    Telegram JSON export (from Settings > Export chat history).
    Expects the standard Telegram format with a "messages" array.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_messages = data.get("messages", [])
    messages = []

    for msg in raw_messages:
        if msg.get("type") != "message":
            continue
        sender = msg.get("from", "")
        # Text can be a string or a list of text/entities
        text = msg.get("text", "")
        if isinstance(text, list):
            text = "".join(
                part if isinstance(part, str) else part.get("text", "")
                for part in text
            )
        text = text.strip()
        if not text:
            continue

        role = "assistant" if sender.lower() == persona_name.lower() else "user"
        messages.append({"role": role, "content": text})

    return messages


def convert_discord(filepath: str, persona_name: str) -> list[dict]:
    """
    Discord JSON export (e.g. from DiscordChatExporter).
    Expects {"messages": [{"author": {"name": "..."}, "content": "..."}]}
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_messages = data.get("messages", [])
    messages = []

    for msg in raw_messages:
        author = msg.get("author", {}).get("name", "")
        content = msg.get("content", "").strip()
        if not content:
            continue
        role = "assistant" if author.lower() == persona_name.lower() else "user"
        messages.append({"role": role, "content": content})

    return messages


def convert_plain(filepath: str, persona_name: str) -> list[dict]:
    """
    Plain text format — each line is:
      Name: message text here
    
    Example:
      Alex: yeah just flush the arp cache, that'll fix it
      User: how?
      Alex: arp -d * on windows or ip neigh flush all on linux
    """
    pattern = re.compile(r"^(.+?):\s+(.+)$")
    messages = []

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = pattern.match(line)
            if m:
                name = m.group(1).strip()
                text = m.group(2).strip()
                role = "assistant" if name.lower() == persona_name.lower() else "user"
                messages.append({"role": role, "content": text})

    return messages


# ─────────────────────────────────────────────────────────────────────────
#  FILTERS — clean up training data quality
# ─────────────────────────────────────────────────────────────────────────

def filter_messages(messages: list[dict]) -> list[dict]:
    """Remove low-quality messages that would hurt training."""
    filtered = []
    skip_patterns = [
        r"^\s*(ok|okay|k|lol|haha|hahaha|nice|cool|thanks|thx|ty|np|sure|yep|nope|yes|no)\s*$",
        r"^https?://\S+$",          # bare links with no context
        r"^\s*[\U0001F300-\U0001FFFF]+\s*$",  # emoji-only
        r"^\s*\+\d+\s*$",           # phone numbers
        r"<Media omitted>",
        r"This message was deleted",
        r"^\s*$",
    ]
    combined = re.compile("|".join(skip_patterns), re.IGNORECASE)

    for msg in messages:
        content = msg["content"]
        if combined.search(content):
            continue
        if len(content) < 8:       # too short to be useful
            continue
        if len(content) > 4000:    # too long, chunk it
            # Split into ~800 char chunks at sentence boundaries
            parts = re.split(r"(?<=[.!?])\s+", content)
            chunk = ""
            for part in parts:
                if len(chunk) + len(part) < 800:
                    chunk += " " + part
                else:
                    if chunk.strip():
                        filtered.append({"role": msg["role"], "content": chunk.strip()})
                    chunk = part
            if chunk.strip():
                filtered.append({"role": msg["role"], "content": chunk.strip()})
        else:
            filtered.append(msg)

    return filtered


def group_into_conversations(messages: list[dict], window: int = 6) -> list[dict]:
    """
    Group consecutive messages into conversation windows.
    This gives the agent context for how the person responds, not just
    isolated messages.
    Returns list of conversation objects ready for the JSON format.
    """
    conversations = []
    for i in range(0, len(messages), window):
        window_msgs = messages[i:i + window]
        if len(window_msgs) < 2:
            continue
        # Only keep windows that have at least one assistant message
        has_assistant = any(m["role"] == "assistant" for m in window_msgs)
        if has_assistant:
            conversations.append({"messages": window_msgs})
    return conversations


# ─────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────

CONVERTERS = {
    "whatsapp": convert_whatsapp,
    "telegram": convert_telegram,
    "discord":  convert_discord,
    "plain":    convert_plain,
}

def save_output(conversations: list[dict], source_name: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"chatlogs_{source_name}_{timestamp}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(conversations, f, indent=2, ensure_ascii=False)
    return str(out_file)


def preview_file(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        convos = data
    else:
        convos = [data]

    print(f"\n📄 {filepath}")
    print(f"   {len(convos)} conversation(s)\n")
    for i, convo in enumerate(convos[:3]):
        print(f"── Conversation {i+1} ──")
        for msg in convo.get("messages", []):
            role = msg["role"]
            content = msg["content"][:120].replace("\n", " ")
            label = "  [agent]" if role == "assistant" else "  [user] "
            print(f"{label} {content}{'…' if len(msg['content']) > 120 else ''}")
        print()
    if len(convos) > 3:
        print(f"  … and {len(convos) - 3} more conversations")


def interactive_guide():
    print("""
╔══════════════════════════════════════════════════════╗
║         Chat Log Preparation Guide                   ║
╚══════════════════════════════════════════════════════╝

This tool converts your raw chat logs into training data.

Supported formats:
  1. WhatsApp  — export from WhatsApp > Chat > Export Chat (without media)
  2. Telegram  — export from Telegram Desktop > Settings > Export Chat History
  3. Discord   — use DiscordChatExporter tool to get JSON
  4. Plain     — manually formatted text file (Name: message)

Usage examples:
  python prepare_data.py whatsapp my_export.txt
  python prepare_data.py telegram result.json
  python prepare_data.py discord  messages.json
  python prepare_data.py plain    notes.txt
  python prepare_data.py preview  data/chatlogs_xxx.json

After conversion, files are saved to data/ automatically.
Then run: python ingest.py  (or python main.py --reingest)

── Manual format (.txt) ──────────────────────────────
If you're writing descriptions of the person's style manually,
create a file like this:

  # data/style_notes.txt
  
  Alex always starts network troubleshooting from Layer 1.
  When someone has a firewall issue, Alex asks to see the rules first.
  Alex is skeptical of commercial security products and prefers open source.
  Common phrases: "check your arp table", "that's a layer 8 problem", 
  "just use nftables, iptables is legacy at this point"

That file gets ingested directly — no conversion needed.
""")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "help":
        interactive_guide()
        return

    if args[0] == "preview":
        if len(args) < 2:
            print("Usage: python prepare_data.py preview <file.json>")
            return
        preview_file(args[1])
        return

    fmt = args[0].lower()
    if fmt not in CONVERTERS:
        print(f"Unknown format '{fmt}'. Use: {', '.join(CONVERTERS.keys())}")
        return

    if len(args) < 2:
        print(f"Usage: python prepare_data.py {fmt} <filepath>")
        return

    filepath = args[1]
    if not Path(filepath).exists():
        print(f"File not found: {filepath}")
        return

    # Get the persona name from config
    try:
        from config import PERSONA_NAME
    except ImportError:
        PERSONA_NAME = input("Enter the person's name (as it appears in the chat): ").strip()

    print(f"\n⟶ Converting {fmt} export: {filepath}")
    print(f"⟶ Persona name: {PERSONA_NAME}")

    converter = CONVERTERS[fmt]
    raw_messages = converter(filepath, PERSONA_NAME)
    print(f"   Parsed {len(raw_messages)} raw messages")

    filtered = filter_messages(raw_messages)
    print(f"   After filtering: {len(filtered)} messages")

    conversations = group_into_conversations(filtered, window=6)
    print(f"   Grouped into {len(conversations)} conversation windows")

    if not conversations:
        print("\n⚠  No usable conversations found.")
        print("   Check that PERSONA_NAME in config.py matches the name in the chat export exactly.")
        return

    source_name = Path(filepath).stem
    out_path = save_output(conversations, source_name)
    print(f"\n✅ Saved to {out_path}")
    print(f"   Run: python ingest.py  to embed this data")

    # Show a quick preview
    print("\n── Preview (first 2 conversations) ──")
    preview_file(out_path)


if __name__ == "__main__":
    main()
