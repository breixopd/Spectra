"""Worker service entry point (python -m app.worker).

Launches the same FastAPI-based worker service used by docker compose,
ensuring health endpoints are available regardless of how the worker starts.
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.worker_service:app", host="0.0.0.0", port=5012)
