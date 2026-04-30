"""
agent.py — IT Expert Persona Agent

Flow per query:
  1. Detect IT domain (hardware / networking / software / sysadmin / security)
  2. Retrieve relevant chunks from vector store (RAG)
  3. Build prompt: persona + retrieved context + conversation history
  4. Stream DeepSeek response, stripping <think> blocks
  5. Save turn to memory
"""

import re
import ollama
from rich.console import Console
from rich.markdown import Markdown

from memory import ConversationMemory
from config import (
    MODEL, PERSONA, OLLAMA_URL, RETRIEVAL_K, MAX_TURNS,
    DOMAIN_KEYWORDS, PERSONA_NAME
)

console = Console()


# ── Domain detection ──────────────────────────────────────────────────────

from typing import Optional

def detect_domain(query: str) -> Optional[str]:
    q = query.lower()
    scores = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q)
        if score:
            scores[domain] = score
    if not scores:
        return None
    return max(scores, key=scores.get)


# ── Context retrieval ─────────────────────────────────────────────────────

def retrieve_context(query: str, vectorstore, domain: str | None, k: int = RETRIEVAL_K) -> str:
    """
    Retrieve relevant chunks. If a domain is detected, do an extra
    domain-boosted search on top of the semantic search.
    """
    results = vectorstore.similarity_search(query, k=k)

    # If domain detected, also search with a domain-flavored query
    if domain:
        domain_query = f"{domain} {query}"
        extra = vectorstore.similarity_search(domain_query, k=2)
        # Deduplicate by content
        seen = {r.page_content for r in results}
        for doc in extra:
            if doc.page_content not in seen:
                results.append(doc)
                seen.add(doc.page_content)

    if not results:
        return ""

    parts = []
    for i, doc in enumerate(results):
        src = doc.metadata.get("filename", "knowledge base")
        dtype = doc.metadata.get("type", "")
        header = f"[Source {i+1}: {src}" + (f" · {dtype}" if dtype else "") + "]"
        parts.append(f"{header}\n{doc.page_content}")

    return "\n\n".join(parts)


# ── Prompt builder ────────────────────────────────────────────────────────

def build_system_prompt(context: str, domain: str | None) -> str:
    domain_hint = ""
    if domain:
        domain_hint = f"\n## This question is about: {domain.upper()}\nDraw especially on your {domain} expertise.\n"

    if context:
        return f"""{PERSONA}
{domain_hint}
## Relevant knowledge from your training data:
{context}

Base your answer on this context first. 
If the context doesn't fully cover the question, use your general IT knowledge.
Never contradict information in the context above.
"""
    return f"{PERSONA}\n{domain_hint}"


# ── Response cleaning ─────────────────────────────────────────────────────

def clean_response(text: str) -> str:
    """Remove DeepSeek R1 <think>...</think> internal reasoning blocks."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()


# ── Agent class ───────────────────────────────────────────────────────────

class ITAgent:
    def __init__(self, vectorstore):
        self.vectorstore = vectorstore
        self.memory = ConversationMemory(max_turns=MAX_TURNS)
        self.client = ollama.Client(host=OLLAMA_URL)
        self.show_sources = False   # toggle with /sources

    def chat(self, user_input: str) -> str:
        # 1. Detect domain
        domain = detect_domain(user_input)

        # 2. Retrieve context
        context = retrieve_context(user_input, self.vectorstore, domain)

        if self.show_sources and context:
            console.print("\n[dim]─── Retrieved context ───[/dim]")
            console.print(f"[dim]{context[:600]}…[/dim]" if len(context) > 600 else f"[dim]{context}[/dim]")
            console.print("[dim]─────────────────────────[/dim]\n")

        # 3. Build messages
        system = build_system_prompt(context, domain)
        messages = [{"role": "system", "content": system}]
        messages += self.memory.get_messages()
        messages.append({"role": "user", "content": user_input})

        if domain:
            console.print(f"[dim]⟶ Domain: {domain}[/dim]")

        # 4. Stream response
        response_text = ""
        in_think = False
        buffer = ""

        try:
            stream = self.client.chat(
                model=MODEL,
                messages=messages,
                stream=True,
                options={"temperature": 0.65, "num_predict": 1024}
            )

            console.print(f"\n[bold green]{PERSONA_NAME}:[/bold green] ", end="")

            for chunk in stream:
                token = chunk["message"]["content"]
                buffer += token

                # Handle <think> blocks — hide from output
                while buffer:
                    if in_think:
                        end = buffer.find("</think>")
                        if end != -1:
                            buffer = buffer[end + len("</think>"):]
                            in_think = False
                        else:
                            buffer = ""  # still inside think block, wait
                            break
                    else:
                        start = buffer.find("<think>")
                        if start != -1:
                            # Print everything before <think>
                            visible = buffer[:start]
                            if visible:
                                print(visible, end="", flush=True)
                                response_text += visible
                            buffer = buffer[start + len("<think>"):]
                            in_think = True
                        else:
                            # No think tag — print and clear buffer
                            print(buffer, end="", flush=True)
                            response_text += buffer
                            buffer = ""
                            break

        except ollama.ResponseError as e:
            console.print(f"\n[red]Model error: {e}[/red]")
            console.print(f"[dim]Try: ollama pull {MODEL}[/dim]")
            return ""
        except Exception as e:
            console.print(f"\n[red]Connection error: {e}[/red]")
            console.print("[dim]Is Ollama running? Try: ollama serve[/dim]")
            return ""

        print("\n")  # newline after streamed response

        # 5. Save to memory
        self.memory.add("user", user_input)
        self.memory.add("assistant", response_text)

        return response_text

    def clear_memory(self):
        self.memory.clear()
        console.print("[yellow]🧹 Memory cleared.[/yellow]")

    def save_session(self):
        path = self.memory.save_log()
        if path:
            console.print(f"[green]💾 Session saved to {path}[/green]")
            console.print("[dim]You can move this file to data/ and re-ingest to train on it.[/dim]")
        else:
            console.print("[yellow]Nothing to save yet.[/yellow]")

    def show_memory(self):
        console.print("\n[bold]── Conversation so far ──[/bold]")
        console.print(self.memory.get_summary_text())
        console.print()

    def toggle_sources(self):
        self.show_sources = not self.show_sources
        state = "ON" if self.show_sources else "OFF"
        console.print(f"[yellow]Source display: {state}[/yellow]")
