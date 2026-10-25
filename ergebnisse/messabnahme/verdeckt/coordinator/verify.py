"""Post-disclosure reconciliation, not a further blind review or instrument run."""
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
import hashlib
import json
import statistics
import zipfile

ROOT = Path(__file__).resolve().parents[5]
RUN = Path(__file__).resolve().parents[1]
checks = []

def read(path):
    return json.loads(path.read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def check(name, observed, expected):
    checks.append({'check': name, 'pass': observed == expected,
                   'observed': observed, 'expected': expected})

def records(base, rows, label):
    for row in rows:
        check(label + ':' + row['path'], sha(base / row['path']), row['sha256'])

def archived(manifest, base):
    d = read(manifest)
    archive = manifest.parent / d['archive']
    check(str(manifest) + ':archive', sha(archive), d['archive_sha256'])
    records(base, d['files'], str(manifest))
    with zipfile.ZipFile(archive) as z:
        for row in d['files']:
            check(str(manifest) + ':member:' + row['path'],
                  hashlib.sha256(z.read(row['path'])).hexdigest(), row['sha256'])

def main():
    # Every source/input was archived before this reconciliation was executed.
    own = read(RUN / 'coordinator/source-manifest.json')
    records(ROOT, own['files'], 'coordinator pre-run')
    check('coordinator archive', sha(RUN / 'coordinator/source-001.zip'), own['archive_sha256'])
    expected = {
        'private/answer-key.json': '32ff0a79d298c97359aa18e6f39689a6499e293e55605d5420e420293a879e0e',
        'reviewer/view1-review.json': '783b536471c8a070a2d904aaa42878df428a58e922c0eb1b9a44ae5decfb2bef',
        'reviewer/view2-review.json': '184547b81b9221355bf9ffc2fbf4994a06e24fa682ed15b886fb99f683290e34',
        'reviewer/view3-review.json': '41ab6badcdc5e59ace416465dc63b00b8e4026a8579789aae375b7e509269167',
        'reviewer/view3-hashreceipt.json': '9be0fab063fa11428dee1b2e25a6cacdd44f7e2f38ffda52cf5af74e6d67b665',
        'instrument/RESULTS.json': 'eb75afe79814b6416eff1acb9f471fa0a6cb0ec8917b8091d0f5c6efdd1a7341',
    }
    records(RUN, [{'path': k, 'sha256': v} for k, v in expected.items()], 'frozen handoffs')
    archived(RUN / 'private/source-manifest.json', ROOT)
    archived(RUN / 'private/truth-manifest.json', RUN / 'private')
    archived(RUN / 'instrument/source-manifest.json', ROOT)
    records(RUN, read(RUN / 'PUBLIC-MANIFEST.json')['files'], 'public data')
    stamps = []
    for stage in (1, 2, 3):
        receipt = read(RUN / f'reviewer/view{stage}-hashreceipt.json')
        records(RUN, receipt.get('inputs', receipt.get('input_files', [])), f'S{stage} inputs')
        records(RUN, receipt['outputs'], f'S{stage} outputs')
        stamps.append(receipt['frozen_at_utc'])
    check('ordered stage freezes', stamps, sorted(set(stamps)))
    key = read(RUN / 'private/answer-key.json')
    reference = {r['case_id']: r for r in read(RUN / 'reviewer/view3-reconstruction-v2-output.json')['cases']}
    review = {r['case_id']: r for r in read(RUN / 'reviewer/view3-review.json')['cases']}
    instrument = {r['case_id']: r for r in read(RUN / 'instrument/RESULTS.json')['cases']}
    ids = sorted(r['case_id'] for r in key['cases'])
    check('twelve unique IDs', len(set(ids)), 12)
    check('exact classes', sorted(r['class'] for r in key['cases']),
          ['K1', 'K2', 'K3', 'K4', 'V1', 'V2', 'V3', 'V4', 'V5', 'V6', 'V7', 'V8'])
    for group in (reference, review, instrument):
        check('same case inventory', sorted(group), ids)
    comparisons = []
    for truth in key['cases']:
        identity = truth['case_id']
        ref, rev, ins, native = reference[identity], review[identity], instrument[identity], truth['native_truth']
        for target, source in [('inner_started', 'started_inner_calls'),
                               ('inner_returned_including_model_failure', 'known_inner_calls'),
                               ('inner_technical_errors', 'unresolved_inner_calls')]:
            check(identity + ':' + target, ref['counts'][target], native[source])
        for target, source in [('reconstructed_status', 'true_status'), ('reconstructed_answer', 'true_answer')]:
            check(identity + ':' + target, ref[target], truth[source])
        check(identity + ':subtotal', Decimal(ref['known_subtotal_usd']), Decimal(native['known_cost_subtotal_usd']))
        check(identity + ':total', None if ref['total_usd'] is None else Decimal(ref['total_usd']),
              None if native['total_cost_usd'] is None else Decimal(native['total_cost_usd']))
        check(identity + ':review status', rev['actual_status'], truth['true_status'])
        check(identity + ':review answer', rev['actual_answer'], truth['true_answer'])
        for output, expected_field in [('trace', 'trace_accepted'), ('journal', 'journal_accepted')]:
            check(identity + ':' + output + ' acceptance', ins[output]['accepted'], truth['expected_instrument'][expected_field])
        check(identity + ':prefix mode', ins['trace']['partial_mode'], truth['expected_instrument']['partial'])
        # Map only outer calls to the creator's outer-message truth; do not treat
        # an unrecorded inner call as the allowed predecessor for later calls.
        messages = {r['call_id']: r['actual_prior_messages'] for r in ref['actual_messages']}
        mapped = sorted(ref['full_request_model_body_matches'], key=lambda r: r['outer_ordinal'])
        check(identity + ':outer message count', len(mapped), truth['observed_request_count'])
        for row, prior in zip(mapped, truth['actual_transferred_prior_messages']):
            check(identity + ':actual messages:' + row['call_id'], messages[row['call_id']],
                  [{k: m[k] for k in ('role', 'round', 'text')} for m in prior])
            check(identity + ':body:' + row['call_id'], row['request_and_entire_model_body_equal'], True)
        check(identity + ':final contract verdict', rev['case_contract'].split()[0],
              'begründet' if truth['class'].startswith('K') else 'kontradiziert')
        comparisons.append({'case_id': identity, 'class': truth['class'], 'truth': native,
                            'instrument': {'trace_accepted': ins['trace']['accepted'],
                                           'journal_accepted': ins['journal']['accepted']},
                            'independent_contract_verdict': rev['case_contract'],
                            'evidence': rev['evidence']})
    costs = read(RUN / 'private/generation-001/cost-sheet-truth.json')
    observed = {r['id']: r for r in read(RUN / 'private/generation-001/cost-sheet-production.json')}
    reconstructed = {r['id']: r for r in read(RUN / 'reviewer/view3-review.json')['cost_sheet']['rows']}
    for row in costs:
        amount = row['cost_usd']
        check('cost sheet reference:' + row['id'], reconstructed[row['id']]['amount_usd'], amount)
        if row['id'] in observed:
            check('cost sheet production:' + row['id'], observed[row['id']]['result']['cost_usd'], amount)
    overhead = read(RUN / 'private/generation-001/overhead.json')
    check('twenty overhead pairs', len(overhead['results']), 20)
    differences = []
    for row in overhead['results']:
        n = row['pair']
        check(f'pair {n}:order', row['order'], ['without', 'with'] if n % 2 else ['with', 'without'])
        folder = RUN / 'private/generation-001/overhead'
        for name in ('trace.json', 'observed_requests.jsonl', 'client.jsonl'):
            check(f'pair {n}:{name}', (folder / f'{n:02d}-without' / name).read_bytes(),
                  (folder / f'{n:02d}-with' / name).read_bytes())
        check(f'pair {n}:journal bytes', (folder / f'{n:02d}-with/journal.jsonl').stat().st_size,
              row['measurements']['with']['journal_bytes'])
        difference = row['measurements']['with']['wall_ns'] - row['measurements']['without']['wall_ns']
        check(f'pair {n}:difference', difference, row['difference_ns'])
        differences.append(difference)
    overhead_summary = {'median': statistics.median(differences), 'minimum': min(differences), 'maximum': max(differences)}
    check('overhead summary', overhead_summary, overhead['difference_ns'])
    failed = [r for r in checks if not r['pass']]
    # Byte equality is retained as its result, avoiding duplication of large raw traces.
    for r in checks:
        for k in ('observed', 'expected'):
            if isinstance(r[k], bytes):
                r[k] = {'bytes': len(r[k]), 'sha256': hashlib.sha256(r[k]).hexdigest()}
    result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'role': 'Coordinator after S3 freeze and answer-key disclosure; not blind',
              'checks': len(checks), 'failures': len(failed), 'failure_details': failed,
              'comparisons': sorted(comparisons, key=lambda x: x['class']),
              'overhead_difference_ns': overhead_summary, 'all_checks': checks,
              'limits': 'Finite artificial cases; no real tariff, statistical or effect acceptance.'}
    destination = RUN / 'coordinator/RESULTS-001.json'
    with destination.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        f.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k not in ('all_checks', 'comparisons')}, ensure_ascii=False, default=str))
    if failed:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
