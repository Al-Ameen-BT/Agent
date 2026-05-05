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
MODEL=gemma4:e4b
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
ollama pull gemma4:e4b
ollama pull nomic-embed-text
```

## 6) Ingest and run

```bash
python ingest.py --clear
python main.py
```

## 7) Run as a 24/7 Background Service

To run the web app and analytics worker continuously, you should use `systemd`. We have provided a template service file: `agent-analytics.service`.

1. Open `agent-analytics.service` and update the `WorkingDirectory` and `ExecStart` paths to match exactly where you cloned this repository (e.g., `/home/user/Agent`). Update the `User` and `Group` to match your linux username.
2. Copy the service file to systemd:
   ```bash
   sudo cp agent-analytics.service /etc/systemd/system/
   ```
3. Reload the systemd daemon to recognize your new service:
   ```bash
   sudo systemctl daemon-reload
   ```
4. Enable the service so it starts automatically on server boot:
   ```bash
   sudo systemctl enable agent-analytics.service
   ```
5. Start the service immediately:
   ```bash
   sudo systemctl start agent-analytics.service
   ```
6. Check the status to ensure it's running smoothly:
   ```bash
   sudo systemctl status agent-analytics.service
   ```
   *(You can view live logs using `sudo journalctl -u agent-analytics.service -f`)*

## Notes

- Python 3.9 compatibility is already handled in this repo.
- Keep real secrets in `.env` only; commit `.env.example` only.
- If DB auth differs, update `PGVECTOR_CONNECTION` accordingly.
