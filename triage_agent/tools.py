"""Tools the agent can call. In production these would hit a CRM / help center API."""
from __future__ import annotations

import csv
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def lookup_customer(email: str) -> dict:
    """Look up a customer record (plan, lifetime value, open tickets) by email."""
    with open(DATA / "customers.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["email"].lower() == email.lower():
                return {
                    "found": True,
                    "name": row["name"],
                    "plan": row["plan"],
                    "ltv_usd": float(row["ltv_usd"]),
                    "customer_since": row["customer_since"],
                }
    return {"found": False}


def search_help_center(query: str, k: int = 2) -> list[dict]:
    """Keyword search over help-center articles; returns the best matches."""
    articles = json.loads((DATA / "help_center.json").read_text())
    q = {w for w in query.lower().split() if len(w) > 3}
    scored = []
    for a in articles:
        text = (a["title"] + " " + " ".join(a["keywords"])).lower()
        score = sum(1 for w in q if w in text)
        if score:
            scored.append((score, a))
    scored.sort(key=lambda x: -x[0])
    return [{"title": a["title"], "url": a["url"]} for _, a in scored[:k]]


TOOLS = {"lookup_customer": lookup_customer, "search_help_center": search_help_center}

# OpenAI tool schemas (used in real mode)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": lookup_customer.__doc__,
            "parameters": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_help_center",
            "description": search_help_center.__doc__,
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
]
