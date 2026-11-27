from contextlib import closing

from release.storage import open_database
from tests import ServiceCase, copy, move, place, remove, trim


class ReviewTests(ServiceCase):
    def test_v4_window_boundary_and_returned_review(self):
        self.cut('R1', 'root', [place('a', 'narration', 'A', [0, 4], 0), place('b', 'translation', 'B', [0, 4], 0)])
        order = self.order('mid', 'R1', [1, 3])
        self.assertEqual(order['window'], [1, 3])
        self.assertEqual([row['beat'] for row in order['playlist']['beats']], [1, 2])
        self.assertEqual([len(row['contributions']) for row in order['playlist']['beats']], [2, 2])
        returned = self.decide('returned', 'mid', 'return')
        self.assertEqual(returned, {'request_id': 'returned', 'order_id': 'mid', 'decision': 'return'})
        self.assertEqual(self.api('/coverage/R1'), {'version': 'R1', 'pending': [[0, 4]], 'evidence': []})
        self.decide('approved', 'mid')
        coverage = self.api('/coverage/R1')
        self.assertEqual(coverage['pending'], [[0, 1], [3, 4]])
        self.assertEqual(coverage['evidence'], [
            {'target_beat': beat, 'receipt_id': 'approved', 'order_id': 'mid', 'review_version': 'R1',
             'review_window': [1, 3], 'review_beat': beat} for beat in (1, 2)
        ])

    def test_v4_invalid_order_and_preview_windows(self):
        self.prepare_mix()
        for window in ([2, 2], [-1, 1], [5, 7], [True, 2], [1.5, 3]):
            with self.subTest(window=window):
                self.assertEqual(self.order('bad', 'R1', window, status=400)['error'], 'invalid_window')
        self.order('bad', 'missing', [1, 3], status=404)
        self.order('bad', 'root', [0, 1], status=400)
        self.decide('unknown', 'bad', status=404)
        accepted = self.order('bad', 'R1', [4, 6])
        self.assertEqual(self.order('bad', 'R1', [4, 6]), accepted)
        self.assertEqual(self.order('bad', 'R1', [4, 5], status=409)['error'], 'conflict')
        for query in ('start=1', 'start=2&end=2', 'start=0&end=7', 'start=1&start=2&end=3'):
            with self.subTest(query=query):
                self.api('/preview_version/R1?' + query, status=400)
        self.api('/preview_version/missing', status=404)
        self.api('/coverage/missing', status=404)

    def test_v5_replay_after_revision_rejects_changed_payload(self):
        self.prepare_mix()
        first_order = self.order('old', 'R1', [4, 6])
        first = self.decide('result', 'old')
        self.assertEqual(self.decide('result', 'old'), first)
        self.cut('R2', 'R1', [move('c', 6), move('d', 6)])
        self.order('new', 'R2', [6, 8])
        self.assertEqual(self.order('old', 'R1', [4, 6]), first_order)
        self.assertEqual(self.order('old', 'R2', [6, 8], status=409)['error'], 'conflict')
        self.assertEqual(self.decide('result', 'old', 'return', status=409)['error'], 'conflict')
        self.assertEqual(self.decide('result', 'new', status=409)['error'], 'conflict')
        self.assertEqual(self.decide('result', 'old'), first)
        with closing(open_database(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM review_receipts').fetchone()[0], 1)
        self.assertEqual({row['receipt_id'] for row in self.api('/coverage/R2')['evidence']}, {'result'})

    def test_v6_late_binding_move_and_copy(self):
        self.prepare_mix()
        old_order = self.order('old', 'R1', [4, 6])
        self.cut('R2', 'R1', [move('c', 6), move('d', 6), copy('c', 'c-copy', 4), copy('d', 'd-copy', 4)])
        self.assertEqual(self.api('/coverage/R2')['pending'], [[4, 8]])
        self.decide('late', 'old')
        self.assertEqual(self.order('old', 'R1', [4, 6]), old_order)
        original = self.api('/preview_version/R1')['beats'][4]['contributions']
        revised = self.api('/preview_version/R2')['beats']
        self.assertEqual([v['occurrence_id'] for v in revised[6]['contributions']], [v['occurrence_id'] for v in original])
        self.assertTrue({v['occurrence_id'] for v in revised[4]['contributions']}.isdisjoint(v['occurrence_id'] for v in original))
        result = self.api('/coverage/R2')
        self.assertEqual(result['pending'], [[4, 6]])
        self.assertEqual(result['evidence'], [
            {'target_beat': new, 'receipt_id': 'late', 'order_id': 'old', 'review_version': 'R1',
             'review_window': [4, 6], 'review_beat': old} for new, old in ((6, 4), (7, 5))
        ])

    def test_v6_offset_and_trim_change_combination(self):
        self.prepare_mix()
        self.listen('original', 'R1', [4, 6])
        self.cut('skew', 'R1', [move('d', 5)])
        self.assertEqual(self.api('/coverage/skew'), {'version': 'skew', 'pending': [[4, 7]], 'evidence': []})
        self.cut('trimmed', 'R1', [trim('c', [2, 3])])
        result = self.api('/coverage/trimmed')
        self.assertEqual(result['pending'], [[4, 5]])
        self.assertEqual([(item['target_beat'], item['review_beat']) for item in result['evidence']], [(5, 5)])
        self.assertEqual(self.api('/preview_version/R1')['beats'][4]['contributions'][0]['source_beat'], 1)

    def test_v6_reusing_a_slot_creates_a_new_occurrence(self):
        self.prepare_mix()
        self.listen('original', 'R1', [4, 6])
        self.cut('replaced', 'R1', [remove('c'), place('c', 'narration', 'C', [1, 3], 4)])
        self.assertEqual(self.api('/coverage/replaced')['pending'], [[4, 6]])
        self.cut('kept', 'R1', [])
        self.assertEqual(self.api('/coverage/kept')['pending'], [])
