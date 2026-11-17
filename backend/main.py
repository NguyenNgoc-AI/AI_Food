from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse


app = FastAPI(title="SmartFood AI")
index = Path(__file__).resolve().parents[1] / "web" / "index.html"


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(index, media_type="text/html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
