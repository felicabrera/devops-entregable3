import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
NOTES_FILE = DATA_DIR / "notes.json"

API_TITLE = os.environ.get("API_TITLE", "Notes API")
WELCOME_MESSAGE = os.environ.get("WELCOME_MESSAGE", "Notes API is enabled and working")
HEALTH_PARAM = os.environ.get("HEALTH_PARAM", "default")
APP_VERSION = os.environ.get("APP_VERSION", "v1.0.0")
APP_COLOR = os.environ.get("APP_COLOR", "blue")

_lock = threading.Lock()

app = FastAPI(title=API_TITLE)

NOTES_CREATED_TOTAL = Counter(
    "notes_created_total", "Notas creadas desde que arrancó el proceso"
)
NOTES_TOTAL = Gauge("notes_total", "Cantidad de notas guardadas actualmente")
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "Duración de las llamadas HTTP por endpoint",
    ["method", "endpoint", "status"],
)


def _load_notes() -> list[dict]:
    if not NOTES_FILE.exists():
        return []
    with NOTES_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_notes(notes: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = NOTES_FILE.with_suffix(".tmp")
    with tmp_file.open("w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)
    tmp_file.replace(NOTES_FILE)


@app.middleware("http")
async def track_requests(request: Request, call_next):
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        endpoint = route.path if route else "unmatched"
        if endpoint != "/metrics":
            HTTP_REQUEST_DURATION.labels(
                request.method, endpoint, str(status)
            ).observe(time.perf_counter() - start)


@app.get("/metrics", include_in_schema=False)
def metrics():
    with _lock:
        NOTES_TOTAL.set(len(_load_notes()))
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/")
def root():
    return {
        "message": WELCOME_MESSAGE,
        "version": APP_VERSION,
        "color": APP_COLOR,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "health_param": HEALTH_PARAM,
        "version": APP_VERSION,
        "color": APP_COLOR,
    }


@app.post("/add/{note}")
def add_note(note: str):
    with _lock:
        notes = _load_notes()
        entry = {
            "id": len(notes) + 1,
            "text": note,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        notes.append(entry)
        _save_notes(notes)
        NOTES_TOTAL.set(len(notes))
    NOTES_CREATED_TOTAL.inc()
    return entry


@app.get("/list")
def list_notes():
    with _lock:
        notes = _load_notes()
    return {"notes": notes}


if APP_VERSION.startswith("v2"):

    @app.get("/stats")
    def stats():
        with _lock:
            notes = _load_notes()
        return {"total_notes": len(notes), "version": APP_VERSION}
