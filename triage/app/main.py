"""Application entry point.

    python -m uvicorn app.main:app --reload --port 8000
or  ./run.sh
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import router
from .triage import pool

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="Wellington EOC — reporting triage",
    version="0.1.0",
    description=(
        "Sorts incoming disaster reportings into action required, verification "
        "required and situational awareness, keeps a full audit trail, and "
        "produces a shift handover briefing.\n\n"
        "**Prototype for Impact Lab Wellington. Not an operational emergency "
        "system. In an emergency, call 111.**"
    ),
)

# Other Impact Lab teams need to read the feed from their own pages.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    db.connect()
    pool.start()


@app.on_event("shutdown")
def shutdown() -> None:
    pool.stop()


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
