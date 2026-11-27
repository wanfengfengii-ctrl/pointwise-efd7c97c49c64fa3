import sqlite3
from dataclasses import dataclass

from edit.layout import order_placements
from edit.snapshots import CutSnapshot
from preview.provenance import AudibleContribution, resolve_contribution
from source.originals import OriginalReference, read_original
from source.windows import BeatWindow, validate_window


@dataclass(frozen=True)
class PreviewBeat:
    beat: int
    contributions: tuple[AudibleContribution, ...]


def build_timeline(
    db: sqlite3.Connection,
    snapshot: CutSnapshot,
    window: BeatWindow | None = None,
) -> tuple[PreviewBeat, ...]:
    full = BeatWindow(0, snapshot.length)
    if window is None:
        window = full
    else:
        validate_window(window.start, window.end, within=full)
    beats: list[list[AudibleContribution]] = [[] for _ in range(window.length)]
    origins: dict[tuple[str, str], OriginalReference] = {}
    for placement in order_placements(snapshot.placements, snapshot.tracks):
        first = max(placement.at, window.start)
        end = min(placement.end, window.end)
        if first >= end:
            continue
        key = (placement.recording, placement.revision)
        if key not in origins:
            origins[key] = read_original(db, *key)
        original = origins[key]
        for beat in range(first, end):
            beats[beat - window.start].append(resolve_contribution(placement, beat, original))
    return tuple(PreviewBeat(window.start + index, tuple(items)) for index, items in enumerate(beats))
