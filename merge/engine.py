"""Pure merge logic: align two direct children of one frozen base.

The engine never raises HTTP-shaped errors for ordinary disagreement; those
become conflicts in the candidate.  Inputs are frozen :class:`CutSnapshot`
objects.  All position comparisons use the constant landing offset
``d = at - source.start`` so the same source beat can be tracked even when the
two branches retained disjoint source windows.
"""
from __future__ import annotations

from dataclasses import dataclass

from edit.layout import order_placements
from edit.occurrences import Occurrence
from edit.snapshots import CutSnapshot
from source.windows import BeatWindow


KEEP_LEFT = 'keep_left'
KEEP_RIGHT = 'keep_right'
WITHDRAW_MOVE = 'withdraw_move'
WITHDRAW_ADD = 'withdraw_add'


def placement_json(item: Occurrence | None) -> dict | None:
    if item is None:
        return None
    return {
        'slot': item.slot,
        'occurrence_id': item.occurrence_id,
        'track': item.track,
        'recording': item.recording,
        'revision': item.revision,
        'source': [item.source.start, item.source.end],
        'at': item.at,
    }


def index_by_id(snapshot: CutSnapshot) -> dict[str, Occurrence]:
    return {item.occurrence_id: item for item in snapshot.placements}


def landing_offset(item: Occurrence) -> int:
    return item.at - item.source.start


@dataclass(frozen=True)
class MergeInput:
    parent: CutSnapshot
    left: CutSnapshot
    right: CutSnapshot
    p_by_id: dict[str, Occurrence]
    l_by_id: dict[str, Occurrence]
    r_by_id: dict[str, Occurrence]
    order: tuple[str, ...]

    @classmethod
    def bind(cls, parent: CutSnapshot, left: CutSnapshot, right: CutSnapshot) -> 'MergeInput':
        p_by_id = index_by_id(parent)
        l_by_id = index_by_id(left)
        r_by_id = index_by_id(right)
        seen: set[str] = set()
        order: list[str] = []
        for source in (parent.placements, left.placements, right.placements):
            for item in source:
                if item.occurrence_id not in seen:
                    seen.add(item.occurrence_id)
                    order.append(item.occurrence_id)
        return cls(parent, left, right, p_by_id, l_by_id, r_by_id, tuple(order))

    def sides(self, oid: str) -> tuple[Occurrence | None, Occurrence | None, Occurrence | None]:
        return self.p_by_id.get(oid), self.l_by_id.get(oid), self.r_by_id.get(oid)

    def is_add(self, oid: str) -> bool:
        return oid not in self.p_by_id


def option_id(kind: str, action: str, oid: str) -> str:
    return f'{kind}:{action}:{oid}'


def withdraw_id(action: str, oid: str) -> str:
    return f'{action}:{oid}'


def _option(kind: str, action: str, oid: str) -> dict:
    ident = option_id(kind, action, oid) if action.startswith('keep_') else withdraw_id(action, oid)
    return {'id': ident, 'occurrence_id': oid, 'action': action}


def _view(mi: MergeInput, oid: str, current: Occurrence | None) -> dict:
    p, l, r = mi.sides(oid)
    return {
        'occurrence_id': oid,
        'parent': placement_json(p),
        'left': placement_json(l),
        'right': placement_json(r),
        'current': placement_json(current),
    }


def _keep_options(kind: str, oid: str) -> list[dict]:
    return [_option(kind, KEEP_LEFT, oid), _option(kind, KEEP_RIGHT, oid)]


def _decision(decisions: dict, key: str):
    return decisions.get(key)


def resolve_phase_one(
    mi: MergeInput,
    decisions: dict,
) -> tuple[dict[str, Occurrence | None], list[dict], dict[str, list[dict]]]:
    """Resolve existence/trim/move.

    Returns a map oid -> Occurrence or None for decided items, a list of
    phase-one conflicts, and an option-id -> decision payload map.  An
    undecided oid is simply absent from the placement map.
    """
    resolved: dict[str, Occurrence | None] = {}
    conflicts: list[dict] = []
    options: dict[str, dict] = {}

    for oid in mi.order:
        p, l, r = mi.sides(oid)

        # New occurrences created on either branch enter the candidate.
        if p is None:
            if _decision(decisions, f'{WITHDRAW_ADD}:{oid}') is not None:
                resolved[oid] = None
                continue
            add = l if l is not None else r
            if l is not None and r is not None and l != r:
                # Defensive only: API-minted identities are branch unique.
                side = _decision(decisions, f'existence:{oid}')
                if side is None:
                    conflict = {
                        'kind': 'existence',
                        'candidates': [_view(mi, oid, None)],
                        'options': _keep_options('existence', oid),
                    }
                    conflicts.append(conflict)
                    for opt in conflict['options']:
                        keep_side = 'left' if opt['action'] == KEEP_LEFT else 'right'
                        options[opt['id']] = {'key': f'existence:{oid}', 'value': {'side': keep_side}}
                    continue
                add = l if side['side'] == 'left' else r
            resolved[oid] = add
            continue

        # Parent occurrence.
        if l is None and r is None:
            resolved[oid] = None
            continue

        if l is None or r is None:
            present = r if l is None else l
            absent_side = 'left' if l is None else 'right'
            present_side = 'right' if l is None else 'left'
            if present == p:
                # One side deleted, the other left it untouched: delete.
                resolved[oid] = None
                continue
            chosen = _decision(decisions, f'existence:{oid}')
            if chosen is None:
                conflict = {
                    'kind': 'existence',
                    'candidates': [_view(mi, oid, None)],
                    'options': _keep_options('existence', oid),
                }
                conflicts.append(conflict)
                for opt in conflict['options']:
                    side = 'left' if opt['action'] == KEEP_LEFT else 'right'
                    options[opt['id']] = {'key': f'existence:{oid}', 'value': {'side': side}}
                continue
            side = chosen['side']
            if side == absent_side:
                resolved[oid] = None
            else:
                resolved[oid] = present if side == present_side else (l if side == 'left' else r)
            continue

        # Both branches still carry the occurrence: split trim and move.
        s_p, s_l, s_r = p.source, l.source, r.source
        trim_left_changed = s_l != s_p
        trim_right_changed = s_r != s_p
        trim_diverges = trim_left_changed and trim_right_changed and s_l != s_r
        trim_choice = _decision(decisions, f'trim:{oid}')
        if trim_diverges and trim_choice is None:
            conflict = {
                'kind': 'trim',
                'candidates': [_view(mi, oid, None)],
                'options': _keep_options('trim', oid),
            }
            conflicts.append(conflict)
            for opt in conflict['options']:
                side = 'left' if opt['action'] == KEEP_LEFT else 'right'
                options[opt['id']] = {'key': f'trim:{oid}', 'value': {'side': side}}
        if trim_diverges and trim_choice is None:
            trim_source = None
        elif trim_diverges:
            trim_source = s_l if trim_choice['side'] == 'left' else s_r
        elif trim_left_changed and not trim_right_changed:
            trim_source = s_l
        elif trim_right_changed and not trim_left_changed:
            trim_source = s_r
        elif trim_left_changed and trim_right_changed:
            trim_source = s_l  # identical changes
        else:
            trim_source = s_p

        d_p = landing_offset(p)
        d_l = landing_offset(l)
        d_r = landing_offset(r)
        move_left_changed = d_l != d_p
        move_right_changed = d_r != d_p
        move_diverges = move_left_changed and move_right_changed and d_l != d_r
        move_choice = _decision(decisions, f'move:{oid}')
        if move_diverges and move_choice is None:
            conflict = {
                'kind': 'move',
                'candidates': [_view(mi, oid, None)],
                'options': _keep_options('move', oid),
            }
            conflicts.append(conflict)
            for opt in conflict['options']:
                side = 'left' if opt['action'] == KEEP_LEFT else 'right'
                options[opt['id']] = {'key': f'move:{oid}', 'value': {'side': side}}
        if move_diverges and move_choice is None:
            move_offset = None
        elif move_diverges:
            move_offset = d_l if move_choice['side'] == 'left' else d_r
        elif move_left_changed and not move_right_changed:
            move_offset = d_l
        elif move_right_changed and not move_left_changed:
            move_offset = d_r
        elif move_left_changed and move_right_changed:
            move_offset = d_l  # identical shifts
        else:
            move_offset = d_p

        if trim_source is None or move_offset is None:
            # Still undecided on at least one aspect; preserve other choices.
            continue

        source: BeatWindow = trim_source
        offset = move_offset
        if _decision(decisions, f'{WITHDRAW_MOVE}:{oid}') is not None:
            offset = d_p
        current = Occurrence(
            slot=p.slot,
            occurrence_id=oid,
            track=p.track,
            recording=p.recording,
            revision=p.revision,
            source=source,
            at=offset + source.start,
        )
        resolved[oid] = current

    return resolved, conflicts, options


def _withdraw_option(action: str, oid: str) -> dict:
    return {'id': withdraw_id(action, oid), 'occurrence_id': oid, 'action': action}


def _occupancy_options(mi: MergeInput, item: Occurrence) -> list[dict]:
    oid = item.occurrence_id
    if mi.is_add(oid):
        return [_withdraw_option(WITHDRAW_ADD, oid)]
    parent = mi.p_by_id[oid]
    if landing_offset(item) != landing_offset(parent):
        return [_withdraw_option(WITHDRAW_MOVE, oid)]
    return []


def _register(options: dict[str, dict], opt: dict) -> None:
    action = opt['action']
    oid = opt['occurrence_id']
    options[opt['id']] = {'key': f'{action}:{oid}', 'value': {'applied': True}}


def phase_two(
    mi: MergeInput,
    ordered: tuple[Occurrence, ...],
) -> tuple[list[dict], dict[str, dict]]:
    """Slot-name and same-track occupancy conflicts over determined placements."""
    conflicts: list[dict] = []
    options: dict[str, dict] = {}

    by_slot: dict[str, list[Occurrence]] = {}
    for item in ordered:
        by_slot.setdefault(item.slot, []).append(item)
    for slot in sorted(by_slot):
        group = by_slot[slot]
        if len(group) < 2:
            continue
        slot_options: list[dict] = []
        for item in group:
            if mi.is_add(item.occurrence_id):
                opt = _withdraw_option(WITHDRAW_ADD, item.occurrence_id)
                slot_options.append(opt)
                _register(options, opt)
        conflicts.append({
            'kind': 'slot',
            'slot': slot,
            'candidates': [_view(mi, item.occurrence_id, item) for item in group],
            'options': slot_options,
        })

    track_order = {track: index for index, track in enumerate(mi.parent.tracks)}
    for track in mi.parent.tracks:
        items = [item for item in ordered if item.track == track]
        for i, first in enumerate(items):
            for second in items[i + 1:]:
                lo = max(first.at, second.at)
                hi = min(first.end, second.end)
                if lo >= hi:
                    continue
                pair_options: list[dict] = []
                for item in (first, second):
                    for opt in _occupancy_options(mi, item):
                        pair_options.append(opt)
                        _register(options, opt)
                conflicts.append({
                    'kind': 'overlap',
                    'track': track,
                    'window': [lo, hi],
                    'candidates': [
                        _view(mi, first.occurrence_id, first),
                        _view(mi, second.occurrence_id, second),
                    ],
                    'options': pair_options,
                })

    conflicts.sort(key=lambda c: 0 if c['kind'] == 'slot' else 1)
    return conflicts, options


@dataclass(frozen=True)
class CandidateResult:
    body: dict
    options: dict[str, dict]
    placements: tuple[Occurrence, ...]

    @property
    def conflicts(self) -> list[dict]:
        return self.body['conflicts']

    @property
    def freezable(self) -> bool:
        return not self.body['conflicts']


def finalize_option_ids(conflicts: list[dict], canonical_options: dict[str, dict]) -> dict[str, dict]:
    """Emit the natural ``action:occurrence`` id when it is unambiguous.

    The internal canonical id keeps an aspect prefix so simultaneous trim and
    move choices on one occurrence never collide.  The lookup map accepts both
    forms (and the canonical form always), which keeps echoed ids working while
    tolerating callers that build the short id themselves.
    """
    emitted = [option for conflict in conflicts for option in conflict['options']]
    short_count: dict[str, int] = {}
    for option in emitted:
        short = f"{option['action']}:{option['occurrence_id']}"
        short_count[short] = short_count.get(short, 0) + 1

    lookup: dict[str, dict] = {}
    for option in emitted:
        canonical = option['id']
        payload = canonical_options[canonical]
        lookup[canonical] = payload
        short = f"{option['action']}:{option['occurrence_id']}"
        if short_count[short] == 1:
            option['id'] = short
            lookup[short] = payload
    return lookup


def resolve_choice(result: 'CandidateResult', choice) -> dict | None:
    """Map a submitted choice id to its decision payload, with tolerant aliases."""
    payload = result.options.get(choice)
    if payload is not None:
        return payload
    if not isinstance(choice, str):
        return None
    emitted = [option for conflict in result.conflicts for option in conflict['options']]
    # A unique bare action (e.g. "keep_right") is unambiguous in this candidate;
    # the same option may be listed by several conflicts, so de-duplicate by id.
    action_ids = {option['id'] for option in emitted if option['action'] == choice}
    if len(action_ids) == 1:
        return result.options.get(next(iter(action_ids)))
    return None


def evaluate(mi: MergeInput, decisions: dict, state: str) -> CandidateResult:
    resolved, phase_conflicts, options = resolve_phase_one(mi, decisions)
    determined = tuple(item for item in resolved.values() if item is not None)
    ordered = order_placements(determined, mi.parent.tracks)

    if phase_conflicts:
        conflicts = phase_conflicts
    else:
        layout_conflicts, layout_options = phase_two(mi, ordered)
        conflicts = layout_conflicts
        options = {**options, **layout_options}

    options = finalize_option_ids(conflicts, options)

    body = {
        'parent': mi.parent.version,
        'left': mi.left.version,
        'right': mi.right.version,
        'state': state,
        'placements': [placement_json(item) for item in ordered],
        'conflicts': conflicts,
    }
    return CandidateResult(body, options, ordered)
