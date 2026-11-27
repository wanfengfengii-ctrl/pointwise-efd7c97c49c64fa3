import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from release.service import running_server


def read_day() -> dict:
    with Path(__file__).with_name('day.json').open(encoding='utf-8') as stream:
        return json.load(stream)


def exchange(base: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    try:
        response = urlopen(request, timeout=5)
    except HTTPError as error:
        response = error
    with response:
        return response.status, json.load(response)


def _call(base: str, path: str, payload: dict | None = None, *, status: int = 200) -> dict:
    actual_status, result = exchange(base, path, payload)
    if actual_status != status:
        raise AssertionError(f'{path}: expected HTTP {status}, got {actual_status} with {result}')
    return result


def _check(actual, expected):
    if actual != expected:
        raise AssertionError(f'Expected {expected!r}, got {actual!r}')


def _scenario(case_id, input_data, expected, actual, downstream_expected, downstream_actual, code_paths, oracle):
    _check(actual, expected)
    _check(downstream_actual, downstream_expected)
    evidence = {
        'case_id': case_id,
        'input': input_data,
        'expected': expected,
        'actual': actual,
        'downstream_expected': downstream_expected,
        'downstream_actual': downstream_actual,
        'code_paths': code_paths,
        'oracle': oracle,
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False))


def _witnesses(coverage_or_artifact: dict) -> list[list]:
    return [[item['target_beat'], item['receipt_id'], item['review_beat']] for item in coverage_or_artifact['evidence']]


def run_day(base: str) -> dict:
    day = read_day()
    for recording in day['recordings']:
        expected = {**recording, 'available': [0, recording['length']]}
        _check(_call(base, '/intake', recording), expected)
    header = _call(base, '/edit_version', day['first_cut'])
    preview = _call(base, '/preview_version/R1')
    order = _call(base, '/review_order', day['original_order'])
    _check(order['preview_id'], header['preview_id'])
    _check(order['playlist']['beats'], preview['beats'][1:3])
    _check(_call(base, '/review_decision', day['original_approval']), day['original_approval'])
    coverage = _call(base, '/coverage/R1')
    _scenario(
        'v1',
        {'recordings': day['recordings'], 'cut': day['first_cut'], 'order': day['original_order']},
        {'spans': [['solo', [0, 1]], ['mix', [1, 3]], ['solo', [3, 4]], ['silence', [4, 5]], ['solo', [5, 6]]],
         'mixed_source_beats': [[3, 1], [4, 2]]},
        {'spans': [[span['kind'], span['window']] for span in preview['spans']],
         'mixed_source_beats': [[voice['source_beat'] for voice in beat['contributions']] for beat in order['playlist']['beats']]},
        [[0, 1], [3, 4], [5, 6]],
        coverage['pending'],
        ['edit/revisions.py', 'preview/timeline.py', 'preview/provenance.py', 'review/coverage.py'],
        '手排两轨的六拍和两条非零源切点，划掉共同听过的第 1、2 拍以及空白的第 4 拍。',
    )

    _call(base, '/edit_version', day['second_cut'])
    revised = _call(base, '/coverage/R2')
    blocked = _call(base, '/issue', day['issue'], status=409)
    missing = _call(base, '/read_release/release-museum-day', status=404)
    _check(missing['error'], 'unknown_release')
    _call(base, '/review_order', day['supplement_order'])
    _call(base, '/review_decision', day['supplement_approval'])
    issued = _call(base, '/issue', day['issue'])
    artifact = issued['artifact']
    _check(_call(base, '/read_release/' + artifact['release_id']), artifact)
    _scenario(
        'v6',
        {'cut': day['second_cut'], 'earlier_approval': day['original_approval'], 'issue': day['issue']},
        {'pending': [[8, 10]], 'witnesses': [[6, 'morning-approved', 1], [7, 'morning-approved', 2]]},
        {'pending': revised['pending'], 'witnesses': _witnesses(revised)},
        {'blocked': {'status': 'pending', 'version': 'R2', 'pending': [[8, 10]]}, 'status': 'issued',
         'witnesses': [[6, 'morning-approved', 1], [7, 'morning-approved', 2],
                       [8, 'afternoon-approved', 8], [9, 'afternoon-approved', 9]]},
        {'blocked': blocked, 'status': issued['status'], 'witnesses': _witnesses(artifact)},
        ['edit/occurrences.py', 'edit/snapshots.py', 'review/coverage.py', 'release/issuance.py'],
        '第 6、7 拍分别对应原听审第 1、2 拍。第 8、9 拍是新出现，只能使用补听回执。',
    )
    return issued


def main() -> None:
    with TemporaryDirectory(prefix='oral-history-demo-') as directory:
        database = Path(directory) / 'guide.sqlite3'
        with running_server(database) as base:
            issued = run_day(base)
        artifact = issued['artifact']
        with running_server(database) as base:
            reread = _call(base, '/read_release/' + artifact['release_id'])
            replay = _call(base, '/issue', read_day()['issue'])
        _check(reread, artifact)
        _check(replay, issued)
        print(json.dumps({'release_id': reread['release_id'], 'version': reread['version'], 'evidence': _witnesses(reread)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
