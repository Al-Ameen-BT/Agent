"""
main.py — IT Expert Persona Agent · Chat Interface

Usage:
  python main.py                # normal start
  python main.py --reingest     # reload all data first
  python main.py --clear-db     # wipe vector store and re-ingest

Commands during chat:
  /help       show commands
  /clear      reset conversation memory
  /save       save session log (usable as training data)
  /memory     show conversation summary
  /sources    toggle showing retrieved context
  /reingest   reload data from data/ folder
  /quit       exit
"""

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from config import MODEL, PERSONA_NAME, DATA_PATH
from ingest import ingest, load_vectorstore
from agent import ITAgent

console = Console()


# ── Banner ────────────────────────────────────────────────────────────────

def print_banner():
    console.print()
    console.print(Panel.fit(
        Text.assemble(
            ("  IT Expert Agent  ", "bold cyan"),
            ("\n  Persona: ", "dim"),
            (PERSONA_NAME, "green bold"),
            ("\n  Model:   ", "dim"),
            (MODEL, "yellow"),
        ),
        border_style="cyan",
        padding=(0, 2)
    ))
    console.print()
    console.print("[dim]  Type [bold]/help[/bold] for commands · [bold]/quit[/bold] to exit[/dim]")
    console.print()


def print_help():
    console.print("""
[bold]Commands:[/bold]
  [cyan]/clear[/cyan]      Reset conversation memory
  [cyan]/save[/cyan]       Save this session as training data
  [cyan]/memory[/cyan]     Show conversation summary
  [cyan]/sources[/cyan]    Toggle retrieved context display
  [cyan]/reingest[/cyan]   Reload all files from data/ folder
  [cyan]/help[/cyan]       Show this message
  [cyan]/quit[/cyan]       Exit
""")


# ── Setup ─────────────────────────────────────────────────────────────────

def ensure_data_folder():
    path = Path(DATA_PATH)
    path.mkdir(exist_ok=True)

    # Create example files if folder is empty
    example_txt = path / "example_style.txt"
    example_qa  = path / "example_qa.csv"

    if not any(path.iterdir()):
        example_txt.write_text(
            f"""# {PERSONA_NAME}'s IT Notes

## On diagnosing POST failures
When a machine won't POST, I always start by pulling everything non-essential.
One stick of RAM, no GPU (use onboard if available), just the CPU and one stick.
Nine times out of ten it's either a bad stick, wrong slot, or a PSU that can't
deliver on its rated wattage under load. Don't trust cheap no-name PSUs.

## On networking fundamentals  
Every network problem I've ever seen falls into one of three buckets: physical layer
(cable, SFP, NIC), addressing (wrong subnet, VLAN mismatch, bad default gateway),
or routing/firewall (ACL blocking traffic, missing route). Work layer 1 up, always.

## On Linux server maintenance
Automation is non-negotiable on anything you touch more than once a week.
If you're SSH-ing into a box to do the same thing manually, write the script.
cron or systemd timers, doesn't matter which — just stop doing it by hand.
""", encoding="utf-8")

        example_qa.write_text(
            "question,answer\n"
            "\"My PC won't turn on at all\",\"Check the PSU switch on the back first — it sounds obvious but it's always worth checking. Then test with a known-good power cable. If still nothing, short the power pins on the motherboard header directly to rule out a bad front-panel connector.\"\n"
            "\"What's the difference between a hub and a switch?\",\"A hub broadcasts every packet to every port — it's basically a dumb repeater. A switch learns MAC addresses and only forwards frames to the right port. You should never use a hub in anything built after 2005.\"\n"
            "\"How do I find what's using a port in Linux?\",\"ss -tlnp | grep PORT or lsof -i :PORT. ss is faster and more reliable than netstat on modern distros.\"\n",
            encoding="utf-8")

        console.print(f"[dim]Created example files in {DATA_PATH}/ — replace them with your real data.[/dim]")


def setup(force_reingest: bool = False, clear_db: bool = False):
    ensure_data_folder()

    if clear_db or force_reingest:
        if clear_db:
            console.print("[yellow]Clearing existing vector store…[/yellow]")
        ingest(clear_existing=clear_db)

    return load_vectorstore()


# ── Main loop ─────────────────────────────────────────────────────────────

def main():
    force_reingest = "--reingest" in sys.argv
    clear_db       = "--clear-db" in sys.argv

    print_banner()

    try:
        vectorstore = setup(force_reingest=force_reingest, clear_db=clear_db)
    except Exception as e:
        console.print(f"[red]Setup failed: {e}[/red]")
        console.print("[dim]Make sure Ollama is running and nomic-embed-text is pulled.[/dim]")
        sys.exit(1)

    agent = ITAgent(vectorstore)

    console.print(f"[green]✓ {PERSONA_NAME} is ready.[/green]\n")

    while True:
        try:
            user_input = console.input("[bold white]You:[/bold white] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye.[/dim]")
            agent.save_session()
            break

        if not user_input:
            continue

        # ── Commands ──────────────────────────────────────────────────────
        cmd = user_input.lower()

        if cmd in ("/quit", "/exit", "exit", "quit"):
            agent.save_session()
            console.print("[dim]Session saved. Goodbye.[/dim]")
            break

        elif cmd == "/help":
            print_help()

        elif cmd == "/clear":
            agent.clear_memory()

        elif cmd == "/save":
            agent.save_session()

        elif cmd == "/memory":
            agent.show_memory()

        elif cmd == "/sources":
            agent.toggle_sources()

        elif cmd == "/reingest":
            console.print("[cyan]Re-ingesting data…[/cyan]")
            try:
                ingest(clear_existing=True)
                vectorstore = load_vectorstore()
                agent.vectorstore = vectorstore
                console.print("[green]Done.[/green]")
            except Exception as e:
                console.print(f"[red]Reingest failed: {e}[/red]")

        # ── Normal chat ───────────────────────────────────────────────────
        else:
            agent.chat(user_input)


if __name__ == "__main__":
    main()
