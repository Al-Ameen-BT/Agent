#!/usr/bin/env python3
"""
Interactive CLI chat + health checks for the Ticketing Analytics Agent.

Use on the server when `start_analytics.py` runs as a systemd service (no browser
required) to verify:

  - Ollama accepts the configured model (same `.env` as the service)
  - HTTP API on port 8050 responds (`/api/live-status`, `/api/integration-status`, …)
  - Optional: PostgreSQL ticket context matches what `/api/chat` uses on the web

Run from the project root with the same virtualenv and WorkingDirectory as the service:

  python agent_chat_cli.py
  python agent_chat_cli.py --no-http-check
  python agent_chat_cli.py --api-base http://127.0.0.1:8050
  python agent_chat_cli.py --no-db-context
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _http_json(url: str, timeout: float = 8.0) -> tuple[int, dict | None, str]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            code = resp.getcode()
            try:
                return code, json.loads(raw), ""
            except json.JSONDecodeError:
                return code, None, raw[:300]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return e.code, None, body
    except Exception as e:
        return 0, None, repr(e)


def print_http_health(api_base: str) -> None:
    base = api_base.rstrip("/")
    print("\n--- HTTP API (dashboard service on 8050) ---")
    checks = [
        ("/api/live-status", lambda d: f"mode={d.get('mode')} status={d.get('status')} processed={d.get('total_processed')}"),
        (
            "/api/integration-status",
            lambda d: f"fetch_http={d.get('last_fetch_status_code')} last_count={d.get('last_fetch_count')} err={d.get('last_fetch_error') or 'none'}",
        ),
        ("/api/stats", lambda d: f"total_analyzed={d.get('total_analyzed')}"),
    ]
    for path, summarize in checks:
        url = base + path
        code, data, err = _http_json(url)
        if code == 200 and data is not None:
            print(f"  [ok] {path} HTTP {code}  {summarize(data)}")
        else:
            print(f"  [warn] {path} HTTP {code}  {err or data}")


def load_system_prompt(use_db: bool) -> str:
    if not use_db:
        return (
            "You are a concise IT helpdesk assistant. "
            "Answer accurately; keep answers focused unless the user asks for detail."
        )
    try:
        from analytics_agent.database import SessionLocal
        from analytics_agent.api import _build_chat_context

        with SessionLocal() as db:
            return _build_chat_context(db)
    except Exception as e:
        print(f"[warn] Could not load ticket DB context ({e}). Using minimal prompt.")
        return (
            "You are a concise IT helpdesk assistant. "
            "Answer accurately; keep answers focused unless the user asks for detail."
        )


def ollama_ping(client, settings_mod) -> bool:
    print("\n--- Ollama connectivity ---")
    try:
        client.chat(
            model=settings_mod.OLLAMA_MODEL,
            messages=[{"role": "user", "content": 'Reply with exactly: ok'}],
            options={
                "temperature": 0.1,
                "num_predict": 24,
                "num_ctx": 512,
                "num_thread": settings_mod.OLLAMA_NUM_THREADS,
            },
        )
        print(f"  [ok] Model `{settings_mod.OLLAMA_MODEL}` at `{settings_mod.OLLAMA_HOST}`")
        return True
    except Exception as e:
        print(f"  [error] {e}")
        print("  Fix OLLAMA_URL / OLLAMA_HOST and run `ollama pull` for this model.")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI chat + health verification for the analytics agent (systemd-friendly)."
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8050",
        help="Base URL of the running dashboard (default: http://127.0.0.1:8050)",
    )
    parser.add_argument(
        "--no-http-check",
        action="store_true",
        help="Do not call /api/live-status etc. (Ollama-only verification)",
    )
    parser.add_argument(
        "--no-db-context",
        action="store_true",
        help="Skip PostgreSQL ticket stats (minimal system prompt only)",
    )
    args = parser.parse_args()

    from analytics_agent.config import settings

    print("=== Analytics agent — CLI verify ===")
    print(f"Ollama host: {settings.OLLAMA_HOST}")
    print(f"Model:       {settings.OLLAMA_MODEL}")

    if not args.no_http_check:
        print_http_health(args.api_base)
    else:
        print("\n--- HTTP API ---  (skipped: --no-http-check)")

    system_prompt = load_system_prompt(use_db=not args.no_db_context)
    if not args.no_db_context:
        print("\n[ok] System prompt includes ticket DB aggregates (same source as web /api/chat).")

    import ollama

    client = ollama.Client(host=settings.OLLAMA_HOST)
    ollama_ping(client, settings)

    print("\nType your question (or /help). Ctrl+C or /quit to exit.\n")

    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            return 0

        if not line:
            continue

        cmd = line.lower()
        if cmd in ("/quit", "/exit", ":q"):
            print("Goodbye.")
            return 0
        if cmd == "/help":
            print(
                "  /help     This message\n"
                "  /status   Re-run HTTP checks against --api-base\n"
                "  /ping     Short Ollama round-trip\n"
                "  /quit     Exit"
            )
            continue
        if cmd == "/status":
            if args.no_http_check:
                print("  HTTP checks disabled; omit --no-http-check to enable.")
            else:
                print_http_health(args.api_base)
            continue
        if cmd == "/ping":
            ollama_ping(client, settings)
            continue

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": line},
        ]
        print("ai> ", end="", flush=True)
        try:
            stream = client.chat(
                model=settings.OLLAMA_MODEL,
                messages=messages,
                stream=True,
                options={
                    "temperature": settings.CHAT_TEMPERATURE,
                    "num_predict": settings.CHAT_NUM_PREDICT,
                    "num_ctx": settings.CHAT_NUM_CTX,
                    "num_thread": settings.OLLAMA_NUM_THREADS,
                    "keep_alive": -1,
                },
            )
            for chunk in stream:
                msg = chunk.get("message") or {}
                token = msg.get("content") or ""
                if token:
                    print(token, end="", flush=True)
                if chunk.get("done"):
                    break
            print()
        except Exception as e:
            print(f"\n[error] {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
