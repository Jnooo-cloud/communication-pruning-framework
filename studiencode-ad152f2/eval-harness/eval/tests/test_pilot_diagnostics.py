"""Hand-valued synthetic contract checks for Z42; no benchmark input or simulation."""

import copy
import json
import math
import unittest

from communication_pruning.pilot_diagnostics import V_W_R5, build_diagnostics


def manifest():
    """Only invented IDs and the already prescribed panel geometry."""
    pairs = []
    for repeat in (1, 2, 3):
        for task in range(120):
            pairs.append({
                'pair_id': f'synthetic-{task}-{repeat}', 'task_id': f'task-{task}',
                'family_id': f'family-{task % 80}',
                'hop': 2 if task < 68 else (3 if task < 102 else 4),
                'repeat': repeat, 'window_id': f'W{(repeat - 1) * 4 + task // 30 + 1:02}',
                'arm_order': ['Q', 'F*'] if task % 30 < 15 else ['F*', 'Q'],
            })
    return {'pairs': pairs}


def observed(task, repeat, a=1., b=1., eq=0, ef=0):
    return [dict(pair_id=f'synthetic-{task}-{repeat}', arm=arm, status='complete',
                 known_cost_usd=cost, reserved_cost_usd=0., em=em, f1=float(em),
                 selection_seconds=seconds, configuration=config)
            for arm, cost, em, seconds, config in [('Q', a, eq, .2, 'C02'), ('F*', b, ef, .01, 'C01')]]


def full_observations():
    return [slot for repeat in (1, 2, 3) for task in range(120)
            for slot in observed(task, repeat)]


def assessment():
    return {name: {'status': 'sufficient', 'reason': 'Synthetic constant positive reference costs are known.'}
            for name in ('overall', 'hop_2', 'hop_3', 'hop_4')}


class PilotDiagnosticsTests(unittest.TestCase):
    def test_empty_panel_preserves_all_slots_without_planning(self):
        result = build_diagnostics(manifest(), [])
        self.assertEqual(len(result['slots']), 720)
        self.assertEqual(result['coverage']['slot_status_counts']['not_started'], 720)
        self.assertEqual(result['planning']['status'], 'partial_no_planning')
        self.assertNotIn('m_precision', json.dumps(result['planning']))
        self.assertIsNone(result['slots'][0]['em'])
        self.assertIsNone(result['views']['overall']['equal_task_means']['A'])
        self.assertIsNone(result['process_initializations']['total_seconds'])
        self.assertEqual(result['selection_timing_all_observed_slots']['Q']['missing_count'], 360)
        json.dumps(result, allow_nan=False)

    def test_hand_values_pair_variance_covariance_and_equal_task_weighting(self):
        observations = (observed(0, 1, 1, 2, 0, 1) + observed(0, 2, 2, 4, 0, 0)
                        + observed(0, 3, 3, 6, 1, 0) + observed(1, 1, 8, 2, 1, 0))
        result = build_diagnostics(manifest(), observations)
        view = result['views']['overall']
        self.assertEqual(view['D_counts'], {'-1': 1, '0': 1, '1': 2})
        self.assertAlmostEqual(view['equal_task_means']['D'], .5)
        self.assertAlmostEqual(view['equal_task_means']['A'], 5)
        self.assertAlmostEqual(view['equal_task_means']['B'], 3)
        self.assertAlmostEqual(view['q_equal_task'], 5 / 6)
        self.assertAlmostEqual(view['ratio_of_equal_task_cost_means'], 5 / 3)
        self.assertAlmostEqual(view['raw_pair_ratio_of_cost_means'], 1)
        self.assertNotEqual(view['ratio_of_equal_task_cost_means'], (0.5 + 0.5 + 0.5 + 4) / 4)
        self.assertAlmostEqual(view['raw_pair_sample']['D']['sample_variance'], 11 / 12)
        self.assertAlmostEqual(view['raw_pair_sample']['A']['sample_variance'], 29 / 3)
        self.assertAlmostEqual(view['raw_pair_cost_covariance'], -5 / 3)
        influence = next(v for v in view['raw_pair_influence']['values'] if v['r'] == 1)
        self.assertAlmostEqual(influence['v_W'], 200 / 147)
        self.assertEqual(influence['variance_denominator'], 3)
        self.assertEqual(view['mean_within_task_sample_variances']['A'],
                         {'value': 1, 'tasks_with_at_least_two_repeats': 1})
        self.assertEqual(view['between_task_means']['A']['sample_variance'], 18)
        self.assertEqual(view['between_task_means']['A']['variance_denominator'], 1)
        self.assertEqual([x['observed_complete_repeats'] for x in view['task_repetition_details']], [3, 1])
        self.assertEqual(result['views']['repeat']['1']['complete_pairs'], 2)
        self.assertEqual(result['views']['window']['W05']['complete_pairs'], 1)
        self.assertEqual(result['views']['family']['family-0']['complete_pairs'], 3)
        self.assertEqual(result['views']['first_arm']['Q']['complete_pairs'], 4)

    def test_missing_half_is_missing_and_all_failure_costs_remain(self):
        q = observed(0, 1, .03, 1)[0]
        q.update(status='F01', error='known terminal no-answer')
        partial = dict(pair_id='synthetic-1-1', arm='Q', status='partial',
                       known_cost_usd=.02, reserved_cost_usd=.14, error='unknown provider outcome')
        result = build_diagnostics(manifest(), [q, partial])
        self.assertEqual(result['coverage']['complete_pairs'], 0)
        self.assertEqual(result['coverage']['slot_status_counts'],
                         {'complete': 0, 'F01': 1, 'partial': 1, 'not_started': 718})
        self.assertAlmostEqual(result['cost_accounting_all_slots']['total']['known_cost_usd'], .05)
        self.assertAlmostEqual(result['cost_accounting_all_slots']['F01_known_cost_usd'], .03)
        self.assertAlmostEqual(result['cost_accounting_all_slots']['total']['reserved_cost_usd'], .14)
        self.assertEqual(result['slots'][1]['status'], 'not_started')
        self.assertIsNone(result['slots'][1]['em'])
        self.assertEqual(result['slots'][0]['error'], 'known terminal no-answer')

    def test_known_f01_can_complete_a_pair_but_never_hide_its_cost(self):
        values = observed(0, 1, .05, .02, 0, 1)
        values[0].update(status='F01', error='known failure')
        result = build_diagnostics(manifest(), values)
        self.assertEqual(result['coverage']['complete_pairs'], 1)
        self.assertEqual(result['complete_pair_rows'][0]['D'], -1)
        self.assertEqual(result['views']['overall']['equal_task_means']['A'], .05)
        self.assertEqual(result['cost_accounting_all_slots']['F01_known_cost_usd'], .05)

    def test_hop_maximum_uses_four_fixed_views_and_retains_outside_rho(self):
        values = full_observations()
        for slot in values:
            task = int(slot['pair_id'].split('-')[1])
            if slot['arm'] == 'Q':
                slot['known_cost_usd'] = 2. if task != 0 else 50.
                if task >= 102:
                    slot.update(em=1, f1=1.)
        result = build_diagnostics(manifest(), values, denominator_assessment=assessment())
        plan = result['planning']
        self.assertTrue(result['coverage']['full_panel'])
        self.assertEqual(result['coverage']['tasks_with_three_complete_repeats'], 120)
        self.assertEqual(plan['scope'], ['overall', 'hop_2', 'hop_3', 'hop_4'])
        self.assertAlmostEqual(result['views']['overall']['q_equal_task'], .15)
        self.assertEqual(plan['v_D_plan'], 1.)
        scoped = [result['views']['overall'], *result['views']['hop'].values()]
        expected = max(v['v_W'] for view in scoped for v in view['raw_pair_influence']['values'])
        self.assertAlmostEqual(plan['v_W_plan'], max(V_W_R5, 2 * expected))
        family_max = max(v['v_W'] for view in result['views']['family'].values()
                         for v in view['raw_pair_influence']['values'])
        self.assertGreater(family_max, expected)
        for view in scoped:
            influences = view['raw_pair_influence']['values']
            self.assertEqual([v['r'] for v in influences[:3]], [.8, .9, 1.])
            self.assertEqual(influences[3]['source'], 'observed_outside_fixed_range')
        self.assertEqual(plan['main_orientation']['m_precision'],
                         math.ceil(max(1.96**2 / .015**2, 1.96**2 * plan['v_W_plan'] / .05**2)))

    def test_zero_observed_quality_variance_keeps_floor_R5_and_all_sensitivities(self):
        result = build_diagnostics(manifest(), full_observations(), denominator_assessment=assessment())
        plan = result['planning']
        self.assertEqual(plan['v_D_plan'], .25)
        self.assertEqual(plan['unmultiplied_max_q'], 0.)
        self.assertEqual(plan['unmultiplied_max_v_W'], 0.)
        self.assertEqual(plan['v_W_plan'], V_W_R5)
        sens = plan['sensitivities']
        self.assertEqual(sens['hard_quality_upper_bound']['v_D'], 1.)
        self.assertEqual(set(sens['original_Z33_R1_R8']), {f'R{i}' for i in range(1, 9)})
        self.assertAlmostEqual(sens['original_Z33_R1_R8']['R5']['v_W'], V_W_R5)
        self.assertAlmostEqual(sens['original_Z33_R1_R8']['R4']['v_D'], .04 - .03**2)
        self.assertAlmostEqual(sens['original_Z33_R1_R8']['R2']['v_W'], .9**2 * 1.03125 * (1.02 * 1.018 - 1))
        json.dumps(result, allow_nan=False)

    def test_complete_panel_requires_explicit_numerical_denominator_assessment(self):
        result = build_diagnostics(manifest(), full_observations())
        self.assertEqual(result['planning']['status'], 'insufficient_reference_denominator')
        self.assertNotIn('m_precision', json.dumps(result['planning']))
        checks = assessment()
        checks['hop_4'] = {'status': 'weak', 'reason': 'Artificial externally specified weak denominator case.'}
        result = build_diagnostics(manifest(), full_observations(), denominator_assessment=checks)
        self.assertIn('hop_4:weak', result['planning']['blockers'])

    def test_zero_cost_is_valid_observation_but_zero_reference_blocks_planning(self):
        values = full_observations()
        for row in values:
            row['known_cost_usd'] = 0.
        result = build_diagnostics(manifest(), values, denominator_assessment=assessment())
        self.assertTrue(result['coverage']['full_panel'])
        self.assertEqual(result['views']['overall']['equal_task_means']['A'], 0.)
        self.assertIsNone(result['views']['overall']['ratio_of_equal_task_cost_means'])
        self.assertEqual(result['planning']['status'], 'insufficient_reference_denominator')
        self.assertNotIn('m_precision', json.dumps(result['planning']))

    def test_numerically_unrepresentable_ratio_keeps_raw_values_and_blocks_planning(self):
        values = full_observations()
        for row in values:
            row['known_cost_usd'] = 1. if row['arm'] == 'Q' else 1e-320
        result = build_diagnostics(manifest(), values, denominator_assessment=assessment())
        view = result['views']['overall']
        self.assertEqual(view['equal_task_means']['A'], 1.)
        self.assertGreater(view['equal_task_means']['B'], 0.)
        self.assertEqual(view['raw_pair_influence']['status'], 'numerically_unrepresentable_ratio')
        self.assertEqual(result['planning']['status'], 'insufficient_reference_denominator')
        self.assertNotIn('m_precision', json.dumps(result['planning']))
        json.dumps(result, allow_nan=False)

    def test_precision_size_overflow_preserves_full_description_without_any_m(self):
        values = full_observations()
        for row in values:
            row['known_cost_usd'] = 0. if row['arm'] == 'Q' else 1e-154
            if row['arm'] == 'Q' and row['pair_id'] == 'synthetic-102-1':
                row['known_cost_usd'] = 1.
        result = build_diagnostics(manifest(), values, denominator_assessment=assessment())
        self.assertTrue(result['coverage']['full_panel'])
        self.assertEqual(len(result['slots']), 720)
        self.assertEqual(len(result['complete_pair_rows']), 360)
        self.assertAlmostEqual(result['cost_accounting_all_slots']['total']['known_cost_usd'], 1.)
        hop = result['views']['hop']['4']
        self.assertAlmostEqual(hop['equal_task_means']['A'], 1 / 54)
        self.assertEqual(hop['raw_pair_influence']['status'], 'descriptive_only')
        self.assertTrue(all(math.isfinite(v['v_W']) for v in hop['raw_pair_influence']['values']))
        self.assertEqual(result['planning']['status'], 'insufficient_precision_arithmetic')
        self.assertNotIn('m_precision', json.dumps(result['planning']))
        json.dumps(result, allow_nan=False)

    def test_invalid_costs_scores_duplicates_and_unknown_slots_are_rejected(self):
        for value in (-.01, float('nan'), float('inf'), True, None):
            for field in ('known_cost_usd', 'reserved_cost_usd', 'selection_seconds'):
                values = observed(0, 1)
                values[0][field] = value
                with self.subTest(value=value, field=field), self.assertRaises(ValueError):
                    build_diagnostics(manifest(), values)
        values = observed(0, 1)
        for change in ({'status': 'F01', 'em': 1, 'error': 'failure'},
                       {'status': 'partial', 'em': 0}, {'em': True},
                       {'f1': float('nan')}, {'reserved_cost_usd': .14},
                       {'pair_id': 'not-in-plan'}):
            bad = copy.deepcopy(values)
            bad[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                build_diagnostics(manifest(), bad)
        with self.assertRaises(ValueError):
            build_diagnostics(manifest(), values + [values[0]])
        values[1]['configuration'] = 'C02'
        with self.assertRaises(ValueError):
            build_diagnostics(manifest(), values)

    def test_manifest_geometry_is_not_silently_relaxed_for_partial_data(self):
        for mutate in (lambda rows: rows.pop(),
                       lambda rows: rows[0].update(hop=3),
                       lambda rows: rows[0].update(repeat=2),
                       lambda rows: rows[0].update(arm_order=['Q', 'Q']),
                       lambda rows: rows[0].update(window_id='W99')):
            plan = manifest()
            mutate(plan['pairs'])
            with self.assertRaises(ValueError):
                build_diagnostics(plan, [])

    def test_initialization_and_partial_selection_time_remain_separate(self):
        rows = [dict(pair_id='synthetic-0-1', arm='Q', status='partial',
                     known_cost_usd=.01, reserved_cost_usd=.14, selection_seconds=.4)]
        result = build_diagnostics(manifest(), rows, process_initializations=[
            {'process_id': 'synthetic-process', 'window_id': 'W01', 'seconds': 1.5}])
        self.assertEqual(result['selection_timing_all_observed_slots']['Q']['mean'], .4)
        self.assertEqual(result['process_initializations']['total_seconds'], 1.5)
        self.assertEqual(result['views']['overall']['complete_pairs'], 0)


if __name__ == '__main__':
    unittest.main()
