# Offline Agent Suite: Deployment Guide

How to deploy the three runnable components on an isolated network or server: the CLI RAG agent, the Agent Bridge API, and the Ticketing Analytics dashboard (worker + UI).

## System requirements

- **Python 3.9+**
- **PostgreSQL 16+** with **pgvector** (embeddings + analytics database)
- **Ollama** for local inference (same host as the apps or reachable on the LAN)

---

## 1. Environment setup

### Install dependencies

From the project root, using a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### PostgreSQL and pgvector (Rocky Linux example)

```bash
sudo dnf install -y postgresql16 postgresql16-server postgresql16-devel
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16

sudo -u postgres psql <<'SQL'
CREATE DATABASE agent_db;
\c agent_db
CREATE EXTENSION IF NOT EXISTS vector;
ALTER USER postgres WITH PASSWORD 'postgres';
SQL
```

Adjust user, password, and database name to match what you put in `ANALYTICS_POSTGRES_URL` / `PGVECTOR_CONNECTION`.

### Pull Ollama models

On the machine that runs Ollama:

```bash
ollama pull gemma4:e4b
ollama pull nomic-embed-text
```

`nomic-embed-text` is required by the CLI ingest/RAG path (`main.py` / `ingest.py`). The analytics dashboard uses the chat/analysis model from `MODEL` / `OLLAMA_MODEL`.

---

## 2. Configuration (`.env`)

### Create your env file

Copy the template and edit secrets and URLs:

```bash
cp .env.example .env
```

Never commit real API keys. Replace placeholder values such as `<your_generated_key>` with production credentials.

### Environment variable naming (important)

The repo supports **two naming styles** so one `.env` can serve both the root CLI agent and the HTTP services:

| Purpose | Either use | Or |
|--------|------------|-----|
| Ollama base URL | `OLLAMA_URL` | `OLLAMA_HOST` |
| Chat/analysis model name | `MODEL` | `OLLAMA_MODEL` |

Resolution order:

- **Analytics dashboard** (`analytics_agent`): `OLLAMA_HOST` or `OLLAMA_URL` (default `http://127.0.0.1:11434`); `OLLAMA_MODEL` or `MODEL` (default `gemma4:e4b`).
- **Agent Bridge** (`agent_bridge`): same fallbacks as above.
- **CLI agent** (`main.py` / `config.py`): reads `OLLAMA_URL` and `MODEL` via `python-dotenv`.

The **analytics** settings class loads env files in this order: **`.env` first, then `.env.example`**. If `.env` is missing, values from `.env.example` are still applied so the dashboard does not silently fall back to built-in localhost mock URLs when you only ship the example file.

### Example `.env` blocks

Root / shared LLM and paths (CLI + defaults):

```env
MODEL=gemma4:e4b
EMBED_MODEL=nomic-embed-text
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_NUM_THREADS=6
```

PostgreSQL:

```env
PGVECTOR_CONNECTION=postgresql+psycopg://postgres:postgres@localhost:5432/agent_db
PGVECTOR_COLLECTION=it_expert_knowledge
ANALYTICS_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/agent_db
```

Ticketing integration (analytics worker). Match **your** API’s path and query parameters:

```env
TICKETING_API_URL=http://<TICKET_HOST>:<PORT>/api/agent-integration/tickets
TICKETING_UPDATE_URL=http://<TICKET_HOST>:<PORT>/api/agent-integration/dashboard-payload
TICKETING_API_KEY=<real_secret_key>

# Pagination: use the names your API expects, e.g. page/per_page or offset/limit
TICKETING_PAGE_PARAM=offset
TICKETING_PER_PAGE_PARAM=limit
TICKETS_PER_PAGE=100

POLL_INTERVAL_SECONDS=120
BACKFILL_DELAY_SECONDS=2.0
```

The worker tries **canonical URL aliases** automatically (for example `/api/agent-integration/tickets` vs `/api/tickets/unprocessed`, and the dashboard-payload vs update URL). You still need the correct base host, key, and pagination params.

Optional:

- **`AGENT_INTEGRATION_KEY`**: if your ticketing server expects an agent identity header; can also be generated from the dashboard (stored in the DB).
- **`STRICT_PRODUCTION_INTEGRATION=true`**: refuse startup if `TICKETING_API_URL` looks like mock/local (see `analytics_agent/api.py`).

---

## 3. Running the applications

Run components with the venv activated and `WorkingDirectory` set to the project root so `.env` is found.

### A. CLI chat agent (RAG over local files)

```bash
python ingest.py --clear    # first-time or full re-ingest
python main.py
```

Uses `config.py` / `.env` for `OLLAMA_URL`, `MODEL`, `PGVECTOR_*`, etc.

### B. Agent Bridge API (on-demand ticket analysis)

```bash
uvicorn agent_bridge.main:app --host 0.0.0.0 --port 8000
```

- OpenAPI docs: `http://<host>:8000/docs`
- Configure auth and Ollama via `.env` (`OLLAMA_HOST`/`OLLAMA_URL`, `OLLAMA_MODEL`/`MODEL`, `AGENT_BRIDGE_*`).

### C. Ticketing analytics and dashboard

```bash
python start_analytics.py
```

- **Port:** `8050`
- **UI:** `http://<SERVER_IP>:8050/` (static dashboard + API on the same port)

Behavior: background worker polls the ticketing API, analyzes tickets with Ollama, persists to PostgreSQL, and serves the SPA. Open the app from this server so browser requests stay **same-origin** (`/api/...`).

### HTTP endpoints useful for operations

| Endpoint | Purpose |
|----------|---------|
| `GET /api/live-status` | Worker mode, backfill page, current ticket, counters |
| `GET /api/integration-status` | Last fetch/push to ticketing API, key masked flags |
| `GET /api/stats` | Aggregations and recent tickets for the UI |
| `GET /api/diagnostics/last-fetched-ticket` | Normalized field mapping for the **first ticket** in the last successful pull (debug schema mismatches) |
| `POST /api/chat` | SSE streaming chat (dashboard) |

The dashboard **Settings** modal saves `TICKETING_API_KEY` (and can generate an agent integration key). Placeholder keys are treated as **not configured** for integration health.

---

## 4. systemd service (Linux)

Use `agent-analytics.service` as a template.

1. Set **`User`/`Group`**, **`WorkingDirectory`** to your project path, and **`ExecStart`** to `.venv/bin/python start_analytics.py`.
2. Optionally set **`Environment=`** for `OLLAMA_HOST`, `OLLAMA_MODEL`, or rely on `.env` in `WorkingDirectory` (the app loads it).

```bash
sudo cp agent-analytics.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agent-analytics.service
sudo journalctl -u agent-analytics.service -f
```

---

## 5. Firewall and network

- Open **8050** (dashboard) only on trusted networks.
- Ensure the app host can reach **Ollama** (`OLLAMA_URL` / `OLLAMA_HOST`) and **PostgreSQL**.
- Ensure the analytics worker can reach **TICKETING_API_URL** and **TICKETING_UPDATE_URL** with the configured keys.

---

## 6. Offline model updates

To refresh `gemma4:e4b` without internet on the server, copy model blobs from a connected machine into the target host’s Ollama model directory (same layout as a normal `ollama pull`).

---

## 7. Troubleshooting

| Symptom | What to check |
|--------|----------------|
| Dashboard shows mock/local warning | `TICKETING_API_URL` hostname is `localhost` or contains `mock`; fix URL or set production env. |
| No tickets ingested | `GET /api/integration-status` for HTTP status and errors; `GET /api/diagnostics/last-fetched-ticket` for raw keys vs normalized id/title/description. |
| Chat returns errors or empty stream | Ollama reachable at `OLLAMA_URL`/`OLLAMA_HOST`; model pulled; `GET /api/live-status` for worker errors. |
| Keys saved but integration still “warning” | Do not leave `TICKETING_API_KEY` as a placeholder string; use a real key from your ticketing system. |

For deeper API debugging, use `GET /api/admin/connectivity-check` (requires the app running and reaches pull/push URLs with current headers).
