"""Bounded D078 operator/CLI gates; no study data, credentials or network calls.

Session tests isolate the wrapper from the core. Core recovery invariants are
covered separately in test_final_r125_resume, not claimed by these stubs.
"""
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile, ZIP_DEFLATED

from study_preparation import final_preflight as gate, final_operator
from study_preparation import final_r125_resume as core
from study_preparation import final_r125_resume_operator as operator


EVAL = Path(__file__).resolve().parents[1]
N = EVAL / 'runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087'
CLI_PATH = N / 'recovery-R00125/activation/r125_operation.py'


def load_cli():
    spec = importlib.util.spec_from_file_location('_test_r125_operation', CLI_PATH)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class OperatorGates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.folder = self.root / 'recovery-R00125/live'
        self.control = self.root / 'control'
        self.folder.mkdir(parents=True)
        original = self.save('original.json', {'source_hashes': {'dev': 'devhash'}})
        provision = self.save('provision.json', {})
        analysis = self.save('analysis.json', {})
        self.candidate = {
            'mode': 'authorized_execution', 'test_authorized': False,
            'control_directory': str(self.control),
            'plan_evidence': self.save('plan.json', {}),
            'operator': {'output_directory': str(self.root / 'old/live'),
                'operation_directory': str(self.root / 'old/operation'),
                'original_manifest': original, 'provision_manifest': provision,
                'analysis_binding': analysis, 'dev_source': {'sha256': 'devhash'}},
            'source_files': {r['path']: r['sha256'] for r in (original, provision, analysis)},
        }
        self.binding = {'folder': str(self.folder), 'control': str(self.control),
            'sha256': 'deliberately-unsealed-wrapper-fixture',
            'source_files': {str(Path(operator.__file__).resolve()): gate.file_hash(operator.__file__)}}
        self.cp = self.save('candidate.json', self.candidate)['path']
        self.bp = self.save('binding.json', self.binding)['path']

    def save(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream:
            json.dump(value, stream)
        return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}

    def session(self):
        return operator.Session(self.cp, self.bp)

    def test_construction_is_metadata_only_preserves_candidate_and_original_methods(self):
        with patch.object(final_operator, 'FrozenMiniLM') as encoder, patch.object(final_operator, 'load_key') as key:
            session = self.session()
            self.assertEqual(session.candidate, self.candidate)
            self.assertEqual(session.settings['output_directory'], str(self.folder))
            self.assertIsNone(session.encoder)
            self.assertIsNone(session.client)
            for name in ('initialize', 'loader', 'transport', 'checkpoint', '_save_resource_record'):
                self.assertIs(getattr(operator.Session, name), getattr(final_operator.Session, name))
            encoder.assert_not_called()
            key.assert_not_called()

    def test_noncanonical_and_symlink_candidate_or_binding_rejected(self):
        alias = self.root / 'alias.json'
        alias.symlink_to(self.cp)
        for candidate, binding in ((alias, self.bp), (self.cp, alias), ('candidate.json', self.bp)):
            with self.subTest(candidate=str(candidate), binding=str(binding)):
                with self.assertRaisesRegex(gate.StudyStop, 'canonical'):
                    operator.Session(candidate, binding)

    def test_real_core_rejects_changed_binding_before_encoder_key_or_loader(self):
        session = self.session()
        with patch.object(final_operator, 'FrozenMiniLM') as encoder, patch.object(final_operator, 'load_key') as key, patch.object(session, 'loader') as loader:
            with self.assertRaisesRegex(gate.StudyStop, 'changed study candidate'):
                session.initialize()
            encoder.assert_not_called()
            key.assert_not_called()
            loader.assert_not_called()

    def test_author_gate_precedes_even_core_gate(self):
        session = self.session()
        session.candidate['test_authorized'] = True
        with patch.object(core, '_check_binding') as binding, patch.object(final_operator, 'FrozenMiniLM') as encoder, patch.object(final_operator, 'load_key') as key:
            with self.assertRaisesRegex(gate.StudyStop, 'author activation'):
                session.initialize()
            binding.assert_not_called()
            encoder.assert_not_called()
            key.assert_not_called()

    def test_wrapper_metadata_mutations_fail_before_encoder_or_key(self):
        for change in ('operator_source', 'metadata_source', 'dev_source', 'output', 'operation'):
            with self.subTest(change=change):
                session = self.session()
                if change == 'operator_source': session.binding['source_files'].clear()
                if change == 'metadata_source': session.candidate['source_files'].clear()
                if change == 'dev_source': session.settings['dev_source']['sha256'] = 'other'
                if change == 'output': session.settings['output_directory'] = str(self.root / 'other')
                if change == 'operation': session.operation = self.root / 'other'
                with patch.object(core, '_check_binding'), patch.object(final_operator, 'FrozenMiniLM') as encoder, patch.object(final_operator, 'load_key') as key:
                    with self.assertRaises(gate.StudyStop): session.initialize()
                    encoder.assert_not_called()
                    key.assert_not_called()

    def test_pre_dispatch_failure_precedes_initialization_and_retains_actual_resources(self):
        session = self.session()
        with patch.object(core, '_check_binding'), patch.object(core, 'pre_dispatch', side_effect=gate.StudyStop('coverage rejected')), patch.object(session, 'initialize') as initialize, patch.object(core, 'run_section') as run:
            with self.assertRaisesRegex(gate.StudyStop, 'coverage rejected'):
                session.run(9166, coverage={})
            initialize.assert_not_called()
            run.assert_not_called()
        self.assertIsNotNone(session.last_resource_evidence)
        path = Path(session.last_resource_evidence['path']).parent / 'RESOURCE.json'
        record = json.loads(path.read_text())
        operator.validate_observation(record['process_observation'])
        self.assertFalse(record['continuous_original_F_latency_available'])
        self.assertFalse(record['historical_timing_gaps_repaired'])
        self.assertEqual(record['error_type'], 'StudyStop')
        self.assertIn('retry waits', record['scope'])

    def test_resource_failure_blocks_success_and_preserves_primary_error(self):
        for primary in (None, gate.StudyStop('original gate failure')):
            with self.subTest(primary=type(primary).__name__):
                session = self.session()
                session.spatial = session.temporal = SimpleNamespace(select=Mock())
                with patch.object(session, 'metadata_gate', return_value={}), patch.object(core, 'pre_dispatch', side_effect=primary), patch.object(session, 'initialize'), patch.object(core, 'run_section', return_value={'state_sha256': 'state'}), patch.object(session, '_save_resource_record', side_effect=OSError('injected archive failure')):
                    with self.assertRaises(gate.StudyStop) as failure:
                        session.run(9166, coverage={})
                    if primary is None:
                        self.assertIn('resource evidence incomplete', str(failure.exception))
                    else:
                        self.assertIs(failure.exception, primary)
                        self.assertIn('OSError', ' '.join(primary.__notes__))
                    self.assertFalse(session._ready)

    def test_success_passes_sleep_and_original_functions_inside_resource_interval(self):
        session = self.session()
        session.spatial = session.temporal = SimpleNamespace(select=Mock())
        def section(*args, **kwargs):
            self.assertIs(kwargs['sleep'], operator.time.sleep)
            self.assertEqual(kwargs['transport'], session.transport)
            self.assertEqual(kwargs['loader'], session.loader)
            self.assertEqual(kwargs['checkpoint'], session.checkpoint)
            self.assertEqual(kwargs['section_end'], 9166)
            return {'state_sha256': 'state'}
        with patch.object(session, 'metadata_gate', return_value={}), patch.object(core, 'pre_dispatch'), patch.object(session, 'initialize'), patch.object(core, 'run_section', side_effect=section):
            self.assertEqual(session.run(9166, coverage={})['state_sha256'], 'state')
        self.assertIsNotNone(session.last_resource_evidence)


class CliGates(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(self.cli, 'RUN', self.root))

    def save(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as stream:
            json.dump(value, stream)
        return {'path': str(path), 'sha256': self.cli.digest(path)}

    def test_request_hash_path_scope_and_command_fields_fail_before_api_import(self):
        good = self.save('activation/request.json', {'candidate': {}, 'binding': {}})
        outside = self.save('outside.json', {'candidate': {}, 'binding': {}})
        extra = self.save('activation/extra.json', {'candidate': {}, 'binding': {}, 'run_all': True})
        for command, request in [('inspect', {**good, 'sha256': 'wrong'}), ('inspect', outside), ('inspect', extra), ('run-all', good)]:
            with self.subTest(command=command, request=request):
                with patch.object(self.cli, '_api') as api:
                    with self.assertRaises(ValueError): self.cli.dispatch(command, request, {})
                    api.assert_not_called()

    def test_symlink_evidence_and_output_escape_rejected(self):
        original = self.save('activation/evidence.json', {})
        link = self.root / 'activation/link.json'
        link.symlink_to(original['path'])
        with self.assertRaisesRegex(ValueError, 'canonical'):
            self.cli.checked({'path': str(link), 'sha256': original['sha256']})
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.cli.own(str(self.root.parent / 'outside.json'))

    def test_unbound_new_source_rejected_before_importing_prior_operation(self):
        bad = self.save('activation/manifest.json', {'files': {str(self.cli.HERE): self.cli.digest(self.cli.HERE)}})
        with patch.object(self.cli.importlib.util, 'spec_from_file_location') as importer:
            with self.assertRaises(ValueError): self.cli._api(bad)
            importer.assert_not_called()

    def test_changed_archive_rejected_before_any_artifact_import(self):
        source_manifest = json.loads((N / 'checks/sources-002/MANIFEST.json').read_text())
        files = dict(source_manifest['files'])
        for path in (CLI_PATH, EVAL / 'study_preparation/final_r125_resume.py', EVAL / 'study_preparation/final_r125_resume_operator.py'):
            files[str(path)] = self.cli.digest(path)
        archive_path = self.root / 'activation/sources.zip'
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        entries = sorted(files.items())
        members = {f'operation-{i:04d}': checksum for i, (_, checksum) in enumerate(entries)}
        with ZipFile(archive_path, 'x', compression=ZIP_DEFLATED) as archive:
            for i, (name, _) in enumerate(entries):
                archive.writestr(f'operation-{i:04d}', b'corrupt' if i == len(entries) - 1 else Path(name).read_bytes())
        manifest = self.save('activation/manifest.json', {'schema': 'z52-operation-sources/v1', 'files': files,
            'archive': {'path': str(archive_path), 'sha256': self.cli.digest(archive_path), 'members': members}})
        import builtins
        original_import = builtins.__import__
        artifact_imports = []
        def guarded_import(name, *args, **kwargs):
            if name.startswith(('study_preparation', 'communication_pruning', 'project.research_control')):
                artifact_imports.append(name)
                raise AssertionError('artifact imported before source archive gate')
            return original_import(name, *args, **kwargs)
        with patch.object(builtins, '__import__', side_effect=guarded_import):
            with self.assertRaisesRegex(ValueError, 'archive full reread differs'):
                self.cli._api(manifest)
        self.assertEqual(artifact_imports, [])

    def test_bad_session_binding_hash_rejected_before_session_construction(self):
        ref = self.save('activation/binding.json', {})
        constructor = Mock()
        with patch.object(self.cli, '_inner_inputs'):
            with self.assertRaises(ValueError):
                self.cli._session({'candidate': {}, 'binding': {**ref, 'sha256': 'wrong'}}, constructor)
        constructor.assert_not_called()

    def test_run_requires_exact_integer_and_analysis_rejects_primary_panel(self):
        for command, fields in [('run-exact-hold', {'section_end': True, 'coverage': {}}), ('analyze', {'panel': 'P'})]:
            request = self.save('activation/' + command + '.json', {'candidate': {}, 'binding': {}, **fields})
            session = SimpleNamespace(folder=self.root/'live', control=self.root/'control', binding={}, candidate={}, plan={}, run=Mock())
            with patch.object(self.cli, '_api', return_value=(None, None, None, None)), patch.object(self.cli, '_session', return_value=session):
                with self.assertRaises(ValueError): self.cli.dispatch(command, request, {})
            session.run.assert_not_called()

    def test_output_is_claimed_before_dispatch_and_failed_attempt_is_retained(self):
        output = self.root/'operation/result.json'
        argv = [str(CLI_PATH), 'inspect', '--request', str(self.root/'activation/request.json'), '--request-sha256', 'h',
            '--source-manifest', str(self.root/'activation/manifest.json'), '--source-manifest-sha256', 'h', '--output', str(output)]
        def fail(*args):
            self.assertTrue(output.exists())
            raise ValueError('not copied into failure record: request-private-text')
        with patch.object(self.cli.sys, 'argv', argv), patch.object(self.cli, 'dispatch', side_effect=fail) as dispatch:
            with self.assertRaises(ValueError): self.cli.main()
            saved = output.read_bytes()
            self.assertTrue(json.loads(saved)['operation_failed'])
            self.assertNotIn(b'request-private-text', saved)
            with self.assertRaises(FileExistsError): self.cli.main()
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(saved, output.read_bytes())


if __name__ == '__main__':
    unittest.main()
