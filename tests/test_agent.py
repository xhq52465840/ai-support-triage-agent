import json
from pathlib import Path

import pytest

from triage_agent.agent import build_graph, triage
from triage_agent.llm import MockLLM
from triage_agent.models import Email

INBOX = {e["id"]: Email(**e) for e in json.loads((Path(__file__).parent.parent / "data" / "inbox.json").read_text())}


@pytest.fixture(scope="module")
def graph():
    return build_graph(MockLLM(), persist=False)


def test_outage_is_p1_and_escalated(graph):
    s = triage(INBOX["T-1001"], graph)
    assert s["classification"].priority == "P1"
    assert s["classification"].category == "bug"
    assert s["status"] == "escalated"


def test_billing_fields_extracted(graph):
    s = triage(INBOX["T-1002"], graph)
    assert s["classification"].category == "billing"
    assert s["extraction"].order_id == "ORD-58213"
    assert s["extraction"].amount == 49.0
    assert s["status"] == "draft_ready"
    assert "James" in s["reply"]


def test_angry_enterprise_customer_escalated(graph):
    s = triage(INBOX["T-1003"], graph)
    assert s["classification"].sentiment == "angry"
    assert s["context"]["lookup_customer"]["plan"] == "Enterprise"
    assert s["status"] == "escalated"


def test_unclear_email_goes_to_human(graph):
    assert triage(INBOX["T-1008"], graph)["status"] == "needs_review"


def test_trace_covers_every_node(graph):
    nodes = [t["node"] for t in triage(INBOX["T-1005"], graph)["trace"]]
    assert nodes == ["classify", "extract_fields", "tool_calls", "draft_reply", "route", "persist"]
