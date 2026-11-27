import sqlite3
from dataclasses import dataclass

from edit.occurrences import Occurrence
from edit.snapshots import CutSnapshot
from source.catalog import find_recording_revision
from source.windows import BeatWindow, GuideError, validate_window


@dataclass(frozen=True)
class EditOperation:
    op: str
    slot: str
    at: int | None = None
    track: str | None = None
    recording: str | None = None
    revision: str | None = None
    source: BeatWindow | None = None
    target_slot: str | None = None


def _require_unused_slot(placements: dict[str, Occurrence], slot: str) -> None:
    if slot in placements:
        raise GuideError('conflict', f'Placement slot {slot} is already in use')


def _place(db: sqlite3.Connection, edit: EditOperation, identity: str, tracks: tuple[str, ...]) -> Occurrence:
    if edit.track not in tracks:
        raise GuideError('invalid_track', f'Unknown track {edit.track}')
    recording = find_recording_revision(db, edit.recording, edit.revision)
    if recording is None:
        raise GuideError('unknown_recording', f'Unknown recording revision {edit.recording}/{edit.revision}')
    source = validate_window(edit.source.start, edit.source.end, within=recording.available)
    return Occurrence(edit.slot, identity, edit.track, recording.recording, recording.revision, source, edit.at)


def apply_edit_sequence(
    db: sqlite3.Connection,
    parent: CutSnapshot,
    version: str,
    operations: tuple[EditOperation, ...],
) -> tuple[Occurrence, ...]:
    placements = {placement.slot: placement for placement in parent.placements}
    for index, edit in enumerate(operations, start=1):
        identity = f'{version}:{index}'
        if edit.op == 'place':
            _require_unused_slot(placements, edit.slot)
            placements[edit.slot] = _place(db, edit, identity, parent.tracks)
            continue
        placement = placements.get(edit.slot)
        if placement is None:
            raise GuideError('invalid_operation', f'Unknown placement slot {edit.slot}')
        if edit.op == 'move':
            placements[edit.slot] = placement.move(edit.at)
        elif edit.op == 'trim':
            placements[edit.slot] = placement.trim(edit.source)
        elif edit.op == 'copy':
            _require_unused_slot(placements, edit.target_slot)
            placements[edit.target_slot] = placement.copy_as(edit.target_slot, identity, edit.at)
        elif edit.op == 'remove':
            del placements[edit.slot]
        else:
            raise GuideError('invalid_operation', f'Unknown edit operation {edit.op}')
    return tuple(placements.values())
