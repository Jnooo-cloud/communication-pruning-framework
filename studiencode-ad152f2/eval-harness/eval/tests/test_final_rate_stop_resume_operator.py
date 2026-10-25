"""Artificial deferred operator gate order and exact additive helper paths."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import unittest
from study_preparation import final_rate_stop_resume_operator as operator, final_preflight as gate


class Observation:
    def finish(self): return {'invented_observation': True}


class OperatorTests(unittest.TestCase):
    def test_helper_paths_and_retained_backup_algorithm(self):
        root = Path(__file__).resolve().parents[1]
        previous = root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462'
        folder = previous/'rate-stop-R01589/activation'
        modules = {}
        for name in ('operation', 'metadata', 'backup'):
            spec = importlib.util.spec_from_file_location('_rate_fixture_'+name, folder/f'rate_stop_{name}.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
        cli, metadata, backup = (modules[n] for n in ('operation', 'metadata', 'backup'))
        self.assertEqual(cli.EVAL, root)
        self.assertEqual(cli.CANDIDATE, root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/activation/CANDIDATE.json')
        self.assertEqual(cli.OLD_BINDING, previous/'activation/BINDING.json')
        self.assertEqual(metadata.EVAL, root)
        self.assertEqual(metadata.ENDPOINTS, ['key', 'credits', 'models/google/gemini-2.5-flash-lite/endpoints'])
        self.assertEqual(backup.PROJECT, root.parent.parent)
        self.assertEqual(backup.RUN, folder.parent)
        old_text = (previous/'activation/coverage_backup.py').read_text()
        new_text = (folder/'rate_stop_backup.py').read_text()
        normalized = old_text.replace('PROJECT = SOURCE.parents[10]',
            "PROJECT = next(p for p in SOURCE.parents if p.name == 'eval' and p.parent.name == 'eval-harness').parent.parent").replace(
            'Z52-KONTODECKUNGS-ANSCHLUSS-PLAN.md', 'Z52-RATE-STOP-FORTSETZUNG-PLAN.md')
        self.assertEqual(new_text, normalized)
        self.assertEqual(backup.LIMITS, {'max_seconds': 3600, 'max_rss_bytes': 2*1024**3,
            'chunk_bytes': 8*1024**2, 'backend_timeout_seconds': 600, 'ps_timeout_seconds': 5, 'sample_seconds': .25})
        with self.assertRaises(ValueError): cli.own(str(previous/'live/STOP.json'))
        with self.assertRaises(ValueError): cli._inner_inputs({'candidate': {'path': '/invented', 'sha256': 'a'*64}})
        self.assertNotIn('reset', cli.FIELDS); self.assertNotIn('renew', cli.FIELDS)

    def session(self):
        session = object.__new__(operator.Session)
        session.encoder = None; session._ready = False
        session.binding = {'sha256': 'b'*64, 'inner_binding': {'sha256': 'a'*64}}
        session.candidate = {}; session.plan = {}; session.folder = '/invented'; session.control = '/invented-control'
        return session

    def test_metadata_failure_precedes_initialization_and_paid_execution(self):
        session = self.session(); events = []
        def fail(): events.append('metadata'); raise gate.StudyStop('invented missing activation')
        session.metadata_gate = fail; session.initialize = lambda: events.append('initialize')
        session._save_resource_record = lambda *args: events.append('resource')
        with patch.object(operator, 'ProcessObservation', Observation), patch.object(operator, 'validate_observation'), \
             patch.object(operator.resume, 'pre_dispatch') as pre, patch.object(operator.resume, 'run_section') as run:
            with self.assertRaises(gate.StudyStop): session.run(10630, coverage={})
            pre.assert_not_called(); run.assert_not_called()
        self.assertEqual(events, ['metadata', 'resource'])

    def test_pre_dispatch_failure_precedes_encoder_loader_and_transport(self):
        session = self.session(); events = []
        session.metadata_gate = lambda: events.append('metadata')
        session.initialize = lambda: events.append('initialize')
        session._save_resource_record = lambda *args: events.append('resource')
        with patch.object(operator, 'ProcessObservation', Observation), patch.object(operator, 'validate_observation'), \
             patch.object(operator.resume, 'pre_dispatch', side_effect=gate.StudyStop('invented undercoverage')), \
             patch.object(operator.resume, 'run_section') as run:
            with self.assertRaises(gate.StudyStop): session.run(10630, coverage={})
            run.assert_not_called()
        self.assertEqual(events, ['metadata', 'resource'])


if __name__ == '__main__':
    unittest.main()
