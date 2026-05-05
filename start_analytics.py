import uvicorn

if __name__ == "__main__":
    print("Starting Offline Ticketing Analytics Agent & Dashboard...")
    # Run the FastAPI server which also manages the background agent worker
    uvicorn.run("analytics_agent.api:app", host="0.0.0.0", port=8050, reload=True)
