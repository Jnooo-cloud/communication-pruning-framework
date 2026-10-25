"""Explicit operating-evidence renewal; the original study identity never changes.

This module is not active merely because it exists. Its source/review/backup
context and an exact clean-hold renewal must be supplied by the new operator.
Scientific functions and old source files are retained unchanged.
"""
from copy import deepcopy
from pathlib import Path
import math

from . import final_technical_resume as base

gate = base.gate
need = base._need
CERTIFICATE_FIELDS = {
    'schema', 'sequence', 'previous_sha256', 'binding_sha256',
    'connection_sha256', 'base_activation', 'context', 'executor',
    'issued_epoch', 'completed_blocks', 'state_sha256', 'halt_confirmation',
    'previous_witness', 'storage_power_review', 'effective_activation', 'sha256',
}


def read_ref(value):
    return gate.read_json(gate.evidence_file(value))


class OperatingContext:
    """Own explicit dependency context, never a mutation of an old module."""

    def __init__(self, context_ref, *, expected_tip=None):
        self.context_ref = deepcopy(context_ref)
        self.spec = read_ref(context_ref)
        self.expected_tip = deepcopy(expected_tip)

    def _extension_guard(self, binding):
        need(read_ref(self.context_ref) == self.spec, 'operating context changed')
        need(set(self.spec) == {'schema', 'binding_sha256', 'source_manifest',
                               'source_review', 'source_backup'}
             and self.spec['schema'] == 'z52-operating-context/v1'
             and self.spec['binding_sha256'] == binding['sha256'],
             'foreign operating context')
        manifest = read_ref(self.spec['source_manifest'])
        root = Path(__file__).resolve().parent.parent
        expected = {
            str(Path(__file__).resolve()),
            str(root / 'study_preparation/final_operating_renewal_operator.py'),
            str(root / 'tests/test_final_operating_renewal.py'),
            str(root / 'tests/test_final_operating_renewal_operator.py'),
            str(Path(binding['folder']).parent / 'operating-renewal/activation/operating_operation.py'),
        }
        need(manifest.get('schema') == 'z52-operating-sources/v1'
             and set(manifest.get('files', {})) == expected,
             'incomplete operating source manifest')
        need(manifest.get('members') == {
            f'source-{i:04d}': checksum
            for i, (_, checksum) in enumerate(sorted(manifest['files'].items()))
        }, 'operating archive does not bind every source')
        base.FileGuard(manifest['files'])()
        base._path(manifest['archive']['path'])
        gate.verify_archive(manifest['archive'], manifest['members'])
        review = read_ref(self.spec['source_review'])
        backup = read_ref(self.spec['source_backup'])
        if binding['mode'] != 'artificial_only':
            base._require_real_evidence(self.spec)
            base._require_real_evidence(review)
            base._require_real_evidence(backup)
        need(review.get('accepted') is True
             and review.get('not_implementation_author') is True
             and isinstance(review.get('reviewer'), str)
             and review['reviewer'].strip()
             and review['reviewer'] != binding['owner']
             and review.get('binding_sha256') == binding['sha256']
             and review.get('source_manifest') == self.spec['source_manifest']
             and review.get('files') == manifest['files'],
             'separate exact operating source review required')
        destination = ('artificial_local' if binding['mode'] == 'artificial_only'
                       else 'Jnooo-cloud/masterarbeit-mas-pruning')
        need(backup.get('accepted') is True and backup.get('full_remote_reread') is True
             and backup.get('source_manifest') == self.spec['source_manifest']
             and backup.get('archive_sha256') == manifest['archive']['sha256']
             and backup.get('members') == manifest['members']
             and backup.get('destination') == destination,
             'operating sources lack exact remote reread')
        return manifest

    def _certificate(self, binding, candidate, value, *, sequence, previous, clock):
        gate._check_seal(value)
        need(set(value) == CERTIFICATE_FIELDS
             and value['schema'] == 'z52-operating-renewal/v1'
             and type(value['sequence']) is int and value['sequence'] == sequence
             and value['previous_sha256'] == previous
             and value['binding_sha256'] == binding['sha256']
             and value['connection_sha256'] == base.connection_hash(binding)
             and value['base_activation'] == binding['activation']
             and value['context'] == self.context_ref
             and value['executor'] == binding['owner'], 'renewal identity or chain differs')
        issued = value['issued_epoch']
        need(type(issued) in (int, float) and math.isfinite(issued)
             and candidate['calendar']['start_epoch'] <= issued <= clock()
             <= candidate['calendar']['end_epoch'], 'invalid renewal issue time')
        proof = read_ref(value['storage_power_review'])
        if binding['mode'] != 'artificial_only':
            base._require_real_evidence(value)
            base._require_real_evidence(proof)
        need(proof.get('accepted') is True and proof.get('executor') == binding['owner']
             and proof.get('connection_sha256') == base.connection_hash(binding)
             and all(type(proof.get(k)) in (int, float) and math.isfinite(proof[k])
                     for k in ('checked_epoch', 'valid_until_epoch'))
             and candidate['calendar']['start_epoch'] <= proof['checked_epoch'] <= issued
             <= proof['valid_until_epoch'] <= candidate['calendar']['end_epoch'],
             'invalid renewed operating observation')
        witness = read_ref(value['previous_witness'])
        witness_path = Path(gate.evidence_file(value['previous_witness']))
        need(witness_path.parent == (Path(binding['witness']) / 'checkpoints').resolve()
             and type(witness['generation']) is int
             and witness_path.name == f"{witness['generation']:020d}.json"
             and witness['checkpoint']['activation_sha256'] == binding['sha256']
             and witness['checkpoint']['stop_active'] is False
             and all(v == 'settled' for v in witness['checkpoint']['admissions'].values()),
             'renewal predecessor was not clean')
        confirmation = read_ref(value['halt_confirmation'])
        expected = Path(binding['folder']) / 'confirmations' / f"{value['completed_blocks']:06d}.json"
        need(Path(gate.evidence_file(value['halt_confirmation'])) == expected.resolve()
             and set(confirmation) == {'review', 'backup'}, 'foreign halt confirmation')
        need(type(value['completed_blocks']) is int
             and value['completed_blocks'] in candidate['section_ends'], 'nonoriginal renewal halt')
        if sequence == 1 and binding['mode'] != 'artificial_only':
            need(value['completed_blocks'] == 9540, 'first renewal must bind R500')
        if binding['mode'] == 'artificial_only':
            need(value['effective_activation'] is None and binding['activation'] is None,
                 'artificial renewal cannot carry live activation')
        else:
            original = read_ref(binding['activation'])
            effective = read_ref(value['effective_activation'])
            wanted = deepcopy(original)
            wanted['storage_power_review'] = value['storage_power_review']
            need(effective == wanted, 'only storage_power_review may be renewed')
        return proof

    def _chain(self, binding, candidate, clock):
        folder = Path(binding['folder']) / 'operating-renewals'
        if not folder.exists():
            need(self.expected_tip is None, 'expected renewal chain missing')
            return []
        need(folder.is_dir() and not folder.is_symlink(), 'noncanonical renewal directory')
        files = sorted(folder.iterdir())
        need(files and [p.name for p in files] == [f'{i:06d}.json' for i in range(1, len(files)+1)],
             'renewal chain gap, branch or foreign file')
        previous, values = binding['sha256'], []
        for number, path in enumerate(files, 1):
            need(path.is_file() and not path.is_symlink(), 'noncanonical renewal file')
            envelope = gate.read_json(path)
            need(set(envelope) == {'certificate', 'proposal', 'proposal_backup'},
                 'renewal envelope differs')
            value = read_ref(envelope['proposal'])
            need(value == envelope['certificate'], 'renewal proposal changed')
            self._proposal_backup(binding, envelope['proposal'], envelope['proposal_backup'])
            self._certificate(binding, candidate, value, sequence=number, previous=previous, clock=clock)
            if values:
                need(value['issued_epoch'] >= values[-1]['issued_epoch']
                     and value['completed_blocks'] > values[-1]['completed_blocks'],
                     'renewal time or halt rolled back')
            previous = base.file_hash(path)
            values.append(value)
        need(self.expected_tip == base.ref(files[-1]), 'renewal tip changed or not selected')
        return values

    def _activation_gate(self, binding, candidate, plan, clock):
        self._extension_guard(binding)
        values = self._chain(binding, candidate, clock)
        if not values:
            return base._activation_gate(binding, candidate, plan, clock)
        latest = values[-1]
        proof = read_ref(latest['storage_power_review'])
        need(clock() <= proof['valid_until_epoch'], 'renewed operating evidence expired')
        # A validation view only; never passed to seal/claim/witness/ledger code.
        view = deepcopy(binding)
        view['activation'] = latest['effective_activation']
        return base._activation_gate(view, candidate, plan, clock)

    def _proposal_backup(self, binding, certificate, proposal_backup):
        backup = read_ref(proposal_backup)
        if binding['mode'] != 'artificial_only':
            base._require_real_evidence(backup)
        destination = ('artificial_local' if binding['mode'] == 'artificial_only'
                       else 'Jnooo-cloud/masterarbeit-mas-pruning')
        need(backup.get('accepted') is True and backup.get('full_remote_reread') is True
             and backup.get('certificate') == certificate
             and backup.get('destination') == destination,
             'renewal proposal lacks private full reread')

    def renew(self, binding, candidate, plan, *, folder, control, clock,
              certificate, proposal_backup):
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            base._verify_confirmation(binding, folder, state)
            values = self._chain(binding, candidate, clock)
            required_hold = (state['completed_blocks'] if binding['mode'] == 'artificial_only' else 9540)
            need(values or state['completed_blocks'] == required_hold, 'first renewal requires R500')
            value = read_ref(certificate)
            previous = self.expected_tip['sha256'] if self.expected_tip else binding['sha256']
            fresh = self._certificate(binding, candidate, value, sequence=len(values)+1,
                                      previous=previous, clock=clock)
            need(clock() <= fresh['valid_until_epoch'], 'new operating evidence expired before publication')
            view = deepcopy(binding)
            view['activation'] = value['effective_activation']
            need(value['completed_blocks'] == state['completed_blocks']
                 and value['state_sha256'] == state['state_sha256'], 'renewal is not for current halt')
            need(not values or value['completed_blocks'] > values[-1]['completed_blocks'],
                 'a halt cannot be renewed twice')
            current_witness = sorted((Path(binding['witness']) / 'checkpoints').glob('*.json'))[-1]
            need(value['previous_witness'] == base.ref(current_witness), 'renewal witness is stale')
            self._proposal_backup(binding, certificate, proposal_backup)
            target = Path(folder) / 'operating-renewals' / f"{value['sequence']:06d}.json"
            base._activation_gate(view, candidate, plan, clock)
            need(clock() <= fresh['valid_until_epoch'], 'new operating evidence expired before publication')
            base._save(target, {'certificate': value, 'proposal': certificate,
                                'proposal_backup': proposal_backup})
            # A crash before publication remains detectable; no reset path exists.
            new_generation = base._publish(binding, folder, control, generation)
            return {'binding_sha256': binding['sha256'], 'state_sha256': state['state_sha256'],
                    'renewal': base.ref(target), 'witness_generation': new_generation,
                    'new_model_calls': 0, 'operating_context': self.context_ref}


    def _check_binding(self, binding, candidate, plan, *, folder, control, clock, dependencies=None):
        self._extension_guard(binding)
        base.gate._check_seal(binding)
        base.gate._check_seal(binding['inner_binding'])
        old = binding['inner_binding']
        origin = binding['origin']
        expected = base.Path(old['folder']).parent / 'technical-R00203'
        base._need(binding['schema'] == 'z52-technical-resume/v1' and binding['mode'] == candidate['mode'] and (binding['folder'] == str(base._path(folder)) == str(expected / 'live')) and (binding['witness'] == str(expected / 'witness')) and (binding['control'] == str(base._path(control)) == old['control'] == candidate['control_directory']) and (binding['claim_path'] == str(base._path(control) / base.CLAIM)), 'canonical technical identity differs')
        base._need(binding['candidate_sha256'] == old['candidate_sha256'] == candidate['sha256'] and binding['plan_hash'] == old['plan_hash'] == plan['plan_hash'] and (binding['execution_binding_sha256'] == base.gate.execution_binding(candidate)) and (binding['source_files'] == base.additional_sources()) and (binding['analysis_contract'] == old['analysis_contract']) and (origin['inner_binding_sha256'] == old['sha256']) and (binding['first_hold'] == origin['completed_blocks'] + 1), 'scientific/source identity changed')
        base.FileGuard(old['source_files'])()
        base._verify_originals(binding)
        base.secondary._preflight(binding, candidate, plan, control=control, clock=clock, dependencies=dependencies)
        base._analysis_contract(binding, candidate, plan)
        self._activation_gate(binding, candidate, plan, clock)


    def _runtime(self, binding, candidate, plan, clock, panel):
        base.gate.runtime_guard(candidate, clock=clock, panel=panel)
        base.FileGuard(binding['source_files'])()
        base._claim(binding, binding['control'])
        base._need(not (base.Path(binding['folder']) / 'STOP.json').exists(), 'persistent stop')
        self._activation_gate(binding, candidate, plan, clock)


    def pre_dispatch(self, binding, candidate, plan, *, folder, control, clock, section_end, coverage):
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            base._assert_current(binding, folder, control)
            state, *_ = base._dispatch_gate(binding, candidate, plan, folder, coverage, section_end, clock)
            return {'state_sha256': state['state_sha256'], 'section_end': section_end}


    def run_section(self, binding, candidate, plan, *, folder, control, section_end, coverage, loader, spatial_selector, temporal_selector, transport, checkpoint, clock, sleep=base.time.sleep):
        dependencies = dict(loader=loader, spatial_selector=spatial_selector, temporal_selector=temporal_selector, transport=transport, checkpoint=checkpoint)
        folder = base.Path(folder)
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock, dependencies=dependencies)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _, prefix, end, panel = base._dispatch_gate(binding, candidate, plan, folder, coverage, section_end, clock)
            base._save(folder / 'coverage' / f"{state['completed_blocks']:06d}.json", coverage)
            base._record_section(folder, section_end, 'admitted')
            generation = base._publish(binding, folder, control, generation)
            active = {'started': None, 'waits': []}
            adapter = None
    
            def measured_sleep(seconds):
                before = clock()
                sleep(seconds)
                after = clock()
                base._need(0 < seconds <= 30 and after > before, 'invalid retry sleep')
                active['waits'].append(dict(started_at=before, finished_at=after, requested_seconds=seconds))
    
            def guard(dispatch, snapshot):
                self._runtime(binding, candidate, plan, clock, panel)
                base._coverage(binding, coverage, clock, adapter, panel)
                base._save(folder / 'physical' / f"{dispatch['number']:06d}.json", dict(dispatch=dispatch, guard_passed=True, logical_wait_started_at=active['started'], guard_checked_at=clock(), sleep_intervals=base.deepcopy(active['waits'])))
                active['waits'] = []
            try:
                adapter = base._adapter(binding, folder, transport=transport, clock=clock, sleep=measured_sleep, guard=guard)
                for number in range(prefix, end):
                    block = base._blocks(plan)[number]
                    self._runtime(binding, candidate, plan, clock, panel)
                    base._coverage(binding, coverage, clock, adapter, panel)
                    directory = folder / 'blocks' / f'{number:06d}'
                    directory.mkdir()
                    recovering = number == binding['origin']['secondary_completed_blocks']
                    first_call = adapter.calls + 1
                    if recovering:
                        old_dir = base.Path(binding['inner_binding']['folder']) / 'blocks' / f'{number:06d}'
                        for path in old_dir.iterdir():
                            if path.is_file():
                                base.shutil.copyfile(path, directory / path.name)
                        public, private = (base.gate.read_json(directory / 'public.json'), base.gate.read_json(directory / 'reference.json'))
                        task = base.TaskInput(public['task_id'], public['question'], tuple(public['paragraphs']))
                        reference = base.AnswerReference(private['task_id'], tuple(private['answers']))
                        selection = base.gate.read_json(directory / 'selection.json')
                        done = binding['origin']['done_arms']
                        for arm in done:
                            base.shutil.copytree(old_dir / arm, directory / arm)
                    else:
                        done = []
                        base._save(directory / 'started.json', {'block': block, 'plan_hash': plan['plan_hash']})
                        task, reference = loader(block['task_id'])
                        base._need(type(task) is base.TaskInput and type(reference) is base.AnswerReference and (task.task_id == base.native.public_task_id(plan, block['task_id'])) and (reference.task_id == task.task_id), 'foreign task')
                        base._save(directory / 'public.json', base.asdict(task))
                        base._save(directory / 'reference.json', base.asdict(reference))
                        q = base.native._select_observed(spatial_selector, task, candidate=candidate, plan=plan, block=block, kind='spatial', directory=directory)
                        qt = base.native._select_observed(temporal_selector, task, candidate=candidate, plan=plan, block=block, kind='temporal', directory=directory) if panel == 'T' else None
                        selection = {'spatial_q': q, 'temporal_qst': qt}
                        base._save(directory / 'selection.json', selection)
    
                    def send(request):
                        active.update(started=clock(), waits=[])
                        before = adapter.calls
                        response = adapter(request)
                        if adapter.calls == before:
                            base._need(recovering and request.attempt_id in {s['logical_id'] for s in binding['origin']['seeds']}, 'unapproved answer replay')
                            base._save(folder / 'replays' / f"{len(list((folder / 'replays').glob('*.json'))) + 1:06d}.json", dict(logical_id=request.attempt_id, request_sha256=base.sha256(base.encoded(base.payload(request, producer_limit=1024))).hexdigest(), new_physical_calls=0, origin=adapter.states[request.attempt_id]['origin']))
                        return base.previous._normal_response(response, binding['mode'])
                    rows = []
                    for slot in block['slots']:
                        arm = slot['arm']
                        sd = directory / arm
                        if arm in done:
                            rows.append(base.gate.read_json(sd / 'result.json'))
                            continue
                        sd.mkdir()
                        run_id = plan['plan_hash'][:16] + ':' + slot['slot_id']
                        config, rounds, failed = base.native._configuration(candidate, block, arm, selection)
                        if config is None:
                            result = base.native._direct(task, reference, run_id, arm, 0 if arm == 'S' else block['tie_break_seed'], sd, send)
                        else:
                            base.execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id, journal_path=sd / 'journal.jsonl', producer_limit=1024, failure_policy=base.F01)
                            result, _ = base.native._mas_result(sd / 'journal.jsonl', config, task, reference, block)
                        row = base.native._row(candidate, block, slot, result, config, rounds, failed, run_id)
                        base._save(sd / 'result.json', row)
                        rows.append(row)
                    if recovering:
                        base._save(directory / 'replay.json', dict(original_partial_journal_sha256=base.file_hash(old_dir / binding['origin']['partial_arm'] / 'journal.jsonl'), original_selection_measurement_sha256=base.file_hash(old_dir / 'spatial-measurement.json'), continuous_arm_latency_available=False))
                    files = [p for p in directory.rglob('*') if p.is_file()]
                    for index in range(first_call, adapter.calls + 1):
                        files.extend((folder / 'dispatch').glob(f'{index:06d}-*.json'))
                        files.append(folder / 'physical' / f'{index:06d}.json')
                    if recovering:
                        files.extend((folder / 'replays').glob('*.json'))
                    base._save(directory / 'complete.json', dict(block=block, plan_hash=plan['plan_hash'], rows=rows, evidence={str(p.relative_to(folder)): base.file_hash(p) for p in files}))
                state, _ = base._inspect(binding, candidate, plan, folder)
                base._checkpoint(folder, state, checkpoint)
                base._record_section(folder, section_end, 'settled')
                base._publish(binding, folder, control, generation)
                return state
            except BaseException as error:
                try:
                    base._save(folder / 'STOP.json', dict(binding_sha256=binding['sha256'], error_type=type(error).__name__, retry_allowed=False, diagnostic=base.safe_exception_chain(error, clock)))
                    base._publish(binding, folder, control, generation)
                except BaseException as recording_error:
                    error.add_note('technical STOP/witness evidence failed: ' + type(recording_error).__name__)
                raise


    def prepare_panel_backup(self, binding, candidate, plan, panel, *, folder, control, clock, checkpoint):
        from .final_analysis import validate_rows
        base._need(panel in base.PANELS, 'secondary panel required')
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            rows = validate_rows(plan, panel, [r for r in state['rows'] if r['panel'] == panel])
            path = base.Path(folder) / 'panels' / panel / 'analysis.json'
            base._need(base.gate.read_json(path) == base._analysis(binding, plan, panel, rows, base._analysis_contract(binding, candidate, plan)), 'panel analysis differs')
            evidence = base._panel_evidence(plan, folder, panel)
            package = {**state, 'evidence': evidence}
            package.pop('state_sha256')
            package['state_sha256'] = base.canonical_hash(package)
            proof = checkpoint(package)
            base.gate.verify_archive(proof, evidence)
            value = dict(binding_sha256=binding['sha256'], panel=panel, analysis_sha256=base.file_hash(path), evidence=evidence, backup=proof)
            base._save(base.Path(folder) / 'panels' / panel / 'backup.json', value)
            base._publish(binding, folder, control, generation)
            return value


    def close_panel(self, binding, candidate, plan, panel, *, folder, control, clock, review, remote_backup):
        base._need(panel in base.PANELS, 'secondary panel required')
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            path = base.Path(folder) / 'panels' / panel / 'analysis.json'
            base._panel_review(binding, panel, path, review)
            prepared = base.gate.read_json(base.Path(folder) / 'panels' / panel / 'backup.json')
            base._need(prepared['binding_sha256'] == binding['sha256'] and prepared['panel'] == panel and (prepared['analysis_sha256'] == base.file_hash(path)) and (prepared['evidence'] == base._panel_evidence(plan, folder, panel)), 'panel backup differs')
            base.gate.verify_archive(prepared['backup'], prepared['evidence'])
            base._verify_panel_remote(binding, panel, base.file_hash(path), prepared['backup'], remote_backup)
            base._save(base.Path(folder) / 'panels' / panel / 'complete.json', {**prepared, 'review': review, 'remote_backup': remote_backup})
            base._publish(binding, folder, control, generation)
            return {'panel': panel, 'closed': True}


    def inspect_study(self, binding, candidate, plan, *, folder, control, clock):
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            base._assert_current(binding, folder, control)
            return base._inspect(binding, candidate, plan, folder)[0]


    def collect_panel(self, binding, candidate, plan, panel, *, folder, control, clock):
        from .final_analysis import validate_rows
        base._need(panel in base.PANELS, 'P is adopted and cannot be collected or dispatched here')
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            return validate_rows(plan, panel, [r for r in state['rows'] if r['panel'] == panel])


    def analyze_panel(self, binding, candidate, plan, panel, *, folder, control, clock):
        """Read original complete rows and run the frozen analysis, under study lock."""
        from .final_analysis import analyze_panel as original_analysis, validate_rows
        base._need(panel in base.PANELS, 'secondary panel required')
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            rows = validate_rows(plan, panel, [r for r in state['rows'] if r['panel'] == panel])
            contract = base._analysis_contract(binding, candidate, plan)
            result = base._analysis(binding, plan, panel, rows, contract)
            path = base.Path(folder) / 'panels' / panel / 'analysis.json'
            base._save(path, result)
            base._publish(binding, folder, control, generation)
            return {'path': str(path), 'sha256': base.file_hash(path)}


    def confirm_hold(self, binding, candidate, plan, *, folder, control, clock, review, backup):
        with base.native.study_lock(control):
            self._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
            base._claim(binding, control)
            generation = base._assert_current(binding, folder, control)
            state, _ = base._inspect(binding, candidate, plan, folder)
            base._verify_receipt(folder, state)
            path = base.Path(folder) / 'confirmations' / f"{state['completed_blocks']:06d}.json"
            base._save(path, {'review': review, 'backup': backup})
            base._verify_confirmation(binding, folder, state)
            base._publish(binding, folder, control, generation)
            return state['state_sha256']
