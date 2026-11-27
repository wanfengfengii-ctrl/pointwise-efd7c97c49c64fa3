from dataclasses import dataclass
from itertools import groupby

from preview.timeline import PreviewBeat
from source.windows import BeatWindow


@dataclass(frozen=True)
class ListeningSpan:
    kind: str
    window: BeatWindow


def _kind(beat: PreviewBeat) -> str:
    return ('silence', 'solo', 'mix')[len(beat.contributions)]


def classify_listening_spans(beats: tuple[PreviewBeat, ...]) -> tuple[ListeningSpan, ...]:
    spans = []
    for kind, group in groupby(beats, _kind):
        first = next(group).beat
        last = first
        for item in group:
            last = item.beat
        spans.append(ListeningSpan(kind, BeatWindow(first, last + 1)))
    return tuple(spans)
