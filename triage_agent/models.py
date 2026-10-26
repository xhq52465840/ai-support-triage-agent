from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["billing", "bug", "account", "shipping", "feature_request", "other"]
Priority = Literal["P1", "P2", "P3"]
Sentiment = Literal["angry", "negative", "neutral", "positive"]


class Email(BaseModel):
    id: str
    sender: str
    subject: str
    body: str
    received_at: str


class Classification(BaseModel):
    category: Category
    priority: Priority
    sentiment: Sentiment
    confidence: float = Field(ge=0, le=1)
    reason: str


class Extraction(BaseModel):
    customer_email: str
    order_id: Optional[str] = None
    amount: Optional[float] = None
    product: Optional[str] = None
    summary: str
