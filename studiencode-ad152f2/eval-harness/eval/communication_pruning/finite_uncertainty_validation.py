"""Create-only Z13 diagnostics with synthetic values; no raw benchmark reads."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import numpy as np
from .finite_uncertainty import covariance_components, repetition_estimate

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / 'eval-harness/eval'
SEED = 20260907013
INPUT = ARTIFACT / 'runs/Z12-STRUCT-001/receipt.json'
INPUT_SHA = '240b43c2dead3e18cbe3d7cc321d3a1b9b879731cbaa297f5099f36cb73b0d24'
SCENARIOS = ('fixed', 'independent', 'family_shared', 'rare_skewed')


def structure():
    data = INPUT.read_bytes()
    if sha256(data).hexdigest() != INPUT_SHA:
        raise ValueError('Z12 structural receipt changed')
    hist = json.loads(data)['inventory']['splits']['dev']['family_size_histogram']
    sizes = np.array([int(m) for m, count in sorted(hist.items(), key=lambda x: int(x[0])) for _ in range(count)])
    if sizes.sum() != 2277 or len(sizes) != 535:
        raise ValueError('unexpected population structure')
    return sizes


def population(scenario, sizes):
    if scenario not in SCENARIOS:
        raise ValueError('unknown scenario')
    types = np.arange(len(sizes)) % 3
    labels = np.repeat(np.arange(len(sizes)), sizes)
    probabilities = np.array([[.20, .30, .30, .20], [.25, .30, .30, .15], [.15, .30, .30, .25]])
    costs = np.array([[1.1, 1.4], [.7, 1.], [1., 1.2], [1.4, 1.8]])
    if scenario == 'rare_skewed':
        probabilities = np.array([[.015, .485, .49, .010], [.020, .48, .49, .010], [.010, .49, .485, .015]])
        costs = np.array([[15., 4.], [.5, 1.], [.8, 1.1], [30., 50.]])
    values = np.empty((3, 4, 3))
    for t in range(3):
        values[t, :, 0] = [-1, 0, 0, 1]
        values[t, :, 1:] = costs * (1 + .3 * t)
    means = np.einsum('ts,tsk->tk', probabilities, values)
    centered = values - means[:, None, :]
    covariances = np.einsum('ts,tsk,tsl->tkl', probabilities, centered, centered)
    shared = .5 if scenario in ('family_shared', 'rare_skewed') else 0.
    W = np.einsum('g,gkl->kl', sizes, covariances[types])
    B = np.einsum('g,gkl->kl', sizes * (sizes - 1) * shared, covariances[types])
    if scenario == 'fixed':
        W *= 0; B *= 0
    return dict(labels=labels, types=types, values=values, probabilities=probabilities,
                means=means[types[labels]], W=W, B=B, shared=shared, fixed=scenario == 'fixed')


def simulate(pop, n, R, seed):
    rng = np.random.default_rng(seed)
    selected = rng.choice(len(pop['labels']), n, replace=False)
    if pop['fixed']:
        return np.repeat(pop['means'][selected][None, :, :], R, axis=0)
    labels = pop['labels'][selected]; types = pop['types'][labels]
    count = len(pop['types'])
    common = rng.random((R, count)) < pop['shared']
    common_u = rng.random((R, count))
    independent_u = rng.random((R, n))
    u = np.where(common[:, labels], common_u[:, labels], independent_u)
    cdf = np.cumsum(pop['probabilities'][types], axis=1)
    states = (u[:, :, None] > cdf[None, :, :-1]).sum(axis=2)
    return pop['values'][types[None, :], states]


def trial(pop, n, R, seed):
    x = simulate(pop, n, R, seed)
    estimate = repetition_estimate(x, len(pop['labels'])) if R >= 2 else None
    return dict(seed=seed, mean=x.mean(axis=(0, 1)).tolist(),
                covariance_estimate=None if estimate is None else estimate['total'].tolist(),
                estimator_status='unavailable_single_repetition' if estimate is None else estimate['status'])


def moment_check(rows, target):
    rows = np.asarray(rows); target = np.asarray(target)
    empirical = rows.mean(axis=0)
    se = rows.std(axis=0, ddof=1) / np.sqrt(len(rows))
    delta = np.abs(empirical - target)
    return dict(empirical=empirical.tolist(), target=target.tolist(), mc_se=se.tolist(),
                passed=bool(np.all(delta <= 5 * se + 1e-12)),
                max_standardized_difference=float(np.max(delta / (se + 1e-12))))


def summarize(rows, oracle):
    means = np.array([row['mean'] for row in rows]); delta = means - oracle['mean']
    result = dict(mean=moment_check(means, oracle['mean']),
                  centered_products=moment_check(np.einsum('ik,il->ikl', delta, delta), oracle['total']),
                  indefinite_estimates=sum(row['estimator_status'] == 'indefinite' for row in rows))
    if rows[0]['covariance_estimate'] is not None:
        result['estimated_covariance'] = moment_check([row['covariance_estimate'] for row in rows], oracle['total'])
    result['passed'] = all(value['passed'] for value in result.values() if isinstance(value, dict))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); args = parser.parse_args()
    if not args.run.isdigit():
        parser.error('numeric run ID required')
    folder = ARTIFACT / 'runs' / ('Z13-SIM-' + args.run)
    folder.mkdir(mode=0o700, exist_ok=False)
    now = lambda: datetime.now(timezone.utc).isoformat()
    files = sorted(set((ARTIFACT / 'communication_pruning').glob('*.py')) |
                   set((ARTIFACT / 'tests').glob('*.py')) |
                   {ROOT / 'project/dsr/Z13-PLAN.md', INPUT, ARTIFACT / 'README.md'})
    hashes = {}
    with zipfile.ZipFile(folder / 'source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            content = path.read_bytes(); name = str(path.relative_to(ROOT))
            hashes[name] = sha256(content).hexdigest(); bundle.writestr(name, content)
    receipt = dict(run_id=folder.name, started_at=now(), status='running', python=sys.version,
                   executable=sys.executable, numpy=np.__version__, command=sys.argv, master_seed=SEED,
                   draws_per_case=1000, model_cost_usd='0', input_sha256=INPUT_SHA,
                   source_bundle_sha256=sha256((folder / 'source.zip').read_bytes()).hexdigest(),
                   files_sha256=hashes, tests=[], results=[], interval_approval=False)
    try:
        for command in ([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                        [sys.executable, '-m', 'communication_pruning'],
                        [sys.executable, '-m', 'communication_pruning.demo']):
            run = subprocess.run(command, cwd=ARTIFACT, capture_output=True, text=True, timeout=180)
            receipt['tests'].append(dict(command=command, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
        if any(row['returncode'] for row in receipt['tests']):
            raise RuntimeError('regression failure; see retained outputs')
        sizes = structure()
        with (folder / 'trials.jsonl').open('x') as raw:
            for s, scenario in enumerate(SCENARIOS):
                pop = population(scenario, sizes)
                for n in (800, 1500, 2277):
                    for R in (1, 3):
                        rows = []
                        for i in range(1000):
                            seed = SEED * 10**12 + s * 10**10 + n * 10**6 + R * 10**4 + i
                            row = dict(scenario=scenario, n=n, repeats=R, index=i, **trial(pop, n, R, seed))
                            rows.append(row); raw.write(json.dumps(row, allow_nan=False) + '\n')
                        oracle = covariance_components(pop['means'], pop['W'], pop['B'], n, R)
                        result = dict(scenario=scenario, n=n, repeats=R, oracle={k: v.tolist() for k, v in oracle.items()},
                                      **summarize(rows, oracle))
                        receipt['results'].append(result)
                        print(json.dumps(dict(scenario=scenario, n=n, repeats=R, passed=result['passed'])), flush=True)
        receipt['status'] = 'passed' if all(r['passed'] for r in receipt['results']) else 'failed_criterion'
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__, error=str(error))
        raise
    finally:
        receipt['source_unchanged'] = all(sha256((ROOT / path).read_bytes()).hexdigest() == value for path, value in hashes.items())
        if not receipt['source_unchanged']:
            receipt['status'] = 'failed_source_changed'
        raw = folder / 'trials.jsonl'
        if raw.exists():
            receipt['trials_sha256'] = sha256(raw.read_bytes()).hexdigest()
        receipt['finished_at'] = now()
        with (folder / 'receipt.json').open('x') as out:
            json.dump(receipt, out, indent=2, allow_nan=False); out.write('\n')
    print(json.dumps(dict(run_id=folder.name, status=receipt['status'])))
    if receipt['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
