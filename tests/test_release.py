from contextlib import closing

from release.storage import open_database
from tests import ServiceCase, move, place


class ReleaseTests(ServiceCase):
    def test_v7_individual_approvals_cannot_issue_a_mix(self):
        self.cut('R1', 'root', [place('a', 'narration', 'A', [0, 2], 0), place('b', 'translation', 'B', [0, 2], 2)])
        self.listen('solo-a', 'R1', [0, 2])
        self.listen('solo-b', 'R1', [2, 4])
        old = self.issue('old', 'R1')
        self.assertEqual(old['status'], 'issued')
        self.cut('R2', 'R1', [move('b', 0)])
        self.assertEqual(self.api('/coverage/R2'), {'version': 'R2', 'pending': [[0, 2]], 'evidence': []})
        self.assertEqual(self.issue('candidate', 'R2', status=409), {'status': 'pending', 'version': 'R2', 'pending': [[0, 2]]})
        self.api('/read_release/release-candidate', status=404)
        with closing(open_database(self.database)) as db:
            self.assertEqual(db.execute('SELECT request_id FROM issue_receipts').fetchone()[0], 'old')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issue_receipts').fetchone()[0], 1)
        self.assertEqual(self.api('/read_release/release-old'), old['artifact'])

    def test_v7_mixed_revision(self):
        self.cut('R1', 'root', [
            place('a', 'narration', 'A', [0, 2], 0), place('b', 'translation', 'B', [0, 2], 2),
            place('c', 'narration', 'C', [0, 2], 4), place('d', 'translation', 'D', [0, 2], 4),
        ])
        self.listen('solo-a', 'R1', [0, 2])
        self.listen('solo-b', 'R1', [2, 4])
        self.order('old-mix', 'R1', [4, 6])
        self.cut('R2', 'R1', [move('b', 0), move('c', 6), move('d', 6)])
        self.decide('old-mix-approved', 'old-mix')
        expected_old = [
            {'target_beat': 6, 'receipt_id': 'old-mix-approved', 'order_id': 'old-mix', 'review_version': 'R1',
             'review_window': [4, 6], 'review_beat': 4},
            {'target_beat': 7, 'receipt_id': 'old-mix-approved', 'order_id': 'old-mix', 'review_version': 'R1',
             'review_window': [4, 6], 'review_beat': 5},
        ]
        self.assertEqual(self.api('/coverage/R2'), {'version': 'R2', 'pending': [[0, 2]], 'evidence': expected_old},
                         'REVIEW_COVERAGE_MISMATCH')
        self.assertEqual(self.issue('finish', 'R2', status=409), {'status': 'pending', 'version': 'R2', 'pending': [[0, 2]]})
        self.api('/read_release/release-finish', status=404)
        self.listen('new-mix', 'R2', [0, 2])
        result = self.issue('finish', 'R2')
        self.assertEqual(result['status'], 'issued')
        self.assertEqual(result['receipt'], {'request_id': 'finish', 'version': 'R2', 'release_id': 'release-finish'})
        self.assertEqual(result['artifact']['playlist'], self.api('/preview_version/R2'))
        evidence = result['artifact']['evidence']
        self.assertEqual([(e['target_beat'], e['receipt_id'], e['review_beat']) for e in evidence],
                         [(0, 'new-mix-approved', 0), (1, 'new-mix-approved', 1),
                          (6, 'old-mix-approved', 4), (7, 'old-mix-approved', 5)])
        self.assertEqual([{k: v for k, v in e.items() if k != 'sources'} for e in evidence[2:]], expected_old)
        self.assertEqual([(v['recording'], v['source_beat']) for v in evidence[2]['sources']], [('C', 0), ('D', 0)])

    def test_v8_archive_survives_preferred_new_evidence_and_reopen(self):
        self.prepare_mix()
        self.listen('z-original', 'R1', [4, 6])
        issued = self.issue('visitor', 'R1')
        artifact = issued['artifact']
        self.assertEqual(self.api('/read_release/release-visitor'), artifact)
        self.assertEqual([item['receipt_id'] for item in artifact['evidence']], ['z-original-approved'] * 2)
        self.assertEqual(artifact['evidence'][0]['sources'][0]['origin'], '渡口采访册·讲述第 7 号')
        self.cut('R2', 'R1', [move('c', 6), move('d', 6)])
        self.listen('a-later', 'R2', [6, 8])
        self.assertEqual([item['receipt_id'] for item in self.api('/coverage/R1')['evidence']], ['a-later-approved'] * 2)
        self.api('/intake', {'recording': 'C', 'revision': '2', 'length': 3, 'origin': '渡口采访册·讲述勘误'})
        self.reopen()
        self.assertEqual(self.api('/read_release/release-visitor'), artifact)
        self.assertEqual(self.issue('visitor', 'R1'), issued)
        self.assertEqual(self.issue('visitor', 'R2', status=409)['error'], 'conflict')
        self.api('/read_release/release-unknown', status=404)

    def test_v8_atomic_save_rolls_back_artifact_when_receipt_write_fails(self):
        self.prepare_mix()
        self.listen('approved', 'R1', [4, 6])
        existing = self.issue('existing', 'R1')
        with closing(open_database(self.database)) as db:
            db.execute('''
                CREATE TRIGGER stop_receipt BEFORE INSERT ON issue_receipts
                WHEN NEW.request_id = 'retry'
                BEGIN SELECT RAISE(ABORT, 'receipt insert rejected'); END
            ''')
        self.assertEqual(self.issue('retry', 'R1', status=500)['error'], 'storage_error')
        self.api('/read_release/release-retry', status=404)
        self.assertEqual(self.api('/read_release/release-existing'), existing['artifact'])
        with closing(open_database(self.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM release_artifacts').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issue_receipts').fetchone()[0], 1)
            db.execute('DROP TRIGGER stop_receipt')
        retried = self.issue('retry', 'R1')
        self.assertEqual(retried['receipt']['release_id'], 'release-retry')
        self.assertEqual(self.api('/read_release/release-retry'), retried['artifact'])
