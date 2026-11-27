from collections.abc import Iterable, Set

from source.windows import BeatWindow


def collect_pending_ranges(audible_beats: Iterable[int], covered_beats: Set[int]) -> tuple[BeatWindow, ...]:
    ranges = []
    start = None
    end = None
    for beat in audible_beats:
        if beat in covered_beats:
            continue
        if start is None:
            start = beat
        elif beat != end:
            ranges.append(BeatWindow(start, end))
            start = beat
        end = beat + 1
    if start is not None:
        ranges.append(BeatWindow(start, end))
    return tuple(ranges)
