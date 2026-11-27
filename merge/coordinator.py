"""Orchestrate merge preview/confirm against the SQLite store."""
from __future__ import annotations

import sqlite3

from edit.layout import layout_extent, validate_layout
from edit.snapshots import CutSnapshot, find_snapshot, read_snapshot, save_snapshot
from merge.engine import MergeInput, evaluate, resolve_choice
from merge.store import (
    new_state_token,
    require_bound_state,
    save_merge_origin,
    save_merge_state,
    update_merge_state,
)
from source.windows import GuideError


def load_merge_input(db: sqlite3.Connection, parent: str, left: str, right: str) -> MergeInput:
    base = read_snapshot(db, parent)
    left_snapshot = read_snapshot(db, left)
    right_snapshot = read_snapshot(db, right)
    if left_snapshot.version == right_snapshot.version:
        raise GuideError('duplicate_branch', 'The two proof branches must be different versions')
    if left_snapshot.parent != base.version or right_snapshot.parent != base.version:
        raise GuideError(
            'invalid_lineage',
            'Both proofs must be direct frozen children of the same base version',
        )
    return MergeInput.bind(base, left_snapshot, right_snapshot)


def preview_merge(db: sqlite3.Connection, parent: str, left: str, right: str) -> dict:
    merge_input = load_merge_input(db, parent, left, right)
    state = new_state_token()
    save_merge_state(
        db,
        state=state,
        parent=parent,
        left=left,
        right=right,
        decisions={},
    )
    return evaluate(merge_input, {}, state).body


def _edit_success(snapshot: CutSnapshot) -> dict:
    return {
        'version': snapshot.version,
        'parent': snapshot.parent,
        'length': snapshot.length,
        'tracks': list(snapshot.tracks),
        'preview_id': snapshot.preview_id,
    }


def _freeze(db: sqlite3.Connection, merge_input: MergeInput, version: str, placements) -> tuple[int, dict]:
    slots = [item.slot for item in placements]
    if len(set(slots)) != len(slots):
        raise GuideError('slot_conflict', 'Cannot freeze while slot names are reused')
    ordered = validate_layout(placements, merge_input.parent.tracks)
    snapshot = CutSnapshot(
        version,
        merge_input.parent.version,
        layout_extent(ordered),
        merge_input.parent.tracks,
        ordered,
    )
    save_snapshot(db, snapshot)
    save_merge_origin(
        db,
        version,
        merge_input.parent.version,
        merge_input.left.version,
        merge_input.right.version,
    )
    return 200, _edit_success(snapshot)


def confirm_merge(
    db: sqlite3.Connection,
    *,
    parent: str,
    left: str,
    right: str,
    version: str,
    state,
    choice,
) -> tuple[int, dict]:
    # House convention: a reused target number is a 409 before deeper work.
    if find_snapshot(db, version) is not None:
        raise GuideError('conflict', f'Cut version {version} already exists')

    merge_input = load_merge_input(db, parent, left, right)
    stored = require_bound_state(db, state, parent, left, right)
    decisions = stored['decisions']
    current = evaluate(merge_input, decisions, state)

    if choice is None:
        if current.conflicts:
            raise GuideError('invalid_option', 'This candidate still needs an adjudication choice')
        return _freeze(db, merge_input, version, current.placements)

    if not isinstance(choice, str):
        raise GuideError('invalid_option', 'The choice must be an option id string')
    payload = resolve_choice(current, choice)
    if payload is None:
        raise GuideError('invalid_option', 'The choice is not an option issued by this candidate')

    next_decisions = {**decisions, payload['key']: payload['value']}
    following = evaluate(merge_input, next_decisions, state)
    update_merge_state(db, state, next_decisions)
    if following.conflicts:
        return 409, following.body
    return _freeze(db, merge_input, version, following.placements)


def read_merge_origin(db: sqlite3.Connection, version: str) -> dict:
    from merge.store import find_merge_origin

    origin = find_merge_origin(db, version)
    if origin is None:
        raise GuideError('unknown_version', f'Unknown merged proof version {version}')
    return origin
