"""E1-E7 artificial operating renewal; no real task or provider access."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import ast
import hashlib
import json
import unittest
import zipfile

from study_preparation import final_technical_resume as base
from study_preparation.final_operating_renewal import OperatingContext
from tests.test_final_technical_resume import TechnicalFixture, technical_fake
from tests.study_fixture import FakeTransport
from tests.test_final_preflight import trial_directory

EVAL = Path(__file__).resolve().parent.parent
LIVE_EXTENSION = EVAL / ('runs/Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/'
    'continuation-R00087/recovery-R00125/technical-R00203/operating-renewal')


def extension(f):
    helper = f.folder.parent / 'operating-renewal/activation/operating_operation.py'
    helper.parent.mkdir(parents=True)
    helper.write_bytes((LIVE_EXTENSION / 'activation/operating_operation.py').read_bytes())
    files = {str(p.resolve()): base.file_hash(p) for p in (
        EVAL / 'study_preparation/final_operating_renewal.py',
        EVAL / 'study_preparation/final_operating_renewal_operator.py',
        EVAL / 'tests/test_final_operating_renewal.py',
        EVAL / 'tests/test_final_operating_renewal_operator.py', helper)}
    archive = f.folder.parent / 'operating-sources.zip'
    members = {}
    with zipfile.ZipFile(archive, 'x') as z:
        for i, (path, checksum) in enumerate(sorted(files.items())):
            member = f'source-{i:04d}'
            z.write(path, member)
            members[member] = checksum
    manifest = f.file('operating-manifest.json', {
        'schema': 'z52-operating-sources/v1', 'files': files, 'members': members,
        'archive': base.ref(archive) | {'members': members}})
    review = f.file('operating-review.json', {
        'origin': 'artificial_fixture', 'accepted': True, 'not_implementation_author': True,
        'reviewer': 'invented-independent-reviewer', 'binding_sha256': f.binding['sha256'],
        'source_manifest': manifest, 'files': files})
    backup = f.file('operating-backup.json', {
        'origin': 'artificial_fixture', 'accepted': True, 'full_remote_reread': True,
        'source_manifest': manifest, 'archive_sha256': base.file_hash(archive),
        'members': members, 'destination': 'artificial_local'})
    return f.file('operating-context.json', {
        'schema': 'z52-operating-context/v1', 'binding_sha256': f.binding['sha256'],
        'source_manifest': manifest, 'source_review': review, 'source_backup': backup})


def proposal(f, context, state, *, suffix='first', change=None):
    proof = f.file('operating-observation-'+suffix+'.json', {
        'origin': 'artificial_fixture', 'accepted': True, 'executor': f.binding['owner'],
        'connection_sha256': base.connection_hash(f.binding),
        'checked_epoch': f.clock(), 'valid_until_epoch': f.candidate['calendar']['end_epoch']})
    value = {
        'schema': 'z52-operating-renewal/v1', 'sequence': 1,
        'previous_sha256': f.binding['sha256'], 'binding_sha256': f.binding['sha256'],
        'connection_sha256': base.connection_hash(f.binding), 'base_activation': f.binding['activation'],
        'context': context, 'executor': f.binding['owner'], 'issued_epoch': f.clock(),
        'completed_blocks': state['completed_blocks'], 'state_sha256': state['state_sha256'],
        'halt_confirmation': base.ref(f.folder / 'confirmations' / f"{state['completed_blocks']:06d}.json"),
        'previous_witness': base.ref(sorted((Path(f.binding['witness']) / 'checkpoints').glob('*.json'))[-1]),
        'storage_power_review': proof, 'effective_activation': None,
    }
    if change:
        change(value)
    cert = f.file('renewal-proposal-'+suffix+'.json', base.gate.seal(value))
    backup = f.file('renewal-proposal-backup-'+suffix+'.json', {
        'origin': 'artificial_fixture', 'accepted': True, 'full_remote_reread': True,
        'certificate': cert, 'destination': 'artificial_local'})
    return cert, backup


def close_panel(f, ctx, panel):
    evidence = ctx.analyze_panel(f.binding, f.candidate, f.plan, panel, **f.args())
    prepared = ctx.prepare_panel_backup(f.binding, f.candidate, f.plan, panel,
                                        **f.args(), checkpoint=f.checkpoint)
    review = f.file('renewal-review-'+panel+'.json', {
        'binding_sha256': f.binding['sha256'], 'panel': panel,
        'analysis_sha256': evidence['sha256'], 'reviewer': 'invented-other',
        'not_implementation_author': True, 'accepted': True})
    remote = f.file('renewal-remote-'+panel+'.json', {
        'artificial_only': True, 'binding_sha256': f.binding['sha256'], 'panel': panel,
        'analysis_sha256': evidence['sha256'], 'archive_sha256': prepared['backup']['sha256'],
        'members': prepared['backup']['members'], 'full_reread': True,
        'accepted': True, 'destination': 'artificial_local'})
    return ctx.close_panel(f.binding, f.candidate, f.plan, panel,
                           **f.args(), review=review, remote_backup=remote)


def confirm_hold(f, ctx, state, label):
    review = f.file(label+'-review.json', {
        'binding_sha256': f.binding['sha256'], 'state_sha256': state['state_sha256'],
        'accepted': True, 'reviewer': 'artificial-independent-reviewer',
        'not_implementation_author': True})
    receipt = base.gate.read_json(base._receipt_path(f.folder, state))
    backup = f.file(label+'-backup.json', {
        'binding_sha256': f.binding['sha256'], 'state_sha256': state['state_sha256'],
        'accepted': True, 'archive_sha256': receipt['backup']['sha256'],
        'members': state['evidence'], 'full_reread': True, 'destination': 'artificial_local'})
    return ctx.confirm_hold(f.binding, f.candidate, f.plan, **f.args(), review=review, backup=backup)


class RenewalTests(unittest.TestCase):
    def setUp(self):
        mock = patch.object(FakeTransport, '__call__', technical_fake)
        mock.start(); self.addCleanup(mock.stop)

    def ready(self, root):
        f = TechnicalFixture(root); f.init(); state = f.run(); f.confirm_technical(state)
        return f, state, extension(f)

    def test_identity_and_all_native_panel_boundaries(self):
        with trial_directory() as root:
            f, state, context = self.ready(root)
            before_binding, before_calls = deepcopy(f.binding), f.transport.calls
            before_claim = base.file_hash(f.binding['claim_path'])
            before_dispatch = base._all_files(f.folder / 'dispatch')
            cert, backup = proposal(f, context, state)
            old = OperatingContext(context)
            self.assertEqual(old.inspect_study(f.binding, f.candidate, f.plan, **f.args()), state)
            result = old.renew(f.binding, f.candidate, f.plan, **f.args(),
                               certificate=cert, proposal_backup=backup)
            first_tip = deepcopy(result['renewal'])
            self.assertEqual(result['new_model_calls'], 0)
            self.assertEqual(f.transport.calls, before_calls)
            self.assertEqual(f.binding, before_binding)
            self.assertEqual(base.file_hash(f.binding['claim_path']), before_claim)
            self.assertEqual(base._all_files(f.folder / 'dispatch'), before_dispatch)
            ctx = OperatingContext(context, expected_tip=result['renewal'])
            self.assertEqual(ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args()), state)
            with self.assertRaises(Exception):
                old.inspect_study(f.binding, f.candidate, f.plan, **f.args())
            with self.assertRaises(Exception):
                ctx.pre_dispatch(f.binding, f.candidate, f.plan, **f.args(),
                    section_end=f.candidate['section_ends'][2], coverage=f.technical_coverage())
            close_panel(f, ctx, 'R')
            with self.assertRaises(Exception):
                ctx.pre_dispatch(f.binding, f.candidate, f.plan, **f.args(),
                    section_end=f.candidate['section_ends'][2], coverage=f.technical_coverage('0'))
            for panel, end in zip(('T', 'F'), f.candidate['section_ends'][2:]):
                state = ctx.run_section(f.binding, f.candidate, f.plan, **f.args(), section_end=end,
                    coverage=f.technical_coverage(), **f.dependencies(), sleep=f.clock.sleep)
                # This helper supplies the same artificial review/backup to the explicit context.
                confirm_hold(f, ctx, state, 'renewal-'+panel)
                if panel == 'T':
                    before = f.transport.calls
                    ledger = base._all_files(f.folder/'dispatch')
                    budget = deepcopy(state['budget'])
                    cert2, backup2 = proposal(f, context, state, suffix='second', change=lambda x: x.update(
                        sequence=2, previous_sha256=result['renewal']['sha256']))
                    result = ctx.renew(f.binding, f.candidate, f.plan, **f.args(),
                                        certificate=cert2, proposal_backup=backup2)
                    ctx = OperatingContext(context, expected_tip=result['renewal'])
                    self.assertEqual(ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args()), state)
                    self.assertEqual(state['budget'], budget)
                    self.assertEqual(base._all_files(f.folder/'dispatch'), ledger)
                    self.assertEqual(f.transport.calls, before)
                    second_path = Path(result['renewal']['path']); second_bytes = second_path.read_bytes()
                    second_path.unlink()
                    with self.assertRaises(Exception):
                        OperatingContext(context, expected_tip=first_tip).inspect_study(
                            f.binding, f.candidate, f.plan, **f.args())
                    second_path.write_bytes(second_bytes)
                    self.assertEqual(ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args()), state)
                close_panel(f, ctx, panel)
            self.assertTrue(state['complete'])
            self.assertEqual(base._all_files(f.old_folder), f.old_inventory)

    def test_wrong_proposal_never_mutates_or_sends(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); before_calls = f.transport.calls
            ctx = OperatingContext(context)
            cases = {
                'foreign': lambda x: x.update(binding_sha256='0'*64),
                'future': lambda x: x.update(issued_epoch=f.clock()+1),
                'nan': lambda x: x.update(issued_epoch=float('nan')),
                'wrong-halt': lambda x: x.update(completed_blocks=state['completed_blocks']+1),
                'state': lambda x: x.update(state_sha256='0'*64),
                'rights': lambda x: x.update(new_budget='999'),
                'branch': lambda x: x.update(previous_sha256='1'*64),
                'operator': lambda x: x.update(executor='other'),
                'witness': lambda x: x.update(previous_witness=base.ref(
                    sorted((Path(f.binding['witness'])/'checkpoints').glob('*.json'))[0])),
            }
            expected_messages = {
                'foreign': 'renewal identity or chain differs', 'future': 'invalid renewal issue time',
                'nan': 'invalid renewal issue time', 'wrong-halt': 'foreign halt confirmation',
                'state': 'renewal is not for current halt', 'rights': 'renewal identity or chain differs',
                'branch': 'renewal identity or chain differs', 'operator': 'renewal identity or chain differs',
                'witness': 'renewal witness is stale',
            }
            for name, change in cases.items():
                with self.subTest(name=name):
                    try:
                        cert, backup = proposal(f, context, state, suffix=name, change=change)
                    except (ValueError, TypeError):
                        # Strict JSON serialization may reject NaN before a proposal exists.
                        self.assertEqual(name, 'nan'); continue
                    with self.assertRaisesRegex(Exception, expected_messages[name]):
                        ctx.renew(f.binding, f.candidate, f.plan, **f.args(),
                                  certificate=cert, proposal_backup=backup)
            self.assertFalse((f.folder / 'operating-renewals').exists())
            self.assertEqual(f.transport.calls, before_calls)

    def test_wrong_connection_and_calendar_bound_of_new_proof(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); before = f.transport.calls
            for label, changes in (
                ('connection', {'connection_sha256': '0'*64}),
                ('calendar', {'valid_until_epoch': f.candidate['calendar']['end_epoch']+1}),
            ):
                proof = {'origin': 'artificial_fixture', 'accepted': True, 'executor': f.binding['owner'],
                         'connection_sha256': base.connection_hash(f.binding),
                         'checked_epoch': f.clock(), 'valid_until_epoch': f.candidate['calendar']['end_epoch']}
                ref = f.file('invalid-observation-'+label+'.json', proof | changes)
                cert, backup = proposal(f, context, state, suffix=label,
                                         change=lambda x: x.update(storage_power_review=ref))
                with self.subTest(label=label), self.assertRaisesRegex(Exception, 'invalid renewed operating observation'):
                    OperatingContext(context).renew(f.binding, f.candidate, f.plan, **f.args(),
                                                    certificate=cert, proposal_backup=backup)
            self.assertEqual(f.transport.calls, before)
            self.assertFalse((f.folder/'operating-renewals').exists())

    def test_expired_current_proof_rejects_before_dispatch(self):
        with trial_directory() as root:
            f, state, context = self.ready(root)
            short = f.file('short-operating-proof.json', {
                'origin': 'artificial_fixture', 'accepted': True, 'executor': f.binding['owner'],
                'connection_sha256': base.connection_hash(f.binding),
                'checked_epoch': f.clock(), 'valid_until_epoch': f.clock()+5})
            cert, backup = proposal(f, context, state, change=lambda x: x.update(storage_power_review=short))
            ctx = OperatingContext(context)
            result = ctx.renew(f.binding, f.candidate, f.plan, **f.args(),
                               certificate=cert, proposal_backup=backup)
            ctx = OperatingContext(context, expected_tip=result['renewal'])
            before = f.transport.calls
            f.clock.sleep(6)
            with self.assertRaisesRegex(Exception, 'expired'):
                ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args())
            self.assertEqual(f.transport.calls, before)

    def test_invalid_source_review_manifest_and_backups_are_distinct(self):
        with trial_directory() as root:
            f, state, context = self.ready(root)
            spec = base.gate.read_json(context['path']); before = f.transport.calls
            for label, key, change, expected in (
                ('review', 'source_review', {'accepted': False}, 'separate exact operating source review'),
                ('author', 'source_review', {'reviewer': f.binding['owner']}, 'separate exact operating source review'),
                ('backup', 'source_backup', {'full_remote_reread': False}, 'lack exact remote reread'),
                ('manifest', 'source_manifest', {'files': {}}, 'incomplete operating source manifest'),
            ):
                record = base.gate.read_json(spec[key]['path']) | change
                modified = f.file('bad-'+label+'.json', record)
                bad_context = f.file('bad-context-'+label+'.json', spec | {key: modified})
                with self.subTest(label=label), self.assertRaisesRegex(Exception, expected):
                    OperatingContext(bad_context).inspect_study(f.binding, f.candidate, f.plan, **f.args())
            cert, backup = proposal(f, context, state)
            bad = f.file('bad-proposal-backup.json', base.gate.read_json(backup['path']) | {'accepted': False})
            with self.assertRaisesRegex(Exception, 'proposal lacks private full reread'):
                OperatingContext(context).renew(f.binding, f.candidate, f.plan, **f.args(),
                                                certificate=cert, proposal_backup=bad)
            self.assertFalse((f.folder/'operating-renewals').exists())
            self.assertEqual(f.transport.calls, before)

    def test_active_section_cannot_be_renewed(self):
        with trial_directory() as root:
            f, state, context = self.ready(root)
            cert, backup = proposal(f, context, state); before = f.transport.calls
            generation = base._assert_current(f.binding, f.folder, f.control)
            base._record_section(f.folder, f.candidate['section_ends'][2], 'admitted')
            base._publish(f.binding, f.folder, f.control, generation)
            with self.assertRaisesRegex(Exception, 'unresolved section'):
                OperatingContext(context).renew(f.binding, f.candidate, f.plan, **f.args(),
                                                certificate=cert, proposal_backup=backup)
            self.assertEqual(f.transport.calls, before)

    def test_proposal_expires_before_publication_without_mutation(self):
        with trial_directory() as root:
            f, state, context = self.ready(root)
            short = f.file('prepublication-short-proof.json', {
                'origin': 'artificial_fixture', 'accepted': True, 'executor': f.binding['owner'],
                'connection_sha256': base.connection_hash(f.binding),
                'checked_epoch': f.clock(), 'valid_until_epoch': f.clock()+5})
            cert, backup = proposal(f, context, state, change=lambda x: x.update(storage_power_review=short))
            inventory = base._all_files(f.folder)
            witness = base._all_files(f.binding['witness'])
            before = f.transport.calls
            f.clock.sleep(6)
            with self.assertRaisesRegex(Exception, 'expired before publication'):
                OperatingContext(context).renew(f.binding, f.candidate, f.plan,
                    **f.args(), certificate=cert, proposal_backup=backup)
            self.assertEqual(base._all_files(f.folder), inventory)
            self.assertEqual(base._all_files(f.binding['witness']), witness)
            self.assertEqual(f.transport.calls, before)

    def test_changed_extension_and_cleanup_provenance(self):
        with trial_directory() as root:
            f, state, context = self.ready(root); ctx = OperatingContext(context)
            cert, backup = proposal(f, context, state)
            result = ctx.renew(f.binding, f.candidate, f.plan, **f.args(),
                               certificate=cert, proposal_backup=backup)
            ctx = OperatingContext(context, expected_tip=result['renewal'])
            path = Path(result['renewal']['path']); raw = path.read_bytes()
            duplicate = path.with_name('000002.json')
            for alteration in ('delete', 'gap', 'duplicate'):
                with self.subTest(alteration=alteration):
                    if alteration == 'delete':
                        path.unlink()
                    elif alteration == 'gap':
                        path.rename(duplicate)
                    else:
                        duplicate.write_bytes(raw)
                    with self.assertRaises(Exception):
                        ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args())
                    if duplicate.exists():
                        duplicate.unlink()
                    path.write_bytes(raw)
                    self.assertEqual(ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args()), state)
            path.write_bytes(raw+b' ')
            with self.assertRaises(Exception):
                ctx.pre_dispatch(f.binding, f.candidate, f.plan, **f.args(),
                    section_end=f.candidate['section_ends'][2], coverage=f.technical_coverage())
            path.write_bytes(raw)
            helper = f.folder.parent / 'operating-renewal/activation/operating_operation.py'
            helper.write_bytes(helper.read_bytes()+b'\n# changed\n')
            with self.assertRaises(Exception):
                ctx.inspect_study(f.binding, f.candidate, f.plan, **f.args())

    def test_static_operating_copies_have_only_declared_routing_changes(self):
        original = ast.parse((EVAL/'study_preparation/final_technical_resume.py').read_text())
        new = ast.parse((EVAL/'study_preparation/final_operating_renewal.py').read_text())
        cls = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == 'OperatingContext')
        methods = ['_check_binding', '_runtime', 'pre_dispatch', 'run_section',
                   'prepare_panel_backup', 'close_panel', 'inspect_study',
                   'collect_panel', 'analyze_panel', 'confirm_hold']
        class Normalize(ast.NodeTransformer):
            def visit_Attribute(self, node):
                if isinstance(node.value, ast.Name) and node.value.id in ('base', 'self'):
                    return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
                return self.generic_visit(node)
        for name in methods:
            a = deepcopy(next(n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == name))
            b = deepcopy(next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name))
            b.args.args.pop(0)
            if name == '_check_binding':
                self.assertEqual(ast.unparse(b.body.pop(0)), 'self._extension_guard(binding)')
            b = Normalize().visit(b)
            self.assertEqual(ast.dump(a, include_attributes=False), ast.dump(b, include_attributes=False), name)


if __name__ == '__main__':
    unittest.main()
