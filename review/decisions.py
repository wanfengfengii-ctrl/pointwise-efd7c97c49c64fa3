import sqlite3
from dataclasses import dataclass

from review.orders import read_review_order
from review.receipts import ReviewReceipt, find_review_receipt, save_review_receipt
from source.windows import GuideError


@dataclass(frozen=True)
class DecisionRequest:
    request_id: str
    order_id: str
    decision: str


def submit_review_decision(db: sqlite3.Connection, request: DecisionRequest) -> ReviewReceipt:
    if request.decision not in ('approve', 'return'):
        raise GuideError('invalid_decision', 'The decision must be approve or return')
    proposed = ReviewReceipt(request.request_id, request.order_id, request.decision)
    existing = find_review_receipt(db, request.request_id)
    if existing is not None:
        if existing != proposed:
            raise GuideError('conflict', 'This decision request number already has a different payload')
        return existing
    read_review_order(db, request.order_id)
    save_review_receipt(db, proposed)
    return proposed
