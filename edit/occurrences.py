from dataclasses import dataclass, replace

from source.windows import BeatWindow, GuideError, validate_window


@dataclass(frozen=True)
class Occurrence:
    slot: str
    occurrence_id: str
    track: str
    recording: str
    revision: str
    source: BeatWindow
    at: int

    def __post_init__(self):
        if type(self.at) is not int or self.at < 0:
            raise GuideError('invalid_position', 'A placement requires a nonnegative integer start')
        if self.source.length == 0:
            raise GuideError('invalid_window', 'A placement cannot use an empty source window')

    @property
    def end(self) -> int:
        return self.at + self.source.length

    def move(self, at: int) -> 'Occurrence':
        return replace(self, at=at)

    def trim(self, source: BeatWindow) -> 'Occurrence':
        validate_window(source.start, source.end, within=self.source)
        return replace(self, at=self.at + source.start - self.source.start, source=source)

    def copy_as(self, slot: str, occurrence_id: str, at: int) -> 'Occurrence':
        return replace(self, slot=slot, occurrence_id=occurrence_id, at=at)

    def source_beat_at(self, beat: int) -> int:
        if not self.at <= beat < self.end:
            raise GuideError('invalid_position', 'The beat is outside this placement')
        return self.source.start + beat - self.at
