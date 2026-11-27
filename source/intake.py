import sqlite3
from dataclasses import dataclass

from source.catalog import RecordingRevision, find_recording_revision, insert_recording_revision
from source.originals import OriginalReference, read_original, save_original
from source.windows import GuideError


@dataclass(frozen=True)
class IntakeRequest:
    recording: str
    revision: str
    length: int
    origin: str


def register_recording(db: sqlite3.Connection, request: IntakeRequest) -> dict:
    candidate = RecordingRevision(request.recording, request.revision, request.length)
    window = candidate.available
    if not isinstance(request.origin, str) or not request.origin.strip():
        raise GuideError('invalid_origin', 'A nonblank recording origin is required')
    proposed_origin = OriginalReference(request.recording, request.revision, request.origin)
    existing = find_recording_revision(db, request.recording, request.revision)
    if existing is None:
        insert_recording_revision(db, candidate)
        save_original(db, proposed_origin)
    elif existing != candidate or read_original(db, request.recording, request.revision) != proposed_origin:
        raise GuideError('conflict', 'This original is already registered with different content')
    return {
        'recording': candidate.recording,
        'revision': candidate.revision,
        'length': candidate.length,
        'origin': proposed_origin.origin,
        'available': window.pair(),
    }
