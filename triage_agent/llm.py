"""LLM backends. MockLLM is deterministic and offline; OpenAILLM uses structured outputs + tool calling."""
from __future__ import annotations

import json
import os
import re
from typing import Protocol

from .models import Classification, Email, Extraction
from .tools import TOOL_SCHEMAS, TOOLS


class LLM(Protocol):
    name: str
    def classify(self, email: Email) -> Classification: ...
    def extract(self, email: Email) -> Extraction: ...
    def plan_tool_calls(self, email: Email, ext: Extraction, cls: Classification) -> list[dict]: ...
    def draft_reply(self, email: Email, cls: Classification, ext: Extraction, context: dict) -> str: ...


# --------------------------------------------------------------------------- mock
KEYWORDS = {
    "billing": ["refund", "charged", "invoice", "payment", "charge", "billing", "subscription", "price"],
    "bug": ["error", "crash", "bug", "broken", "not working", "fails", "500", "down", "outage"],
    "account": ["password", "login", "log in", "2fa", "account", "locked", "sign in", "email change"],
    "shipping": ["delivery", "shipping", "package", "tracking", "arrived", "shipped", "courier"],
    "feature_request": ["feature", "would be great", "suggest", "please add", "integration", "roadmap"],
}
ANGRY = ["unacceptable", "ridiculous", "furious", "worst", "immediately", "!!!", "scam", "lawyer"]
NEGATIVE = ["disappointed", "frustrat", "still", "again", "annoy", "problem", "issue", "cannot", "can't", "charged twice"]
POSITIVE = ["love", "awesome", "appreciate", "amazing"]
BLOCKING = ["refund", "charged", "locked", "can't log in", "cannot log in", "crash"]
URGENT = ["outage", "down", "production", "all users", "urgent", "asap", "immediately", "cannot access"]


class MockLLM:
    name = "mock"

    def classify(self, email: Email) -> Classification:
        text = f"{email.subject} {email.body}".lower()
        scores = {c: sum(text.count(k) for k in kws) for c, kws in KEYWORDS.items()}
        category, top = max(scores.items(), key=lambda kv: kv[1])
        if top == 0:
            category = "other"
        if any(w in text for w in ANGRY):
            sentiment = "angry"
        elif any(w in text for w in NEGATIVE):
            sentiment = "negative"
        elif any(w in text for w in POSITIVE):
            sentiment = "positive"
        else:
            sentiment = "neutral"
        urgent = sum(w in text for w in URGENT)
        priority = "P1" if urgent >= 2 or (category == "bug" and urgent) else "P2" if sentiment in ("angry", "negative") or any(w in text for w in BLOCKING) else "P3"
        total = sum(scores.values()) or 1
        conf = round(min(0.97, 0.55 + 0.45 * (top / total)), 2) if top else 0.5
        hits = [k for k in KEYWORDS.get(category, []) if k in text][:3]
        reason = f"Matched {', '.join(repr(h) for h in hits)}" if hits else "No strong signal"
        if urgent:
            reason += f"; urgency signals: {urgent}"
        return Classification(category=category, priority=priority, sentiment=sentiment, confidence=conf, reason=reason)

    def extract(self, email: Email) -> Extraction:
        text = f"{email.subject}\n{email.body}"
        order = re.search(r"\b(?:order|ord|#)\s*#?\s*([A-Z]{0,3}-?\d{4,})", text, re.I)
        amount = re.search(r"\$\s?(\d+(?:,\d{3})*(?:\.\d{2})?)", text)
        product = re.search(r"\b(Pro|Team|Starter|Enterprise) plan\b|\b(iOS app|Android app|web app|API)\b", text, re.I)
        first = re.split(r"(?<=[.!?])\s", email.body.strip())[0]
        return Extraction(
            customer_email=re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", email.sender).group(0),
            order_id=order.group(1).upper() if order else None,
            amount=float(amount.group(1).replace(",", "")) if amount else None,
            product=(product.group(0) if product else None),
            summary=(first[:140] + "…") if len(first) > 140 else first,
        )

    def plan_tool_calls(self, email, ext, cls):
        calls = [{"name": "lookup_customer", "args": {"email": ext.customer_email}}]
        calls.append({"name": "search_help_center", "args": {"query": f"{cls.category} {email.subject}"}})
        return calls

    def draft_reply(self, email, cls, ext, context):
        cust = context.get("lookup_customer", {})
        display = email.sender.split("<")[0].strip().strip('"')
        name = (cust.get("name") if cust.get("found") else display).split(" ")[0] if (cust.get("found") or display) else "there"
        opener = {
            "angry": "I'm really sorry about this experience — I understand how frustrating it is, and I'm on it.",
            "negative": "Sorry for the trouble, and thanks for letting us know.",
            "positive": "Thanks so much for the kind words!",
            "neutral": "Thanks for reaching out.",
        }[cls.sentiment]
        body = {
            "billing": f"I've located the charge{f' on order {ext.order_id}' if ext.order_id else ''}{f' (${ext.amount:,.2f})' if ext.amount else ''} and opened a billing review. If it qualifies under our 30-day policy, the refund will reach your original payment method within 5–7 business days.",
            "bug": "Our engineering team has the details and is investigating. Could you share the time it happened and a screenshot or error message, if you have one?",
            "account": "For your security I've sent a verified reset link to the email on file. If you no longer have access to that inbox, reply here and we'll verify your identity another way.",
            "shipping": f"I've asked our logistics team to trace{f' order {ext.order_id}' if ext.order_id else ' your package'} with the carrier and will update you within 24 hours.",
            "feature_request": "I've logged this with our product team so it's considered for the roadmap. I'll let you know if it ships.",
            "other": "I've passed this to the right team and we'll follow up shortly.",
        }[cls.category]
        links = context.get("search_help_center") or []
        help_line = ("\n\nThis article may help in the meantime: " + links[0]["title"] + " — " + links[0]["url"]) if links else ""
        sla = {"P1": "within the hour", "P2": "within 4 business hours", "P3": "within 1 business day"}[cls.priority]
        return f"Hi {name},\n\n{opener} {body}{help_line}\n\nYou'll hear from us again {sla}.\n\nBest,\nAcme Support"


# --------------------------------------------------------------------------- OpenAI
class OpenAILLM:
    name = "openai"

    def __init__(self):
        from openai import OpenAI
        self.client = OpenAI()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _structured(self, schema_model, system: str, user: str):
        res = self.client.beta.chat.completions.parse(
            model=self.model, temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=schema_model,
        )
        return res.choices[0].message.parsed

    def classify(self, email):
        return self._structured(Classification, "Classify this customer support email. P1 = outage/security/many users blocked, P2 = a customer is blocked or upset, P3 = everything else.", _fmt(email))

    def extract(self, email):
        return self._structured(Extraction, "Extract structured fields from the support email. Use null when a field is absent.", _fmt(email))

    def plan_tool_calls(self, email, ext, cls):
        res = self.client.chat.completions.create(
            model=self.model, temperature=0, tools=TOOL_SCHEMAS, tool_choice="required",
            messages=[
                {"role": "system", "content": "Gather the context needed to answer this ticket. Call every useful tool."},
                {"role": "user", "content": f"{_fmt(email)}\n\nCategory: {cls.category}\nCustomer email: {ext.customer_email}"},
            ],
        )
        return [{"name": c.function.name, "args": json.loads(c.function.arguments)} for c in res.choices[0].message.tool_calls or [] if c.function.name in TOOLS]

    def draft_reply(self, email, cls, ext, context):
        res = self.client.chat.completions.create(
            model=self.model, temperature=0.3,
            messages=[
                {"role": "system", "content": "You are a senior support agent for Acme. Write a concise, empathetic reply (<120 words). Never promise anything not supported by the context. Sign as 'Acme Support'."},
                {"role": "user", "content": f"{_fmt(email)}\n\nTriage: {cls.model_dump_json()}\nFields: {ext.model_dump_json()}\nTool results: {json.dumps(context)}"},
            ],
        )
        return res.choices[0].message.content.strip()


def _fmt(email: Email) -> str:
    return f"From: {email.sender}\nSubject: {email.subject}\n\n{email.body}"


def get_llm() -> LLM:
    return OpenAILLM() if os.getenv("OPENAI_API_KEY") else MockLLM()
