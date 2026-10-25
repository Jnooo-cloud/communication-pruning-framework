"""Metadata-only tests of the accepted deterministic R3 continuation."""
from copy import deepcopy
from datetime import datetime, timedelta
from collections import Counter
import unittest

from communication_pruning.data import digest
from communication_pruning.pilot_calendar import make_calendar, require_pair_start, window_interval
from communication_pruning.pilot_continuation_calendar import make_schedule, validate_schedule, section_for_pair
from tests.test_pilot_calendar import fixture


class ContinuationCalendarTests(unittest.TestCase):
    def setUp(self):
        manifest, ids, bindings = fixture()
        self.plan = make_calendar(manifest, ids, bindings=bindings)

    def test_fixed_remaining_mapping_and_no_original_mutation(self):
        original = deepcopy(self.plan)
        schedule = make_schedule(self.plan, acceptance_utc='2026-09-14T11:00:00+00:00',
                                 technical_ready_utc='2026-09-14T11:30:00+00:00')
        self.assertEqual(self.plan, original)
        self.assertEqual(schedule['anchor']['s_utc'], '2026-09-14T14:00:00+00:00')
        self.assertEqual([len(s['pair_ids']) for s in schedule['sections']], [29] + [30] * 11)
        self.assertEqual([p for s in schedule['sections'] for p in s['pair_ids']],
                         [p['pair_id'] for p in self.plan['pairs'][1:]])
        for pair in self.plan['pairs'][1:]:
            self.assertEqual(section_for_pair(schedule, pair['pair_id'])['original_window_id'], pair['window_id'])
        with self.assertRaises(ValueError):
            section_for_pair(schedule, 'P0001')

    def test_anchor_uses_later_prerequisite_and_rounds_once(self):
        for accepted, ready, expected in [('13:30:00', '12:00:00', '14:00:00'),
                                           ('12:00:00', '13:30:00.000001', '16:00:00'),
                                           ('23:45:00', '13:00:00', '02:00:00')]:
            schedule = make_schedule(self.plan, acceptance_utc=f'2026-09-14T{accepted}+00:00',
                                     technical_ready_utc=f'2026-09-14T{ready}+00:00')
            self.assertIn('T' + expected, schedule['anchor']['s_utc'])

    def test_resigned_times_anchor_and_membership_still_rejected(self):
        schedule = make_schedule(self.plan, acceptance_utc='2026-09-14T11:00:00+00:00',
                                 technical_ready_utc='2026-09-14T11:30:00+00:00')
        for mutate in (lambda s: s['sections'][0]['pair_ids'].append('P0001'),
                       lambda s: s['sections'][0].update(start_utc='2026-09-14T12:00:00+00:00'),
                       lambda s: s['anchor'].update(s_utc='2026-09-14T16:00:00+00:00')):
            changed = deepcopy(schedule)
            mutate(changed)
            changed['sha256'] = digest({k: v for k, v in changed.items() if k != 'sha256'})
            with self.assertRaises(ValueError):
                validate_schedule(self.plan, changed)

    def test_strict_pair_start_and_105_minute_end(self):
        schedule = make_schedule(self.plan, acceptance_utc='2026-09-14T11:00:00+00:00',
                                 technical_ready_utc='2026-09-14T11:30:00+00:00')
        first = schedule['sections'][0]
        start, cutoff, end = window_interval(first)
        self.assertEqual(end - start, timedelta(minutes=105))
        self.assertEqual(cutoff - start, timedelta(minutes=75))
        require_pair_start(first, start)
        require_pair_start(first, cutoff - timedelta(microseconds=1))
        for time in (start - timedelta(microseconds=1), cutoff, end):
            with self.assertRaises(ValueError):
                require_pair_start(first, time)
