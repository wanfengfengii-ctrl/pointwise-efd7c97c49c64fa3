import sqlite3

from release.artifact import ReleaseArtifact, find_artifact
from source.windows import GuideError


def read_release(db: sqlite3.Connection, release_id: str) -> ReleaseArtifact:
    artifact = find_artifact(db, release_id)
    if artifact is None:
        raise GuideError('unknown_release', f'Unknown release {release_id}')
    return artifact
