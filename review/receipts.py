import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewReceipt:
    request_id: str
    order_id: str
    decision: str


def create_receipt_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_receipts (
            request_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES review_orders (order_id),
            decision TEXT NOT NULL CHECK (decision IN ('approve', 'return'))
        )
    ''')


def find_review_receipt(db: sqlite3.Connection, request_id: str) -> ReviewReceipt | None:
    row = db.execute('SELECT * FROM review_receipts WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        return None
    return ReviewReceipt(row['request_id'], row['order_id'], row['decision'])


def save_review_receipt(db: sqlite3.Connection, receipt: ReviewReceipt) -> None:
    db.execute(
        'INSERT INTO review_receipts (request_id, order_id, decision) VALUES (?, ?, ?)',
        (receipt.request_id, receipt.order_id, receipt.decision),
    )


def list_approval_receipts(db: sqlite3.Connection) -> tuple[ReviewReceipt, ...]:
    rows = db.execute("SELECT * FROM review_receipts WHERE decision = 'approve' ORDER BY request_id")
    return tuple(ReviewReceipt(row['request_id'], row['order_id'], row['decision']) for row in rows)
