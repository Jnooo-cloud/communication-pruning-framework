"""Z14 separate receipt/rate audit and RNG replay by the implementation agent."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from statistics import NormalDist, mean
import sys
import zipfile
from .cluster_interval_validation import ARTIFACT, ROOT, SEED, cases, make_population, structure, trial, source_bundle


def require(value, message):
    if not value: raise ValueError(message)


def rate_reference(values):
    successes = sum(values); n = len(values); p = successes / n; z = NormalDist().inv_cdf(.975)
    denominator = 1 + z ** 2 / n
    center = (p + z ** 2 / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z ** 2 / (4 * n ** 2)) / denominator
    return dict(count=successes, total=n, rate=p, mc_se=math.sqrt(p * (1 - p) / n),
                wilson_lower=max(0., center - radius), wilson_upper=min(1., center + radius))


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); parser.add_argument('simulation'); args = parser.parse_args()
    require(args.run.isdigit() and args.simulation.isdigit(), 'numeric IDs required')
    folder = ARTIFACT / 'runs' / ('Z14-VERIFY-' + args.run); folder.mkdir(mode=0o700, exist_ok=False)
    source = ARTIFACT / 'runs' / ('Z14-SIM-' + args.simulation)
    hashes = source_bundle(folder)
    receipt = dict(run_id=folder.name, simulation=source.name, status='running', command=sys.argv,
                   started_at=datetime.now(timezone.utc).isoformat(), author='Codex; same agent as implementation',
                   files_sha256=hashes, source_bundle_sha256=sha256((folder / 'source.zip').read_bytes()).hexdigest(), model_cost_usd='0')
    try:
        data = (source / 'receipt.json').read_bytes(); sim = json.loads(data)
        receipt['simulation_receipt_sha256'] = sha256(data).hexdigest()
        require(sim['status'] == 'completed', 'simulation not completed')
        require(sha256((source / 'source.zip').read_bytes()).hexdigest() == sim['source_bundle_sha256'], 'source bundle changed')
        with zipfile.ZipFile(source / 'source.zip') as bundle:
            require(set(bundle.namelist()) == set(sim['files_sha256']) | {'Z14-runtime-requirements.txt'}, 'bundle inventory')
            for name, expected in sim['files_sha256'].items():
                require(sha256(bundle.read(name)).hexdigest() == expected, 'archived source hash ' + name)
                require(sha256((ROOT / name).read_bytes()).hexdigest() == expected, 'current source hash ' + name)
            expected = f"numpy=={sim['numpy']}\nscipy=={sim['scipy']}\n".encode()
            require(bundle.read('Z14-runtime-requirements.txt') == expected, 'runtime requirements')
            require(sha256(expected).hexdigest() == sim['runtime_requirements_sha256'], 'runtime requirements hash')
        data = (source / 'trials.jsonl').read_bytes()
        require(sha256(data).hexdigest() == sim['trials_sha256'], 'trial file changed')
        grouped = defaultdict(list)
        for line in data.splitlines():
            row = json.loads(line); grouped[(row['scenario'], row['n'])].append(row)
        require(len(sim['results']) == 26 and len(grouped) == 26 and set(grouped) == set(cases()), 'case inventory')
        sizes = structure(); rate_checks = 0; replays = 0; regular_pass = True
        require(len({(r['scenario'], r['n']) for r in sim['results']}) == 26, 'unique summary cases')
        for result in sim['results']:
            name, n = result['scenario'], result['n']; rows = grouped[(name, n)]
            require([row['index'] for row in rows] == list(range(2000)), 'ordered complete trial indices')
            pop = make_population(name, sizes)
            for row in rows:
                expected_seed = SEED * 10**10 + cases().index((name, n)) * 10**5 + row['index']
                require(row['seed'] == expected_seed, 'seed derivation')
                require(row['quality_miss'] == (row['quality_lower'] > result['delta']), 'quality miss classification')
                require(row['cost_miss'] == (row['cost_upper'] is not None and row['cost_upper'] < result['ratio']), 'cost miss classification')
                require(row['candidate_joint_pass'] == (row['quality_lower'] > -.03 and row['cost_upper'] is not None and row['cost_upper'] < .90), 'strict joint rule')
                require(row['study_approved'] is False, 'no automatic study approval')
            for index in (0, 999, 1999):
                saved = rows[index]; replay = trial(pop, n, saved['seed'])
                require(all(saved[key] == value for key, value in replay.items()), 'exact selected seed replay'); replays += 1
            rates = {
                'quality_miss': [r['quality_miss'] for r in rows],
                'cost_miss': [r['cost_miss'] for r in rows],
                'joint_pass': [r['candidate_joint_pass'] for r in rows],
                'quality_uninformative': [r['quality_reason'] != 'finite_candidate' for r in rows],
                'cost_unbounded': [r['cost_upper'] is None for r in rows],
            }
            references = {}
            for key, values in rates.items():
                ref = rate_reference(values); references[key] = ref
                require(all(abs(ref[k] - result[key][k]) < 1e-12 for k in ref), 'rate/MCSE/Wilson reference ' + key)
                rate_checks += 1
            passed = all(references[k]['wilson_lower'] <= .025 and references[k]['wilson_upper'] <= .04 for k in ('quality_miss', 'cost_miss'))
            require(passed == result['calibration_passed'], 'calibration verdict')
            if not result['control']: regular_pass &= passed
            if name == 'few_families':
                require(all(r['families'] < 30 and not r['candidate_joint_pass'] and r['quality_lower'] == -1 and r['cost_upper'] is None for r in rows), 'few-family gate')
            quality_distance = mean(r['mean'][0] - r['quality_lower'] for r in rows)
            require(abs(quality_distance - result['quality_mean_distance']) < 1e-12, 'quality distance')
            finite = [r for r in rows if r['cost_upper'] is not None]
            if finite:
                distance = mean(r['cost_upper'] - r['mean'][1] / r['mean'][2] for r in finite)
                require(abs(distance - result['cost_mean_distance_finite']) < 1e-12 * max(1., abs(distance)), 'cost distance')
        verdict = 'retain_for_offline_only' if regular_pass else 'reject_general_use'
        require(sim['candidate_verdict'] == verdict, 'overall verdict')
        receipt.update(status='passed', cases=26, trials=sum(map(len, grouped.values())), rate_checks=rate_checks,
                       seed_replays=replays, verified_candidate_verdict=verdict)
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__, error=str(error)); raise
    finally:
        receipt['source_unchanged'] = all(sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        if not receipt['source_unchanged']: receipt['status'] = 'failed_source_changed'
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        with (folder / 'receipt.json').open('x') as out: json.dump(receipt, out, indent=2); out.write('\n')
    print(json.dumps({k: receipt[k] for k in ('run_id', 'status', 'cases', 'trials', 'rate_checks', 'seed_replays', 'verified_candidate_verdict')}))
    if receipt['status'] != 'passed': raise SystemExit(1)


if __name__ == '__main__':
    main()
