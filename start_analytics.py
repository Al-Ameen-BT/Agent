import uvicorn

if __name__ == "__main__":
    print("Starting Offline Ticketing Analytics Agent & Dashboard...")
    uvicorn.run(
        "analytics_agent.api:app",
        host="0.0.0.0",
        port=8050,
        reload=False,       # Never True in production — causes file watcher CPU spike
        log_level="info"
        # NOTE: Do NOT set workers= here. The workers parameter only works via the
        # uvicorn CLI, not the Python API. Setting it causes exit code 3/NOTIMPLEMENTED.
    )
