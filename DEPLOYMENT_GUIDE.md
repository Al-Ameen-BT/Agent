# 🚀 Offline Agent Suite: Deployment Guide

This document outlines how to deploy all three components of the Agent suite on an isolated network/server. 

## 🏗️ System Requirements
1. **Python 3.9+** (For the application code)
2. **PostgreSQL 16+** with `pgvector` (For storing embeddings and the Analytics DB)
3. **Ollama** (Running locally on the server for isolated inference)

---

## 🛠️ 1. Environment Setup

### Install Dependencies
Navigate to the project root and install the required Python packages into a virtual environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Install & Configure PostgreSQL (Rocky Linux Example)
If you don't already have PostgreSQL set up, initialize it and create the database for the agent.

```bash
# Install postgres and pgvector
sudo dnf install -y postgresql16 postgresql16-server postgresql16-devel

# Initialize and start
sudo /usr/pgsql-16/bin/postgresql-16-setup initdb
sudo systemctl enable --now postgresql-16

# Create the database and user
sudo -u postgres psql <<'SQL'
CREATE DATABASE agent_db;
\c agent_db
CREATE EXTENSION IF NOT EXISTS vector;
ALTER USER postgres WITH PASSWORD 'postgres';
SQL
```

### Pull the Local Models
Ensure your isolated Ollama instance is running, then pull the required models:

```bash
ollama pull gemma4:e4b
ollama pull nomic-embed-text
```

---

## ⚙️ 2. Configuration (`.env`)

Copy the `.env.example` file to create your own local `.env` configuration:
```bash
cp .env.example .env
```

Ensure your `.env` contains the correct paths, particularly the new configuration settings for the Ticketing Analytics Dashboard.

```env
# LLM settings
MODEL=gemma4:e4b
EMBED_MODEL=nomic-embed-text
OLLAMA_URL=http://127.0.0.1:11434

# PostgreSQL + pgvector
PGVECTOR_CONNECTION=postgresql+psycopg://postgres:postgres@localhost:5432/agent_db
ANALYTICS_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/agent_db

# External Ticketing API Configuration
TICKETING_API_URL=http://<YOUR_PRODUCTION_TICKETING_API>/tickets/unprocessed
TICKETING_API_KEY=<YOUR_API_KEY_IF_NEEDED>

# Worker Configuration
POLL_INTERVAL_SECONDS=30
```

---

## 🚀 3. Running the Applications

This project contains three separate execution modules depending on your needs. You can run them concurrently using standard Linux tools like `tmux`, `screen`, or as `systemd` background services.

### A. The CLI Chat Agent (Interactive Knowledge Base)
Used for interacting directly with the agent through the terminal using your vectorized documents.
```bash
# First time setup: ingest your files
python ingest.py --clear

# Run the CLI chat
python main.py
```

### B. The Agent Bridge API (SQLite-based on-demand analysis)
A FastAPI bridge used for submitting single tickets manually via HTTP POST requests.
```bash
uvicorn agent_bridge.main:app --host 0.0.0.0 --port 8000
```
- **API Docs:** `http://localhost:8000/docs`

### C. The Offline Ticketing Analytics & Dashboard 🌟
The newest module: runs a continuous background worker polling your Ticketing API, saving intelligence to PostgreSQL, and serving a stunning web dashboard.

```bash
python start_analytics.py
```
- **Port:** `8050`
- **Dashboard UI:** Open `http://<SERVER_IP>:8050/` in any browser on your network (No login required).
- **Behavior:** The script handles both the background `ollama` processing loop and serving the web dashboard concurrently.

---

## 🛠️ 4. Running as a Linux Service (`systemd`)

To ensure the Analytics Agent runs continuously in the background and restarts automatically on server reboots or crashes, you should deploy it as a `systemd` service.

1. **Review the template**: I have created a file named `agent-analytics.service` in your project folder.
2. **Update the paths**: Edit `agent-analytics.service` and change `WorkingDirectory` to the absolute path of your project directory, and ensure `ExecStart` points to your `.venv/bin/python`.
3. **Install the service**:

```bash
# Copy the service file to systemd
sudo cp agent-analytics.service /etc/systemd/system/

# Reload systemd to recognize the new service
sudo systemctl daemon-reload

# Start the service
sudo systemctl start agent-analytics.service

# Enable it to start automatically on boot
sudo systemctl enable agent-analytics.service
```

4. **Monitor logs**:
```bash
# View the live logs
sudo tail -f /var/log/agent-analytics.log
# Or using journalctl
sudo journalctl -u agent-analytics.service -f
```

---

## 🔒 Best Practices for Isolated Networks
- **Firewall Rules:** Ensure port `8050` is exposed internally so administrators can access the Analytics dashboard, but block outbound connections from the server if strict isolation is required.
- **Model Updates:** To update `gemma4:e4b` offline, you will need to download the model blobs from a connected machine and `scp` them into the isolated server's `~/.ollama/models` directory.
