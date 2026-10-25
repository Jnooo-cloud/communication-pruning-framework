"""Finite artificial Q-sem checks; fake encoder checks do not establish real MiniLM Q1."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import math
from pathlib import Path
import tempfile
import unittest

from communication_pruning.contracts import TaskInput
from communication_pruning.evaluation import PlannedTask, RunResult, development_observations
from communication_pruning.selection import CONFIG_IDS, Observation
from communication_pruning.semantic_selection import (
    ALPHAS, DIMENSION, FrozenMiniLM, SemanticSelector, _hash, _matrix, _select_alpha,
    choose_scores, encoder_identity, evaluate_learning_curves, fit_ridge,
    fit_semantic_selector, predict_scores,
)


class ArtificialEncoder:
    """Known unit vectors for synthetic tests, explicitly no pretrained encoder evidence."""
    def __init__(self):
        self.identity = encoder_identity({f: '1' * 64 for f in (
            'config.json', 'tokenizer.json', 'tokenizer_config.json',
            'special_tokens_map.json', 'vocab.txt', 'model.safetensors')},
            {'test_double': True, 'not_real_encoder_evidence': True})
        self.initialization_ns = 0
        self.questions = []

    def encode_questions(self, questions):
        self.questions.extend(questions)
        rows = [[(-1. if q == 'negative' else 1.) / math.sqrt(384)] * 384 for q in questions]
        return rows, {'encoder_ns': 0, 'questions': len(questions),
                      'token_lengths_before_truncation': [1] * len(questions), 'truncated_questions': 0}


def observations(*, reversed_folds=()):
    rows, folds = [], []
    for fold in range(5):
        ids = []
        for positive in (False, True):
            task_id = f'synthetic-{fold}-{int(positive)}'
            task = TaskInput(task_id, 'positive' if positive else 'negative', ('visible context',))
            label = float(positive != (fold in reversed_folds))
            rows.append(Observation(task, f'family-{fold}', 'spatial',
                                    (.7, label) + (0.,) * 12,
                                    (Decimal('2'), Decimal('1')) + (Decimal('3'),) * 12))
            ids.append(task_id)
        folds.append(ids)
    return rows, folds


BINDINGS = {'artificial_matrix': '2' * 64, 'prebound_folds': '3' * 64}


class SemanticSelectionTests(unittest.TestCase):
    def test_scores_unbounded_margin_cost_id_and_invalid(self):
        scores, costs = [2., 1.99] + [-3.] * 12, [Decimal('2'), Decimal('1')] + [Decimal('0')] * 12
        self.assertEqual(choose_scores(scores, costs), 1)
        scores[1] = 1.989
        self.assertEqual(choose_scores(scores, costs), 0)
        self.assertEqual(choose_scores([-2.] * 14, [Decimal('1')] * 14), 0)
        for invalid in ([float('nan')] * 14, [0.] * 13, [True] * 14):
            with self.assertRaises(ValueError):
                choose_scores(invalid, costs)

    def test_alpha_uses_actual_validation_cost_then_larger_alpha(self):
        reports = [{'alpha': 1, 'quality': .8, 'cost_usd': '2'},
                   {'alpha': 10, 'quality': .795, 'cost_usd': '1'},
                   {'alpha': 100, 'quality': .790, 'cost_usd': '1'}]
        self.assertEqual(_select_alpha(reports), 100)
        reports[2]['quality'] = .789
        self.assertEqual(_select_alpha(reports), 10)

    def test_public_inputs_unchanged_and_ids_irrelevant(self):
        encoder = ArtificialEncoder()
        task = TaskInput('first', '  Visible? UnCHanged\n', ('visible context',))
        x, _ = _matrix([task, replace(task, task_id='other')], encoder)
        self.assertEqual(encoder.questions, [task.question, task.question])
        self.assertEqual(x.shape, (2, 388))
        self.assertEqual(x[0].tolist(), x[1].tolist())
        with self.assertRaises(ValueError):
            _matrix([{'question': task.question, 'gold': 'forbidden'}], encoder)

    def test_ridge_independent_closed_form_and_constant_zero(self):
        import numpy as np
        rows, _ = observations()
        rows = rows[:4]
        # One nonconstant coordinate makes a scalar normal equation sufficient as reference.
        x = np.zeros((4, DIMENSION))
        x[:, 0] = [-3., -1., 1., 3.]
        x[:, 1] = .123456789
        for alpha in ALPHAS:
            model = fit_ridge(rows, x, alpha=alpha)
            z = [-3 / math.sqrt(5), -1 / math.sqrt(5), 1 / math.sqrt(5), 3 / math.sqrt(5)]
            for head in range(14):
                y = [r.quality[head] for r in rows]
                intercept = math.fsum(y) / 4
                coefficient = math.fsum(a * (b - intercept) for a, b in zip(z, y)) / (4 + alpha)
                self.assertAlmostEqual(model['coefficients'][head][0], coefficient, places=12)
                self.assertAlmostEqual(model['intercepts'][head], intercept, places=12)
                self.assertEqual(model['coefficients'][head][1], 0.)
            self.assertEqual(model['scale'][1], 1.)
            self.assertTrue(model['constant'][1])
            probe = x.copy()
            probe[:, 1:] = 1e6
            self.assertEqual(predict_scores(model, x), predict_scores(model, probe))

    def test_fixed_alpha_fit_heldout_labels_costs_and_features_do_not_leak(self):
        rows, folds = observations()
        encoder = ArtificialEncoder()
        before = fit_semantic_selector(rows, encoder=encoder, folds=folds, bindings=BINDINGS).to_dict()
        changed = [replace(r, quality=(1.,) * 14, costs=(Decimal('99'),) * 14,
                           task=replace(r.task, paragraphs=('many different heldout words',)))
                   if r.task.task_id in folds[0] else r for r in rows]
        after = fit_semantic_selector(changed, encoder=encoder, folds=folds, bindings=BINDINGS).to_dict()
        for old, new in zip(before['cross_validation'], after['cross_validation']):
            self.assertEqual(old['folds'][0]['model'], new['folds'][0]['model'])
            self.assertNotEqual(old['outcomes'][0]['quality'], new['outcomes'][0]['quality'])
        self.assertEqual(before['model']['training_task_ids'], sorted(r.task.task_id for r in rows))
        self.assertEqual(before['chosen_alpha'], 100)
        self.assertEqual(before['model']['alpha'], 100)

    def test_family_fold_list_rejects_overlap_missing_and_family_split(self):
        rows, folds = observations()
        for wrong in (folds[:-1], folds[:4] + [folds[0]], folds[:4] + [[]]):
            with self.assertRaises(ValueError):
                fit_semantic_selector(rows, encoder=ArtificialEncoder(), folds=wrong, bindings=BINDINGS)
        wrong = deepcopy(folds)
        wrong[0][0], wrong[1][0] = wrong[1][0], wrong[0][0]
        with self.assertRaises(ValueError):
            fit_semantic_selector(rows, encoder=ArtificialEncoder(), folds=wrong, bindings=BINDINGS)
        mapping = {f'family-{i}': i for i in range(5)}
        selector = fit_semantic_selector(rows, encoder=ArtificialEncoder(), folds=mapping, bindings=BINDINGS)
        self.assertEqual(selector.to_dict()['folds'], folds)

    def test_negative_filter_keeps_raw_candidate_and_does_not_force_fixed(self):
        rows, folds = observations(reversed_folds=(3, 4))
        rows = [replace(r, quality=(.59,) + r.quality[1:]) for r in rows]
        selector = fit_semantic_selector(rows, encoder=ArtificialEncoder(), folds=folds, bindings=BINDINGS)
        report = selector.to_dict()
        self.assertFalse(report['diagnosis']['admitted'])
        self.assertEqual(report['diagnosis']['recommended_rule'], 'F_star')
        self.assertTrue(report['diagnosis']['raw_candidate_preserved'])
        self.assertEqual(report['model']['fixed_index'], 0)
        self.assertEqual(selector.select(TaskInput('unseen', 'positive', ('visible context',))), CONFIG_IDS[1])
        self.assertEqual(selector.select(TaskInput('unseen', 'negative', ('visible context',))), CONFIG_IDS[0])

    def test_constant_raw_candidate_is_valid_and_roundtrip_preserves_binding(self):
        rows, folds = observations()
        rows = [replace(r, quality=(.8,) + (0.,) * 13) for r in rows]
        encoder = ArtificialEncoder()
        selector = fit_semantic_selector(rows, encoder=encoder, folds=folds, bindings=BINDINGS)
        self.assertTrue(selector.to_dict()['diagnosis']['constant_on_training_inputs'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'selector.json'
            selector.save(path)
            loaded = SemanticSelector.load(path, encoder=encoder)
            self.assertEqual(loaded.to_dict(), selector.to_dict())
            self.assertEqual(loaded.select(rows[0].task), CONFIG_IDS[0])
            with self.assertRaises(FileExistsError):
                selector.save(path)
        bad_encoder = ArtificialEncoder()
        bad_encoder.identity['revision'] = 'wrong'
        with self.assertRaises(ValueError):
            SemanticSelector.from_dict(selector.to_dict(), encoder=bad_encoder)

    def test_export_rejects_resigned_dimensions_identity_alpha_and_diagnosis(self):
        rows, folds = observations()
        encoder = ArtificialEncoder()
        original = fit_semantic_selector(rows, encoder=encoder, folds=folds, bindings=BINDINGS).to_dict()
        def short(v): v['model']['coefficients'][0].pop()
        def ids(v): v['config_ids'].reverse()
        def alpha(v): v['chosen_alpha'] = 1
        def diag(v): v['diagnosis']['raw_candidate_preserved'] = False
        def cost(v): v['cross_validation'][0]['outcomes'][0]['cost_usd'] = '-1'
        def fold(v): v['cross_validation'][0]['folds'][0]['model']['training_task_ids'] = list(v['model']['training_task_ids'])
        for mutate in (short, ids, alpha, diag, cost, fold):
            value = deepcopy(original)
            value.pop('sha256')
            mutate(value)
            value['sha256'] = _hash(value)
            with self.assertRaises(ValueError):
                SemanticSelector.from_dict(value, encoder=encoder)
        original['model']['intercepts'][0] += 1
        with self.assertRaises(ValueError):
            SemanticSelector.from_dict(original, encoder=encoder)

    def test_missing_or_changed_encoder_files_fail_before_import(self):
        encoder = ArtificialEncoder()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                FrozenMiniLM(directory, files=encoder.identity['files'], runtime={'test': True})
            files = {}
            for name in encoder.identity['files']:
                path = Path(directory) / name
                path.write_text('{}')
                files[name] = '0' * 64
            with self.assertRaises(ValueError):
                FrozenMiniLM(directory, files=files, runtime={'test': True})

    def test_repeat_means_and_complete_14_grid_flow_through_raw_fit_export(self):
        rows, folds = observations()
        plan = [PlannedTask(r.task, r.family_id, 'spatial', (1, 2) if i == 0 else (1,)) for i, r in enumerate(rows)]
        results = []
        for planned, row in zip(plan, rows):
            for repeat in planned.repeats:
                for head, config in enumerate(CONFIG_IDS):
                    # Repeated synthetic task has different real per-repeat bookkeeping.
                    cost = row.costs[head] * repeat
                    em = float(head == (repeat - 1)) if len(planned.repeats) == 2 else row.quality[head]
                    results.append(RunResult(f'{row.task.task_id}-{repeat}-{config}', row.task.task_id,
                        row.family_id, 'spatial', config, repeat, 'completed', em, em, cost, cost, 1, 'a' * 64))
        aggregate = development_observations(results, plan)
        self.assertEqual(aggregate['executed_runs'], 154)
        self.assertEqual(aggregate['observations'][0].quality[:2], (.5, .5))
        self.assertEqual(aggregate['observations'][0].costs[0], Decimal('3'))
        self.assertEqual(aggregate['executed_cost_usd'], sum((r.cost_usd for r in results), Decimal(0)))
        encoder = ArtificialEncoder()
        selector = fit_semantic_selector(aggregate['observations'], encoder=encoder, folds=folds, bindings=BINDINGS)
        loaded = SemanticSelector.from_dict(selector.to_dict(), encoder=encoder)
        self.assertEqual([loaded.select(r.task) for r in rows], [selector.select(r.task) for r in rows])
        with self.assertRaises(ValueError):
            development_observations(results[:-1], plan)

    def test_learning_curves_use_each_prebound_fold_set_and_keep_all_sizes(self):
        # A 300-row synthetic matrix with constant input keeps this one finite check cheap.
        rows, fold_ids = [], []
        for i in range(300):
            task = TaskInput(f'curve-{i:03}', 'positive', ())
            rows.append(Observation(task, f'curve-family-{i:03}', 'spatial', (.8,) + (0.,) * 13,
                                    (Decimal('1'),) * 14))
        curves = []
        for target, n in ((100, 103), (200, 201), (300, 300)):
            ids = [r.task.task_id for r in rows[:n]]
            # Intentionally distinct saved folds across curves; no regeneration in implementation.
            folds = [[t for j, t in enumerate(ids) if (j + target // 100) % 5 == f] for f in range(5)]
            curves.append({'target': target, 'n': n, 'task_ids': ids, 'folds': folds})
        result = evaluate_learning_curves(rows, encoder=ArtificialEncoder(), curves=curves, bindings=BINDINGS)
        self.assertFalse(result['checkpoint_selection'])
        self.assertEqual([c['n'] for c in result['curves']], [103, 201, 300])
        for actual, expected in zip(result['curves'], curves):
            self.assertEqual(actual['selector']['folds'], expected['folds'])
            self.assertEqual(len(actual['selector']['model']['training_task_ids']), expected['n'])


if __name__ == '__main__':
    unittest.main()
