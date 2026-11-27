import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from edit.revisions import ensure_initial_cut
from edit.snapshots import create_snapshot_store
from release.artifact import create_release_store
from review.orders import create_order_store
from review.receipts import create_receipt_store
from source.catalog import create_recording_catalog
from source.fixture import DEFAULT_FIXTURE, seed_missing_recordings
from source.originals import create_original_store


def open_database(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def write_transaction(db: sqlite3.Connection):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


def initialize_database(path: str | Path, fixture_path: Path = DEFAULT_FIXTURE) -> None:
    with closing(open_database(path)) as db, write_transaction(db):
        create_recording_catalog(db)
        create_original_store(db)
        create_snapshot_store(db)
        create_order_store(db)
        create_receipt_store(db)
        create_release_store(db)
        ensure_initial_cut(db)
        seed_missing_recordings(db, fixture_path)
