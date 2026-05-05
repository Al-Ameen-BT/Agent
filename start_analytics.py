import uvicorn

if __name__ == "__main__":
    print("Starting Offline Ticketing Analytics Agent & Dashboard...")
    # NOTE: reload=False is required in production.
    # reload=True causes a file-system watcher process that pegs CPU at 100%.
    uvicorn.run(
        "analytics_agent.api:app",
        host="0.0.0.0",
        port=8050,
        reload=False,       # NEVER True in production/systemd
        workers=1,          # Single worker — the background task lives here
        log_level="info"
    )
