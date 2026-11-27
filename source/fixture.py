import json
import sqlite3
from pathlib import Path

from source.catalog import find_recording_revision
from source.intake import IntakeRequest, register_recording


DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / 'examples' / 'recordings.json'


def read_recording_fixture(path: Path = DEFAULT_FIXTURE) -> list[IntakeRequest]:
    with path.open(encoding='utf-8') as stream:
        return [IntakeRequest(**item) for item in json.load(stream)]


def seed_missing_recordings(db: sqlite3.Connection, path: Path = DEFAULT_FIXTURE) -> None:
    for request in read_recording_fixture(path):
        if find_recording_revision(db, request.recording, request.revision) is None:
            register_recording(db, request)
