import sqlite3
from dataclasses import dataclass

from source.windows import GuideError


@dataclass(frozen=True)
class OriginalReference:
    recording: str
    revision: str
    origin: str


def create_original_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS originals (
            recording TEXT NOT NULL,
            revision TEXT NOT NULL,
            origin TEXT NOT NULL,
            PRIMARY KEY (recording, revision),
            FOREIGN KEY (recording, revision) REFERENCES recordings (recording, revision)
        )
    ''')


def save_original(db: sqlite3.Connection, original: OriginalReference) -> None:
    db.execute(
        'INSERT INTO originals (recording, revision, origin) VALUES (?, ?, ?)',
        (original.recording, original.revision, original.origin),
    )


def read_original(db: sqlite3.Connection, recording: str, revision: str) -> OriginalReference:
    row = db.execute(
        'SELECT origin FROM originals WHERE recording = ? AND revision = ?',
        (recording, revision),
    ).fetchone()
    if row is None:
        raise GuideError('unknown_recording', f'Unknown recording revision {recording}/{revision}')
    return OriginalReference(recording, revision, row['origin'])
