import sqlite3
from dataclasses import dataclass

from edit.snapshots import read_snapshot
from preview.timeline import PreviewBeat, build_timeline
from review.gaps import collect_pending_ranges
from review.orders import ReviewOrder, read_review_order
from review.receipts import list_approval_receipts
from source.windows import BeatWindow


@dataclass(frozen=True)
class BeatEvidence:
    target_beat: int
    receipt_id: str
    order_id: str
    review_version: str
    review_window: BeatWindow
    review_beat: int

    def as_json(self) -> dict:
        return {
            'target_beat': self.target_beat,
            'receipt_id': self.receipt_id,
            'order_id': self.order_id,
            'review_version': self.review_version,
            'review_window': self.review_window.pair(),
            'review_beat': self.review_beat,
        }


@dataclass(frozen=True)
class CoverageResult:
    version: str
    pending: tuple[BeatWindow, ...]
    evidence: tuple[BeatEvidence, ...]

    def as_json(self) -> dict:
        return {
            'version': self.version,
            'pending': [window.pair() for window in self.pending],
            'evidence': [item.as_json() for item in self.evidence],
        }


Combination = tuple[tuple[str, str, str, int], ...]


def _combination(beat: PreviewBeat) -> Combination:
    return tuple(
        (voice.occurrence_id, voice.recording, voice.revision, voice.source_beat)
        for voice in beat.contributions
    )


def _approved_combinations(db: sqlite3.Connection) -> dict[Combination, tuple[str, ReviewOrder, int]]:
    approved = {}
    for receipt in list_approval_receipts(db):
        order = read_review_order(db, receipt.order_id)
        snapshot = read_snapshot(db, order.version)
        for old_beat in build_timeline(db, snapshot, order.window):
            if old_beat.contributions:
                approved.setdefault(_combination(old_beat), (receipt.request_id, order, old_beat.beat))
    return approved


def coverage_for_version(db: sqlite3.Connection, version: str) -> CoverageResult:
    target = read_snapshot(db, version)
    audible = [item for item in build_timeline(db, target) if item.contributions]
    if not audible:
        return CoverageResult(version, (), ())
    approved = _approved_combinations(db)
    evidence = []
    for beat in audible:
        matched = approved.get(_combination(beat))
        if matched is not None:
            receipt_id, order, review_beat = matched
            evidence.append(BeatEvidence(beat.beat, receipt_id, order.order_id, order.version, order.window, review_beat))
    pending = collect_pending_ranges((beat.beat for beat in audible), {item.target_beat for item in evidence})
    return CoverageResult(version, pending, tuple(evidence))
