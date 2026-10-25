"""Create-only Z14 calibration; all values synthetic, one fresh paired run/task."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import zipfile
import numpy as np
import scipy
from .cluster_intervals import candidate_intervals
from .finite_uncertainty_validation import ROOT, ARTIFACT, INPUT, INPUT_SHA, structure

SEED = 20260907014
DRAWS = 2000
SCENARIOS = {
    'boundary_independent': (-.03, .90, .30, 0., False),
    'boundary_shared': (-.03, .90, .30, .5, False),
    'boundary_rare_skew': (-.03, .90, .04, .5, True),
    'quality_boundary': (-.03, .75, .04, .5, True),
    'cost_boundary': (0., .90, .30, .5, True),
    'favorable': (0., .75, .30, .5, False),
    'quality_violation': (-.05, .75, .15, .5, False),
    'cost_violation': (0., 1., .30, .5, False),
    'few_families': (-.03, .90, .30, .5, False),
    'global_shared': (-.03, .90, .30, .5, False),
}


def cases():
    return [(name, n) for name in SCENARIOS for n in ((1500,) if name in ('few_families', 'global_shared') else (800, 1500, 2277))]


def make_population(name, sizes):
    delta, ratio, discordance, shared, skewed = SCENARIOS[name]
    if name == 'few_families':
        sizes = np.bincount(np.arange(len(sizes)) % 12, weights=sizes).astype(int)
    types = np.arange(len(sizes)) % 3
    labels = np.repeat(np.arange(len(sizes)), sizes)
    weights = np.bincount(types, weights=sizes, minlength=3)
    shifts = (np.arange(3) - np.average(np.arange(3), weights=weights)) * .002
    differences = delta + shifts
    probabilities = np.stack(((discordance - differences) / 2,
                               np.full(3, (1 - discordance) / 2),
                               np.full(3, (1 - discordance) / 2),
                               (discordance + differences) / 2), axis=1)
    if np.any(probabilities < 0) or not np.allclose(probabilities.sum(axis=1), 1):
        raise ValueError('invalid synthetic probabilities')
    costs = np.array([[15., 4.], [.5, 1.], [.8, 1.1], [30., 50.]]) if skewed else np.array([[1.1, 1.4], [.7, 1.], [1., 1.2], [1.4, 1.8]])
    values = np.empty((3, 4, 3))
    for typ in range(3):
        values[typ, :, 0] = [-1, 0, 0, 1]
        values[typ, :, 1:] = costs * (1 + .3 * typ)
    means = np.einsum('ts,tsk->tk', probabilities, values)
    overall = np.average(means, weights=weights, axis=0)
    values[:, :, 1] *= ratio * overall[2] / overall[1]
    means = np.einsum('ts,tsk->tk', probabilities, values)
    overall = np.average(means, weights=weights, axis=0)
    if abs(overall[0] - delta) > 1e-12 or abs(overall[1] / overall[2] - ratio) > 1e-12:
        raise ValueError('synthetic targets disagree')
    return dict(name=name, labels=labels, types=types, probabilities=probabilities, values=values,
                mean=overall, delta=delta, ratio=ratio, shared=shared, global_shared=name == 'global_shared')


def simulate(pop, n, seed):
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(pop['labels']), n, replace=False)
    labels = pop['labels'][selected]; types = pop['types'][labels]
    groups = 1 if pop['global_shared'] else len(pop['types'])
    common = rng.random(groups) < pop['shared']; common_u = rng.random(groups)
    independent_u = rng.random(n)
    selection = np.zeros(n, dtype=int) if pop['global_shared'] else labels
    u = np.where(common[selection], common_u[selection], independent_u)
    cdf = np.cumsum(pop['probabilities'][types], axis=1)
    states = (u[:, None] > cdf[:, :-1]).sum(axis=1)
    return pop['values'][types, states], labels


def trial(pop, n, seed):
    x, labels = simulate(pop, n, seed)
    result = candidate_intervals(x, labels, len(pop['labels']))
    result['quality_miss'] = bool(result['quality_lower'] > pop['delta'])
    result['cost_miss'] = bool(result['cost_upper'] is not None and result['cost_upper'] < pop['ratio'])
    return result


def binomial(count, total):
    p = count / total; z = 1.959963984540054
    den = 1 + z * z / total
    center = (p + z * z / (2 * total)) / den
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / den
    return dict(count=count, total=total, rate=p, mc_se=math.sqrt(p * (1 - p) / total),
                wilson_lower=max(0., center - half), wilson_upper=min(1., center + half))


def summarize(rows, pop):
    quality = binomial(sum(r['quality_miss'] for r in rows), len(rows))
    cost = binomial(sum(r['cost_miss'] for r in rows), len(rows))
    informative_quality = [r for r in rows if r['quality_reason'] == 'finite_candidate']
    finite_cost = [r for r in rows if r['cost_upper'] is not None]
    checks = {key: rate['wilson_lower'] <= .025 and rate['wilson_upper'] <= .04 for key, rate in [('quality', quality), ('cost', cost)]}
    return dict(quality_miss=quality, cost_miss=cost,
                joint_pass=binomial(sum(r['candidate_joint_pass'] for r in rows), len(rows)),
                quality_uninformative=binomial(len(rows) - len(informative_quality), len(rows)),
                cost_unbounded=binomial(len(rows) - len(finite_cost), len(rows)),
                quality_mean_distance=float(np.mean([r['mean'][0] - r['quality_lower'] for r in rows])),
                cost_mean_distance_finite=None if not finite_cost else float(np.mean([r['cost_upper'] - r['mean'][1] / r['mean'][2] for r in finite_cost])),
                mean_bias=(np.mean([r['mean'] for r in rows], axis=0) - pop['mean']).tolist(),
                min_families=min(r['families'] for r in rows), max_families=max(r['families'] for r in rows),
                calibration_checks=checks, calibration_passed=all(checks.values()))


def source_bundle(folder):
    files = sorted(set((ARTIFACT / 'communication_pruning').glob('*.py')) |
                   set((ARTIFACT / 'tests').glob('*.py')) |
                   {ROOT / 'project/dsr/Z14-PLAN.md', INPUT, ARTIFACT / 'README.md',
                    ARTIFACT / 'runs/Z13-SIM-001/receipt.json'})
    hashes = {}
    with zipfile.ZipFile(folder / 'source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            data = path.read_bytes(); name = str(path.relative_to(ROOT))
            hashes[name] = sha256(data).hexdigest(); bundle.writestr(name, data)
        bundle.writestr('Z14-runtime-requirements.txt', f'numpy=={np.__version__}\nscipy=={scipy.__version__}\n')
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); args = parser.parse_args()
    if not args.run.isdigit(): parser.error('numeric run ID required')
    folder = ARTIFACT / 'runs' / ('Z14-SIM-' + args.run); folder.mkdir(mode=0o700, exist_ok=False)
    now = lambda: datetime.now(timezone.utc).isoformat()
    hashes = source_bundle(folder)
    receipt = dict(run_id=folder.name, started_at=now(), status='running', command=sys.argv,
                   python=sys.version, executable=sys.executable, numpy=np.__version__, scipy=scipy.__version__,
                   pythonpath=os.environ.get('PYTHONPATH', ''), master_seed=SEED, draws=DRAWS,
                   runtime_requirements_sha256=sha256(f'numpy=={np.__version__}\nscipy=={scipy.__version__}\n'.encode()).hexdigest(),
                   model_cost_usd='0', input_sha256=INPUT_SHA, files_sha256=hashes,
                   source_bundle_sha256=sha256((folder / 'source.zip').read_bytes()).hexdigest(),
                   tests=[], results=[], study_approved=False)
    try:
        for command in ([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                        [sys.executable, '-m', 'communication_pruning'],
                        [sys.executable, '-m', 'communication_pruning.demo']):
            run = subprocess.run(command, cwd=ARTIFACT, capture_output=True, text=True, timeout=180)
            receipt['tests'].append(dict(command=command, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
        if any(t['returncode'] for t in receipt['tests']): raise RuntimeError('regression failure; retained output in receipt')
        sizes = structure()
        with (folder / 'trials.jsonl').open('x') as out:
            for case, (name, n) in enumerate(cases()):
                pop = make_population(name, sizes); rows = []
                for i in range(DRAWS):
                    seed = SEED * 10**10 + case * 10**5 + i
                    row = dict(case=case, scenario=name, n=n, index=i, seed=seed, **trial(pop, n, seed))
                    rows.append(row); out.write(json.dumps(row, allow_nan=False) + '\n')
                result = dict(case=case, scenario=name, n=n, control=name in ('few_families', 'global_shared'),
                              target_mean=pop['mean'].tolist(), delta=pop['delta'], ratio=pop['ratio'],
                              probabilities=pop['probabilities'].tolist(), values=pop['values'].tolist(), **summarize(rows, pop))
                receipt['results'].append(result)
                print(json.dumps({k: result[k] for k in ('case', 'scenario', 'n', 'calibration_passed')}), flush=True)
        regular = [r for r in receipt['results'] if not r['control']]
        receipt['candidate_verdict'] = 'retain_for_offline_only' if all(r['calibration_passed'] for r in regular) else 'reject_general_use'
        few = next(r for r in receipt['results'] if r['scenario'] == 'few_families')
        receipt['few_family_guard_passed'] = few['joint_pass']['count'] == 0 and few['quality_uninformative']['rate'] == 1 and few['cost_unbounded']['rate'] == 1
        receipt['status'] = 'completed' if receipt['few_family_guard_passed'] else 'failed_control'
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__, error=str(error)); raise
    finally:
        receipt['source_unchanged'] = all(sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        if not receipt['source_unchanged']: receipt['status'] = 'failed_source_changed'
        raw = folder / 'trials.jsonl'
        if raw.exists(): receipt['trials_sha256'] = sha256(raw.read_bytes()).hexdigest()
        receipt['finished_at'] = now()
        with (folder / 'receipt.json').open('x') as out: json.dump(receipt, out, indent=2, allow_nan=False); out.write('\n')
    print(json.dumps({k: receipt[k] for k in ('run_id', 'status', 'candidate_verdict')}))
    if receipt['status'] != 'completed': raise SystemExit(1)


if __name__ == '__main__':
    main()
