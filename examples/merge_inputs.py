import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.demo import exchange
from release.service import running_server


def place(slot, source, at):
    return dict(op="place", slot=slot, track="narration", recording="A", revision="1", source=source, at=at)


CUTS = (
    ("P", "root", [place("a", [0, 4], 0)]),
    ("L", "P", [dict(op="move", slot="a", at=4), place("c", [4, 6], 1)]),
    ("R", "P", [dict(op="trim", slot="a", source=[1, 4]), place("b", [4, 6], 6)]),
    ("L2", "P", [dict(op="remove", slot="a"), place("a", [4, 6], 0)]),
)

EXPECTED = {
    "P": [[0, "P:1", 0], [1, "P:1", 1], [2, "P:1", 2], [3, "P:1", 3]],
    "L": [[1, "L:2", 4], [2, "L:2", 5], [4, "P:1", 0], [5, "P:1", 1], [6, "P:1", 2], [7, "P:1", 3]],
    "R": [[1, "P:1", 1], [2, "P:1", 2], [3, "P:1", 3], [6, "R:2", 4], [7, "R:2", 5]],
    "L2": [[0, "L2:2", 4], [1, "L2:2", 5]],
}


def call(base, path, payload=None):
    status, result = exchange(base, path, payload)
    if status != 200:
        raise AssertionError(f"{path}: HTTP {status}: {result}")
    return result


def build(base):
    for version, parent, operations in CUTS:
        header = call(base, "/edit_version", dict(version=version, parent=parent, operations=operations))
        if (header["version"], header["parent"]) != (version, parent):
            raise AssertionError(header)
    previews = {}
    for version, _, _ in CUTS:
        preview = call(base, f"/preview_version/{version}")
        previews[version] = [
            [row["beat"], voice["occurrence_id"], voice["source_beat"]]
            for row in preview["beats"]
            for voice in row["contributions"]
        ]
    if previews != EXPECTED:
        raise AssertionError(f"Unexpected input previews: {previews}")
    return previews


def main():
    with TemporaryDirectory(prefix="guide-merge-inputs-") as directory:
        with running_server(Path(directory) / "guide.sqlite3") as base:
            previews = build(base)
    print(json.dumps(previews, ensure_ascii=False))


if __name__ == "__main__":
    main()
