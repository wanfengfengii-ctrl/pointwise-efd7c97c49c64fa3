"""SQLite persistence for immutable merge candidates and frozen origins."""
import json
import sqlite3
import uuid

from source.windows import GuideError


def create_merge_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS merge_states (
            state TEXT PRIMARY KEY,
            parent TEXT NOT NULL,
            left_version TEXT NOT NULL,
            right_version TEXT NOT NULL,
            decisions TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS merge_origins (
            version TEXT PRIMARY KEY REFERENCES snapshots (version),
            parent TEXT NOT NULL,
            left_version TEXT NOT NULL,
            right_version TEXT NOT NULL
        )
    ''')


def new_state_token() -> str:
    return uuid.uuid4().hex


def save_merge_state(
    db: sqlite3.Connection,
    *,
    parent: str,
    left: str,
    right: str,
    decisions: dict,
    state: str | None = None,
) -> str:
    token = state or new_state_token()
    db.execute(
        'INSERT INTO merge_states (state, parent, left_version, right_version, decisions)'
        ' VALUES (?, ?, ?, ?, ?)',
        (token, parent, left, right, json.dumps(decisions, ensure_ascii=False, sort_keys=True)),
    )
    return token


def update_merge_state(db: sqlite3.Connection, state: str, decisions: dict) -> None:
    db.execute(
        'UPDATE merge_states SET decisions = ? WHERE state = ?',
        (json.dumps(decisions, ensure_ascii=False, sort_keys=True), state),
    )


def find_merge_state(db: sqlite3.Connection, state: str) -> dict | None:
    row = db.execute('SELECT * FROM merge_states WHERE state = ?', (state,)).fetchone()
    if row is None:
        return None
    return {
        'state': row['state'],
        'parent': row['parent'],
        'left': row['left_version'],
        'right': row['right_version'],
        'decisions': json.loads(row['decisions']),
    }


def require_bound_state(db: sqlite3.Connection, state: str, parent: str, left: str, right: str) -> dict:
    if not isinstance(state, str) or not state:
        raise GuideError('invalid_merge_state', 'A non-empty candidate state is required')
    stored = find_merge_state(db, state)
    if stored is None:
        raise GuideError('merge_state_mismatch', 'Unknown or superseded merge candidate state')
    if (stored['parent'], stored['left'], stored['right']) != (parent, left, right):
        raise GuideError('merge_state_mismatch', 'The candidate state belongs to different base or branches')
    return stored


def save_merge_origin(db: sqlite3.Connection, version: str, parent: str, left: str, right: str) -> None:
    db.execute(
        'INSERT INTO merge_origins (version, parent, left_version, right_version) VALUES (?, ?, ?, ?)',
        (version, parent, left, right),
    )


def find_merge_origin(db: sqlite3.Connection, version: str) -> dict | None:
    row = db.execute('SELECT * FROM merge_origins WHERE version = ?', (version,)).fetchone()
    if row is None:
        return None
    return {'version': row['version'], 'parent': row['parent'], 'left': row['left_version'], 'right': row['right_version']}
