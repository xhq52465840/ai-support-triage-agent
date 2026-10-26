"""FastAPI dashboard + JSON API."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .agent import build_graph, triage
from .models import Email

HERE = Path(__file__).resolve().parent
INBOX = HERE.parent / "data" / "inbox.json"

app = FastAPI(title="AI Support Triage Agent")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
_graph = None


def graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


class NewEmail(BaseModel):
    sender: str
    subject: str
    body: str


class StatusUpdate(BaseModel):
    status: str
    reply: str | None = None


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/meta")
def meta():
    return {"mode": "openai" if os.getenv("OPENAI_API_KEY") else "mock", "inbox_size": len(json.loads(INBOX.read_text()))}


@app.get("/api/tickets")
def tickets():
    return db.list_tickets()


@app.get("/api/tickets/{tid}")
def ticket(tid: str):
    t = db.get_ticket(tid)
    if not t:
        raise HTTPException(404)
    return t


@app.post("/api/process-inbox")
def process_inbox():
    done = {t["id"] for t in db.list_tickets()}
    new = [Email(**e) for e in json.loads(INBOX.read_text()) if e["id"] not in done]
    for e in new:
        triage(e, graph())
    return {"processed": len(new)}


@app.post("/api/emails")
def ingest_email(body: NewEmail):
    email = Email(id="T-" + uuid.uuid4().hex[:6].upper(), received_at=datetime.now(timezone.utc).isoformat(timespec="minutes"), **body.model_dump())
    triage(email, graph())
    return db.get_ticket(email.id)


@app.patch("/api/tickets/{tid}")
def set_status(tid: str, upd: StatusUpdate):
    if not db.get_ticket(tid):
        raise HTTPException(404)
    db.update_status(tid, upd.status, upd.reply)
    return db.get_ticket(tid)


@app.post("/api/reset")
def reset():
    db.reset()
    return {"ok": True}


@app.get("/api/export.csv")
def export():
    return FileResponse(db.export_csv(), media_type="text/csv", filename="tickets.csv")
