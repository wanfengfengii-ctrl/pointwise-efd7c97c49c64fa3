import json
from contextlib import closing

from release.storage import initialize_database, open_database
from tests import ServiceCase, place


class InitializationTests(ServiceCase):
    def test_reseed_keeps_originals_edits_orders_receipts_and_release(self):
        self.server.close()
        database = self.database.with_name('prior.sqlite3')
        fixture = database.with_name('earlier-recording.json')
        original = {'recording': 'A', 'revision': '1', 'length': 2, 'origin': '开馆前登记的采访原件'}
        fixture.write_text(json.dumps([original], ensure_ascii=False), encoding='utf-8')
        initialize_database(database, fixture)
        self.database = database
        self.reopen()
        self.assertEqual(self.api('/intake/A/1'), {**original, 'available': [0, 2]})
        self.assertEqual(self.api('/intake/B/1')['available'], [0, 4])
        self.cut('staff-edit', 'root', [place('local', 'narration', 'A', [1, 2], 2)])
        order = self.order('staff-order', 'staff-edit', [2, 3])
        decision = self.decide('staff-approval', 'staff-order')
        issued = self.issue('staff-issue', 'staff-edit')
        preview = self.api('/preview_version/staff-edit')
        self.server.close()
        initialize_database(database)
        initialize_database(database)
        self.reopen()
        self.assertEqual(self.api('/intake/A/1'), {**original, 'available': [0, 2]})
        self.assertEqual(self.api('/preview_version/staff-edit'), preview)
        self.assertEqual(self.order('staff-order', 'staff-edit', [2, 3]), order)
        self.assertEqual(self.decide('staff-approval', 'staff-order'), decision)
        self.assertEqual(self.api('/read_release/release-staff-issue'), issued['artifact'])
        self.assertEqual(self.issue('staff-issue', 'staff-edit'), issued)
        with closing(open_database(database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM recordings').fetchone()[0], 4)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM issue_receipts').fetchone()[0], 1)
