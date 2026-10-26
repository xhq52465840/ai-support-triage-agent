"""LangGraph workflow: classify -> extract -> gather_context (tool calls) -> draft_reply -> route -> persist."""
from __future__ import annotations

import time
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from . import db
from .llm import LLM, get_llm
from .models import Classification, Email, Extraction
from .tools import TOOLS


class TriageState(TypedDict, total=False):
    email: Email
    classification: Classification
    extraction: Extraction
    context: dict[str, Any]
    reply: str
    status: str
    assignee: str
    trace: list[dict]


def _log(state: TriageState, node: str, detail: str, t0: float) -> list[dict]:
    return state.get("trace", []) + [{"node": node, "detail": detail, "ms": round((time.perf_counter() - t0) * 1000, 1)}]


def build_graph(llm: Optional[LLM] = None, persist: bool = True):
    llm = llm or get_llm()

    def classify(state: TriageState):
        t0 = time.perf_counter()
        c = llm.classify(state["email"])
        return {"classification": c, "trace": _log(state, "classify", f"{c.category} · {c.priority} · {c.sentiment} ({c.confidence:.0%})", t0)}

    def extract(state: TriageState):
        t0 = time.perf_counter()
        e = llm.extract(state["email"])
        fields = ", ".join(f"{k}={v}" for k, v in e.model_dump(exclude={"summary"}).items() if v is not None)
        return {"extraction": e, "trace": _log(state, "extract_fields", fields, t0)}

    def gather_context(state: TriageState):
        t0 = time.perf_counter()
        calls = llm.plan_tool_calls(state["email"], state["extraction"], state["classification"])
        context = {}
        for call in calls:
            context[call["name"]] = TOOLS[call["name"]](**call["args"])
        names = ", ".join(f"{c['name']}({', '.join(map(repr, c['args'].values()))})" for c in calls)
        return {"context": context, "trace": _log(state, "tool_calls", names, t0)}

    def draft_reply(state: TriageState):
        t0 = time.perf_counter()
        reply = llm.draft_reply(state["email"], state["classification"], state["extraction"], state["context"])
        return {"reply": reply, "trace": _log(state, "draft_reply", f"{len(reply.split())} words", t0)}

    def route(state: TriageState) -> str:
        c = state["classification"]
        cust = state["context"].get("lookup_customer", {})
        vip = cust.get("found") and (cust.get("plan") == "Enterprise" or cust.get("ltv_usd", 0) >= 5000)
        if c.priority == "P1" or (c.sentiment == "angry" and vip):
            return "escalate"
        if c.confidence < 0.7 or c.category == "other":
            return "human_review"
        return "queue_reply"

    def escalate(state: TriageState):
        t0 = time.perf_counter()
        team = "On-call engineering" if state["classification"].category == "bug" else "Support lead"
        return {"status": "escalated", "assignee": team, "trace": _log(state, "route", f"escalate → {team}", t0)}

    def human_review(state: TriageState):
        t0 = time.perf_counter()
        return {"status": "needs_review", "assignee": "Tier-1 queue", "trace": _log(state, "route", "low confidence → human review", t0)}

    def queue_reply(state: TriageState):
        t0 = time.perf_counter()
        team = {"billing": "Billing", "shipping": "Logistics", "account": "Tier-1 queue", "feature_request": "Product", "bug": "Tier-2 support"}.get(state["classification"].category, "Tier-1 queue")
        return {"status": "draft_ready", "assignee": team, "trace": _log(state, "route", f"draft ready → {team}", t0)}

    def save(state: TriageState):
        t0 = time.perf_counter()
        trace = _log(state, "persist", "sqlite + csv" if persist else "skipped", t0)
        if persist:
            db.save_ticket({**state, "trace": trace})
        return {"trace": trace}

    g = StateGraph(TriageState)
    for name, fn in [("classify", classify), ("extract_fields", extract), ("gather_context", gather_context),
                     ("draft_reply", draft_reply), ("escalate", escalate), ("human_review", human_review),
                     ("queue_reply", queue_reply), ("persist", save)]:
        g.add_node(name, fn)
    g.add_edge(START, "classify")
    g.add_edge("classify", "extract_fields")
    g.add_edge("extract_fields", "gather_context")
    g.add_edge("gather_context", "draft_reply")
    g.add_conditional_edges("draft_reply", route, {"escalate": "escalate", "human_review": "human_review", "queue_reply": "queue_reply"})
    for n in ("escalate", "human_review", "queue_reply"):
        g.add_edge(n, "persist")
    g.add_edge("persist", END)
    return g.compile()


def triage(email: Email, graph=None) -> TriageState:
    graph = graph or build_graph()
    return graph.invoke({"email": email, "trace": []})
