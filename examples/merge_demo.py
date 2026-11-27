"""Walk through MERGING.md's two-round adjudication sample over HTTP.

Run with ``python3 -B -m examples.merge_demo``.  A temporary guide database is
created, the P/L/R/L2 proofs are seeded through the ordinary edit API, and the
demo then resolves the first overlap, handles the second conflict, freezes a
merged proof, opens a listening order and issues the release.  A second branch
and the slot-reuse case are demonstrated as well.  Assertion failures propagate
so the process exits non-zero.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from examples.demo import exchange
from examples.merge_inputs import build
from release.service import running_server


def expect(base, path, payload=None, status=200):
    actual, body = exchange(base, path, payload)
    if actual != status:
        raise AssertionError(f'{path}: expected HTTP {status}, got {actual}: {json.dumps(body, ensure_ascii=False)}')
    return body


def pick_option(candidate, kind, action, occurrence_id):
    for conflict in candidate['conflicts']:
        if conflict['kind'] != kind:
            continue
        for option in conflict['options']:
            if option['action'] == action and option['occurrence_id'] == occurrence_id:
                return option['id']
    raise AssertionError(f'no option {kind}/{action}/{occurrence_id} in '
                         + json.dumps(candidate['conflicts'], ensure_ascii=False))


def narration_beats(preview):
    return [
        {'beat': row['beat'],
         'voices': [[voice['occurrence_id'], voice['slot'], voice['source_beat']]
                    for voice in row['contributions'] if voice['track'] == 'narration']}
        for row in preview['beats']
        if any(voice['track'] == 'narration' for voice in row['contributions'])
    ]


def run_merge_demo(base):
    previews = build(base)
    summary = {'input_preview_beats': previews}

    # ---- Round 0: preview P/L/R -------------------------------------
    triple = {'parent': 'P', 'left': 'L', 'right': 'R'}
    candidate = expect(base, '/merge_preview', triple)
    p1 = next(p for p in candidate['placements'] if p['occurrence_id'] == 'P:1')
    first_conflict = candidate['conflicts'][0]
    assert p1['at'] == 5 and p1['source'] == [1, 4], p1
    assert first_conflict['kind'] == 'overlap' and first_conflict['window'] == [6, 8]
    summary['first_conflict'] = {
        'a_candidate': {'at': p1['at'], 'source': p1['source']},
        'window': first_conflict['window'],
        'options': first_conflict['options'],
    }
    print('首轮候选：a 承接 R 的裁切 [1,4) 与 L 的移位，落在 [5,8)，'
          f'与 b 实际相撞 {first_conflict["window"]}；选项 '
          + ', '.join(o['id'] for o in first_conflict['options']))

    # ---- Round 1: withdraw a's move -> 409 with a/c collision --------
    withdraw_move = pick_option(candidate, 'overlap', 'withdraw_move', 'P:1')
    moved_back = expect(base, '/merge_confirm', {
        **triple, 'version': 'M', 'state': candidate['state'], 'choice': withdraw_move,
    }, status=409)
    p1 = next(p for p in moved_back['placements'] if p['occurrence_id'] == 'P:1')
    second_conflict = next(c for c in moved_back['conflicts'] if c['kind'] == 'overlap')
    assert (p1['at'], p1['source']) == (1, [1, 4]), p1
    assert second_conflict['window'] == [1, 3], second_conflict
    summary['second_conflict'] = {'a_at': p1['at'], 'window': second_conflict['window'],
                                  'options': second_conflict['options']}
    print(f'撤回 a 的移位后，a 保留裁切回到 [1,4)，与 c 相撞 {second_conflict["window"]}（HTTP 409）')

    # A stale first-round option on the updated candidate is rejected.
    stale_b = pick_option(candidate, 'overlap', 'withdraw_add', 'R:2')
    expect(base, '/merge_confirm', {
        **triple, 'version': 'M', 'state': moved_back['state'], 'choice': stale_b,
    }, status=400)
    expect(base, '/preview_version/M', status=404)
    summary['stale_option_rejected'] = True
    print('用更新后的候选交首轮“撤回 b”选项 -> HTTP 400；未定稿时目标版号 M 试播 -> HTTP 404')

    # ---- Round 2: withdraw c -> freeze M -----------------------------
    withdraw_c = pick_option(moved_back, 'overlap', 'withdraw_add', 'L:2')
    header = expect(base, '/merge_confirm', {
        **triple, 'version': 'M', 'state': moved_back['state'], 'choice': withdraw_c,
    }, status=200)
    assert header == {'version': 'M', 'parent': 'P', 'length': 8,
                      'tracks': ['narration', 'translation'], 'preview_id': 'preview-M'}, header
    merged_preview = expect(base, '/preview_version/M')
    summary['frozen_M'] = {'header': header, 'narration_beats': narration_beats(merged_preview)}
    print('撤回 c 后整份摆放合法，冻结 M：'
          + json.dumps(summary['frozen_M']['narration_beats'], ensure_ascii=False))

    # ---- Listening order + review + issue on the merged version ------
    order = expect(base, '/review_order',
                   {'order_id': 'merge-demo-order', 'version': 'M', 'window': [1, 4]})
    heard = [[v['occurrence_id'], v['source_beat']]
             for row in order['playlist']['beats'] for v in row['contributions']]
    assert heard == [['P:1', 1], ['P:1', 2], ['P:1', 3]], heard
    expect(base, '/review_decision',
           {'request_id': 'merge-demo-approve', 'order_id': 'merge-demo-order', 'decision': 'approve'})
    coverage = expect(base, '/coverage/M')
    assert coverage['pending'] == [[6, 8]], coverage['pending']
    blocked = expect(base, '/issue', {'request_id': 'merge-demo-issue', 'version': 'M'}, status=409)
    assert blocked['status'] == 'pending'
    expect(base, '/review_order', {'order_id': 'merge-tail', 'version': 'M', 'window': [6, 8]})
    expect(base, '/review_decision',
           {'request_id': 'merge-tail-approve', 'order_id': 'merge-tail', 'decision': 'approve'})
    issued = expect(base, '/issue', {'request_id': 'merge-demo-issue', 'version': 'M'})
    assert issued['status'] == 'issued'
    summary['release_id'] = issued['artifact']['release_id']
    summary['origin_M'] = expect(base, '/merge_origin/M')
    print('审听单 [1,4) 听到 P:1 源拍 1-3；补听 [6,8) 后签发 '
          + summary['release_id'] + '；合稿出处 ' + json.dumps(summary['origin_M'], ensure_ascii=False))

    # ---- Route 2: fresh candidate, withdraw b ------------------------
    again = expect(base, '/merge_preview', triple)
    withdraw_b = pick_option(again, 'overlap', 'withdraw_add', 'R:2')
    route_two = expect(base, '/merge_confirm', {
        **triple, 'version': 'N', 'state': again['state'], 'choice': withdraw_b,
    }, status=200)
    n_preview = expect(base, '/preview_version/N')
    a_beats = [(row['beat'], voice['source_beat'])
               for row in n_preview['beats'] for voice in row['contributions']
               if voice['occurrence_id'] == 'P:1']
    assert a_beats == [(5, 1), (6, 2), (7, 3)], a_beats
    summary['route_two_N'] = {'header': route_two, 'a_beats': a_beats}
    print('另起办理撤回 b：c 与 a 的移位都保留，a 在 [5,8) 依次播源拍 1、2、3')

    # ---- Slot reuse: P/L2/R treats a as two identities ---------------
    l2r = {'parent': 'P', 'left': 'L2', 'right': 'R'}
    reused = expect(base, '/merge_preview', l2r)
    keep_right = pick_option(reused, 'existence', 'keep_right', 'P:1')
    slot_candidate = expect(base, '/merge_confirm', {
        **l2r, 'version': 'Q', 'state': reused['state'], 'choice': keep_right,
    }, status=409)
    slot_conflict = next(c for c in slot_candidate['conflicts'] if c['kind'] == 'slot')
    assert slot_conflict['slot'] == 'a'
    assert {x['occurrence_id'] for x in slot_conflict['candidates']} == {'P:1', 'L2:2'}
    withdraw_l2 = pick_option(slot_candidate, 'slot', 'withdraw_add', 'L2:2')
    expect(base, '/merge_confirm', {
        **l2r, 'version': 'Q', 'state': slot_candidate['state'], 'choice': withdraw_l2,
    }, status=200)
    summary['slot_reuse_Q'] = {'slot': 'a', 'identities': ['P:1', 'L2:2'], 'frozen': 'Q'}
    print('P/L2/R 按两个身份处理；保留右支修改的 P:1 后指出与新身份 L2:2 共用槽 a，撤回新增后冻结 Q')

    # ---- Binding validation ------------------------------------------
    expect(base, '/merge_confirm', {
        **l2r, 'version': 'BAD', 'state': candidate['state'], 'choice': None,
    }, status=400)
    summary['misbound_rejected'] = True
    print('把 P/L/R 候选状态用于 P/L2/R -> HTTP 400')
    return summary


def main():
    with TemporaryDirectory(prefix='oral-history-merge-demo-') as directory:
        database = Path(directory) / 'guide.sqlite3'
        with running_server(database) as base:
            summary = run_merge_demo(base)
        with running_server(database) as base:
            origin = expect(base, '/merge_origin/M')
            artifact = expect(base, '/read_release/' + summary['release_id'])
    assert origin == summary['origin_M']
    assert artifact['release_id'] == summary['release_id']
    summary['reopen'] = {'origin': origin, 'release_id': artifact['release_id']}
    print('重开服务后按版号查回 L/R 双支出处与成品：' + json.dumps(origin, ensure_ascii=False))
    print('MERGE_DEMO ' + json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
