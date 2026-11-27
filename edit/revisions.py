import sqlite3
from dataclasses import dataclass

from edit.layout import TRACKS, layout_extent, validate_layout
from edit.operations import EditOperation, apply_edit_sequence
from edit.snapshots import CutSnapshot, find_snapshot, read_snapshot, save_snapshot
from source.windows import GuideError


INITIAL_CUT = 'root'


@dataclass(frozen=True)
class RevisionRequest:
    version: str
    parent: str
    operations: tuple[EditOperation, ...]


def ensure_initial_cut(db: sqlite3.Connection) -> None:
    if find_snapshot(db, INITIAL_CUT) is None:
        save_snapshot(db, CutSnapshot(INITIAL_CUT, None, 0, TRACKS, ()))


def submit_revision(db: sqlite3.Connection, request: RevisionRequest) -> CutSnapshot:
    if find_snapshot(db, request.version) is not None:
        raise GuideError('conflict', f'Cut version {request.version} already exists')
    parent = read_snapshot(db, request.parent)
    placements = apply_edit_sequence(db, parent, request.version, request.operations)
    ordered = validate_layout(placements, parent.tracks)
    snapshot = CutSnapshot(request.version, parent.version, layout_extent(ordered), parent.tracks, ordered)
    save_snapshot(db, snapshot)
    return snapshot
