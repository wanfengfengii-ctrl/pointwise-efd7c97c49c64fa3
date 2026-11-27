import sqlite3
from dataclasses import dataclass

from preview.playlist import PreviewPlaylist, get_preview
from source.windows import BeatWindow, GuideError


@dataclass(frozen=True)
class ReviewOrder:
    order_id: str
    version: str
    window: BeatWindow
    preview_id: str


def create_order_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS review_orders (
            order_id TEXT PRIMARY KEY,
            version TEXT NOT NULL REFERENCES snapshots (version),
            start_beat TEXT NOT NULL,
            end_beat TEXT NOT NULL,
            preview_id TEXT NOT NULL
        )
    ''')


def _find_order(db: sqlite3.Connection, order_id: str) -> ReviewOrder | None:
    row = db.execute('SELECT * FROM review_orders WHERE order_id = ?', (order_id,)).fetchone()
    if row is None:
        return None
    window = BeatWindow(int(row['start_beat']), int(row['end_beat']))
    return ReviewOrder(order_id, row['version'], window, row['preview_id'])


def read_review_order(db: sqlite3.Connection, order_id: str) -> ReviewOrder:
    order = _find_order(db, order_id)
    if order is None:
        raise GuideError('unknown_order', f'Unknown review order {order_id}')
    return order


def open_review_order(
    db: sqlite3.Connection,
    order_id: str,
    version: str,
    window: BeatWindow,
) -> tuple[ReviewOrder, PreviewPlaylist]:
    prior = _find_order(db, order_id)
    if prior is not None:
        if (prior.version, prior.window) != (version, window):
            raise GuideError('conflict', 'This order number already refers to a different version or window')
        return prior, get_preview(db, prior.version, prior.window)
    playlist = get_preview(db, version, window)
    order = ReviewOrder(order_id, version, window, playlist.preview_id)
    db.execute(
        'INSERT INTO review_orders (order_id, version, start_beat, end_beat, preview_id) VALUES (?, ?, ?, ?, ?)',
        (order.order_id, order.version, str(window.start), str(window.end), order.preview_id),
    )
    return order, playlist
