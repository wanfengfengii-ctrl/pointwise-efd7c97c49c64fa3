import sqlite3
from dataclasses import asdict, dataclass

from edit.snapshots import read_snapshot
from preview.overlaps import ListeningSpan, classify_listening_spans
from preview.timeline import PreviewBeat, build_timeline
from source.windows import BeatWindow


@dataclass(frozen=True)
class PreviewPlaylist:
    version: str
    preview_id: str
    tracks: tuple[str, ...]
    window: BeatWindow
    beats: tuple[PreviewBeat, ...]
    spans: tuple[ListeningSpan, ...]


def get_preview(db: sqlite3.Connection, version: str, window: BeatWindow | None = None) -> PreviewPlaylist:
    snapshot = read_snapshot(db, version)
    beats = build_timeline(db, snapshot, window)
    return PreviewPlaylist(
        snapshot.version,
        snapshot.preview_id,
        snapshot.tracks,
        window if window is not None else BeatWindow(0, snapshot.length),
        beats,
        classify_listening_spans(beats),
    )


def serialize_playlist(playlist: PreviewPlaylist) -> dict:
    return {
        'version': playlist.version,
        'preview_id': playlist.preview_id,
        'tracks': list(playlist.tracks),
        'window': playlist.window.pair(),
        'beats': [
            {'beat': item.beat, 'contributions': [asdict(voice) for voice in item.contributions]}
            for item in playlist.beats
        ],
        'spans': [{'kind': span.kind, 'window': span.window.pair()} for span in playlist.spans],
    }
