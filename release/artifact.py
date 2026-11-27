import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseArtifact:
    release_id: str
    version: str
    playlist: dict
    evidence: list[dict]


@dataclass(frozen=True)
class IssueReceipt:
    request_id: str
    version: str
    release_id: str


def create_release_store(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS release_artifacts (
            release_id TEXT PRIMARY KEY,
            version TEXT NOT NULL REFERENCES snapshots (version),
            playlist TEXT NOT NULL,
            evidence TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS issue_receipts (
            request_id TEXT PRIMARY KEY,
            version TEXT NOT NULL REFERENCES snapshots (version),
            release_id TEXT NOT NULL UNIQUE REFERENCES release_artifacts (release_id)
        )
    ''')


def save_artifact(db: sqlite3.Connection, artifact: ReleaseArtifact) -> None:
    db.execute(
        'INSERT INTO release_artifacts (release_id, version, playlist, evidence) VALUES (?, ?, ?, ?)',
        (
            artifact.release_id,
            artifact.version,
            json.dumps(artifact.playlist, ensure_ascii=False),
            json.dumps(artifact.evidence, ensure_ascii=False),
        ),
    )


def save_issue_receipt(db: sqlite3.Connection, receipt: IssueReceipt) -> None:
    db.execute(
        'INSERT INTO issue_receipts (request_id, version, release_id) VALUES (?, ?, ?)',
        (receipt.request_id, receipt.version, receipt.release_id),
    )


def find_artifact(db: sqlite3.Connection, release_id: str) -> ReleaseArtifact | None:
    row = db.execute('SELECT * FROM release_artifacts WHERE release_id = ?', (release_id,)).fetchone()
    if row is None:
        return None
    return ReleaseArtifact(release_id, row['version'], json.loads(row['playlist']), json.loads(row['evidence']))


def find_issue_receipt(db: sqlite3.Connection, request_id: str) -> IssueReceipt | None:
    row = db.execute('SELECT * FROM issue_receipts WHERE request_id = ?', (request_id,)).fetchone()
    if row is None:
        return None
    return IssueReceipt(request_id, row['version'], row['release_id'])
