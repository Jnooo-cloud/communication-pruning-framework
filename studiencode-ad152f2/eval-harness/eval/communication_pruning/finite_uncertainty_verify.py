"""Separate Z13 receipt audit and selected seed replay, by the same author.

Recomputes scalar moment checks from retained rows without using summarize or
moment_check. RNG replay deliberately uses the generator; it is not an
independent simulation implementation or a person-independent review.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
import sys
import zipfile
from .finite_uncertainty_validation import ARTIFACT, ROOT, SEED, SCENARIOS, population, structure, trial


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run'); parser.add_argument('simulation'); args = parser.parse_args()
    require(args.run.isdigit() and args.simulation.isdigit(), 'numeric run IDs required')
    folder = ARTIFACT / 'runs' / ('Z13-VERIFY-' + args.run); folder.mkdir(mode=0o700, exist_ok=False)
    source = ARTIFACT / 'runs' / ('Z13-SIM-' + args.simulation)
    receipt = dict(run_id=folder.name, simulation=source.name, status='running',
                   started_at=datetime.now(timezone.utc).isoformat(), command=sys.argv,
                   author='Codex, same agent as implementation', model_cost_usd='0')
    paths = sorted(set((ARTIFACT / 'communication_pruning').glob('*.py')) |
                   set((ARTIFACT / 'tests').glob('*.py')) | {ROOT / 'project/dsr/Z13-PLAN.md'})
    hashes = {}
    with zipfile.ZipFile(folder / 'source.zip', 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:
            data = path.read_bytes(); name = str(path.relative_to(ROOT)); hashes[name] = sha256(data).hexdigest()
            bundle.writestr(name, data)
    receipt['files_sha256'] = hashes
    receipt['source_bundle_sha256'] = sha256((folder / 'source.zip').read_bytes()).hexdigest()
    try:
        data = (source / 'receipt.json').read_bytes(); simulation = json.loads(data)
        receipt['simulation_receipt_sha256'] = sha256(data).hexdigest()
        require(simulation['status'] == 'passed', 'simulation did not pass')
        require(sha256((source / 'source.zip').read_bytes()).hexdigest() == simulation['source_bundle_sha256'], 'source ZIP hash')
        with zipfile.ZipFile(source / 'source.zip') as bundle:
            require(set(bundle.namelist()) == set(simulation['files_sha256']), 'source ZIP manifest')
            for name, expected in simulation['files_sha256'].items():
                require(sha256(bundle.read(name)).hexdigest() == expected, 'archived source hash ' + name)
                require(sha256((ROOT / name).read_bytes()).hexdigest() == expected, 'current source hash ' + name)
        data = (source / 'trials.jsonl').read_bytes()
        require(sha256(data).hexdigest() == simulation['trials_sha256'], 'trials hash')
        grouped = defaultdict(list)
        for line in data.splitlines():
            row = json.loads(line); grouped[(row['scenario'], row['n'], row['repeats'])].append(row)
        expected_keys = {(s, n, R) for s in SCENARIOS for n in (800, 1500, 2277) for R in (1, 3)}
        require(set(grouped) == expected_keys, 'exact case inventory')
        require(len(simulation['results']) == 24, '24 receipt results')
        sizes = structure(); checks = 0; replays = 0
        for result in simulation['results']:
            scenario, n, R = result['scenario'], result['n'], result['repeats']
            rows = grouped[(scenario, n, R)]
            require([row['index'] for row in rows] == list(range(1000)), 'complete ordered trial indices')
            for row in rows:
                expected_seed = SEED * 10**12 + SCENARIOS.index(scenario) * 10**10 + n * 10**6 + R * 10**4 + row['index']
                require(row['seed'] == expected_seed, 'seed derivation')
                require((row['covariance_estimate'] is None) == (R == 1), 'single repetition availability')
            for index in (0, 499, 999):
                saved = rows[index]; replay = trial(population(scenario, sizes), n, R, saved['seed'])
                require(all(saved[key] == value for key, value in replay.items()), 'exact RNG replay')
                replays += 1
            for k in range(3):
                vectors = [( [r['mean'][k] for r in rows], result['oracle']['mean'][k])]
                for l in range(k, 3):
                    vectors.append(([(r['mean'][k] - result['oracle']['mean'][k]) *
                                     (r['mean'][l] - result['oracle']['mean'][l]) for r in rows],
                                    result['oracle']['total'][k][l]))
                    if R >= 2:
                        vectors.append(([r['covariance_estimate'][k][l] for r in rows], result['oracle']['total'][k][l]))
                for values, target in vectors:
                    error = abs(statistics.mean(values) - target)
                    require(error <= 5 * statistics.stdev(values) / math.sqrt(len(values)) + 1e-12, 'scalar Monte Carlo criterion')
                    checks += 1
        receipt.update(status='passed', cases=len(grouped), trials=sum(map(len, grouped.values())),
                       scalar_checks=checks, exact_seed_replays=replays)
    except Exception as error:
        receipt.update(status='failed', error_type=type(error).__name__, error=str(error)); raise
    finally:
        receipt['source_unchanged'] = all(sha256((ROOT / name).read_bytes()).hexdigest() == value for name, value in hashes.items())
        if not receipt['source_unchanged']:
            receipt['status'] = 'failed_source_changed'
        receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
        with (folder / 'receipt.json').open('x') as out:
            json.dump(receipt, out, indent=2); out.write('\n')
    print(json.dumps({k: receipt[k] for k in ('run_id', 'status', 'cases', 'trials', 'scalar_checks', 'exact_seed_replays')}))
    if receipt['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
