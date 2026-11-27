from dataclasses import dataclass


class GuideError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BeatWindow:
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int:
            raise GuideError('invalid_window', 'Beat endpoints must be integers')
        if self.start < 0 or self.end < self.start:
            raise GuideError('invalid_window', 'Beat endpoints are out of order or negative')

    @property
    def length(self) -> int:
        return self.end - self.start

    def contains(self, other: 'BeatWindow') -> bool:
        return self.start <= other.start <= other.end <= self.end

    def pair(self) -> list[int]:
        return [self.start, self.end]


def validate_window(start: int, end: int, *, within: BeatWindow | None = None) -> BeatWindow:
    window = BeatWindow(start, end)
    if window.length == 0:
        raise GuideError('invalid_window', 'The window must contain at least one beat')
    if within is not None and not within.contains(window):
        raise GuideError('invalid_window', 'The window is outside the available beats')
    return window


def available_window(length: int) -> BeatWindow:
    if type(length) is not int or length <= 0:
        raise GuideError('invalid_length', 'Recording length must be a positive integer')
    return BeatWindow(0, length)
