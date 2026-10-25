"""Bounded T/F runtime amendment; native scientific and ledger identities remain.

Only the repeated archive-member checks are routed through an explicit cache.
Start, checkpoint, hold and panel-closeout verification stays in the original
rate-stop implementation. No old module is modified or patched at runtime.
"""
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
import math
import shutil
import time

from communication_pruning.contracts import TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01
from communication_pruning.openrouter import encoded, payload
from communication_pruning.study import FileGuard, file_hash
from communication_pruning.technical_retry import ref
from . import final_rate_stop_resume as rate
from . import final_coverage_resume as coverage_module
from . import final_technical_resume as base
from . import final_operating_renewal as operating
from . import final_r125_resume as previous
from . import final_secondary as secondary, final_execution as native, final_preflight as gate
from .final_plan import canonical_hash
from .tf_archive_guard import ArchiveVerificationCache

PLAN_SHA256 = '8776fdf9af9c3902c603564cc494cd317fda4f3d3eabd3d619d2d49da0973c51'
AUTHOR_SHA256 = '17c468bb7759b2267c2a62288c04a869acc39f2f6083717873ff54e861d17169'
PLAN_REVISION = 'b5e8bb927f73e26bf102ee89beb400bd0158d24e'
SOURCE_NAMES = ('study_preparation/tf_archive_guard.py',
    'study_preparation/final_tf_performance.py', 'study_preparation/final_tf_performance_operator.py',
    'tests/test_tf_archive_guard.py', 'tests/test_final_tf_performance.py',
    'tests/test_final_tf_performance_operator.py')
need = _need = secondary._need
read_ref = operating.read_ref
PANELS = secondary.PANELS


def source_files(binding):
    root = Path(__file__).resolve().parents[1]
    paths = [root / name for name in SOURCE_NAMES]
    if binding['mode'] != 'artificial_only':
        paths.append(Path(binding['folder']).parent / 'activation/tf-performance/tf_operation.py')
    return {str(path.resolve()): file_hash(path) for path in paths}


def prepare_version(binding, candidate, plan, *, source_manifest, source_review, source_backup):
    """Pure metadata constructor; neither accepts nor activates its own result."""
    project = Path(__file__).resolve().parents[3]
    return gate.seal(dict(schema='z52-tf-performance-version/v1', mode=binding['mode'],
        native_binding_sha256=binding['sha256'], candidate_sha256=candidate['sha256'],
        plan_hash=plan['plan_hash'], owner=binding['owner'], panels=['T', 'F'],
        source_files=source_files(binding), source_manifest=deepcopy(source_manifest),
        source_review=deepcopy(source_review), source_backup=deepcopy(source_backup),
        plan_revision=PLAN_REVISION,
        performance_plan=dict(path=str(project/'project/dsr/Z52-TF-PERFORMANCE-PLAN.md'), sha256=PLAN_SHA256),
        author_request=dict(path=str(project/'output/studienfortsetzung-2026-09-30/tf-performance-prep/REQUEST-001.json'),
                            sha256=AUTHOR_SHA256)))


def version_identity(version):
    return canonical_hash({k: v for k, v in version.items()
                           if k not in ('sha256', 'source_review', 'source_backup')})


def check_version(version, binding, candidate, plan):
    """Full current source, authority and acceptance verification at every gate."""
    gate._check_seal(version)
    expected = prepare_version(binding, candidate, plan, source_manifest=version['source_manifest'],
        source_review=version['source_review'], source_backup=version['source_backup'])
    need(version == expected, 'T/F version, exact sources or authority changed')
    FileGuard(version['source_files'])()
    gate.evidence_file(version['performance_plan']); gate.evidence_file(version['author_request'])
    manifest = read_ref(version['source_manifest'])
    need(manifest.get('schema') == 'z52-tf-performance-sources/v1'
         and manifest.get('files') == version['source_files'], 'T/F manifest source set differs')
    members = {f'source-{i:04d}': h for i, (_, h) in enumerate(sorted(version['source_files'].items()))}
    need(manifest.get('members') == members, 'T/F archive membership differs')
    # This new, small source archive remains a complete check. The four old
    # repeated archives alone receive the P2 cache optimization.
    gate.verify_archive(manifest['archive'], members)
    review, backup = read_ref(version['source_review']), read_ref(version['source_backup'])
    for record in (review, backup):
        if binding['mode'] != 'artificial_only': secondary._require_real_evidence(record)
        need(record.get('accepted') is True and record.get('version_identity') == version_identity(version)
             and record.get('source_manifest') == version['source_manifest'], 'T/F source acceptance differs')
    need(review.get('not_implementation_author') is True and isinstance(review.get('reviewer'), str)
         and review['reviewer'].strip() and review['reviewer'] != binding['owner']
         and review.get('criteria') == {key: 'accepted' for key in ('P1', 'P2', 'P3', 'P4', 'P5')},
         'T/F separate exact P1-P5 source acceptance required')
    need(backup.get('full_remote_reread') is True and backup.get('members') == members
         and backup.get('archive_sha256') == manifest['archive']['sha256']
         and backup.get('destination') == ('artificial_local' if binding['mode'] == 'artificial_only'
              else 'Jnooo-cloud/masterarbeit-mas-pruning'), 'T/F sources require exact private full reread')
    return manifest


def _transition_path(binding):
    return Path(binding['folder'])/'tf-performance/transition.json'


def _transition_snapshot(version, binding, candidate, plan, *, folder, control, clock):
    """Only called under the original exclusive study lock; never dispatches."""
    check_version(version, binding, candidate, plan)
    rate._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
    rate._claim(binding, control); generation = rate._assert_current(binding, folder, control)
    state, adapter = rate._inspect(binding, candidate, plan, folder)
    boundary = plan['counts']['P'] + plan['counts']['R']
    need(state['completed_blocks'] == boundary and state['secondary_completed_blocks'] == plan['counts']['R'],
         'T/F handoff requires the completed R panel before any T block')
    if binding['mode'] != 'artificial_only':
        need(boundary == 11992 and plan['counts'] == {'P': 9040, 'R': 2952, 'T': 2952, 'F': 2952},
             'actual T/F panel boundary changed')
    rate._verify_receipt(folder, state); rate._verify_confirmation(binding, folder, state)
    rate._verify_panel_closeout(binding, candidate, plan, folder, 'R')
    return gate.seal(dict(schema='z52-tf-performance-transition/v1',
        version_sha256=version['sha256'], native_binding_sha256=binding['sha256'],
        candidate_sha256=candidate['sha256'], plan_hash=plan['plan_hash'], owner=binding['owner'],
        completed_blocks=boundary, next_global_block=boundary+1, next_panel='T',
        next_section_end=rate._next_end(binding, candidate, state), state_sha256=state['state_sha256'],
        budget=deepcopy(adapter.snapshot()), levels=deepcopy(state['levels']), generation=generation,
        claim=ref(binding['claim_path']), R_closeout=ref(Path(folder)/'panels/R/complete.json'),
        confirmation=ref(Path(folder)/'confirmations'/f'{boundary:06d}.json'),
        receipt=ref(rate._receipt_path(folder, state)), new_model_calls=0,
        native_folder=binding['folder'], native_control=binding['control'], native_witness=binding['witness']))


def prepare_transition(version, binding, candidate, plan, *, folder, control, clock):
    with native.study_lock(control):
        need(not _transition_path(binding).exists(), 'T/F transition already exists')
        return _transition_snapshot(version, binding, candidate, plan, folder=folder, control=control, clock=clock)


def _acceptance(version, binding, proposal, review, backup):
    value = read_ref(proposal); gate._check_seal(value)
    need(value.get('version_sha256') == version['sha256']
         and value.get('native_binding_sha256') == binding['sha256'] and value.get('new_model_calls') == 0,
         'foreign T/F handoff proposal')
    for reference in (review, backup):
        record = read_ref(reference)
        if binding['mode'] != 'artificial_only': secondary._require_real_evidence(record)
        need(record.get('accepted') is True and record.get('proposal') == proposal
             and record.get('version_sha256') == version['sha256'], 'T/F handoff acceptance differs')
    checked = read_ref(review)
    need(checked.get('not_implementation_author') is True and isinstance(checked.get('reviewer'), str)
         and checked['reviewer'].strip() and checked['reviewer'] != binding['owner']
         and checked.get('P7') == 'accepted', 'separate actual R/T handoff review required')
    saved = read_ref(backup)
    need(saved.get('full_remote_reread') is True and saved.get('proposal_sha256') == proposal['sha256']
         and saved.get('destination') == ('artificial_local' if binding['mode'] == 'artificial_only'
              else 'Jnooo-cloud/masterarbeit-mas-pruning'), 'T/F handoff proposal requires private full reread')
    return value


def activate_transition(version, binding, candidate, plan, *, folder, control, clock, proposal, review, backup):
    """Explicit zero-call append-only handoff; never reinitializes a native ledger."""
    with native.study_lock(control):
        need(not _transition_path(binding).exists(), 'T/F transition already exists')
        expected = _transition_snapshot(version, binding, candidate, plan, folder=folder, control=control, clock=clock)
        value = _acceptance(version, binding, proposal, review, backup)
        need(value == expected, 'R state changed since T/F handoff proposal')
        envelope = dict(version=deepcopy(version), proposal=proposal, review=review, backup=backup)
        rate._save(_transition_path(binding), envelope)
        rate._publish(binding, folder, control, value['generation'])
        # No ledger, native identity, counter, cost, reserve or response changes.
        after, adapter = rate._inspect(binding, candidate, plan, folder)
        need(after['state_sha256'] == value['state_sha256'] and adapter.snapshot() == value['budget'],
             'T/F zero-call handoff changed native accounting or state')
        return dict(transition=ref(_transition_path(binding)), state_sha256=after['state_sha256'], new_model_calls=0)


def check_transition(version, binding):
    envelope = gate.read_json(_transition_path(binding))
    need(set(envelope) == {'version', 'proposal', 'review', 'backup'} and envelope['version'] == version,
         'T/F accepted version or transition changed')
    value = _acceptance(version, binding, envelope['proposal'], envelope['review'], envelope['backup'])
    for key in ('claim', 'R_closeout', 'confirmation', 'receipt'):
        gate.evidence_file(value[key])
    return value


def pre_dispatch(version, binding, candidate, plan, *, folder, control, clock, section_end, coverage):
    with native.study_lock(control):
        check_version(version, binding, candidate, plan); check_transition(version, binding)
        rate._check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock)
        rate._claim(binding, control); rate._assert_current(binding, folder, control)
        state, _, _, _, panel = rate._dispatch_gate(binding, candidate, plan, folder, coverage, section_end, clock)
        need(panel in ('T', 'F'), 'performance execution is limited to T and F')
        return {'state_sha256': state['state_sha256'], 'section_end': section_end,
                'tf_version_sha256': version['sha256']}


class RuntimeContext:
    def __init__(self, version, *, cache=None):
        self.version = deepcopy(version)
        self.cache = ArchiveVerificationCache(max_entries=32) if cache is None else cache

    def runtime(self, binding, candidate, plan, clock, panel):
        need(panel in ('T', 'F'), 'performance execution is limited to T and F')
        check_version(self.version, binding, candidate, plan); check_transition(self.version, binding)
        gate.runtime_guard(candidate, clock=clock, panel=panel)
        FileGuard(binding['source_files'])(); rate._claim(binding, binding['control'])
        need(not (Path(binding['folder'])/'STOP.json').exists(), 'persistent stop')
        self._rate_activation(binding, candidate, plan, clock)


    def _rate_predecessor(self, binding, candidate, plan, clock):
        old = binding['inner_binding']
        _need(binding['operating_context'] == old['operating_context'] and binding['operating_tip'] == old['operating_tip'], 'predecessor operating evidence differs')
        return self._coverage_activation(old, candidate, plan, clock)

    def _rate_activation(self, binding, candidate, plan, clock):
        self._rate_predecessor(binding, candidate, plan, clock)
        if binding['mode'] == 'artificial_only':
            _need(binding['activation'] is None, 'artificial connection cannot carry live activation')
            return
        value = gate.read_json(gate.evidence_file(binding['activation']))
        secondary._require_real_evidence(value)
        _need(value.get('schema') == 'z52-rate-stop-activation/v1' and value.get('connection_sha256') == secondary.connection_hash(binding) and (value.get('executor') == binding['owner']) and (value.get('send_enabled') is True) and (value.get('continuation_authority') == 'Jannik-2026-09-29-rate-stop-decision') and (value.get('plan_sha256') == '3233234f349863e44c942c49305bdac1f8756fd64b9af27b6b25c26e3db88a5f'), 'exact authorized rate-stop connection missing')
        manifest = gate.read_json(gate.evidence_file(value['source_manifest']))
        _need(manifest['files'] == binding['source_files'], 'rate-stop source manifest differs')
        _need(manifest['members'] == {f'source-{i:04d}': h for i, (_, h) in enumerate(sorted(manifest['files'].items()))}, 'rate-stop source archive members differ')
        self.cache.verify_archive(manifest['archive'], manifest['members'])
        review = gate.read_json(gate.evidence_file(value['source_review']))
        backup = gate.read_json(gate.evidence_file(value['source_backup']))
        for record in (review, backup):
            secondary._require_real_evidence(record)
            _need(record.get('accepted') is True and record.get('connection_sha256') == secondary.connection_hash(binding) and (record.get('source_manifest') == value['source_manifest']), 'rate-stop source acceptance differs')
        _need(review.get('not_implementation_author') is True and isinstance(review.get('reviewer'), str) and review['reviewer'].strip() and (review['reviewer'] != binding['owner']), 'separate rate-stop review required')
        _need(backup.get('destination') == 'Jnooo-cloud/masterarbeit-mas-pruning' and backup.get('full_remote_reread') is True and (backup.get('members') == manifest['members']) and (backup.get('archive_sha256') == manifest['archive']['sha256']), 'rate-stop source full reread required')
        project = Path(__file__).resolve().parents[3]
        old_operation = Path(binding['inner_binding']['folder']).parent / 'operation'
        for key, path, checksum in (('decision', project / 'output/studienfortsetzung-2026-09-29/rate-stop-continuation-decision/ENTSCHEIDUNG-001.md', '616873b1c78ce4a4566121b8bd258b9fb27fdcf683931c1e9951b43a26801b3f'), ('author_approval', old_operation / 'RATE-STOP-EXPLICIT-USER-APPROVAL-001.json', 'd48b6d31042a40cf6e21b4818a84f4dccc1befc9d78b42a30b1ecfb9fa0be979'), ('plan', project / 'project/dsr/Z52-RATE-STOP-FORTSETZUNG-PLAN.md', '3233234f349863e44c942c49305bdac1f8756fd64b9af27b6b25c26e3db88a5f'), ('stop_backup', old_operation / 'STOP-R01589-PARTIAL-R01590-BACKUP-VERIFICATION-001.json', '124e88fe60817182446b89953cddb486e419843c3d9798fca75cce59133c8a9b')):
            _need(value.get(key) == dict(path=str(path), sha256=checksum), 'exact rate-stop authority/evidence differs')
            gate.evidence_file(value[key])

    def _coverage_activation(self, binding, candidate, plan, clock):
        self._coverage_predecessor(binding, candidate, plan, clock)
        if binding['mode'] == 'artificial_only':
            _need(binding['activation'] is None, 'artificial connection cannot carry live activation')
            return
        value = gate.read_json(gate.evidence_file(binding['activation']))
        secondary._require_real_evidence(value)
        _need(value.get('schema') == 'z52-coverage-activation/v1' and value.get('connection_sha256') == secondary.connection_hash(binding) and (value.get('executor') == binding['owner']) and (value.get('send_enabled') is True) and (value.get('continuation_authority') == 'existing-Jannik-2026-09-26-continuation') and (value.get('plan_sha256') == '204f3fa88a0a1ba241af7bd7ceccf5006108dff4a776b25ba1a1164c45566e90'), 'exact authorized coverage connection missing')
        manifest = gate.read_json(gate.evidence_file(value['source_manifest']))
        _need(manifest['files'] == binding['source_files'], 'coverage source manifest differs')
        _need(manifest['members'] == {f'source-{i:04d}': h for i, (_, h) in enumerate(sorted(manifest['files'].items()))}, 'coverage source archive members differ')
        self.cache.verify_archive(manifest['archive'], manifest['members'])
        review = gate.read_json(gate.evidence_file(value['source_review']))
        backup = gate.read_json(gate.evidence_file(value['source_backup']))
        for record in (review, backup):
            secondary._require_real_evidence(record)
            _need(record.get('accepted') is True and record.get('connection_sha256') == secondary.connection_hash(binding) and (record.get('source_manifest') == value['source_manifest']), 'coverage source acceptance differs')
        _need(review.get('not_implementation_author') is True and isinstance(review.get('reviewer'), str) and review['reviewer'].strip() and (review['reviewer'] != binding['owner']), 'separate coverage review required')
        _need(backup.get('destination') == 'Jnooo-cloud/masterarbeit-mas-pruning' and backup.get('full_remote_reread') is True and (backup.get('members') == manifest['members']) and (backup.get('archive_sha256') == manifest['archive']['sha256']), 'coverage source full reread required')
        for key, expected in (('stop_review', 'd1fa6ffc4f92703eb00d374768be73f12f10415e253f2a9d70e71c0d672c2851'), ('stop_backup', 'b8ab1dc5c298abd18b5303cf7deca8eccd77a0ace5bb04f85a8975aa0e7b3ad7'), ('supplement_backup', '42fb5cd61cf000df4970fd195a1035f8790a4b3ff073de50597295949b5a951d')):
            _need(value[key]['sha256'] == expected, 'wrong stopped-state acceptance')
            gate.evidence_file(value[key])

    def _technical_activation(self, binding, candidate, plan, clock):
        self._secondary_activation(binding, candidate, plan, clock)
        if binding['mode'] != 'artificial_only':
            value = gate.read_json(gate.evidence_file(binding['activation']))
            _need(value.get('technical_completion_authorization') == 'Jannik-2026-09-26' and value.get('technical_retries') == {'per_logical': 2, 'global': 20, 'wait_seconds': [30, 120]} and (value.get('origin_sha256') == canonical_hash(binding['origin'])), 'specific technical activation missing')

    def _secondary_activation(self, binding, candidate, plan, clock):
        if binding['mode'] == 'artificial_only':
            _need(binding['activation'] is None, 'artificial tests cannot carry live activation')
            return
        activation = gate.read_json(gate.evidence_file(binding['activation']))
        secondary._require_real_evidence(activation)
        secondary._require_real_evidence(binding['predecessor'])
        secondary._verify_live_predecessor(binding['predecessor'])
        secondary._require_real_evidence(gate.read_json(gate.evidence_file(candidate['author_release'])))
        _need(activation.get('schema') == 'z52-secondary-activation/v1' and activation.get('author') == 'Jannik' and (activation.get('explicit_authorization') is True) and (activation.get('send_enabled') is True) and (activation.get('study_frozen') is True) and (activation.get('connection_sha256') == secondary.connection_hash(binding)) and (activation.get('executor') == binding['owner']) and (activation.get('panels') == list(PANELS)) and isinstance(activation.get('approval_reference'), str) and bool(activation['approval_reference'].strip()), 'specific author activation for exact secondary connection missing')
        for panel in PANELS:
            gate._release(candidate, panel)
        scientific = gate.read_json(gate.evidence_file(binding['predecessor']['scientific_candidate']))
        _need(binding['predecessor']['scientific_candidate']['sha256'] == '05a2c6f3d2b44734c978f396fe9ee19984b5b6883d0b876c127cb3e4ea569d45', 'only the actual Z50-NACHARBEIT scientific candidate may continue')
        for key in ('bindings', 'source_files', 'documents', 'fixed_config_id', 'fixed_rounds', 'direct_prompt', 'section_ends'):
            _need(candidate[key] == scientific[key], 'scientific candidate field changed: ' + key)
        expected_budget = deepcopy(scientific['budget'])
        expected_budget['unresolved'] = True
        _need(candidate['budget'] == expected_budget, 'historical accounting caps/positions changed')
        _need(plan['plan_hash'] == '50d4c906a74daf4810511ddaec90218d26dd9897ccd9c9fb5f9cf1b532d23539' and plan['counts'] == {'P': 9040, 'R': 2952, 'T': 2952, 'F': 2952}, 'scientific plan changed')
        _need(candidate['calendar'] == {'start_epoch': 1789937789.191509, 'end_epoch': 1791147389.191509, 'maximum_duration_seconds': 1209600, 'origin': 'author_bound'}, 'original shared calendar changed')
        _need(binding['predecessor']['state_sha256'] == '960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6' and binding['predecessor']['analysis']['sha256'] == 'fc4be29676749d7611d7c3f0d11e912193e4588609acb5d4734a15c387dcba65', 'actual adopted P completion identity changed')
        _need(activation.get('data_rights') == {'public_question_context': True, 'gold_local_only': True, 'new_training_or_fit': False, 'model': 'google/gemini-2.5-flash-lite', 'provider': 'google-vertex/eu'}, 'explicit unchanged exposure rights required')
        _need(activation.get('account_policy') == 'next_whole_block_covered_ongoing_topups_by_Jannik', 'account coverage and ongoing funding responsibility must be explicit')
        rights = activation.get('backup_rights', {})
        _need(rights.get('private_destination') == 'Jnooo-cloud/masterarbeit-mas-pruning' and rights.get('secondary_payload_explicitly_authorized') is True and (rights.get('includes_questions_responses_local_references_costs_reviews') is True) and isinstance(rights.get('approval_reference'), str) and bool(rights['approval_reference'].strip()), 'secondary private backup rights not bound')
        for name in ('source_review', 'runtime_review', 'storage_power_review', 'initial_backup', 'extension_backup'):
            record = gate.read_json(gate.evidence_file(activation[name]))
            secondary._require_real_evidence(record)
            _need(record.get('connection_sha256') == secondary.connection_hash(binding) and record.get('accepted') is True and (record.get('executor') == binding['owner']) and (type(record.get('checked_epoch')) in (int, float)) and (type(record.get('valid_until_epoch')) in (int, float)) and math.isfinite(record['checked_epoch']) and math.isfinite(record['valid_until_epoch']) and (candidate['calendar']['start_epoch'] <= record['checked_epoch'] <= clock() <= record['valid_until_epoch'] <= candidate['calendar']['end_epoch']), 'missing or stale actual activation input: ' + name)
            if name == 'initial_backup':
                _need(record.get('destination') == rights['private_destination'] and record.get('full_remote_reread') is True and (record.get('archive_sha256') == candidate['source_backup']['sha256']) and (record.get('members') == candidate['source_backup']['members']), 'exact start archive lacks bound remote reread')
            if name == 'extension_backup':
                self._verify_extension_backup(binding, record)
            if name == 'source_review':
                _need(record.get('reviewer') != binding['owner'] and isinstance(record.get('reviewer'), str) and (record.get('not_implementation_author') is True) and (record.get('additive_sources') == binding['source_files']), 'separate exact implementation review missing')
        marker = gate.read_json(gate.evidence_file(activation['architecture_installation']))
        _need(activation['architecture_installation']['sha256'] == '0d628ac1b175b0fc5cf630e2511de8a25020c9bc432d31db055c43f51fc158c4', 'installed architecture identity changed')
        _need(isinstance(marker, dict), 'installation metadata unavailable')

    def _verify_extension_backup(self, binding, record):
        """Reread every additive/installed dependency byte, plus bind remote receipt.

        The remote record is evidence supplied by the sole executor, not a network
        check or an authentication mechanism. The local archive is actually opened
        and every member is hashed here; a hash-only source list cannot pass.
        """
        if binding['mode'] != 'artificial_only':
            secondary._require_real_evidence(record)
        expected = {f'extension-{index:04d}': checksum for index, (_, checksum) in enumerate(sorted(binding['source_files'].items()))}
        _need(record.get('source_files') == binding['source_files'], 'extension backup source mapping differs')
        archive = record.get('local_archive')
        self.cache.verify_archive(archive, expected)
        remote = record.get('remote_receipt', {})
        _need(remote.get('destination') == 'Jnooo-cloud/masterarbeit-mas-pruning' and remote.get('archive_sha256') == archive['sha256'] and (remote.get('members') == expected) and (remote.get('full_remote_reread') is True), 'extension source archive lacks exact remote reread receipt')
        return expected

    def _coverage_predecessor(self, binding, candidate, plan, clock):
        old = binding['inner_binding']
        if binding['mode'] == 'artificial_only':
            need(binding['operating_context'] is None and binding['operating_tip'] is None,
                 'artificial coverage connection cannot carry live operating evidence')
            return self._technical_activation(old, candidate, plan, clock)
        context = TFOperatingContext(binding['operating_context'], expected_tip=binding['operating_tip'], runtime_context=self)
        return context._activation_gate(old, candidate, plan, clock)


class TFOperatingContext(operating.OperatingContext):
    def __init__(self, context_ref, *, expected_tip=None, runtime_context):
        super().__init__(context_ref, expected_tip=expected_tip)
        self.runtime_context = runtime_context
        self.cache = runtime_context.cache

    def _extension_guard(self, binding):
        need(read_ref(self.context_ref) == self.spec, 'operating context changed')
        need(set(self.spec) == {'schema', 'binding_sha256', 'source_manifest', 'source_review', 'source_backup'} and self.spec['schema'] == 'z52-operating-context/v1' and (self.spec['binding_sha256'] == binding['sha256']), 'foreign operating context')
        manifest = read_ref(self.spec['source_manifest'])
        root = Path(operating.__file__).resolve().parent.parent
        expected = {str(Path(operating.__file__).resolve()), str(root / 'study_preparation/final_operating_renewal_operator.py'), str(root / 'tests/test_final_operating_renewal.py'), str(root / 'tests/test_final_operating_renewal_operator.py'), str(Path(binding['folder']).parent / 'operating-renewal/activation/operating_operation.py')}
        need(manifest.get('schema') == 'z52-operating-sources/v1' and set(manifest.get('files', {})) == expected, 'incomplete operating source manifest')
        need(manifest.get('members') == {f'source-{i:04d}': checksum for i, (_, checksum) in enumerate(sorted(manifest['files'].items()))}, 'operating archive does not bind every source')
        base.FileGuard(manifest['files'])()
        base._path(manifest['archive']['path'])
        self.cache.verify_archive(manifest['archive'], manifest['members'])
        review = read_ref(self.spec['source_review'])
        backup = read_ref(self.spec['source_backup'])
        if binding['mode'] != 'artificial_only':
            base._require_real_evidence(self.spec)
            base._require_real_evidence(review)
            base._require_real_evidence(backup)
        need(review.get('accepted') is True and review.get('not_implementation_author') is True and isinstance(review.get('reviewer'), str) and review['reviewer'].strip() and (review['reviewer'] != binding['owner']) and (review.get('binding_sha256') == binding['sha256']) and (review.get('source_manifest') == self.spec['source_manifest']) and (review.get('files') == manifest['files']), 'separate exact operating source review required')
        destination = 'artificial_local' if binding['mode'] == 'artificial_only' else 'Jnooo-cloud/masterarbeit-mas-pruning'
        need(backup.get('accepted') is True and backup.get('full_remote_reread') is True and (backup.get('source_manifest') == self.spec['source_manifest']) and (backup.get('archive_sha256') == manifest['archive']['sha256']) and (backup.get('members') == manifest['members']) and (backup.get('destination') == destination), 'operating sources lack exact remote reread')
        return manifest

    def _activation_gate(self, binding, candidate, plan, clock):
        self._extension_guard(binding)
        values = self._chain(binding, candidate, clock)
        if not values:
            return self.runtime_context._technical_activation(binding, candidate, plan, clock)
        latest = values[-1]
        proof = read_ref(latest['storage_power_review'])
        need(clock() <= proof['valid_until_epoch'], 'renewed operating evidence expired')
        view = deepcopy(binding)
        view['activation'] = latest['effective_activation']
        return self.runtime_context._technical_activation(view, candidate, plan, clock)


_check_binding = rate._check_binding
_claim = rate._claim
_assert_current = rate._assert_current
_dispatch_gate = rate._dispatch_gate
_save = rate._save
_record_section = rate._record_section
_publish = rate._publish
_adapter = rate._adapter
_coverage = rate._coverage
_blocks = rate._blocks
_inspect = rate._inspect
_checkpoint = rate._checkpoint
safe_exception_chain = rate.safe_exception_chain

def _record_tf_section(folder, section_end, status, version, transition):
    path = Path(folder)/'sections'
    index = len(list(path.glob('*.json')))
    _save(path/f'{index:06d}.json', dict(section_id='section-'+str(section_end), status=status,
        tf_version_sha256=version['sha256'], tf_transition_sha256=transition['sha256']))


def run_section(version, binding, candidate, plan, *, folder, control, section_end, coverage, loader, spatial_selector, temporal_selector, transport, checkpoint, clock, sleep=time.sleep, context=None):
    context = RuntimeContext(version) if context is None else context
    need(type(context) is RuntimeContext and context.version == version, 'foreign T/F runtime context')
    if binding['mode'] != 'artificial_only':
        need(type(context.cache) is ArchiveVerificationCache, 'foreign live archive cache')
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, temporal_selector=temporal_selector, transport=transport, checkpoint=checkpoint)
    folder = Path(folder)
    with native.study_lock(control):
        check_version(version, binding, candidate, plan); transition = check_transition(version, binding)
        _check_binding(binding, candidate, plan, folder=folder, control=control, clock=clock, dependencies=dependencies)
        _claim(binding, control)
        generation = _assert_current(binding, folder, control)
        state, _, prefix, end, panel = _dispatch_gate(binding, candidate, plan, folder, coverage, section_end, clock)
        need(panel in ('T', 'F'), 'performance execution is limited to T and F')
        _save(folder / 'coverage' / f"{state['completed_blocks']:06d}.json", coverage)
        _record_tf_section(folder, section_end, 'admitted', version, transition)
        generation = _publish(binding, folder, control, generation)
        active = {'started': None, 'waits': []}
        adapter = None

        def measured_sleep(seconds):
            before = clock()
            sleep(seconds)
            after = clock()
            _need(0 < seconds <= 30 and after > before, 'invalid retry sleep')
            active['waits'].append(dict(started_at=before, finished_at=after, requested_seconds=seconds))

        def guard(dispatch, snapshot):
            context.runtime(binding, candidate, plan, clock, panel)
            _coverage(binding, coverage, clock, adapter, panel)
            _save(folder / 'physical' / f"{dispatch['number']:06d}.json", dict(dispatch=dispatch, guard_passed=True, logical_wait_started_at=active['started'], guard_checked_at=clock(), sleep_intervals=deepcopy(active['waits']), tf_version_sha256=version['sha256'], tf_transition_sha256=transition['sha256']))
            active['waits'] = []
        try:
            adapter = _adapter(binding, folder, transport=transport, clock=clock, sleep=measured_sleep, guard=guard)
            for number in range(prefix, end):
                block = _blocks(plan)[number]
                context.runtime(binding, candidate, plan, clock, panel)
                _coverage(binding, coverage, clock, adapter, panel)
                directory = folder / 'blocks' / f'{number:06d}'
                directory.mkdir()
                _save(directory / 'tf-performance.json', dict(version=version, transition=transition, section_end=section_end))
                recovering = number == binding['origin']['secondary_completed_blocks']
                first_call = adapter.calls + 1
                if recovering:
                    old_dir = Path(binding['inner_binding']['folder']) / 'blocks' / f'{number:06d}'
                    for path in old_dir.iterdir():
                        if path.is_file():
                            shutil.copyfile(path, directory / path.name)
                    public, private = (gate.read_json(directory / 'public.json'), gate.read_json(directory / 'reference.json'))
                    task = TaskInput(public['task_id'], public['question'], tuple(public['paragraphs']))
                    reference = AnswerReference(private['task_id'], tuple(private['answers']))
                    selection = gate.read_json(directory / 'selection.json')
                    done = binding['origin']['done_arms']
                    for arm in done:
                        shutil.copytree(old_dir / arm, directory / arm)
                else:
                    done = []
                    _save(directory / 'started.json', {'block': block, 'plan_hash': plan['plan_hash']})
                    task, reference = loader(block['task_id'])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference and (task.task_id == native.public_task_id(plan, block['task_id'])) and (reference.task_id == task.task_id), 'foreign task')
                    _save(directory / 'public.json', asdict(task))
                    _save(directory / 'reference.json', asdict(reference))
                    q = native._select_observed(spatial_selector, task, candidate=candidate, plan=plan, block=block, kind='spatial', directory=directory)
                    qt = native._select_observed(temporal_selector, task, candidate=candidate, plan=plan, block=block, kind='temporal', directory=directory) if panel == 'T' else None
                    selection = {'spatial_q': q, 'temporal_qst': qt}
                    _save(directory / 'selection.json', selection)

                def send(request):
                    active.update(started=clock(), waits=[])
                    before = adapter.calls
                    response = adapter(request)
                    if adapter.calls == before:
                        _need(recovering and request.attempt_id in {s['logical_id'] for s in binding['origin']['replays']}, 'unapproved answer replay')
                        _save(folder / 'replays' / f"{len(list((folder / 'replays').glob('*.json'))) + 1:06d}.json", dict(logical_id=request.attempt_id, request_sha256=sha256(encoded(payload(request, producer_limit=1024))).hexdigest(), new_physical_calls=0, origin=adapter.states[request.attempt_id]['origin']))
                    return previous._normal_response(response, binding['mode'])
                rows = []
                for slot in block['slots']:
                    arm = slot['arm']
                    sd = directory / arm
                    if arm in done:
                        rows.append(gate.read_json(sd / 'result.json'))
                        continue
                    sd.mkdir()
                    run_id = plan['plan_hash'][:16] + ':' + slot['slot_id']
                    config, rounds, failed = native._configuration(candidate, block, arm, selection)
                    if config is None:
                        result = native._direct(task, reference, run_id, arm, 0 if arm == 'S' else block['tie_break_seed'], sd, send)
                    else:
                        execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id, journal_path=sd / 'journal.jsonl', producer_limit=1024, failure_policy=F01)
                        result, _ = native._mas_result(sd / 'journal.jsonl', config, task, reference, block)
                    row = native._row(candidate, block, slot, result, config, rounds, failed, run_id)
                    _save(sd / 'result.json', row)
                    rows.append(row)
                if recovering:
                    _save(directory / 'replay.json', dict(original_partial_journal_sha256=file_hash(old_dir / binding['origin']['partial_arm'] / 'journal.jsonl'), original_selection_measurement_sha256=file_hash(old_dir / 'spatial-measurement.json'), continuous_arm_latency_available=False))
                files = [p for p in directory.rglob('*') if p.is_file()]
                for index in range(first_call, adapter.calls + 1):
                    files.extend((folder / 'dispatch').glob(f'{index:06d}-*.json'))
                    files.append(folder / 'physical' / f'{index:06d}.json')
                if recovering:
                    files.extend((folder / 'replays').glob('*.json'))
                _save(directory / 'complete.json', dict(block=block, plan_hash=plan['plan_hash'], rows=rows, evidence={str(p.relative_to(folder)): file_hash(p) for p in files}))
            state, _ = _inspect(binding, candidate, plan, folder)
            _checkpoint(folder, state, checkpoint)
            _record_tf_section(folder, section_end, 'settled', version, transition)
            _publish(binding, folder, control, generation)
            return state
        except BaseException as error:
            try:
                _save(folder / 'STOP.json', dict(binding_sha256=binding['sha256'], error_type=type(error).__name__, retry_allowed=False, diagnostic=safe_exception_chain(error, clock)))
                _publish(binding, folder, control, generation)
            except BaseException as recording_error:
                error.add_note('technical STOP/witness evidence failed: ' + type(recording_error).__name__)
            raise
