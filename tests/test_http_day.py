from examples.demo import read_day, run_day
from tests import ServiceCase


class HttpDayTests(ServiceCase):
    def test_working_day_and_old_artifact_after_restart(self):
        issued = run_day(self.base)
        artifact = issued['artifact']
        self.assertEqual(artifact['release_id'], 'release-museum-day')
        self.assertEqual(artifact['playlist']['window'], [0, 10])
        self.assertEqual([len(row['contributions']) for row in artifact['playlist']['beats']], [0, 0, 0, 0, 0, 0, 2, 2, 2, 2])
        self.assertEqual([row['review_version'] for row in artifact['evidence']], ['R1', 'R1', 'R2', 'R2'])
        self.assertEqual([row['review_window'] for row in artifact['evidence']], [[1, 3], [1, 3], [8, 10], [8, 10]])
        self.reopen()
        self.assertEqual(self.api('/read_release/release-museum-day'), artifact)
        self.assertEqual(self.api('/issue', read_day()['issue']), issued)
