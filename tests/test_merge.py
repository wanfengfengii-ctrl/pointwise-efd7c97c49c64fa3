"""Business assertions for the dual-proof merge interface (MERGING.md)."""
from tests import ServiceCase, move, place, remove, trim
from examples.merge_inputs import build


NARRATION_BEATS = lambda preview: {  # noqa: E731 - small test helper
    row['beat']: [(v['occurrence_id'], v['source_beat']) for v in row['contributions']]
    for row in preview['beats']
    if row['contributions']
}


def option_id(candidate, kind, action, occurrence_id):
    for conflict in candidate['conflicts']:
        if conflict['kind'] != kind:
            continue
        for option in conflict['options']:
            if option['action'] == action and option['occurrence_id'] == occurrence_id:
                return option['id']
    raise AssertionError(f'missing option {kind}/{action}/{occurrence_id}: {candidate["conflicts"]}')


def options_for(candidate, kind):
    for conflict in candidate['conflicts']:
        if conflict['kind'] == kind:
            return conflict['options']
    raise AssertionError(f'missing {kind} conflict: {candidate["conflicts"]}')


def placement_map(candidate):
    return {item['occurrence_id']: item for item in candidate['placements']}


class MergeSampleTests(ServiceCase):
    TRIPLE = {'parent': 'P', 'left': 'L', 'right': 'R'}

    def setUp(self):
        super().setUp()
        build(self.base)

    def preview(self, triple=None, status=200):
        return self.api('/merge_preview', triple or self.TRIPLE, status=status)

    def confirm(self, version, state, choice, *, triple=None, status=200):
        payload = {'version': version, 'state': state, 'choice': choice, **(triple or self.TRIPLE)}
        return self.api('/merge_confirm', payload, status=status)

    def test_initial_candidate_accepts_single_side_changes_and_reports_collision(self):
        candidate = self.preview()
        self.assertTrue(candidate['state'])
        self.assertEqual({k: candidate[k] for k in ('parent', 'left', 'right')}, self.TRIPLE)
        placements = placement_map(candidate)
        self.assertEqual(placements['P:1']['source'], [1, 4])
        self.assertEqual(placements['P:1']['at'], 5)  # R trim + L shift compose to [5,8)
        self.assertEqual((placements['L:2']['at'], placements['L:2']['source']), (1, [4, 6]))
        self.assertEqual((placements['R:2']['at'], placements['R:2']['source']), (6, [4, 6]))

        overlap = [c for c in candidate['conflicts'] if c['kind'] == 'overlap']
        self.assertEqual(len(overlap), 1)
        conflict = overlap[0]
        self.assertEqual((conflict['track'], conflict['window']), ('narration', [6, 8]))
        self.assertEqual({x['occurrence_id'] for x in conflict['candidates']}, {'P:1', 'R:2'})
        views = {x['occurrence_id']: x for x in conflict['candidates']}
        p1 = views['P:1']
        self.assertEqual(set(p1), {'occurrence_id', 'parent', 'left', 'right', 'current'})
        self.assertEqual((p1['parent']['at'], p1['parent']['source']), (0, [0, 4]))
        self.assertEqual((p1['left']['at'], p1['left']['source']), (4, [0, 4]))
        self.assertEqual((p1['right']['at'], p1['right']['source']), (1, [1, 4]))
        self.assertEqual((p1['current']['at'], p1['current']['source']), (5, [1, 4]))
        actions = {(o['occurrence_id'], o['action']) for o in conflict['options']}
        self.assertEqual(actions, {('P:1', 'withdraw_move'), ('R:2', 'withdraw_add')})

    def test_two_round_adjudication_freezes_reviewable_merge_and_origin(self):
        first_candidate = self.preview()
        withdraw_move = option_id(first_candidate, 'overlap', 'withdraw_move', 'P:1')
        moved_back = self.confirm('M', first_candidate['state'], withdraw_move, status=409)

        placements = placement_map(moved_back)
        self.assertEqual((placements['P:1']['at'], placements['P:1']['source']), (1, [1, 4]))
        overlap = [c for c in moved_back['conflicts'] if c['kind'] == 'overlap']
        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0]['window'], [1, 3])
        self.assertEqual(overlap[0]['track'], 'narration')
        self.assertEqual({x['occurrence_id'] for x in overlap[0]['candidates']}, {'P:1', 'L:2'})
        # Move is no longer effective, so only the added c can be withdrawn.
        self.assertEqual([(o['occurrence_id'], o['action']) for o in overlap[0]['options']],
                         [('L:2', 'withdraw_add')])

        # Target number stays free (and unpreviewable) until the final freeze.
        self.api('/preview_version/M', status=404)

        # A first-round option is not usable on the updated candidate.
        stale_b = option_id(first_candidate, 'overlap', 'withdraw_add', 'R:2')
        bad = self.confirm('M', moved_back['state'], stale_b, status=400)
        self.assertIn('error', bad)

        withdraw_c = option_id(moved_back, 'overlap', 'withdraw_add', 'L:2')
        header = self.confirm('M', moved_back['state'], withdraw_c, status=200)
        self.assertEqual(header, {'version': 'M', 'parent': 'P', 'length': 8,
                                 'tracks': ['narration', 'translation'], 'preview_id': 'preview-M'})

        beats = NARRATION_BEATS(self.api('/preview_version/M'))
        self.assertEqual(
            {beat: voices for beat, voices in beats.items()},
            {1: [('P:1', 1)], 2: [('P:1', 2)], 3: [('P:1', 3)],
             6: [('R:2', 4)], 7: [('R:2', 5)]},
        )
        self.assertEqual(self.api('/merge_origin/M'),
                         {'version': 'M', 'parent': 'P', 'left': 'L', 'right': 'R'})

        # Frozen merge feeds the ordinary review/issue pipeline.
        order = self.order('merge-listen', 'M', [1, 4])
        self.assertEqual([row['beat'] for row in order['playlist']['beats']], [1, 2, 3])
        self.assertEqual(
            [[v['occurrence_id'], v['source_beat']] for row in order['playlist']['beats'] for v in row['contributions']],
            [['P:1', 1], ['P:1', 2], ['P:1', 3]],
        )
        self.decide('merge-approved', 'merge-listen')
        self.assertEqual(self.api('/coverage/M')['pending'], [[6, 8]])
        blocked = self.issue('merge-issue', 'M', status=409)
        self.assertEqual(blocked['pending'], [[6, 8]])
        self.listen('tail-listen', 'M', [6, 8])
        issued = self.issue('merge-issue', 'M')
        self.assertEqual(issued['status'], 'issued')

        # Reopen: version, origin and issuance all survive.
        self.reopen()
        self.assertEqual(self.api('/merge_origin/M'),
                         {'version': 'M', 'parent': 'P', 'left': 'L', 'right': 'R'})
        self.assertEqual(self.issue('merge-issue', 'M'), issued)

    def test_route_two_withdraw_b_keeps_c_and_shifted_a(self):
        candidate = self.preview()
        withdraw_b = option_id(candidate, 'overlap', 'withdraw_add', 'R:2')
        header = self.confirm('N', candidate['state'], withdraw_b, status=200)
        self.assertEqual(header['length'], 8)
        beats = NARRATION_BEATS(self.api('/preview_version/N'))
        self.assertEqual(beats[1], [('L:2', 4)])
        self.assertEqual(beats[2], [('L:2', 5)])
        self.assertEqual({beat: beats[beat] for beat in (5, 6, 7)},
                         {5: [('P:1', 1)], 6: [('P:1', 2)], 7: [('P:1', 3)]})

    def test_duplicate_target_and_replay_return_409(self):
        candidate = self.preview()
        move = option_id(candidate, 'overlap', 'withdraw_move', 'P:1')
        updated = self.confirm('DUP', candidate['state'], move, status=409)
        c_option = option_id(updated, 'overlap', 'withdraw_add', 'L:2')
        payload_state = updated['state']
        self.confirm('DUP', payload_state, c_option, status=200)
        replay = self.confirm('DUP', payload_state, c_option, status=409)
        self.assertEqual(replay['error'], 'conflict')

    def test_misbound_state_and_bad_lineage_are_400(self):
        plr = self.preview()
        pl2r = {'parent': 'P', 'left': 'L2', 'right': 'R'}
        bad = self.confirm('ZB', plr['state'], None, triple=pl2r, status=400)
        self.assertIn('error', bad)
        # The correctly bound P/L2/R candidate still works.
        self.preview(pl2r)

        self.api('/merge_preview', {'parent': 'P', 'left': 'L', 'right': 'L'}, status=400)
        self.api('/merge_preview', {'parent': 'L', 'left': 'P', 'right': 'R'}, status=400)
        self.cut('G', 'L', [])
        self.api('/merge_preview', {'parent': 'P', 'left': 'G', 'right': 'R'}, status=400)
        self.api('/merge_preview', {'parent': 'P', 'left': 'L', 'right': 'missing'}, status=404)
        self.confirm('ZZ', 'not-a-real-state', None, status=400)

    def test_merge_origin_unknown_and_ordinary_are_404(self):
        self.api('/merge_origin/missing', status=404)
        self.api('/merge_origin/P', status=404)


class ReusedSlotMergeTests(ServiceCase):
    def setUp(self):
        super().setUp()
        build(self.base)

    def test_reused_slot_is_two_identities_and_reports_slot_conflict(self):
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'L2', 'right': 'R'})
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['existence'])
        placements = placement_map(candidate)
        self.assertNotIn('P:1', placements)
        self.assertIn('L2:2', placements)
        self.assertIn('R:2', placements)

        keep_right = option_id(candidate, 'existence', 'keep_right', 'P:1')
        decided = self.api('/merge_confirm', {
            'parent': 'P', 'left': 'L2', 'right': 'R', 'version': 'RS',
            'state': candidate['state'], 'choice': keep_right,
        }, status=409)

        slot_conflicts = [c for c in decided['conflicts'] if c['kind'] == 'slot']
        self.assertEqual(len(slot_conflicts), 1)
        self.assertEqual(slot_conflicts[0]['slot'], 'a')
        self.assertEqual({x['occurrence_id'] for x in slot_conflicts[0]['candidates']},
                         {'P:1', 'L2:2'})
        slot_options = options_for(decided, 'slot')
        self.assertEqual([(o['occurrence_id'], o['action']) for o in slot_options],
                         [('L2:2', 'withdraw_add')])

        withdraw_new = option_id(decided, 'slot', 'withdraw_add', 'L2:2')
        header = self.api('/merge_confirm', {
            'parent': 'P', 'left': 'L2', 'right': 'R', 'version': 'RS',
            'state': decided['state'], 'choice': withdraw_new,
        }, status=200)
        self.assertEqual(header['parent'], 'P')
        beats = NARRATION_BEATS(self.api('/preview_version/RS'))
        self.assertEqual({1: beats[1], 2: beats[2], 3: beats[3], 6: beats[6], 7: beats[7]},
                         {1: [('P:1', 1)], 2: [('P:1', 2)], 3: [('P:1', 3)],
                          6: [('R:2', 4)], 7: [('R:2', 5)]})
        self.assertEqual(self.api('/merge_origin/RS')['left'], 'L2')


class MergeSemanticsTests(ServiceCase):
    def _base_with_a(self, version='P'):
        self.cut(version, 'root', [place('a', 'narration', 'A', [0, 4], 0)])

    def _merge_freeze(self, parent, left, right, target, choice=None, status=200):
        candidate = self.api('/merge_preview', {'parent': parent, 'left': left, 'right': right})
        return self.api('/merge_confirm', {
            'parent': parent, 'left': left, 'right': right, 'version': target,
            'state': candidate['state'], 'choice': choice,
        }, status=status)

    def test_clean_merge_accepts_null_choice(self):
        self._base_with_a()
        self.cut('CL', 'P', [move('a', 4), place('c', 'narration', 'A', [0, 2], 8)])
        self.cut('CR', 'P', [place('z', 'narration', 'A', [0, 1], 10)])
        header = self._merge_freeze('P', 'CL', 'CR', 'CLEAN', None)
        self.assertEqual(header['length'], 11)

    def test_trim_disagreement_chooses_side(self):
        self._base_with_a()
        self.cut('TL', 'P', [trim('a', [0, 2])])
        self.cut('TR', 'P', [trim('a', [2, 4])])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'TL', 'right': 'TR'})
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['trim'])
        choice = option_id(candidate, 'trim', 'keep_left', 'P:1')
        self._merge_freeze('P', 'TL', 'TR', 'TRIMM', choice)
        beats = NARRATION_BEATS(self.api('/preview_version/TRIMM'))
        self.assertEqual({b: v for b, v in beats.items()}, {0: [('P:1', 0)], 1: [('P:1', 1)]})

    def test_move_disagreement_chooses_side(self):
        self._base_with_a()
        self.cut('ML', 'P', [move('a', 2)])
        self.cut('MR', 'P', [move('a', 4)])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'ML', 'right': 'MR'})
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['move'])
        choice = option_id(candidate, 'move', 'keep_right', 'P:1')
        self._merge_freeze('P', 'ML', 'MR', 'MOVEM', choice)
        beats = NARRATION_BEATS(self.api('/preview_version/MOVEM'))
        self.assertEqual(sorted(beats), [4, 5, 6, 7])

    def test_trim_and_move_choices_compose_and_preserve_decisions(self):
        self._base_with_a()
        # Left keeps source [0,2) and shifts offset to 3; right keeps [2,4) offset 4.
        self.cut('XL', 'P', [trim('a', [0, 2]), move('a', 3)])
        self.cut('XR', 'P', [trim('a', [2, 4]), move('a', 6)])
        triple = {'parent': 'P', 'left': 'XL', 'right': 'XR'}
        candidate = self.api('/merge_preview', triple)
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['trim', 'move'])

        trim_left = option_id(candidate, 'trim', 'keep_left', 'P:1')
        still_move = self.confirm_generic(triple, 'COMP', candidate['state'], trim_left, status=409)
        self.assertEqual([c['kind'] for c in still_move['conflicts']], ['move'])
        move_right = option_id(still_move, 'move', 'keep_right', 'P:1')
        self.confirm_generic(triple, 'COMP', still_move['state'], move_right, status=200)
        beats = NARRATION_BEATS(self.api('/preview_version/COMP'))
        # Chosen trim [0,2) with chosen right offset d=4 lands at [4,6).
        self.assertEqual(beats, {4: [('P:1', 0)], 5: [('P:1', 1)]})

    def confirm_generic(self, triple, version, state, choice, *, status):
        return self.api('/merge_confirm',
                        {**triple, 'version': version, 'state': state, 'choice': choice},
                        status=status)

    def test_existence_rules(self):
        self._base_with_a()
        self.cut('EL', 'P', [remove('a')])
        self.cut('ER', 'P', [move('a', 6)])

        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'EL', 'right': 'ER'})
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['existence'])
        delete = option_id(candidate, 'existence', 'keep_left', 'P:1')
        self._merge_freeze('P', 'EL', 'ER', 'EXD', delete)
        self.assertEqual(NARRATION_BEATS(self.api('/preview_version/EXD')), {})

        keep = option_id(candidate, 'existence', 'keep_right', 'P:1')
        self._merge_freeze('P', 'EL', 'ER', 'EXK', keep)
        self.assertEqual(sorted(NARRATION_BEATS(self.api('/preview_version/EXK'))), [6, 7, 8, 9])

        # One side deletes, other untouched: deletion is accepted without a conflict.
        self.cut('UU', 'P', [])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'UU', 'right': 'EL'})
        self.assertEqual(candidate['conflicts'], [])
        self.assertNotIn('P:1', placement_map(candidate))

    def test_two_adds_share_slot_name_conflict(self):
        self.cut('EP', 'root', [place('z', 'narration', 'A', [0, 1], 10)])
        self.cut('AL', 'EP', [place('x', 'narration', 'A', [0, 2], 0)])
        self.cut('AR', 'EP', [place('x', 'narration', 'A', [2, 4], 4)])
        candidate = self.api('/merge_preview', {'parent': 'EP', 'left': 'AL', 'right': 'AR'})
        slot = [c for c in candidate['conflicts'] if c['kind'] == 'slot']
        self.assertEqual(len(slot), 1)
        self.assertEqual(slot[0]['slot'], 'x')
        self.assertEqual(len(slot[0]['candidates']), 2)
        self.assertEqual({o['action'] for o in slot[0]['options']}, {'withdraw_add'})
        withdraw = slot[0]['options'][0]['id']
        header = self.api('/merge_confirm', {
            'parent': 'EP', 'left': 'AL', 'right': 'AR', 'version': 'SX',
            'state': candidate['state'], 'choice': withdraw,
        })
        self.assertEqual(header['parent'], 'EP')
        preview = self.api('/preview_version/SX')
        audible_slots = {v['slot'] for row in preview['beats'] for v in row['contributions']}
        self.assertIn('x', audible_slots)
        self.assertIn('z', audible_slots)

    def test_identical_changes_and_both_delete_need_no_choice(self):
        self._base_with_a()
        self.cut('IL', 'P', [trim('a', [1, 3]), move('a', 5)])
        self.cut('IR', 'P', [trim('a', [1, 3]), move('a', 5)])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'IL', 'right': 'IR'})
        self.assertEqual(candidate['conflicts'], [])
        p1 = next(p for p in candidate['placements'] if p['occurrence_id'] == 'P:1')
        self.assertEqual((p1['source'], p1['at']), ([1, 3], 5))

        self.cut('DL', 'P', [remove('a')])
        self.cut('DR', 'P', [remove('a')])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'DL', 'right': 'DR'})
        self.assertEqual(candidate['conflicts'], [])
        self.assertFalse(any(p['occurrence_id'] == 'P:1' for p in candidate['placements']))
        header = self.api('/merge_confirm', {
            'parent': 'P', 'left': 'DL', 'right': 'DR', 'version': 'BDEL',
            'state': candidate['state'], 'choice': None,
        })
        self.assertEqual(header['length'], 0)

    def test_landing_offset_compares_same_source_beats_across_disjoint_windows(self):
        self._base_with_a()
        # Different retained windows, but both shifts move parent beats by +4.
        self.cut('SL', 'P', [trim('a', [0, 2]), move('a', 4)])
        self.cut('SR', 'P', [trim('a', [2, 4]), move('a', 6)])
        candidate = self.api('/merge_preview', {'parent': 'P', 'left': 'SL', 'right': 'SR'})
        self.assertEqual([c['kind'] for c in candidate['conflicts']], ['trim'])

    def test_cross_track_overlap_and_touching_are_legal(self):
        self.cut('TP', 'root', [place('a', 'narration', 'A', [0, 2], 0),
                                place('b', 'translation', 'B', [0, 2], 0)])
        # Translation moves one beat so the tracks mix; still legal.
        self.cut('TL2', 'TP', [move('b', 1)])
        self.cut('TR2', 'TP', [])
        candidate = self.api('/merge_preview', {'parent': 'TP', 'left': 'TL2', 'right': 'TR2'})
        self.assertEqual(candidate['conflicts'], [])
        header = self.api('/merge_confirm', {
            'parent': 'TP', 'left': 'TL2', 'right': 'TR2', 'version': 'TMIX',
            'state': candidate['state'], 'choice': None,
        })
        self.assertEqual(header['length'], 3)

        # Same-track head-tail touching is legal too.
        self.cut('HP', 'root', [place('a', 'narration', 'A', [0, 2], 0)])
        self.cut('HL', 'HP', [place('c', 'narration', 'A', [2, 4], 2)])
        self.cut('HR', 'HP', [])
        candidate = self.api('/merge_preview', {'parent': 'HP', 'left': 'HL', 'right': 'HR'})
        self.assertEqual(candidate['conflicts'], [])


class MergeHttpShapeTests(ServiceCase):
    def test_preview_requires_object_fields_and_unknown_route_still_404(self):
        self.api('/merge_preview', {'parent': 'P'}, status=400)
        # Existing endpoints remain intact.
        self.api('/preview_version/nope', status=404)
        unknown = self.api('/totally_unknown', status=404)
        self.assertEqual(unknown['error'], 'unknown_route')
