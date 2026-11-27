import json
import sqlite3
from dataclasses import asdict, dataclass

from edit.occurrences import Occurrence
from source.windows import BeatWindow, GuideError


@dataclass(frozen=True)
class CutSnapshot:
    version: str
    parent: str | None
    length: int
    tracks: tuple[str, ...]
    placements: tuple[Occurrence, ...]

    @property
    def preview_id(self) -> str:
        return f'preview-{self.version}'


def create_snapshot_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            version TEXT PRIMARY KEY,
            parent TEXT REFERENCES snapshots (version),
            length TEXT NOT NULL,
            tracks TEXT NOT NULL,
            placements TEXT NOT NULL
        )
    ''')


def save_snapshot(db: sqlite3.Connection, snapshot: CutSnapshot) -> None:
    db.execute(
        'INSERT INTO snapshots (version, parent, length, tracks, placements) VALUES (?, ?, ?, ?, ?)',
        (
            snapshot.version,
            snapshot.parent,
            str(snapshot.length),
            json.dumps(snapshot.tracks),
            json.dumps([asdict(placement) for placement in snapshot.placements]),
        ),
    )


def find_snapshot(db: sqlite3.Connection, version: str) -> CutSnapshot | None:
    row = db.execute('SELECT * FROM snapshots WHERE version = ?', (version,)).fetchone()
    if row is None:
        return None
    placements = []
    for item in json.loads(row['placements']):
        item['source'] = BeatWindow(**item['source'])
        placements.append(Occurrence(**item))
    return CutSnapshot(version, row['parent'], int(row['length']), tuple(json.loads(row['tracks'])), tuple(placements))


def read_snapshot(db: sqlite3.Connection, version: str) -> CutSnapshot:
    snapshot = find_snapshot(db, version)
    if snapshot is None:
        raise GuideError('unknown_version', f'Unknown cut version {version}')
    return snapshot
