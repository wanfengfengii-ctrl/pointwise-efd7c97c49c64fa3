from examples.demo import read_day
from tests import ServiceCase, place


class PrepareTests(ServiceCase):
    def test_v1_preview_spans_absolute_beats_and_originals(self):
        day = read_day()
        for original in day['recordings']:
            self.assertEqual(self.api('/intake', original), {**original, 'available': [0, original['length']]})
        header = self.api('/edit_version', day['first_cut'])
        self.assertEqual(header, {'version': 'R1', 'parent': 'root', 'length': 6,
                                  'tracks': ['narration', 'translation'], 'preview_id': 'preview-R1'})
        playlist = self.api('/preview_version/R1')
        self.assertEqual([row['beat'] for row in playlist['beats']], list(range(6)))
        self.assertEqual(playlist['spans'], [
            {'kind': 'solo', 'window': [0, 1]}, {'kind': 'mix', 'window': [1, 3]},
            {'kind': 'solo', 'window': [3, 4]}, {'kind': 'silence', 'window': [4, 5]},
            {'kind': 'solo', 'window': [5, 6]},
        ])
        self.assertEqual(playlist['beats'][4], {'beat': 4, 'contributions': []})
        sliced = self.api('/preview_version/R1?start=1&end=3')
        self.assertEqual(sliced['window'], [1, 3])
        self.assertEqual(sliced['beats'], playlist['beats'][1:3])
        contributions = [[(v['track'], v['recording'], v['revision'], v['source_beat'], v['origin'])
                          for v in row['contributions']] for row in sliced['beats']]
        self.assertEqual(contributions, [
            [('narration', 'A', '1', 3, '河岸采访册·讲述第 12 号'), ('translation', 'B', '1', 1, '河岸采访册·译声第 12 号')],
            [('narration', 'A', '1', 4, '河岸采访册·讲述第 12 号'), ('translation', 'B', '1', 2, '河岸采访册·译声第 12 号')],
        ])
        through_silence = self.api('/preview_version/R1?start=3&end=6')
        self.assertEqual(through_silence['beats'], playlist['beats'][3:6])
        self.assertEqual(through_silence['spans'][1], {'kind': 'silence', 'window': [4, 5]})
        self.assertEqual(through_silence['beats'][2]['contributions'][0]['source_beat'], 3)

    def test_v2_conflict_and_later_recording_revision_keep_original(self):
        self.cut('R1', 'root', [place('a', 'narration', 'A', [4, 6], 0)])
        original = self.api('/intake/A/1')
        preview = self.api('/preview_version/R1')
        conflicting = {'recording': 'A', 'revision': '1', 'length': 8, 'origin': '后来的采访出处'}
        self.assertEqual(self.api('/intake', conflicting, status=409)['error'], 'conflict')
        self.assertEqual(self.api('/intake/A/1'), original)
        later = {**conflicting, 'revision': '2'}
        self.assertEqual(self.api('/intake', later), {**later, 'available': [0, 8]})
        self.assertEqual(self.api('/intake/A/1'), original)
        self.assertEqual(self.api('/intake/A/2')['origin'], later['origin'])
        self.assertEqual(self.api('/preview_version/R1'), preview)
        self.assertEqual(preview['beats'][1]['contributions'][0]['source_beat'], 5)
        self.assertEqual(self.api('/intake', {**later, 'revision': '3', 'length': True}, status=400)['error'], 'invalid_length')
        self.api('/intake/A/3', status=404)

    def test_v3_overlap_creates_no_version_and_touching_is_valid(self):
        self.cut('R1', 'root', [place('a', 'narration', 'A', [0, 3], 0)])
        parent = self.api('/preview_version/R1')
        failed = self.cut('R2', 'R1', [place('second', 'narration', 'A', [3, 5], 2)], status=400)
        self.assertEqual(failed['error'], 'same_track_overlap')
        self.api('/preview_version/R2', status=404)
        self.assertEqual(self.api('/preview_version/R1'), parent)
        self.cut('R2', 'R1', [place('second', 'narration', 'A', [3, 5], 3),
                              place('b', 'translation', 'B', [0, 2], 2)])
        rows = self.api('/preview_version/R2')['beats']
        self.assertEqual([[v['slot'] for v in row['contributions']] for row in rows],
                         [['a'], ['a'], ['a', 'b'], ['second', 'b'], ['second']])

    def test_v3_invalid_source_or_track_rejects_entire_batch(self):
        valid = place('first', 'narration', 'A', [0, 1], 0)
        invalid = [
            (place('bad', 'translation', 'A', [5, 7], 1), 400, 'invalid_window'),
            (place('bad', 'other', 'B', [0, 1], 1), 400, 'invalid_track'),
            (place('bad', 'translation', 'missing', [0, 1], 1), 404, 'unknown_recording'),
            (place('bad', 'translation', 'B', [0, 1], True), 400, 'invalid_position'),
        ]
        for operation, status, code in invalid:
            with self.subTest(code=code):
                self.assertEqual(self.cut('R1', 'root', [valid, operation], status=status)['error'], code)
                self.api('/preview_version/R1', status=404)
        self.assertEqual(self.api('/preview_version/root')['beats'], [])
        self.assertEqual(self.cut('R1', 'root', [valid])['length'], 1)
