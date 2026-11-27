import sqlite3
from dataclasses import dataclass

from source.windows import BeatWindow, available_window


@dataclass(frozen=True)
class RecordingRevision:
    recording: str
    revision: str
    length: int

    @property
    def available(self) -> BeatWindow:
        return available_window(self.length)


def create_recording_catalog(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS recordings (
            recording TEXT NOT NULL,
            revision TEXT NOT NULL,
            length TEXT NOT NULL,
            PRIMARY KEY (recording, revision)
        )
    ''')


def find_recording_revision(db: sqlite3.Connection, recording: str, revision: str) -> RecordingRevision | None:
    row = db.execute(
        'SELECT length FROM recordings WHERE recording = ? AND revision = ?',
        (recording, revision),
    ).fetchone()
    if row is None:
        return None
    return RecordingRevision(recording, revision, int(row['length']))


def insert_recording_revision(db: sqlite3.Connection, recording: RecordingRevision) -> None:
    db.execute(
        'INSERT INTO recordings (recording, revision, length) VALUES (?, ?, ?)',
        (recording.recording, recording.revision, str(recording.length)),
    )
