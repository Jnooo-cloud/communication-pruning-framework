"""P1/P3/P4/P7 synthetic T/F equivalence and strict clean-panel handoff.

Fixtures generate invented tasks/responses only. Existing real source files are
read as code; no actual study task, answer, gold or ledger is opened.
"""
import ast
import inspect
import json
import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from communication_pruning.study import file_hash
from study_preparation import final_tf_performance as tf
from study_preparation import final_rate_stop_resume as rate, final_preflight as gate, final_execution as native
from tests.study_fixture import FakeTransport
from tests.test_final_rate_stop_resume import RateStopFixture
from tests.test_final_technical_resume import technical_fake
from tests.test_final_preflight import trial_directory


def make_version(f):
    files = tf.source_files(f.binding)
    archive = f.root/'tf-sources.zip'; members = {}
    with ZipFile(archive, 'x') as output:
        for i, (path, checksum) in enumerate(sorted(files.items())):
            name = f'source-{i:04d}'; output.write(path, name); members[name] = checksum
    manifest = f.file('tf-manifest.json', dict(schema='z52-tf-performance-sources/v1', files=files,
        members=members, archive=dict(path=str(archive), sha256=file_hash(archive), members=members)))
    value = tf.prepare_version(f.binding, f.candidate, f.plan, source_manifest=manifest,
        source_review=None, source_backup=None)
    common = dict(origin='artificial_fixture', accepted=True, source_manifest=manifest,
                  version_identity=tf.version_identity(value))
    review = f.file('tf-review.json', dict(common, not_implementation_author=True,
        reviewer='invented-independent-reviewer', criteria={k: 'accepted' for k in ('P1','P2','P3','P4','P5')}))
    backup = f.file('tf-backup.json', dict(common, full_remote_reread=True, members=members,
        archive_sha256=file_hash(archive), destination='artificial_local'))
    return tf.prepare_version(f.binding, f.candidate, f.plan, source_manifest=manifest,
        source_review=review, source_backup=backup)


def ready_R(root, *, close=True):
    f = RateStopFixture(root)
    state = f.init(); f.accept_adoption(state)
    state = f.run(); f.confirm_rate(state)
    state = f.run(f.candidate['section_ends'][1]); f.confirm_rate(state)
    if close: f.close('R')
    return f


def accept_tf(f, version):
    value = tf.prepare_transition(version, f.binding, f.candidate, f.plan, **f.args())
    proposal = f.file('tf-handoff.json', value)
    common = dict(accepted=True, proposal=proposal, version_sha256=version['sha256'], origin='artificial_fixture')
    review = f.file('tf-handoff-review.json', dict(common, reviewer='invented-independent-reviewer',
        not_implementation_author=True, P7='accepted'))
    backup = f.file('tf-handoff-backup.json', dict(common, full_remote_reread=True,
        proposal_sha256=proposal['sha256'], destination='artificial_local'))
    before = f.transport.calls
    result = tf.activate_transition(version, f.binding, f.candidate, f.plan, **f.args(),
        proposal=proposal, review=review, backup=backup)
    assert result['new_model_calls'] == 0 and f.transport.calls == before
    return value


def run_tf(f, version, end, *, coverage=None, context=None):
    return tf.run_section(version, f.binding, f.candidate, f.plan, **f.args(), section_end=end,
        coverage=f.current_coverage() if coverage is None else coverage,
        **f.dependencies(), sleep=f.clock.sleep, context=context)


class TFPerformanceTests(unittest.TestCase):
    def setUp(self):
        fake = patch.object(FakeTransport, '__call__', technical_fake)
        fake.start(); self.addCleanup(fake.stop)

    def test_native_and_tf_controlled_requests_results_accounting_and_retries_match(self):
        summaries = []
        for fast in (False, True):
            with trial_directory() as directory:
                f = ready_R(directory); before = f.transport.calls
                original_claim = file_hash(f.binding['claim_path'])
                original_binding = deepcopy(f.binding)
                old_state, old_adapter = rate._inspect(f.binding, f.candidate, f.plan, f.folder)
                version = make_version(f) if fast else None
                if fast:
                    handoff = accept_tf(f, version)
                    new_state, new_adapter = rate._inspect(f.binding, f.candidate, f.plan, f.folder)
                    self.assertEqual((new_state, new_adapter.snapshot()), (old_state, old_adapter.snapshot()))
                    self.assertEqual(handoff['next_global_block'], f.plan['counts']['P']+f.plan['counts']['R']+1)
                # One free rate retry and one accounted paid technical retry in T.
                f.transport.actions = {before+1: 'free'}
                f.transport.paid_failure_call = before+3
                context = tf.RuntimeContext(version) if fast else None
                for panel, end in zip(('T','F'), f.candidate['section_ends'][2:]):
                    state = run_tf(f, version, end, context=context) if fast else f.run(end)
                    f.confirm_rate(state); f.close(panel)
                adapter = rate._adapter(f.binding, f.folder, audit_only=True)
                records = adapter.records[old_adapter.calls:]
                stable = [(r['dispatch']['logical_id'], r['dispatch']['request_sha256'],
                    r['dispatch']['retry_kind'], r['dispatch']['rate_retry'], r['dispatch']['technical_retry'],
                    r['dispatch']['global_rate_retry'], r['dispatch']['global_technical_retry'],
                    r['dispatch']['not_before'], r['usage']) for r in records]
                # Timing/resource observations and evidence hashes deliberately
                # differ; scientific row values, request bytes and costs do not.
                rows = [{k:v for k,v in row.items() if k not in ('elapsed_ms','wall_seconds','elapsed_seconds',
                    'latency_ms','duration_ns','spatial_selection_ns','temporal_selection_ns')}
                    for row in state['rows'] if row['panel'] in ('T','F')]
                summaries.append(dict(bodies=f.transport.bodies[before:], records=stable,
                    budget=adapter.snapshot(), levels=state['levels'], rows=rows,
                    loads=f.loads, selections=[t.task_id for t in f.selections],
                    time_selections=[t.task_id for t in f.time_selections]))
                self.assertEqual(file_hash(f.binding['claim_path']), original_claim)
                self.assertEqual(f.binding, original_binding)
                self.assertEqual(adapter.rate_retries, old_adapter.rate_retries+1)
                self.assertEqual(adapter.technical_retries, old_adapter.technical_retries+1)
                if fast:
                    for r in records:
                        proof = gate.read_json(f.folder/'physical'/f"{r['dispatch']['number']:06d}.json")
                        self.assertEqual(proof['tf_version_sha256'], version['sha256'])
                        self.assertEqual(proof['tf_transition_sha256'], handoff['sha256'])
                    for block in f.plan['panels']['T']+f.plan['panels']['F']:
                        index = rate._blocks(f.plan).index(block)
                        path = f.folder/'blocks'/f'{index:06d}'/'tf-performance.json'
                        self.assertEqual(gate.read_json(path)['version'], version)
                        self.assertIn(str(path.relative_to(f.folder)), state['evidence'])
        # The two independently created fixtures have different absolute
        # control/document locations, which are deliberately included by
        # gate.execution_binding. Retain both complete, unnormalized summaries
        # and admit only this exact per-row identity field as a difference.
        differences = []
        def compare(left, right, path=''):
            if type(left) is not type(right):
                differences.append(dict(path=path, old=left, new=right)); return
            if isinstance(left, dict):
                for key in sorted(set(left) | set(right)):
                    if key not in left or key not in right:
                        differences.append(dict(path=path+'/'+key, old=left.get(key), new=right.get(key)))
                    else: compare(left[key], right[key], path+'/'+key)
            elif isinstance(left, list):
                if len(left) != len(right): differences.append(dict(path=path+'/length', old=len(left), new=len(right)))
                for index, (a, b) in enumerate(zip(left, right)): compare(a, b, path+'/'+str(index))
            elif left != right: differences.append(dict(path=path, old=left, new=right))
        compare(summaries[0], summaries[1])
        allowed = {f'/rows/{i}/provenance/execution_binding_sha256' for i in range(len(summaries[0]['rows']))}
        report = dict(summaries=summaries, differences=differences, exact_allowed_paths=sorted(allowed),
            explanation='execution_binding includes the distinct absolute fixture metadata/control paths; every other field is compared without normalization')
        if os.environ.get('Z50_TEST_EVIDENCE_DIR'):
            Path(os.environ['Z50_TEST_EVIDENCE_DIR'], 'P3-COMPLETE-UNNORMALIZED-COMPARISON.json').write_text(json.dumps(report, indent=2)+'\n')
        self.maxDiff = None
        self.assertEqual({d['path'] for d in differences}, allowed)

    def test_transition_requires_closed_R_review_backup_version_exact_hold_and_single_writer(self):
        with trial_directory() as directory:
            f = ready_R(directory, close=False); version = make_version(f); before = f.transport.calls
            with self.assertRaises(Exception): tf.prepare_transition(version, f.binding, f.candidate, f.plan, **f.args())
            f.close('R')
            with native.study_lock(f.control):
                with self.assertRaises(Exception): tf.prepare_transition(version, f.binding, f.candidate, f.plan, **f.args())
            for key in ('source_review','source_backup'):
                broken = deepcopy(version); broken[key] = None
                broken = gate.seal({k:v for k,v in broken.items() if k!='sha256'})
                with self.assertRaises(Exception): tf.prepare_transition(broken, f.binding, f.candidate, f.plan, **f.args())
            broken = deepcopy(version); broken['source_files'] = {}
            broken = gate.seal({k:v for k,v in broken.items() if k!='sha256'})
            with self.assertRaises(Exception): tf.prepare_transition(broken, f.binding, f.candidate, f.plan, **f.args())
            accept_tf(f, version)
            with self.assertRaises(Exception): tf.prepare_transition(version, f.binding, f.candidate, f.plan, **f.args())
            next_end = f.candidate['section_ends'][2]
            for end in (next_end-1,next_end+1,f.candidate['section_ends'][1]):
                with self.assertRaises(Exception): run_tf(f, version, end)
            with native.study_lock(f.control):
                with self.assertRaises(Exception): run_tf(f, version, next_end)
            self.assertEqual(f.transport.calls, before)

    def test_warm_version_source_account_freshness_calendar_stop_and_claim_gates(self):
        with trial_directory() as directory:
            f = ready_R(directory); version = make_version(f); accept_tf(f,version)
            ctx = tf.RuntimeContext(version); end = f.candidate['section_ends'][2]; before=f.transport.calls
            ctx.runtime(f.binding,f.candidate,f.plan,f.clock,'T')
            for coverage in (dict(f.current_coverage(), available_usd='0'),
                dict(f.current_coverage(), valid_until_epoch=0),
                dict(f.current_coverage(), native_cost_at_observation_usd='999')):
                with self.assertRaises(Exception): run_tf(f, version, end, coverage=coverage, context=ctx)
            now=f.clock.value; f.clock.value=f.candidate['calendar']['end_epoch']+1
            with self.assertRaises(Exception): ctx.runtime(f.binding,f.candidate,f.plan,f.clock,'T')
            f.clock.value=now
            stop=f.folder/'STOP.json'; stop.write_text('{}')
            with self.assertRaises(Exception): ctx.runtime(f.binding,f.candidate,f.plan,f.clock,'T')
            stop.unlink()
            claim=Path(f.binding['claim_path']); old=claim.read_bytes(); claim.write_text('{}')
            with self.assertRaises(Exception): ctx.runtime(f.binding,f.candidate,f.plan,f.clock,'T')
            claim.write_bytes(old)
            for name in ('source_review','source_backup','source_manifest'):
                path=Path(version[name]['path']); old=path.read_bytes(); path.write_text('{}')
                with self.assertRaises(Exception): ctx.runtime(f.binding,f.candidate,f.plan,f.clock,'T')
                path.write_bytes(old)
            self.assertEqual(f.transport.calls,before)

    def test_static_activation_transfers_only_change_declared_routes(self):
        root=Path(tf.__file__).parent
        common={'_require_real_evidence':'secondary._require_real_evidence',
            'connection_hash':'secondary.connection_hash','gate.verify_archive':'self.cache.verify_archive'}
        routes=[
            ('final_rate_stop_resume.py','_predecessor_activation','_rate_predecessor',{'coverage._activation_gate':'self._coverage_activation'},None),
            ('final_rate_stop_resume.py','_activation_gate','_rate_activation',dict(common,_predecessor_activation='self._rate_predecessor'),None),
            ('final_coverage_resume.py','_activation_gate','_coverage_activation',dict(common,_predecessor_activation='self._coverage_predecessor'),None),
            ('final_technical_resume.py','_activation_gate','_technical_activation',{'secondary._activation_gate':'self._secondary_activation'},None),
            ('final_secondary.py','_activation_gate','_secondary_activation',dict(common,_verify_live_predecessor='secondary._verify_live_predecessor',_verify_extension_backup='self._verify_extension_backup'),None),
            ('final_secondary.py','_verify_extension_backup','_verify_extension_backup',common,None),
            ('final_operating_renewal.py','_extension_guard','_extension_guard',{'__file__':'operating.__file__','gate.verify_archive':'self.cache.verify_archive'},'OperatingContext'),
            ('final_operating_renewal.py','_activation_gate','_activation_gate',{'base._activation_gate':'self.runtime_context._technical_activation'},'OperatingContext')]
        new=ast.parse(Path(tf.__file__).read_text())
        for filename, oldname, newname, mapping, parent in routes:
            tree=ast.parse((root/filename).read_text())
            body=tree.body if parent is None else next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==parent).body
            fn=next(n for n in body if isinstance(n,ast.FunctionDef) and n.name==oldname)
            class Route(ast.NodeTransformer):
                def visit_Attribute(self,node):
                    key=ast.unparse(node)
                    return ast.parse(mapping[key],mode='eval').body if key in mapping else self.generic_visit(node)
                def visit_Name(self,node):
                    return ast.parse(mapping[node.id],mode='eval').body if node.id in mapping else node
            fn=Route().visit(fn); fn.name=newname
            if fn.args.args[0].arg!='self':fn.args.args.insert(0,ast.arg(arg='self'))
            cls=next(n for n in new.body if isinstance(n,ast.ClassDef) and n.name==('TFOperatingContext' if parent else 'RuntimeContext'))
            actual=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==newname)
            # Static nesting indents the copied explanatory docstring. Prove
            # its text first, then compare every executable AST node exactly.
            old_doc, new_doc = ast.get_docstring(fn, clean=False), ast.get_docstring(actual, clean=False)
            if old_doc is not None or new_doc is not None:
                self.assertEqual(inspect.cleandoc(old_doc or ''), inspect.cleandoc(new_doc or ''))
                self.assertEqual(oldname, '_verify_extension_backup')
                if os.environ.get('Z50_TEST_EVIDENCE_DIR'):
                    Path(os.environ['Z50_TEST_EVIDENCE_DIR']).mkdir(parents=True, exist_ok=True)
                    Path(os.environ['Z50_TEST_EVIDENCE_DIR'], 'AST-DOCSTRING-DIFFERENCE.json').write_text(json.dumps(
                        dict(symbol=oldname, original=old_doc, copied=new_doc, reason='class indentation only'), indent=2)+'\n')
                actual.body = actual.body[1:]; fn.body = fn.body[1:]
            self.maxDiff = None
            self.assertEqual(ast.dump(actual),ast.dump(fn),filename+':'+oldname)


if __name__ == '__main__': unittest.main()
