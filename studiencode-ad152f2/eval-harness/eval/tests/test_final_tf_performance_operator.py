"""T/F operator defers initialization and never invokes recovery initialize."""
import unittest
import importlib.util
from pathlib import Path
from unittest.mock import patch
from study_preparation import final_tf_performance_operator as operator, final_preflight as gate


class Observation:
    def finish(self): return {'invented_observation': True}


class TFOperatorTests(unittest.TestCase):
    def test_prepared_cli_uses_existing_native_binding_and_has_no_recovery_command(self):
        root = Path(__file__).resolve().parents[1]
        run = root/'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/recovery-R00125/technical-R00203/coverage-R01462/rate-stop-R01589'
        path = run/'activation/tf-performance/tf_operation.py'
        spec = importlib.util.spec_from_file_location('_synthetic_tf_cli', path)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        self.assertEqual(cli.RUN, run)
        self.assertEqual(cli.NATIVE, run/'activation/BINDING-ACTIVE-001.json')
        self.assertEqual(cli.NATIVE_SHA, '2ed7535538f93466b64b6eb7506de76833f035efd536e7cccf5c700ddde843b8')
        self.assertEqual(set(cli.FIELDS), {'prepare-version','metadata-check','prepare-transition','activate-transition','run-exact-hold'})
        with self.assertRaises(ValueError): cli.own(run/'live/STOP.json')

    def session(self):
        session=object.__new__(operator.Session)
        session.encoder=None; session._ready=False
        session.binding={'sha256':'b'*64,'inner_binding':{'sha256':'a'*64}}
        session.version={'sha256':'c'*64}; session.runtime_context=object()
        session.candidate={}; session.plan={}; session.folder='/invented'; session.control='/invented-control'
        return session

    def test_create_cannot_reinitialize_native_ledger(self):
        session=self.session()
        with patch.object(operator.previous.resume,'initialize') as init:
            with self.assertRaises(gate.StudyStop):session.create_execution()
            init.assert_not_called()

    def test_pre_dispatch_failure_precedes_encoder_loader_and_transport(self):
        session=self.session(); events=[]
        session.metadata_gate=lambda:events.append('metadata')
        session.initialize=lambda:events.append('initialize')
        session._save_resource_record=lambda *args:events.append('resource')
        with patch.object(operator,'ProcessObservation',Observation), patch.object(operator,'validate_observation'), \
             patch.object(operator.resume,'pre_dispatch',side_effect=gate.StudyStop('invented missing T/F gate')), \
             patch.object(operator.resume,'run_section') as run:
            with self.assertRaises(gate.StudyStop):session.run(11993,coverage={})
            run.assert_not_called()
        self.assertEqual(events,['metadata','resource'])

    def test_metadata_failure_precedes_admission_or_initialization(self):
        session=self.session();events=[]
        def fail():events.append('metadata');raise gate.StudyStop('invented missing version')
        session.metadata_gate=fail;session.initialize=lambda:events.append('initialize')
        session._save_resource_record=lambda *args:events.append('resource')
        with patch.object(operator,'ProcessObservation',Observation), patch.object(operator,'validate_observation'), \
             patch.object(operator.resume,'pre_dispatch') as pre, patch.object(operator.resume,'run_section') as run:
            with self.assertRaises(gate.StudyStop):session.run(11993,coverage={})
            pre.assert_not_called();run.assert_not_called()
        self.assertEqual(events,['metadata','resource'])


if __name__=='__main__':unittest.main()
