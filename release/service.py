import argparse
import json
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, unquote, urlsplit

from edit.operations import EditOperation
from edit.revisions import RevisionRequest, submit_revision
from merge.coordinator import confirm_merge, preview_merge, read_merge_origin
from preview.playlist import get_preview, serialize_playlist
from release.history import read_release
from release.issuance import IssueRequest, issue_release
from release.storage import initialize_database, open_database, write_transaction
from review.coverage import coverage_for_version
from review.decisions import DecisionRequest, submit_review_decision
from review.orders import open_review_order
from source.catalog import find_recording_revision
from source.intake import IntakeRequest, register_recording
from source.originals import read_original
from source.windows import GuideError, validate_window


_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
_NOT_FOUND = {'unknown_route', 'unknown_recording', 'unknown_version', 'unknown_order', 'unknown_release'}
_EDIT_FIELDS = {
    'place': {'track', 'recording', 'revision', 'source', 'at'},
    'move': {'at'},
    'trim': {'source'},
    'copy': {'as', 'at'},
    'remove': set(),
}


def _shape(data: dict, fields: set[str]) -> None:
    if not isinstance(data, dict) or data.keys() != fields:
        raise GuideError('invalid_request', 'Expected exactly these fields: ' + ', '.join(sorted(fields)))


def _identifier(data: dict, key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise GuideError('invalid_request', f'Invalid identifier for {key}')
    return value


def _window(value):
    if not isinstance(value, list) or len(value) != 2:
        raise GuideError('invalid_window', 'A beat window is an array of two integers')
    return validate_window(*value)


def _operations(items) -> tuple[EditOperation, ...]:
    if not isinstance(items, list):
        raise GuideError('invalid_request', 'Operations must be an array')
    result = []
    for item in items:
        name = item.get('op') if isinstance(item, dict) else None
        if not isinstance(name, str) or name not in _EDIT_FIELDS:
            raise GuideError('invalid_operation', 'Unknown edit operation')
        _shape(item, {'op', 'slot'} | _EDIT_FIELDS[name])
        result.append(EditOperation(
            name,
            _identifier(item, 'slot'),
            at=item.get('at'),
            track=_identifier(item, 'track') if 'track' in item else None,
            recording=_identifier(item, 'recording') if 'recording' in item else None,
            revision=_identifier(item, 'revision') if 'revision' in item else None,
            source=_window(item['source']) if 'source' in item else None,
            target_slot=_identifier(item, 'as') if 'as' in item else None,
        ))
    return tuple(result)


def _preview_window(query: str):
    if not query:
        return None
    try:
        params = parse_qs(query, keep_blank_values=True, strict_parsing=True)
        if set(params) == {'start', 'end'} and all(len(values) == 1 for values in params.values()):
            return validate_window(int(params['start'][0]), int(params['end'][0]))
    except GuideError:
        raise
    except ValueError:
        pass
    raise GuideError('invalid_window', 'Supply one integer start and one integer end')


def _enter_recording(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'recording', 'revision', 'length', 'origin'})
    request = IntakeRequest(_identifier(data, 'recording'), _identifier(data, 'revision'), data['length'], data['origin'])
    return 200, register_recording(db, request)


def _edit_version(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'version', 'parent', 'operations'})
    request = RevisionRequest(_identifier(data, 'version'), _identifier(data, 'parent'), _operations(data['operations']))
    snapshot = submit_revision(db, request)
    return 200, {
        'version': snapshot.version,
        'parent': snapshot.parent,
        'length': snapshot.length,
        'tracks': list(snapshot.tracks),
        'preview_id': snapshot.preview_id,
    }


def _merge_preview(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'parent', 'left', 'right'})
    candidate = preview_merge(
        db,
        _identifier(data, 'parent'),
        _identifier(data, 'left'),
        _identifier(data, 'right'),
    )
    return 200, candidate


def _merge_confirm(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'parent', 'left', 'right', 'version', 'state', 'choice'})
    state = data['state']
    if not isinstance(state, str) or not state:
        raise GuideError('invalid_request', 'A non-empty candidate state is required')
    choice = data['choice']
    if choice is not None and not isinstance(choice, str):
        raise GuideError('invalid_request', 'choice must be an option id string or null')
    return confirm_merge(
        db,
        parent=_identifier(data, 'parent'),
        left=_identifier(data, 'left'),
        right=_identifier(data, 'right'),
        version=_identifier(data, 'version'),
        state=state,
        choice=choice,
    )


def _review_order(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'order_id', 'version', 'window'})
    order, playlist = open_review_order(db, _identifier(data, 'order_id'), _identifier(data, 'version'), _window(data['window']))
    return 200, {
        'order_id': order.order_id,
        'version': order.version,
        'window': order.window.pair(),
        'preview_id': order.preview_id,
        'playlist': serialize_playlist(playlist),
    }


def _review_decision(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'request_id', 'order_id', 'decision'})
    request = DecisionRequest(_identifier(data, 'request_id'), _identifier(data, 'order_id'), data['decision'])
    return 200, asdict(submit_review_decision(db, request))


def _issue(db: sqlite3.Connection, data: dict) -> tuple[int, dict]:
    _shape(data, {'request_id', 'version'})
    result = issue_release(db, IssueRequest(_identifier(data, 'request_id'), _identifier(data, 'version')))
    return (409 if result.pending else 200), result.as_json()


_POST = {
    '/intake': _enter_recording,
    '/edit_version': _edit_version,
    '/merge_preview': _merge_preview,
    '/merge_confirm': _merge_confirm,
    '/review_order': _review_order,
    '/review_decision': _review_decision,
    '/issue': _issue,
}


def _get(db: sqlite3.Connection, path: str, query: str) -> dict:
    parts = tuple(unquote(part) for part in path.removeprefix('/').split('/'))
    if len(parts) == 2 and parts[0] == 'preview_version':
        return serialize_playlist(get_preview(db, parts[1], _preview_window(query)))
    if query:
        raise GuideError('invalid_request', 'Only a preview accepts query parameters')
    match parts:
        case ('intake', recording, revision):
            original = read_original(db, recording, revision)
            entry = find_recording_revision(db, recording, revision)
            return {**asdict(original), 'length': entry.length, 'available': entry.available.pair()}
        case ('coverage', version):
            return coverage_for_version(db, version).as_json()
        case ('merge_origin', version):
            return read_merge_origin(db, version)
        case ('read_release', release_id):
            return asdict(read_release(db, release_id))
        case _:
            raise GuideError('unknown_route', 'Unknown guide endpoint')


class GuideRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _respond(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, error: GuideError) -> None:
        if error.code in _NOT_FOUND:
            status = 404
        elif error.code == 'conflict':
            status = 409
        else:
            status = 400
        self._respond(status, {'error': error.code, 'message': str(error)})

    def _target(self):
        try:
            return urlsplit(self.path)
        except ValueError as error:
            raise GuideError('invalid_request', 'Invalid request target') from error

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0:
                raise ValueError('empty body')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError('incomplete body')
            data = json.loads(body.decode('utf-8'))
        except ValueError as error:
            raise GuideError('invalid_request', 'A complete UTF-8 JSON object is required') from error
        if not isinstance(data, dict):
            raise GuideError('invalid_request', 'The JSON body must be an object')
        return data

    def do_GET(self):
        try:
            target = self._target()
            with closing(open_database(self.server.database)) as db:
                db.execute('BEGIN')
                response = _get(db, target.path, target.query)
        except GuideError as error:
            self._error(error)
        except sqlite3.Error:
            self._respond(500, {'error': 'storage_error', 'message': 'The database could not complete the read'})
        else:
            self._respond(200, response)

    def do_POST(self):
        try:
            target = self._target()
            handler = _POST.get(target.path)
            if handler is None:
                raise GuideError('unknown_route', 'Unknown guide endpoint')
            if target.query:
                raise GuideError('invalid_request', 'POST endpoints take parameters in the JSON body')
            data = self._read_json()
            with closing(open_database(self.server.database)) as db, write_transaction(db):
                status, response = handler(db, data)
        except GuideError as error:
            self._error(error)
        except sqlite3.Error:
            self._respond(500, {'error': 'storage_error', 'message': 'The database could not commit the request'})
        else:
            self._respond(status, response)


class _GuideServer(ThreadingHTTPServer):
    def __init__(self, database: str | Path, port: int):
        initialize_database(database)
        self.database = database
        super().__init__(('127.0.0.1', port), GuideRequestHandler)


@contextmanager
def running_server(database: str | Path):
    with _GuideServer(database, 0) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05})
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


def serve(database: str | Path, port: int = 8080) -> None:
    with _GuideServer(database, port) as server:
        print(f'Guide service on http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description='Oral history guide review service')
    commands = parser.add_subparsers(dest='command', required=True)
    initialize = commands.add_parser('init')
    initialize.add_argument('--db', type=Path, required=True)
    listener = commands.add_parser('serve')
    listener.add_argument('--db', type=Path, required=True)
    listener.add_argument('--port', type=int, default=8080)
    args = parser.parse_args()
    if args.command == 'init':
        initialize_database(args.db)
    else:
        serve(args.db, args.port)


if __name__ == '__main__':
    main()
