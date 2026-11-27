from dataclasses import dataclass

from edit.occurrences import Occurrence
from source.originals import OriginalReference


@dataclass(frozen=True)
class AudibleContribution:
    track: str
    slot: str
    occurrence_id: str
    recording: str
    revision: str
    source_beat: int
    origin: str


def resolve_contribution(placement: Occurrence, beat: int, original: OriginalReference) -> AudibleContribution:
    return AudibleContribution(
        placement.track,
        placement.slot,
        placement.occurrence_id,
        original.recording,
        original.revision,
        placement.source_beat_at(beat),
        original.origin,
    )
