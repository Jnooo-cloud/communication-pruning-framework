"""Artificial deferred operator ordering: a failed gate reaches no model/data."""
from types import SimpleNamespace
from pathlib import Path
import importlib.util
import json
from unittest.mock import patch
import unittest

from study_preparation import final_coverage_resume_operator as operator
from study_preparation import final_preflight as gate


class Observation:
    def finish(self): return {'invented': True}


class OperatorTests(unittest.TestCase):
    def test_cli_paths_get_only_metadata_and_backup_policy_are_bound(self):
        root = Path(__file__).resolve().parents[1]
        folder = root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/activation'
        modules = {}
        for name in ('operation', 'metadata', 'backup'):
            spec = importlib.util.spec_from_file_location('_coverage_fixture_'+name, folder/f'coverage_{name}.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); modules[name] = module
        cli, metadata, backup = (modules[k] for k in ('operation', 'metadata', 'backup'))
        self.assertEqual(cli.EVAL, root)
        self.assertEqual(cli.CANDIDATE, root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/activation/CANDIDATE.json')
        self.assertEqual(metadata.EVAL, root)
        self.assertEqual(metadata.ENDPOINTS, ['key', 'credits', 'models/google/gemini-2.5-flash-lite/endpoints'])
        self.assertEqual(backup.PROJECT, root.parent.parent)
        self.assertEqual(backup.RUN, folder.parent)
        self.assertEqual(backup.LIMITS['max_seconds'], 3600)
        self.assertEqual(backup.LIMITS['max_rss_bytes'], 2*1024**3)
        self.assertEqual(backup.LIMITS['chunk_bytes'], 8*1024**2)
        with self.assertRaises(ValueError): cli.own(str(folder.parent.parent/'live/STOP.json'))
        with self.assertRaises(ValueError): cli._inner_inputs({'candidate': {'path': '/invented', 'sha256': 'a'*64}})
        self.assertNotIn('reset', cli.FIELDS)
        self.assertNotIn('renew', cli.FIELDS)

    def test_metadata_and_backup_helpers_retain_the_original_algorithms(self):
        root = Path(__file__).resolve().parents[1]
        folder = root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462'
        transformations = json.loads((folder/'implementation/HELPER-ADAPTATION-001.json').read_text())
        for record in transformations:
            original = Path(record['original']).read_text()
            for before, after in record['changes']: original = original.replace(before, after)
            self.assertEqual(original, Path(record['successor']).read_text())

    def test_metadata_failure_precedes_initialization_and_paid_execution(self):
        session = object.__new__(operator.Session)
        session.encoder = None; session._ready = False
        session.binding = {'sha256': 'b'*64, 'inner_binding': {'sha256': 'a'*64}}
        events = []
        def fail():
            events.append('metadata'); raise gate.StudyStop('invented missing activation')
        session.metadata_gate = fail
        session.initialize = lambda: events.append('initialize')
        session._save_resource_record = lambda *args: events.append('resource')
        with patch.object(operator, 'ProcessObservation', Observation), \
             patch.object(operator, 'validate_observation'), \
             patch.object(operator.resume, 'pre_dispatch') as pre, \
             patch.object(operator.resume, 'run_section') as run:
            with self.assertRaises(gate.StudyStop): session.run(10503, coverage={})
            pre.assert_not_called(); run.assert_not_called()
        self.assertEqual(events, ['metadata', 'resource'])

    def test_actual_pre_dispatch_gate_precedes_encoder_and_callbacks(self):
        session = object.__new__(operator.Session)
        session.encoder = None; session._ready = False
        session.binding = {'sha256': 'b'*64, 'inner_binding': {'sha256': 'a'*64}}
        session.candidate = {}; session.plan = {}; session.folder = '/invented'; session.control = '/invented-control'
        events = []
        session.metadata_gate = lambda: events.append('metadata')
        session.initialize = lambda: events.append('initialize')
        session._save_resource_record = lambda *args: events.append('resource')
        with patch.object(operator, 'ProcessObservation', Observation), \
             patch.object(operator, 'validate_observation'), \
             patch.object(operator.resume, 'pre_dispatch', side_effect=gate.StudyStop('invented undercoverage')), \
             patch.object(operator.resume, 'run_section') as run:
            with self.assertRaises(gate.StudyStop): session.run(10503, coverage={})
            run.assert_not_called()
        self.assertEqual(events, ['metadata', 'resource'])


if __name__ == '__main__':
    unittest.main()
