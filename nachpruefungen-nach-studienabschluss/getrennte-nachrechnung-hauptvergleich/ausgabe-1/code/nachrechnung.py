#!/opt/anaconda3/bin/python
import csv
import decimal
import hashlib
import json
import math
import platform
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

decimal.getcontext().prec = 60

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'bewertung'))
from metrics.answer import compute_exact, compute_f1, metric_max_over_ground_truths

B = 19999
SEEDS = [
    ('S1', 142211229048427227715370149966446052232),
    ('S2', 25293223086774291045588755186233620233),
]


def read_jsonl(path):
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def canonical_seed(label, binding):
    seed_data = ['Z50-analysis-v1', binding['study_id'], binding['seed_base'], label]
    encoded = json.dumps(seed_data, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return int.from_bytes(hashlib.sha256(encoded).digest()[:16], 'little')


def serial_float(x):
    x = float(x)
    return x if math.isfinite(x) else ('Infinity' if x > 0 else '-Infinity' if x < 0 else 'NaN')


def evaluate_run(row, musique):
    records = read_jsonl(ROOT / row['pfad'])
    headers = [r for r in records if r.get('payload', {}).get('kind') == 'header']
    finished_records = [r for r in records if r.get('payload', {}).get('kind') == 'finished']
    header = headers[0].get('payload', {}).get('trace', {}) if headers else {}
    run_id = header.get('run_id')
    task = header.get('task') or {}
    plaus = []
    if not isinstance(run_id, str) or not run_id.endswith(':' + row['lauf_kennung']):
        plaus.append('run_id endet nicht auf :lauf_kennung')
    entry = musique.get(row['musique_id'])
    if entry is None:
        plaus.append('MuSiQue-ID fehlt im Datensatz')
    elif task.get('question') != entry.get('question'):
        plaus.append('Frage im Protokollkopf weicht vom MuSiQue-Eintrag ab')

    events = [r.get('payload', {}).get('event', {}) for r in records
              if r.get('payload', {}).get('kind') == 'event']
    starts = sum(e.get('kind') == 'started' for e in events)
    known_cost = decimal.Decimal(0)
    unknown_ids = set()
    unknown_without_id = 0
    attempt_started = set()
    attempt_terminal = set()
    for e in events:
        aid = e.get('attempt_id')
        if e.get('kind') == 'started' and aid is not None:
            attempt_started.add(aid)
        if e.get('kind') in ('completed', 'model_failed') and aid is not None:
            attempt_terminal.add(aid)
        if 'usage' in e:
            cost = e['usage'].get('cost_usd')
            if cost is None:
                if aid is None:
                    unknown_without_id += 1
                else:
                    unknown_ids.add(aid)
            else:
                known_cost += decimal.Decimal(str(cost))
        elif aid is None and e.get('kind') == 'started':
            # Without an attempt identifier no later terminal event can
            # establish this start as completed for accounting purposes.
            unknown_without_id += 1
    unknown_ids.update(attempt_started - attempt_terminal)
    unknown = len(unknown_ids) + unknown_without_id

    if not finished_records:
        status, reason, answer = 'nicht_nachrechenbar', 'finished-Nutzlast fehlt', None
    else:
        fin = finished_records[-1].get('payload', {})
        fin_status = fin.get('status')
        if fin_status == 'completed':
            status, reason, answer = 'ok', None, fin.get('answer')
        elif fin_status == 'model_failed':
            status, reason, answer = 'model_failure', None, None
        else:
            status, reason, answer = 'nicht_nachrechenbar', f'finished.status ist {fin_status!r}', None

    em, f1 = 0, 0.0
    if status == 'ok' and isinstance(answer, str) and answer.strip() != '' and entry is not None:
        golds = [entry['answer']] + entry.get('answer_aliases', [])
        em = int(metric_max_over_ground_truths(compute_exact, answer, golds))
        f1 = float(metric_max_over_ground_truths(compute_f1, answer, golds))

    return {
        'paarindex': int(row['paarindex']), 'arm': row['arm'],
        'lauf_kennung': row['lauf_kennung'], 'run_id': run_id,
        'status': status, 'grund': reason, 'endantwort': answer,
        'exact_match': em, 'f1': f1, 'gestartete_aufrufe': starts,
        'bekannte_kosten_usd': format(known_cost, 'f'),
        'unbekannte_betraege': unknown, 'plausibilitaet': plaus,
    }, known_cost


def se_sample(x):
    return float(np.std(x, ddof=1) / np.sqrt(len(x)))


def bootstrap_endpoint(d, cq, cf, theta_delta, theta_ratio, seed, name, binding):
    n = len(d)
    delta_se = se_sample(d)
    cf_mean = float(np.mean(cf))
    cf_se = se_sample(cf)
    cf_quotient = cf_mean / cf_se if cf_se != 0 else math.inf
    rho_se = float(np.std(cq - theta_ratio * cf, ddof=1) / np.sqrt(n) / cf_mean) if cf_mean != 0 else math.inf
    rng = np.random.Generator(np.random.PCG64(seed))
    t_delta = np.empty(B, dtype=np.float64)
    t_ratio = np.empty(B, dtype=np.float64)
    undef_delta = undef_ratio = 0
    bad_delta_reason = bad_ratio_reason = None
    for _ in range(B):
        idx = rng.integers(0, n, size=n)
        ds, qs, fs = d[idx], cq[idx], cf[idx]
        dstar = float(np.mean(ds))
        dse = se_sample(ds)
        if not math.isfinite(dse) or dse == 0:
            undef_delta += 1
            bad_delta_reason = 'se* null oder nicht endlich'
        else:
            t_delta[_] = (dstar - theta_delta) / dse

        denom = float(np.sum(fs))
        if not math.isfinite(denom) or denom <= 0:
            undef_ratio += 1
            bad_ratio_reason = 'Bootstrap-Kostennenner <= 0 oder nicht endlich'
        else:
            rstar = float(np.sum(qs) / denom)
            rse = float(np.std(qs - rstar * fs, ddof=1) / np.sqrt(n) / np.mean(fs))
            if not math.isfinite(rse) or rse == 0:
                undef_ratio += 1
                bad_ratio_reason = 'se* null oder nicht endlich'
            else:
                t_ratio[_] = (rstar - theta_ratio) / rse

    d_bad_original = not math.isfinite(delta_se) or delta_se == 0
    r_bad_original = not math.isfinite(rho_se) or rho_se == 0 or cf_mean <= 0
    d_bad = d_bad_original or undef_delta > 0
    r_bad = r_bad_original or undef_ratio > 0
    if d_bad:
        d_bounds, d_status = (-1.0, 1.0), 'nicht_aussagekraeftig'
        d_reason = 'Original-se null/nicht endlich' if d_bad_original else bad_delta_reason
    else:
        td = np.sort(t_delta)
        d_bounds = (theta_delta - td[19499] * delta_se, theta_delta - td[499] * delta_se)
        d_status, d_reason = 'ok', None
    if r_bad:
        r_bounds, r_status = (0.0, math.inf), 'nicht_aussagekraeftig'
        r_reason = ('Original-se null/nicht endlich oder mittlerer Kostennenner <= 0'
                    if r_bad_original else bad_ratio_reason)
    else:
        tr = np.sort(t_ratio)
        r_bounds = (theta_ratio - tr[19499] * rho_se, theta_ratio - tr[499] * rho_se)
        r_status, r_reason = 'ok', None

    rules = {
        'regel_erfuellt': d_bounds[0] > -0.03 and r_bounds[1] < 0.90,
        'qualitaet_erhalten_3pp': d_bounds[0] > -0.03,
        'ersparnis_10pct_belegt': r_bounds[1] < 0.90,
        'qualitaetsverlust_belegt': d_bounds[1] < 0,
        'verlust_ueber_3pp_belegt': d_bounds[1] < -0.03,
        'ersparnis_10pct_ausgeschlossen': r_bounds[0] > 0.90,
        'mehrkosten_belegt': r_bounds[0] > 1,
        'grenze_nicht_berechenbar': d_status != 'ok' or r_status != 'ok',
    }
    rules['offen_ohne_nachteil'] = (
        not rules['regel_erfuellt'] and not rules['qualitaetsverlust_belegt']
        and not rules['ersparnis_10pct_ausgeschlossen'] and not rules['mehrkosten_belegt']
        and not rules['grenze_nicht_berechenbar']
    )
    rules = {key: bool(value) for key, value in rules.items()}
    mapping = [
        ('regel_erfuellt', 'N0556'), ('offen_ohne_nachteil', 'N0558'),
        ('qualitaetsverlust_belegt', 'N0560'), ('verlust_ueber_3pp_belegt', 'N0562'),
        ('ersparnis_10pct_ausgeschlossen', 'N0564'), ('mehrkosten_belegt', 'N0566'),
        ('grenze_nicht_berechenbar', 'N0568'),
    ]
    table_rows, seen = [], set()
    for key, row in mapping:
        if rules[key] and row not in seen:
            seen.add(row)
            table_rows.append(row)

    return {
        'name': name, 'seed': str(seed), 'wiederholungen': B,
        'seedregel_reproduziert_s1': canonical_seed('P-bootstrap', binding) == SEEDS[0][1],
        'differenz': {'untere': serial_float(d_bounds[0]), 'obere': serial_float(d_bounds[1]),
                      'status': d_status, 'undefinierte_wiederholungen': undef_delta, 'grund': d_reason},
        'verhaeltnis': {'untere': serial_float(r_bounds[0]), 'obere': serial_float(r_bounds[1]),
                        'status': r_status, 'undefinierte_wiederholungen': undef_ratio, 'grund': r_reason},
        'regel_erfuellt': rules['regel_erfuellt'],
        'lesart': {k: v for k, v in rules.items() if k != 'regel_erfuellt'},
        'zeilen_tabelle_4_5': table_rows,
    }


ROOT = Path(__file__).resolve().parents[2]
binding = json.loads((ROOT / 'plan/ANALYSIS-BINDING.json').read_text(encoding='utf-8'))
assert canonical_seed('P-bootstrap', binding) == SEEDS[0][1]
assert canonical_seed('N-Nachrechnung-2', binding) == SEEDS[1][1]

musique = {}
with (ROOT / 'daten/musique_ans_v1.0_dev.jsonl').open(encoding='utf-8') as f:
    for line in f:
        obj = json.loads(line)
        musique[str(obj['id'])] = obj

rows = []
with (ROOT / 'laufliste.tsv').open(encoding='utf-8', newline='') as f:
    rows.extend(csv.DictReader(f, delimiter='\t'))
rows.sort(key=lambda r: (int(r['paarindex']), 0 if r['arm'] == 'Q' else 1))
assert len(rows) == 18080

out = ROOT / 'ausgabe'
results, costs = [], {}
for row in rows:
    result, cost = evaluate_run(row, musique)
    results.append(result)
    costs[(result['paarindex'], result['arm'])] = cost
with (out / 'laeufe.jsonl').open('w', encoding='utf-8', newline='\n') as f:
    for result in results:
        f.write(json.dumps(result, ensure_ascii=False, allow_nan=False) + '\n')

by_pair = defaultdict(dict)
for result in results:
    by_pair[result['paarindex']][result['arm']] = result
incomplete = [i for i, p in by_pair.items() if any(p[a]['status'] == 'nicht_nachrechenbar' for a in ('Q', 'F'))]
valid_ids = [i for i, p in sorted(by_pair.items()) if all(p[a]['status'] != 'nicht_nachrechenbar' for a in ('Q', 'F'))]
valid_n = len(valid_ids)

pair_counts = {'beide_richtig': 0, 'beide_falsch': 0, 'nur_q': 0, 'nur_f': 0}
D = []
arm_stats = {}
for arm in ('Q', 'F'):
    rs = [by_pair[i][arm] for i in valid_ids]
    cost_sum = sum((costs[(i, arm)] for i in valid_ids), decimal.Decimal(0))
    arm_stats[arm] = {
        'anteil_exakt_richtig': float(np.mean([r['exact_match'] for r in rs])) if rs else 0.0,
        'f1_mittel': float(np.mean([r['f1'] for r in rs])) if rs else 0.0,
        'modellausfaelle': sum(r['status'] == 'model_failure' for r in rs),
        'kosten_summe_usd': format(cost_sum, 'f'),
        'kosten_mittel_usd': format(cost_sum / decimal.Decimal(valid_n), 'f') if valid_n else '0',
        'gestartete_aufrufe_summe': sum(r['gestartete_aufrufe'] for r in rs),
        'unbekannte_betraege': sum(r['unbekannte_betraege'] for r in rs),
    }
for i in valid_ids:
    q, f = by_pair[i]['Q'], by_pair[i]['F']
    if q['exact_match'] and f['exact_match']:
        pair_counts['beide_richtig'] += 1
    elif q['exact_match']:
        pair_counts['nur_q'] += 1
    elif f['exact_match']:
        pair_counts['nur_f'] += 1
    else:
        pair_counts['beide_falsch'] += 1
    D.append(q['exact_match'] - f['exact_match'])
pair_counts['gleich'] = pair_counts['beide_richtig'] + pair_counts['beide_falsch']

D = np.asarray(D, dtype=np.float64)
CQ = np.asarray([float(costs[(i, 'Q')]) for i in valid_ids], dtype=np.float64)
CF = np.asarray([float(costs[(i, 'F')]) for i in valid_ids], dtype=np.float64)
delta = float(np.mean(D)) if valid_n else 0.0
delta_se = se_sample(D) if valid_n > 1 else 0.0
sq = sum((costs[(i, 'Q')] for i in valid_ids), decimal.Decimal(0))
sf = sum((costs[(i, 'F')] for i in valid_ids), decimal.Decimal(0))
rho = float(sq / sf) if sf != 0 else math.inf
cf_mean = float(np.mean(CF)) if valid_n else 0.0
cf_se = se_sample(CF) if valid_n > 1 else 0.0
cf_quot = cf_mean / cf_se if cf_se else math.inf
rho_se = float(np.std(CQ - rho * CF, ddof=1) / np.sqrt(valid_n) / cf_mean) if valid_n > 1 and cf_mean != 0 else math.inf

bootstrap = []
if not incomplete:
    for name, seed in SEEDS:
        bootstrap.append(bootstrap_endpoint(D, CQ, CF, delta, rho, seed, name, binding))
else:
    for name, seed in SEEDS:
        bootstrap.append({'name': name, 'seed': str(seed), 'wiederholungen': B,
                          'seedregel_reproduziert_s1': True,
                          'differenz': {'untere': -1, 'obere': 1, 'status': 'nicht_aussagekraeftig', 'undefinierte_wiederholungen': 0, 'grund': 'unvollständige Rechnung'},
                          'verhaeltnis': {'untere': 0, 'obere': 'Infinity', 'status': 'nicht_aussagekraeftig', 'undefinierte_wiederholungen': 0, 'grund': 'unvollständige Rechnung'},
                          'regel_erfuellt': False, 'lesart': {}, 'zeilen_tabelle_4_5': []})

aggregate = {
    'schema': 'n-nachrechnung-aggregat/v1',
    'n_paare': len(by_pair), 'n_laeufe': len(results), 'vollstaendig': not incomplete,
    'nicht_nachrechenbar': {'laeufe': sum(r['status'] == 'nicht_nachrechenbar' for r in results),
                            'ausgelassene_paare': len(incomplete),
                            'lauf_kennungen': [r['lauf_kennung'] for r in results if r['status'] == 'nicht_nachrechenbar']},
    'paarzahlen': pair_counts, 'summe_paarwerte': pair_counts['nur_q'] - pair_counts['nur_f'],
    'arme': arm_stats,
    'qualitaetsdifferenz': {'schaetzer': serial_float(delta), 'se': serial_float(delta_se)},
    'kostenverhaeltnis': {'schaetzer': serial_float(rho), 'se': serial_float(rho_se),
                          'nenner_mittel': serial_float(cf_mean),
                          'nenner_se': serial_float(cf_se), 'nenner_quotient': serial_float(cf_quot)},
    'bootstrap': bootstrap,
    'umgebung': {'python': sys.version, 'numpy': np.__version__, 'plattform': platform.platform()},
    'festlegungen_ohne_plantext': [],
}
with (out / 'aggregat.json').open('w', encoding='utf-8', newline='\n') as f:
    json.dump(aggregate, f, ensure_ascii=False, indent=2, allow_nan=False)
    f.write('\n')
