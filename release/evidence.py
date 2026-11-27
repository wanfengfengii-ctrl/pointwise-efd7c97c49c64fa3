from dataclasses import asdict, dataclass

from preview.playlist import PreviewPlaylist
from preview.provenance import AudibleContribution
from review.coverage import BeatEvidence, CoverageResult


@dataclass(frozen=True)
class ReleaseEvidence:
    witness: BeatEvidence
    sources: tuple[AudibleContribution, ...]

    def as_json(self) -> dict:
        return {**self.witness.as_json(), 'sources': [asdict(item) for item in self.sources]}


def build_release_evidence(coverage: CoverageResult, playlist: PreviewPlaylist) -> tuple[ReleaseEvidence, ...]:
    by_beat = {item.beat: item.contributions for item in playlist.beats}
    return tuple(ReleaseEvidence(item, by_beat[item.target_beat]) for item in coverage.evidence)
