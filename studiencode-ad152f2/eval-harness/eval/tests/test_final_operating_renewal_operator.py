"""Explicit operator integration and fail-closed renewal boundary tests."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import ast
import importlib.util
import json
import unittest

from study_preparation import final_technical_resume as base
from study_preparation.final_operating_renewal import OperatingContext
from study_preparation.final_operating_renewal_operator import Session, probe_storage_power
from tests.test_final_operating_renewal import EVAL, LIVE_EXTENSION, extension, proposal
from tests.test_final_technical_resume import TechnicalFixture, technical_fake
from tests.study_fixture import FakeTransport
from tests.test_final_preflight import trial_directory


class OperatingBoundaryTests(unittest.TestCase):
    def setUp(self):
        p = patch.object(FakeTransport, '__call__', technical_fake)
        p.start(); self.addCleanup(p.stop)

    def ready(self, root):
        f = TechnicalFixture(root); f.init(); state = f.run(); f.confirm_technical(state)
        context = extension(f)
        return f, state, context

    def test_no_initialization_api(self):
        with self.assertRaisesRegex(base.StudyStop, 'cannot initialize'):
            Session.__new__(Session).create_execution()
        source = LIVE_EXTENSION / 'activation/operating_operation.py'
        spec = importlib.util.spec_from_file_location('unit_operating_cli', source)
        cli = importlib.util.module_from_spec(spec); spec.loader.exec_module(cli)
        self.assertFalse({'create', 'prepare-binding', 'activate-binding', 'prepare-origin'} & set(cli.FIELDS))

    def test_session_metadata_and_run_route_only_operating_gates(self):
        original = ast.parse((EVAL/'study_preparation/final_technical_resume_operator.py').read_text())
        renewed = ast.parse((EVAL/'study_preparation/final_operating_renewal_operator.py').read_text())
        oldcls = next(n for n in original.body if isinstance(n, ast.ClassDef) and n.name == 'Session')
        newcls = next(n for n in renewed.body if isinstance(n, ast.ClassDef) and n.name == 'Session')
        class Normalize(ast.NodeTransformer):
            def visit_Attribute(self, node):
                if isinstance(node.value, ast.Attribute) and isinstance(node.value.value, ast.Name) \
                        and node.value.value.id == 'self' and node.value.attr == 'operating':
                    return ast.copy_location(ast.Attribute(value=ast.Name(id='resume', ctx=ast.Load()),
                                                          attr=node.attr, ctx=node.ctx), node)
                if isinstance(node.value, ast.Name) and node.value.id == 'technical':
                    return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
                return self.generic_visit(node)
        for name in ('metadata_gate', 'run'):
            old = deepcopy(next(n for n in oldcls.body if isinstance(n, ast.FunctionDef) and n.name == name))
            new = deepcopy(next(n for n in newcls.body if isinstance(n, ast.FunctionDef) and n.name == name))
            if name == 'run':
                record = next(n for n in ast.walk(new) if isinstance(n, ast.Assign)
                              and any(isinstance(t, ast.Name) and t.id == 'record' for t in n.targets))
                self.assertEqual([k.value for k in record.value.keys[-2:]],
                                 ['operating_context', 'operating_renewal_tip'])
                record.value.keys = record.value.keys[:-2]
                record.value.values = record.value.values[:-2]
            new = Normalize().visit(new)
            self.assertEqual(ast.dump(old, include_attributes=False), ast.dump(new, include_attributes=False), name)

    def test_stop_and_unconfirmed_hold_do_not_renew(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); ctx = OperatingContext(context)
            cert, backup = proposal(f, context, state); before = f.transport.calls
            stop = f.folder/'STOP.json'; stop.write_text('{"unit_stop":true}\n')
            with self.assertRaises(Exception):
                ctx.renew(f.binding, f.candidate, f.plan, **f.args(), certificate=cert, proposal_backup=backup)
            stop.unlink()
            confirmation = f.folder/'confirmations'/f"{state['completed_blocks']:06d}.json"
            raw = confirmation.read_bytes(); confirmation.unlink()
            with self.assertRaises(Exception):
                ctx.renew(f.binding, f.candidate, f.plan, **f.args(), certificate=cert, proposal_backup=backup)
            confirmation.write_bytes(raw)
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.folder/'operating-renewals').exists())

    def test_competing_study_lock_prevents_renewal(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); ctx = OperatingContext(context)
            cert, backup = proposal(f, context, state); before = f.transport.calls
            with base.native.study_lock(f.args()['control']):
                with self.assertRaisesRegex(base.StudyStop, 'another study writer owns'):
                    ctx.renew(f.binding, f.candidate, f.plan, **f.args(), certificate=cert, proposal_backup=backup)
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.folder/'operating-renewals').exists())

    def test_crash_before_witness_is_not_recovered_or_sent(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); ctx = OperatingContext(context)
            cert, backup = proposal(f, context, state); before = f.transport.calls
            with patch.object(base, '_publish', side_effect=RuntimeError('invented checkpoint failure')):
                with self.assertRaisesRegex(RuntimeError, 'invented checkpoint'):
                    ctx.renew(f.binding, f.candidate, f.plan, **f.args(), certificate=cert, proposal_backup=backup)
            path = f.folder/'operating-renewals/000001.json'
            self.assertTrue(path.is_file())
            selected = OperatingContext(context, expected_tip=base.ref(path))
            with self.assertRaises(Exception):
                selected.inspect_study(f.binding, f.candidate, f.plan, **f.args())
            self.assertEqual(f.transport.calls, before)

    def test_expiry_and_foreign_activation_fields_are_rejected(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); ctx = OperatingContext(context)
            cert, backup = proposal(f, context, state)
            value = base.gate.read_json(cert['path'])
            # A unit-level live validation view tests field selection only;
            # it is never passed to live dispatch or source authorization.
            binding = deepcopy(f.binding); binding['mode'] = 'authorized_execution'
            original = {'author': 'Jannik', 'budget': 'unchanged', 'storage_power_review': {'old': True}}
            binding['activation'] = f.file('unit-base-activation.json', original)
            value['base_activation'] = binding['activation']
            value['connection_sha256'] = base.connection_hash(binding)
            proof = base.gate.read_json(value['storage_power_review']['path'])
            proof.pop('origin'); proof['connection_sha256'] = base.connection_hash(binding)
            value['storage_power_review'] = f.file('unit-current-observation.json', proof)
            wanted = original | {'storage_power_review': value['storage_power_review']}
            value['effective_activation'] = f.file('unit-effective-activation.json', wanted)
            # Live first-hold rule is checked separately from the small artificial fixture.
            value['sequence'] = 2
            positive = base.gate.seal(value)
            self.assertEqual(ctx._certificate(binding, f.candidate, positive, sequence=2,
                                              previous=binding['sha256'], clock=f.clock), proof)
            first = base.gate.seal(positive | {'sequence': 1})
            with self.assertRaisesRegex(Exception, 'first renewal must bind R500'):
                ctx._certificate(binding, f.candidate, first, sequence=1,
                                 previous=binding['sha256'], clock=f.clock)
            self.assertEqual(base._next_end(binding, {'section_ends': [9540, 10040]},
                                             {'completed_blocks': 9540}), 10040)
            for suffix, changed in (
                ('rights', wanted | {'new_right': True}),
                ('budget', wanted | {'budget': 'changed'}),
                ('author', wanted | {'author': 'other'}),
            ):
                variant = deepcopy(value)
                variant['effective_activation'] = f.file('unit-invalid-'+suffix+'.json', changed)
                variant = base.gate.seal(variant)
                with self.assertRaises(Exception):
                    ctx._certificate(binding, f.candidate, variant, sequence=2,
                                     previous=binding['sha256'], clock=f.clock)
            # Real time remains a required argument; an expired current proof rejects.
            short = deepcopy(proof); short['valid_until_epoch'] = f.clock()-1
            value['storage_power_review'] = f.file('unit-expired-observation.json', short)
            value = base.gate.seal(value)
            with self.assertRaises(Exception):
                ctx._certificate(binding, f.candidate, value, sequence=2,
                                 previous=binding['sha256'], clock=f.clock)

    def test_current_power_and_owned_wake_observation(self):
        with trial_directory() as root:
            path = Path(root)/'unit-wake.json'
            base._save(path, {'checked_epoch': 100, 'pid': 424242, 'executor': 'unit-owner',
                              'command': ['/usr/bin/caffeinate', '-i', '-s', '-t', '100']})
            proof = {'accepted': True, 'executor': 'unit-owner', 'checked_epoch': 100,
                     'valid_until_epoch': 190, 'wake_process': base.ref(path)}
            observed = [SimpleNamespace(stdout="Now drawing from 'AC Power'\n"),
                        SimpleNamespace(stdout='pid 424242(caffeinate): PreventUserIdleSystemSleep\n'
                                               'pid 424242(caffeinate): PreventSystemSleep\n')]
            module = 'study_preparation.final_operating_renewal_operator'
            with patch(module+'.os.kill') as alive, patch(module+'.subprocess.run', side_effect=observed), \
                    patch(module+'.shutil.disk_usage', return_value=SimpleNamespace(free=123456)):
                result = probe_storage_power(proof, root, executor='unit-owner', clock=lambda: 110)
                self.assertTrue(result['owned_wake_assertions_verified'])
                self.assertTrue(result['ac_power']); self.assertEqual(result['disk_free_bytes'], 123456)
                alive.assert_called_once_with(424242, 0)
            with patch(module+'.os.kill', side_effect=ProcessLookupError), patch(module+'.subprocess.run') as run:
                with self.assertRaisesRegex(base.StudyStop, 'owned wake process unavailable'):
                    probe_storage_power(proof, root, executor='unit-owner', clock=lambda: 110)
                run.assert_not_called()
            with patch(module+'.os.kill'), patch(module+'.subprocess.run',
                    return_value=SimpleNamespace(stdout="Now drawing from 'Battery Power'\n")):
                with self.assertRaisesRegex(base.StudyStop, 'AC power unavailable'):
                    probe_storage_power(proof, root, executor='unit-owner', clock=lambda: 110)
            with patch(module+'.os.kill') as alive:
                with self.assertRaisesRegex(base.StudyStop, 'stale operating observation'):
                    probe_storage_power(proof, root, executor='unit-owner', clock=lambda: 191)
                alive.assert_not_called()
            with patch(module+'.os.kill'), patch(module+'.subprocess.run', side_effect=[
                    observed[0], SimpleNamespace(stdout='pid 424242(caffeinate): PreventUserIdleSystemSleep\n')]):
                with self.assertRaisesRegex(base.StudyStop, 'owned wake assertions unavailable'):
                    probe_storage_power(proof, root, executor='unit-owner', clock=lambda: 110)
            future_path = Path(root)/'unit-future-wake.json'
            future_wake = base.gate.read_json(path)
            future_wake['checked_epoch'] = 1000
            base._save(future_path, future_wake)
            future_proof = {**proof, 'wake_process': base.ref(future_path)}
            with patch(module+'.os.kill') as alive, patch(module+'.subprocess.run') as run:
                with self.assertRaisesRegex(base.StudyStop, 'future owned wake observation'):
                    probe_storage_power(future_proof, root, executor='unit-owner', clock=lambda: 110)
                alive.assert_not_called(); run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
