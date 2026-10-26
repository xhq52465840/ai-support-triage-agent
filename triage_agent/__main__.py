"""CLI: python -m triage_agent [inbox.json]  — triage every email and print a summary table."""
import json
import sys
from pathlib import Path

from .agent import build_graph, triage
from .db import CSV_PATH
from .models import Email

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data" / "inbox.json"
g = build_graph()
print(f"{'ID':<8} {'PRI':<4} {'CATEGORY':<16} {'SENTIMENT':<9} {'STATUS':<13} ASSIGNEE")
for raw in json.loads(path.read_text()):
    s = triage(Email(**raw), g)
    c = s["classification"]
    print(f"{raw['id']:<8} {c.priority:<4} {c.category:<16} {c.sentiment:<9} {s['status']:<13} {s['assignee']}")
print(f"\nSaved to SQLite and {CSV_PATH}")
