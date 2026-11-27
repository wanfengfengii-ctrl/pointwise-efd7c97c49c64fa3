import sqlite3
from dataclasses import asdict, dataclass

from preview.playlist import get_preview, serialize_playlist
from release.artifact import IssueReceipt, ReleaseArtifact, find_issue_receipt, save_artifact, save_issue_receipt
from release.evidence import build_release_evidence
from release.history import read_release
from review.coverage import coverage_for_version
from source.windows import BeatWindow, GuideError


@dataclass(frozen=True)
class IssueRequest:
    request_id: str
    version: str


@dataclass(frozen=True)
class IssueResult:
    version: str
    pending: tuple[BeatWindow, ...] = ()
    artifact: ReleaseArtifact | None = None
    receipt: IssueReceipt | None = None

    def as_json(self) -> dict:
        if self.pending:
            return {'status': 'pending', 'version': self.version, 'pending': [window.pair() for window in self.pending]}
        return {'status': 'issued', 'artifact': asdict(self.artifact), 'receipt': asdict(self.receipt)}


def issue_release(db: sqlite3.Connection, request: IssueRequest) -> IssueResult:
    prior = find_issue_receipt(db, request.request_id)
    if prior is not None:
        if prior.version != request.version:
            raise GuideError('conflict', 'This issue request number is already used for a different version')
        return IssueResult(prior.version, artifact=read_release(db, prior.release_id), receipt=prior)

    coverage = coverage_for_version(db, request.version)
    if coverage.pending:
        return IssueResult(request.version, pending=coverage.pending)

    playlist = get_preview(db, request.version)
    release_id = f'release-{request.request_id}'
    evidence = [item.as_json() for item in build_release_evidence(coverage, playlist)]
    artifact = ReleaseArtifact(release_id, request.version, serialize_playlist(playlist), evidence)
    receipt = IssueReceipt(request.request_id, request.version, release_id)
    save_artifact(db, artifact)
    save_issue_receipt(db, receipt)
    return IssueResult(request.version, artifact=artifact, receipt=receipt)
