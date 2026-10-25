"""Apply the unchanged journal/trace instrument; never reads private expectations."""
from pathlib import Path
import hashlib
import json
import sys
import time

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
EVAL = RUN.parents[1]
sys.path.insert(0, str(EVAL))
from communication_pruning.audit import audit, audit_prefix
from communication_pruning.contracts import Configuration
from communication_pruning.journal import read_journal


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    binding = json.loads((HERE / 'source-manifest.json').read_text())
    root = EVAL.parents[1]
    for item in binding['files']:
        if sha(root / item['path']) != item['sha256']:
            raise RuntimeError('prebound source or input changed: ' + item['path'])
    if sha(HERE / binding['archive']) != binding['archive_sha256']:
        raise RuntimeError('recoverable source archive changed')
    rows = []
    cases = sorted((RUN / 'view1').glob('*/case.json'))
    if len(cases) != 12:
        raise RuntimeError('exactly twelve cases required')
    for case_path in cases:
        case = json.loads(case_path.read_text())
        cid = case['case_id']
        if cid != case_path.parent.name:
            raise RuntimeError('case ID/path mismatch')
        raw = case['expected_config']
        config = Configuration(raw['config_id'], tuple(raw['roles']),
                               tuple(tuple(edge) for edge in raw['edges']))
        folder = RUN / 'view2' / cid
        trace = json.loads((folder / 'trace.json').read_text())
        record = {'case_id': cid, 'source': 'unchanged production trace/journal functions',
                  'external_client_or_tariff_truth_checked': False,
                  'input_hashes': {str(p.relative_to(RUN)): sha(p)
                                   for p in (case_path, folder / 'trace.json', folder / 'journal.jsonl')},
                  'claimed': case.get('claimed')}
        partial = not ('answer' in trace and 'status' in trace)
        started = time.perf_counter_ns()
        try:
            metrics = (audit_prefix if partial else audit)(trace, config)
            record['trace'] = {'accepted': True, 'partial_mode': partial, 'metrics': metrics}
        except Exception as error:
            record['trace'] = {'accepted': False, 'partial_mode': partial,
                               'exception': type(error).__name__, 'message': str(error)}
        try:
            report = read_journal(folder / 'journal.jsonl', config)
            record['journal'] = {'accepted': True, 'sealed': report['sealed'],
                                 'metrics': report['audit'],
                                 'returned_trace_matches_supplied_trace': report['trace'] == trace}
        except Exception as error:
            record['journal'] = {'accepted': False, 'exception': type(error).__name__,
                                 'message': str(error)}
        record['local_audit_ns'] = time.perf_counter_ns() - started
        rows.append(record)
    with (HERE / 'RESULTS.json').open('x') as out:
        json.dump({'cases': rows, 'case_count': len(rows), 'new_model_calls': 0,
                   'claim': 'Instrument outputs only; acceptance needs independent ground truth.'},
                  out, indent=2, ensure_ascii=False, allow_nan=False)
        out.write('\n')
    print(json.dumps({'cases': len(rows), 'results_sha256': sha(HERE / 'RESULTS.json')}, indent=2))


if __name__ == '__main__':
    main()
