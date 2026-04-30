"""
ingest.py — Load your training data into the vector store

Supports:
  - .txt  plain text
  - .md   markdown
  - .pdf  PDFs
  - .json chat/conversation exports  {"messages": [{"role":..., "content":...}]}
  - .csv  Q&A pairs  columns: question, answer
"""

import json
import csv
from typing import List
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_postgres import PGVector
from rich.console import Console
from rich.progress import track

from config import (
    EMBED_MODEL,
    DATA_PATH,
    OLLAMA_URL,
    PERSONA_NAME,
    PGVECTOR_CONNECTION,
    PGVECTOR_COLLECTION,
)

console = Console()


# ── Loaders ───────────────────────────────────────────────────────────────

def load_text_file(path: str) -> List[Document]:
    loader = TextLoader(path, encoding="utf-8")
    return loader.load()


def load_pdf_file(path: str) -> List[Document]:
    loader = PyPDFLoader(path)
    return loader.load()


def load_json_conversations(path: str) -> List[Document]:
    """
    Expects JSON format:
      {"messages": [{"role": "user"|"assistant", "content": "..."}]}
    OR a list of such objects.
    Converts conversations into Q&A text blocks so the agent learns the style.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = [data]

    docs = []
    for convo in data:
        msgs = convo.get("messages", [])
        blocks = []
        for m in msgs:
            role = m.get("role", "unknown")
            content = m.get("content", "").strip()
            label = f"{PERSONA_NAME}" if role == "assistant" else "User"
            blocks.append(f"{label}: {content}")
        text = "\n\n".join(blocks)
        if text.strip():
            docs.append(Document(
                page_content=text,
                metadata={"source": path, "type": "conversation"}
            ))
    return docs


def load_csv_qa(path: str) -> List[Document]:
    """
    Expects CSV with columns: question, answer
    Each row becomes one document chunk.
    """
    docs = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = row.get("question", "").strip()
            a = row.get("answer", "").strip()
            if q and a:
                text = f"Q: {q}\n\nA: {a}"
                docs.append(Document(
                    page_content=text,
                    metadata={"source": path, "type": "qa_pair"}
                ))
    return docs


# ── Main ingestion ─────────────────────────────────────────────────────────

def load_all_documents() -> List[Document]:
    loaders = {
        ".txt": load_text_file,
        ".md":  load_text_file,
        ".pdf": load_pdf_file,
        ".json": load_json_conversations,
        ".csv": load_csv_qa,
    }

    all_docs = []
    data_dir = Path(DATA_PATH)

    if not data_dir.exists():
        data_dir.mkdir(parents=True)
        console.print(f"[yellow]Created {DATA_PATH}/ — add your files there and re-run.[/yellow]")
        return []

    files = list(data_dir.rglob("*"))
    supported = [f for f in files if f.suffix.lower() in loaders and f.is_file()]

    if not supported:
        console.print(f"[yellow]No supported files found in {DATA_PATH}/[/yellow]")
        console.print("[dim]Supported: .txt .md .pdf .json .csv[/dim]")
        return []

    for fpath in track(supported, description="Loading files"):
        ext = fpath.suffix.lower()
        try:
            docs = loaders[ext](str(fpath))
            for d in docs:
                d.metadata["filename"] = fpath.name
            all_docs.extend(docs)
            console.print(f"  [green]✓[/green] {fpath.name} → {len(docs)} doc(s)")
        except Exception as e:
            console.print(f"  [red]✗[/red] {fpath.name}: {e}")

    return all_docs


def ingest(clear_existing: bool = False):
    console.rule("[bold cyan]Data Ingestion")

    docs = load_all_documents()
    if not docs:
        return None

    console.print(f"\n[cyan]Loaded {len(docs)} document(s) total[/cyan]")

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,
        chunk_overlap=80,
        separators=["\n\n", "\n", ". ", " ", ""]
    )
    chunks = splitter.split_documents(docs)
    console.print(f"[cyan]Split into {len(chunks)} chunks[/cyan]")

    # Embed and store
    console.print("\n[cyan]Embedding chunks (this may take a minute)…[/cyan]")
    embeddings = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)

    db = PGVector.from_documents(
        documents=chunks,
        embedding=embeddings,
        connection=PGVECTOR_CONNECTION,
        collection_name=PGVECTOR_COLLECTION,
        pre_delete_collection=clear_existing,
    )

    console.print(
        f"\n[bold green]✅ Done! {len(chunks)} chunks stored in PostgreSQL collection '{PGVECTOR_COLLECTION}'[/bold green]"
    )
    return db


def load_vectorstore():
    embeddings = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
    return PGVector(
        embeddings=embeddings,
        connection=PGVECTOR_CONNECTION,
        collection_name=PGVECTOR_COLLECTION,
    )


if __name__ == "__main__":
    import sys
    clear = "--clear" in sys.argv
    ingest(clear_existing=clear)
