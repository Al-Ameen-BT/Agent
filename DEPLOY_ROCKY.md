# Deploy on Rocky Linux (Quick Guide)

This project runs with Ollama + PostgreSQL (`pgvector`) on Rocky Linux.

## 1) System packages

```bash
sudo dnf install -y python3-devel gcc postgresql16 postgresql16-server postgresql16-devel
```

## 2) Python dependencies

From the project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 3) Configure environment

Create your env file from template:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```env
MODEL=deepseek-r1:7b
EMBED_MODEL=nomic-embed-text
OLLAMA_URL=http://localhost:11434
PGVECTOR_CONNECTION=postgresql+psycopg://postgres:postgres@localhost:5432/agent_db
PGVECTOR_COLLECTION=it_expert_knowledge
```

## 4) PostgreSQL + pgvector setup

Initialize/start PostgreSQL (first time):

```bash
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16
```

Create DB + extension:

```bash
sudo -u postgres psql <<'SQL'
CREATE DATABASE agent_db;
\c agent_db
CREATE EXTENSION IF NOT EXISTS vector;
ALTER USER postgres WITH PASSWORD 'postgres';
SQL
```

## 5) Ollama models

Ensure Ollama is running, then pull models:

```bash
ollama pull deepseek-r1:7b
ollama pull nomic-embed-text
```

## 6) Ingest and run

```bash
python ingest.py --clear
python main.py
```

## Notes

- Python 3.9 compatibility is already handled in this repo.
- Keep real secrets in `.env` only; commit `.env.example` only.
- If DB auth differs, update `PGVECTOR_CONNECTION` accordingly.
