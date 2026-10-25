"""Descriptive Z42 pilot diagnostics; no intervals, fitting, or provider access.

Input contract, schema 1:
* manifest['pairs']: all 360 precommitted rows with pair_id, task_id,
  family_id (nonempty strings), hop (2/3/4), repeat (1/2/3), window_id,
  arm_order (['Q', 'F*'] or its reverse). This validates panel geometry,
  not the provenance of the manifest or its calendar; the executor owns that.
* observations: at most one row per (pair_id, arm), arm Q/F*. Required:
  status complete/F01/partial/not_started, known_cost_usd, reserved_cost_usd.
  Complete/F01 also require em (0/1), f1 (0..1), configuration (string),
  selection_seconds (nonnegative). F01 requires error and em=f1=0.
  Partial/not_started outcomes are null/absent, never zero imputed.
  Complete/F01 costs are final (no outstanding reserves). F* is C01.
  Absent slots are reported as not_started. Additional JSON metadata such as
  timestamps, request IDs and cost provenance is preserved, not certified.
* denominator_assessment: optional overall/hop_2/hop_3/hop_4 mapping to
  {'status': 'sufficient'|'weak'|'unassessed', 'reason': nonempty string}.
  Z40 does not specify a numerical weak-denominator cutoff. The calculator
  therefore invents none: positive but unassessed denominators block planning.
* process_initializations: optional records {process_id, window_id, seconds};
  initialization is separate from per-selection timing, not amortized away.

For partial data the primary means average each task's observed complete
repeats, then tasks equally. Raw pair sample variances are explicitly separate;
their n-1 denominator does not assert independence. Full panel planning uses
only overall and the three prespecified hops. Currency is USD, times seconds.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import copy
import math
from numbers import Real
from statistics import fmean, variance
from typing import Any


ARMS = ('Q', 'F*')
STATUSES = ('complete', 'F01', 'partial', 'not_started')
TERMINAL = ('complete', 'F01')
HOP_TASK_COUNTS = {2: 68, 3: 34, 4: 18}
FIXED_R = (0.8, 0.9, 1.0)
METRICS = ('em_Q', 'em_F', 'f1_Q', 'f1_F', 'D', 'A', 'B',
           'selection_Q_seconds', 'selection_F_seconds')
V_W_R5 = 0.90**2 * 1.03125 * (3.25 * 1.0027 / 0.991**2 - 1)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must be a nonempty string')
    return value


def _number(value: Any, field: str, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{field} must be a finite nonnegative number')
    value = float(value)
    if not math.isfinite(value) or value < 0 or (upper is not None and value > upper):
        raise ValueError(f'{field} must be finite and in the permitted range')
    return value


def _manifest_rows(manifest: dict) -> list[dict]:
    rows = copy.deepcopy(manifest.get('pairs'))
    if not isinstance(rows, list) or len(rows) != 360:
        raise ValueError('manifest must contain exactly 360 precommitted pairs')
    seen, task_meta, repeats, windows = set(), {}, defaultdict(set), defaultdict(list)
    for row in rows:
        for name in ('pair_id', 'task_id', 'family_id', 'window_id'):
            _text(row.get(name), name)
        if row['pair_id'] in seen:
            raise ValueError('duplicate pair_id')
        seen.add(row['pair_id'])
        hop, repeat = row.get('hop'), row.get('repeat')
        if type(hop) is not int or hop not in HOP_TASK_COUNTS:
            raise ValueError('hop must be 2, 3 or 4')
        if type(repeat) is not int or repeat not in (1, 2, 3):
            raise ValueError('repeat must be 1, 2 or 3')
        if row.get('arm_order') not in (['Q', 'F*'], ['F*', 'Q']):
            raise ValueError('arm_order must contain Q and F* exactly once')
        task = row['task_id']
        meta = (row['family_id'], hop)
        if task in task_meta and task_meta[task] != meta:
            raise ValueError('task family/hop changed across repeats')
        task_meta[task] = meta
        if repeat in repeats[task]:
            raise ValueError('duplicate task repetition')
        repeats[task].add(repeat)
        windows[row['window_id']].append(row)
    if len(task_meta) != 120 or len({v[0] for v in task_meta.values()}) != 80:
        raise ValueError('manifest must contain 120 tasks in 80 families')
    if Counter(v[1] for v in task_meta.values()) != HOP_TASK_COUNTS:
        raise ValueError('manifest hop counts must be 68/34/18')
    if any(v != {1, 2, 3} for v in repeats.values()):
        raise ValueError('every task needs three precommitted repeats')
    if len(windows) != 12:
        raise ValueError('manifest needs twelve windows')
    for values in windows.values():
        if len(values) != 30 or len({v['repeat'] for v in values}) != 1:
            raise ValueError('each window needs 30 pairs from one repetition')
        if Counter(v['arm_order'][0] for v in values) != {'Q': 15, 'F*': 15}:
            raise ValueError('each window needs 15/15 first-arm positions')
    return rows


def _slots(rows: list[dict], observations: list[dict]) -> list[dict]:
    pairs = {r['pair_id']: r for r in rows}
    observed = {}
    for raw in observations:
        row = copy.deepcopy(raw)
        key = (row.get('pair_id'), row.get('arm'))
        if key[0] not in pairs or key[1] not in ARMS or key in observed:
            raise ValueError('unknown or duplicate observed slot')
        status = row.get('status')
        if status not in STATUSES:
            raise ValueError('invalid slot status')
        for name in ('known_cost_usd', 'reserved_cost_usd'):
            row[name] = _number(row.get(name), name)
        if status in TERMINAL:
            if row['reserved_cost_usd'] != 0:
                raise ValueError('a complete outcome cannot have unresolved cost reserves')
            if type(row.get('em')) is not int or row['em'] not in (0, 1):
                raise ValueError('complete em must be 0 or 1')
            row['f1'] = _number(row.get('f1'), 'f1', 1)
            row['selection_seconds'] = _number(row.get('selection_seconds'), 'selection_seconds')
            _text(row.get('configuration'), 'configuration')
            if row['arm'] == 'F*' and row['configuration'] != 'C01':
                raise ValueError('F* configuration must remain C01')
            if status == 'F01':
                if row['em'] != 0 or row['f1'] != 0:
                    raise ValueError('known F01 must have em=f1=0')
                _text(row.get('error'), 'F01 error')
        else:
            if row.get('em') is not None or row.get('f1') is not None:
                raise ValueError('an incomplete slot must not contribute outcome scores')
            row['em'], row['f1'] = None, None
            if row.get('selection_seconds') is not None:
                row['selection_seconds'] = _number(row['selection_seconds'], 'selection_seconds')
            if status == 'not_started' and (row['known_cost_usd'] or row['reserved_cost_usd']):
                raise ValueError('not_started cannot contain execution cost or reserves')
        observed[key] = row
    result = []
    for pair in rows:
        for position, arm in enumerate(pair['arm_order'], 1):
            key = (pair['pair_id'], arm)
            slot = observed.get(key, {
                'pair_id': key[0], 'arm': arm, 'status': 'not_started',
                'known_cost_usd': 0.0, 'reserved_cost_usd': 0.0,
                'em': None, 'f1': None, 'selection_seconds': None,
                'configuration': None, 'observation_present': False,
            })
            slot.setdefault('observation_present', True)
            slot.update({name: pair[name] for name in ('task_id', 'family_id', 'hop', 'repeat', 'window_id')})
            slot['arm_position'] = position
            result.append(slot)
    return result


def _sample(values: list[float]) -> dict:
    n = len(values)
    try:
        sample_variance = variance(values) if n > 1 else None
    except OverflowError:
        sample_variance = None
    return {'n': n, 'variance_denominator': n - 1 if n > 1 else None,
            'mean': fmean(values) if n else None,
            'sample_variance': sample_variance,
            'variance_status': 'available' if sample_variance is not None else
                               ('fewer_than_two' if n < 2 else 'numerically_unrepresentable'),
            'minimum': min(values) if n else None,
            'maximum': max(values) if n else None}


def _covariance(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2:
        return None
    ma, mb = fmean(a), fmean(b)
    try:
        result = math.fsum((x - ma) * (y - mb) for x, y in zip(a, b)) / (len(a) - 1)
        return result if math.isfinite(result) else None
    except (OverflowError, ValueError):
        return None


def _ratio(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    result = a / b
    return result if math.isfinite(result) else None


def _influences(pairs: list[dict], mean_b: float | None) -> dict:
    if not mean_b or len(pairs) < 2:
        return {'status': 'nonpositive_reference_mean' if pairs and not mean_b else 'fewer_than_two_pairs',
                'values': []}
    rho = _ratio(fmean(p['A'] for p in pairs), mean_b)
    if rho is None:
        return {'status': 'numerically_unrepresentable_ratio', 'values': []}
    rs = list(FIXED_R)
    if rho < FIXED_R[0] or rho > FIXED_R[-1]:
        rs.append(rho)
    values = []
    for r in rs:
        # Scaling before squaring avoids an artificial underflow of mean(B)^2.
        scaled = [p['A'] / mean_b - r * (p['B'] / mean_b) for p in pairs]
        if not all(math.isfinite(value) for value in scaled):
            return {'status': 'numerically_unrepresentable_influence', 'values': values}
        try:
            v_w = variance(scaled)
        except OverflowError:
            return {'status': 'numerically_unrepresentable_variance', 'values': values}
        values.append({'r': r, 'source': 'fixed' if r in FIXED_R else 'observed_outside_fixed_range',
                       'v_W': v_w, 'pair_count': len(pairs),
                       'variance_denominator': len(pairs) - 1, 'reference_mean_usd': mean_b})
    return {'status': 'descriptive_only', 'values': values}


def _view(pairs: list[dict], expected: list[dict]) -> dict:
    by_task = defaultdict(list)
    for row in pairs:
        by_task[row['task_id']].append(row)
    task_means, within = [], {name: [] for name in METRICS}
    for task, values in sorted(by_task.items()):
        means = {name: fmean(row[name] for row in values) for name in METRICS}
        variances = {name: _sample([row[name] for row in values])['sample_variance']
                     for name in METRICS}
        task_means.append({'task_id': task, 'observed_complete_repeats': len(values),
                           'repeats': sorted(row['repeat'] for row in values),
                           'within_variance_denominator': len(values) - 1 if len(values) > 1 else None,
                           'means': means, 'within_sample_variances': variances})
        for name, value in variances.items():
            if value is not None:
                within[name].append(value)
    means = {name: fmean(row['means'][name] for row in task_means) if task_means else None
             for name in METRICS}
    pair_samples = {name: _sample([row[name] for row in pairs]) for name in METRICS}
    mean_b = pair_samples['B']['mean']
    return {
        'expected_pairs': len(expected), 'complete_pairs': len(pairs),
        'expected_tasks': len({p['task_id'] for p in expected}), 'observed_tasks': len(by_task),
        'status': 'complete' if len(pairs) == len(expected) else 'partial_descriptive',
        'weighting': 'equal tasks; equal observed complete repetitions within each task',
        'equal_task_means': means,
        'ratio_of_equal_task_cost_means': _ratio(means['A'], means['B']),
        'D_counts': {str(d): sum(row['D'] == d for row in pairs) for d in (-1, 0, 1)},
        'q_equal_task': fmean(fmean(row['D'] != 0 for row in values) for values in by_task.values()) if pairs else None,
        'raw_pair_sample': pair_samples,
        'raw_pair_cost_covariance': _covariance([p['A'] for p in pairs], [p['B'] for p in pairs]),
        'raw_pair_ratio_of_cost_means': _ratio(pair_samples['A']['mean'], mean_b),
        'raw_pair_influence': _influences(pairs, mean_b),
        'task_repetition_details': task_means,
        'mean_within_task_sample_variances': {
            name: {'value': fmean(values) if values else None, 'tasks_with_at_least_two_repeats': len(values)}
            for name, values in within.items()},
        'between_task_means': {name: _sample([row['means'][name] for row in task_means]) for name in METRICS},
        'selected_configurations': {arm: dict(sorted(Counter(p['configuration_' + arm] for p in pairs).items())) for arm in ARMS},
    }


def _precision(v_d: float, v_w: float) -> dict:
    quality_m = 1.96**2 * v_d / 0.015**2
    cost_m = 1.96**2 * v_w / 0.05**2
    quantities = {'v_D': v_d, 'v_W': v_w, 'quality_m_unrounded': quality_m,
                  'cost_m_unrounded': cost_m}
    if not all(math.isfinite(value) for value in quantities.values()):
        return {'status': 'numerically_unrepresentable_precision',
                **{name: value if math.isfinite(value) else None for name, value in quantities.items()}}
    m = math.ceil(max(quality_m, cost_m))
    return {'v_D': v_d, 'v_W': v_w, 'quality_m_unrounded': quality_m,
            'cost_m_unrounded': cost_m, 'm_precision': m,
            'h_D_orientation': 1.96 * math.sqrt(v_d / m) if m else 0.0,
            'h_rho_orientation': 1.96 * math.sqrt(v_w / m) if m else 0.0}


def _original_stress_sensitivities() -> dict:
    """Analytic moments of the fixed Z32 §6 cases; no simulated observations."""
    cases = [('R1', -.03, .8), ('R2', 0., .9), ('R3', -.03, .9),
             ('R4', -.03, .9), ('R5', -.03, .9), ('R6', -.04, .8),
             ('R7', 0., 1.), ('R8', 0., .8)]
    result = {}
    for name, delta, rho in cases:
        p_plus = .005 if name == 'R4' else .1
        q = 2 * p_plus - delta
        v_d = q - delta**2
        ev2 = 3.25 if name == 'R5' else 1.02
        et2 = (1 + .6 * delta + .09 * q) / (1 + .3 * delta)**2
        v_w = rho**2 * 1.03125 * (ev2 * et2 - 1)
        result[name] = {'source': 'analytic Z32 section 6; not pilot or new evaluation',
                        'delta': delta, 'rho': rho, **_precision(v_d, v_w)}
    return result


def _planning(views: dict, complete: bool, assessment: dict | None) -> dict:
    scope = {'overall': views['overall'], **{'hop_' + h: v for h, v in views['hop'].items()}}
    base = {'scope': list(scope), 'status': 'partial_no_planning',
            'limitations': 'Normal approximation orientation only; no interval, calibration, effect success or study authorization.'}
    if not complete:
        return base
    checks, blockers = {}, []
    assessment = assessment or {}
    if set(assessment) - set(scope):
        raise ValueError('denominator assessment may only name overall and hop_2/hop_3/hop_4')
    for name, view in scope.items():
        raw = assessment.get(name, {'status': 'unassessed', 'reason': 'No external assessment supplied'})
        status = raw.get('status')
        if status not in ('sufficient', 'weak', 'unassessed'):
            raise ValueError('invalid denominator assessment status')
        _text(raw.get('reason'), 'denominator assessment reason')
        mean_b = view['raw_pair_sample']['B']['mean']
        checks[name] = {**raw, 'mean_B_usd': mean_b,
                        'sample_variance_B': view['raw_pair_sample']['B']['sample_variance'],
                        'pair_count': view['complete_pairs']}
        if not mean_b or status != 'sufficient':
            blockers.append(name + ':' + ('nonpositive_mean' if not mean_b else status))
        if view['raw_pair_influence']['status'] != 'descriptive_only':
            blockers.append(name + ':' + view['raw_pair_influence']['status'])
    base['denominator_assessments'] = checks
    if blockers:
        base.update(status='insufficient_reference_denominator', blockers=blockers)
        return base
    q_max = max(v['q_equal_task'] for v in scope.values())
    all_v = [entry['v_W'] for view in scope.values() for entry in view['raw_pair_influence']['values']]
    v_w_max = max(all_v)
    v_d_plan = max(.25, min(1., 2 * q_max))
    v_w_plan = max(V_W_R5, 2 * v_w_max)
    main_orientation = _precision(v_d_plan, v_w_plan)
    if main_orientation.get('status') == 'numerically_unrepresentable_precision':
        base.update(status='insufficient_precision_arithmetic',
                    blockers=['numerically_unrepresentable_precision'],
                    attempted_main_orientation=main_orientation)
        return base
    base.update(status='precision_orientation_only', v_D_plan=v_d_plan, v_W_plan=v_w_plan,
                v_W_R5=V_W_R5,
                R5_formula='0.90^2 * 1.03125 * (3.25 * 1.0027 / 0.991^2 - 1)',
                unmultiplied_max_q=q_max, unmultiplied_max_v_W=v_w_max,
                main_orientation=main_orientation,
                sensitivities={
                    'unmultiplied_maxima': _precision(q_max, v_w_max),
                    'hard_quality_upper_bound': _precision(1., v_w_plan),
                    'each_fixed_planning_view': {
                        name: {'q': view['q_equal_task'], 'orientations': [
                            {'r': entry['r'], 'source': entry['source'], **_precision(view['q_equal_task'], entry['v_W'])}
                            for entry in view['raw_pair_influence']['values']]}
                        for name, view in scope.items()},
                    'original_Z33_R1_R8': _original_stress_sensitivities(),
                })
    return base


def build_diagnostics(manifest: dict, observations: list[dict], *,
                      denominator_assessment: dict | None = None,
                      process_initializations: list[dict] | None = None) -> dict:
    """Return schema-1 JSON-compatible diagnostics from a full planned manifest."""
    rows = _manifest_rows(manifest)
    slots = _slots(rows, observations)
    by_pair = defaultdict(dict)
    for slot in slots:
        by_pair[slot['pair_id']][slot['arm']] = slot
    pairs = []
    for row in rows:
        q, f = (by_pair[row['pair_id']][arm] for arm in ARMS)
        if q['status'] not in TERMINAL or f['status'] not in TERMINAL:
            continue
        pairs.append({**row, 'em_Q': q['em'], 'em_F': f['em'],
                      'f1_Q': q['f1'], 'f1_F': f['f1'], 'D': q['em'] - f['em'],
                      'A': q['known_cost_usd'], 'B': f['known_cost_usd'],
                      'selection_Q_seconds': q['selection_seconds'], 'selection_F_seconds': f['selection_seconds'],
                      'configuration_Q': q['configuration'], 'configuration_F*': f['configuration'],
                      'status_Q': q['status'], 'status_F*': f['status']})
    views = {'overall': _view(pairs, rows)}
    for dimension in ('hop', 'family_id', 'repeat', 'window_id'):
        key = {'family_id': 'family', 'window_id': 'window'}.get(dimension, dimension)
        views[key] = {str(value): _view([p for p in pairs if p[dimension] == value],
                                       [p for p in rows if p[dimension] == value])
                      for value in sorted({p[dimension] for p in rows})}
    views['first_arm'] = {arm: _view([p for p in pairs if p['arm_order'][0] == arm],
                                    [p for p in rows if p['arm_order'][0] == arm]) for arm in ARMS}
    init = copy.deepcopy(process_initializations or [])
    init_keys = set()
    for entry in init:
        key = (_text(entry.get('process_id'), 'process_id'), _text(entry.get('window_id'), 'window_id'))
        if key in init_keys or key[1] not in views['window']:
            raise ValueError('unknown window or duplicate process initialization')
        init_keys.add(key)
        entry['seconds'] = _number(entry.get('seconds'), 'initialization seconds')
    def cost_summary(values):
        return {'known_cost_usd': math.fsum(s['known_cost_usd'] for s in values),
                'reserved_cost_usd': math.fsum(s['reserved_cost_usd'] for s in values),
                'slots': len(values), 'status_counts': {status: sum(s['status'] == status for s in values) for status in STATUSES}}
    counts = {status: sum(s['status'] == status for s in slots) for status in STATUSES}
    return {
        'schema': 1, 'purpose': 'Z42 descriptive pilot diagnostics and conditional Z40 planning orientation',
        'limitations': ['Pilot is neither a uniform Train sample nor a Dev sample.',
                        '360 paired repeats are not 360 independently drawn tasks.',
                        'Group means alone do not establish stability or a shared disturbance.',
                        'Metadata and reported costs require separate executor/provenance review.'],
        'coverage': {'expected_slots': 720, 'expected_pairs': 360, 'expected_tasks': 120,
                     'expected_families': 80, 'expected_repetitions': 3,
                     'slot_status_counts': counts, 'complete_pairs': len(pairs),
                     'observed_complete_tasks': len({p['task_id'] for p in pairs}),
                     'tasks_with_three_complete_repeats': sum(n == 3 for n in Counter(p['task_id'] for p in pairs).values()),
                     'full_panel': len(pairs) == 360},
        'slots': slots, 'complete_pair_rows': pairs, 'views': views,
        'cost_accounting_all_slots': {
            'total': cost_summary(slots),
            'by_arm': {arm: cost_summary([s for s in slots if s['arm'] == arm]) for arm in ARMS},
            'by_status': {status: cost_summary([s for s in slots if s['status'] == status]) for status in STATUSES},
            'by_window': {window: cost_summary([s for s in slots if s['window_id'] == window]) for window in views['window']},
            'F01_known_cost_usd': math.fsum(s['known_cost_usd'] for s in slots if s['status'] == 'F01'),
        },
        'selection_timing_all_observed_slots': {
            arm: {**_sample([s['selection_seconds'] for s in slots if s['arm'] == arm and s.get('selection_seconds') is not None]),
                  'missing_count': sum(s['arm'] == arm and s.get('selection_seconds') is None for s in slots)} for arm in ARMS},
        'process_initializations': {'status': 'reported' if init else 'not_supplied', 'records': init,
                                    'total_seconds': math.fsum(x['seconds'] for x in init) if init else None},
        'planning': _planning(views, len(pairs) == 360, denominator_assessment),
    }
