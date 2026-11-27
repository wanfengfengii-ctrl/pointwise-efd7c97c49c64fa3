from collections.abc import Iterable

from edit.occurrences import Occurrence
from source.windows import GuideError


TRACKS = ('narration', 'translation')


def order_placements(placements: Iterable[Occurrence], tracks: tuple[str, ...]) -> tuple[Occurrence, ...]:
    track_order = {track: index for index, track in enumerate(tracks)}
    return tuple(sorted(placements, key=lambda item: (track_order[item.track], item.at, item.slot)))


def validate_layout(placements: Iterable[Occurrence], tracks: tuple[str, ...]) -> tuple[Occurrence, ...]:
    placements = tuple(placements)
    for placement in placements:
        if placement.track not in tracks:
            raise GuideError('invalid_track', f'Unknown track {placement.track}')
    ordered = order_placements(placements, tracks)
    previous = None
    for placement in ordered:
        if previous is not None and placement.track == previous.track and placement.at < previous.end:
            raise GuideError(
                'same_track_overlap',
                f'{previous.slot} and {placement.slot} overlap on {placement.track}',
            )
        previous = placement
    return ordered


def layout_extent(placements: Iterable[Occurrence]) -> int:
    return max((placement.end for placement in placements), default=0)
