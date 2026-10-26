"""Persistence: SQLite as the system of record + a CSV mirror for spreadsheets / Zapier / Sheets."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("TRIAGE_DB", ROOT / "data" / "tickets.db"))
CSV_PATH = DB_PATH.with_suffix(".csv")

SCHEMA = """
create table if not exists tickets (
  id text primary key,
  received_at text, sender text, subject text, body text,
  category text, priority text, sentiment text, confidence real, reason text,
  customer_email text, order_id text, amount real, product text, summary text,
  status text, assignee text, reply text, context text, trace text,
  processed_at text default (datetime('now'))
)
"""
CSV_FIELDS = ["id", "received_at", "sender", "subject", "category", "priority", "sentiment", "confidence",
              "order_id", "amount", "status", "assignee", "summary"]


def conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute(SCHEMA)
    return c


def save_ticket(state: dict) -> None:
    e, c, x = state["email"], state["classification"], state["extraction"]
    row = dict(
        id=e.id, received_at=e.received_at, sender=e.sender, subject=e.subject, body=e.body,
        category=c.category, priority=c.priority, sentiment=c.sentiment, confidence=c.confidence, reason=c.reason,
        customer_email=x.customer_email, order_id=x.order_id, amount=x.amount, product=x.product, summary=x.summary,
        status=state["status"], assignee=state["assignee"], reply=state["reply"],
        context=json.dumps(state.get("context", {})), trace=json.dumps(state.get("trace", [])),
    )
    with conn() as db:
        db.execute(f"insert or replace into tickets ({','.join(row)}) values ({','.join('?' * len(row))})", list(row.values()))
    export_csv()


def list_tickets() -> list[dict]:
    with conn() as db:
        rows = db.execute("select * from tickets order by case priority when 'P1' then 0 when 'P2' then 1 else 2 end, received_at desc").fetchall()
    return [_decode(dict(r)) for r in rows]


def get_ticket(tid: str) -> dict | None:
    with conn() as db:
        r = db.execute("select * from tickets where id = ?", (tid,)).fetchone()
    return _decode(dict(r)) if r else None


def update_status(tid: str, status: str, reply: str | None = None) -> None:
    with conn() as db:
        if reply is not None:
            db.execute("update tickets set status = ?, reply = ? where id = ?", (status, reply, tid))
        else:
            db.execute("update tickets set status = ? where id = ?", (status, tid))
    export_csv()


def reset() -> None:
    with conn() as db:
        db.execute("delete from tickets")
    export_csv()


def export_csv() -> Path:
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for t in list_tickets():
            w.writerow(t)
    return CSV_PATH


def _decode(r: dict) -> dict:
    r["context"] = json.loads(r.get("context") or "{}")
    r["trace"] = json.loads(r.get("trace") or "[]")
    return r
