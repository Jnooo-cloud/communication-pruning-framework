"""N5: additive, one-time recovery of the bound Z42 first-pair audit failure.

This supplements the original release, never grants one. Live use requires the
separately accepted supplemental contract and original guard. No keys/network.
Synthetic fixtures must be outside the real project. Hashes detect accidental
changes; they do not authenticate a hostile author of all local evidence.
"""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import zipfile

from .data import digest
from .failure_policy import strict_json
from .openrouter import encoded, save_new
from .phase_budget import PhaseBudget
from .pilot_calendar import PHASE_ID, require_pair_start, utc
from .pilot_execution import PilotStop, pilot_lock

PROJECT = Path('/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit')
PACK_REL = Path('eval-harness/eval/runs/Z42-PILOT-001')
OLD_CALL = 'window-evidence/W01-first-pair/CALL.json'
OLD_STATE = 'window-evidence/W01-first-pair/W01-first-pair-STATE.json'
OLD_STOP = 'window-evidence/W01-first-pair/STOP.json'
CLAIM = 'control/Z42-PILOT-001.claim.json'
CHECKPOINT = 'live/checkpoints/W01-first-pair.json'
PREFIX = {'bytes': 10170, 'lines': 25,
          'sha256': '2d1a95af0c9be7c5d176472c6c031b0c9f2d398eb092ebc2095c3426869d6078',
          'last_sequence': 24,
          'last_chain': 'cf6ebf4c1a6312213f90bd737f75d37d1d17e6ef1c3e65eaa3fb7bef9e57c305'}
ANCHORS = {
    'live/halted.json': 'b01ea0f04cfa06d905d90c7e5bae24dfa6f0f9393eaea39beb6dce3750a47009',
    OLD_STOP: '0e644114ed5c7f5a61fe3781b98e1647a98d13744133827edab3cc9f3eb76638',
    OLD_CALL: '543cfac2d816e5c8b4f312f7a479d54797ca85153a5daf38859a35b9e2828683',
    OLD_STATE: '6926fa13d70180cbd095b0e1841ee4f7f1a4061b14356a9481a17a984a5cfb8a',
    CLAIM: '760b6883ff96d6b45d3201dd509b58cb1b7ce2ff69b33e8ca15fa74d586c387e',
}
REQUIRED_CRITERIA = {'N1', 'N2', 'N3', 'N4', 'N5-offline'}


def require(value, reason):
    if not value:
        raise PilotStop('recovery: ' + reason)


def read(path):
    return strict_json(Path(path).read_bytes())


def checksum(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_new(path, encoded(value) + b'\n')


def canonical_path(root, name):
    part = Path(name)
    require(isinstance(name, str) and not part.is_absolute() and '..' not in part.parts
            and str(part) == name, 'noncanonical relative path')
    result = root / part
    require(result.resolve() == result.absolute(), 'symlink or noncanonical root')
    current = result
    while current != root.parent:
        require(not current.is_symlink(), 'symlink in path')
        current = current.parent
    return result


def check_files(root, entries):
    require(isinstance(entries, dict) and bool(entries), 'missing file bindings')
    for name, expected in entries.items():
        path = canonical_path(root, name)
        require(path.is_file() and checksum(path) == expected, 'changed bound file: ' + name)


def snapshot(root, destination, paths, clock):
    """Create-only archive and full byte comparison; caller owns the phase lock."""
    destination.mkdir(parents=True, exist_ok=False)
    members = {}
    for path in sorted(set(paths)):
        name = str(path.relative_to(root))
        path = canonical_path(root, name)
        require(path.is_file() and not path.name.startswith('.env') and 'secrets' not in path.parts,
                'unsafe snapshot member')
        members[name] = {'sha256': checksum(path), 'bytes': path.stat().st_size}
    manifest = destination / 'MANIFEST.json'
    save(manifest, {'members': members, 'utc': utc(clock()).isoformat()})
    archive = destination / 'source.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as stream:
        for name in members:
            stream.write(root / name, name)
    with zipfile.ZipFile(archive) as stream:
        require(set(stream.namelist()) == set(members) and len(stream.namelist()) == len(members),
                'snapshot member set differs')
        for name, entry in members.items():
            old, current = stream.read(name), (root / name).read_bytes()
            require(old == current and len(old) == entry['bytes']
                    and sha256(old).hexdigest() == entry['sha256'], 'snapshot bytes differ')
    receipt = {'status': 'passed', 'all_members_compared_to_sources': True,
               'utc': utc(clock()).isoformat(), 'members': len(members),
               'archive': str(archive.relative_to(root)), 'archive_sha256': checksum(archive),
               'manifest': str(manifest.relative_to(root)), 'manifest_sha256': checksum(manifest)}
    save(destination / 'VERIFICATION.json', receipt)
    return destination / 'VERIFICATION.json'


def verify_snapshot(root, receipt_path, required_members=(), *, verify_archive=True):
    receipt = read(receipt_path)
    require(receipt.get('status') == 'passed' and receipt.get('all_members_compared_to_sources') is True,
            'snapshot was not fully compared')
    archive = canonical_path(root, receipt['archive'])
    manifest = canonical_path(root, receipt['manifest'])
    require((not verify_archive or checksum(archive) == receipt['archive_sha256'])
            and checksum(manifest) == receipt['manifest_sha256'],
            'snapshot archive or manifest changed')
    entries = read(manifest)['members']
    require(set(required_members) <= set(entries), 'required recovery evidence absent from snapshot')
    for name in required_members:
        require(checksum(canonical_path(root, name)) == entries[name]['sha256'], 'required snapshot member changed')
    return receipt


class RecoverySession:
    """One accepted supplemental contract, with the existing claim and lock.

    The original guard must still validate its original contract and archives.
    It is called again before every dispatch by the new execution copy.
    """
    def __init__(self, *, root, contract_path, acceptance_path, original_guard,
                 original_start_guard, auditor, clock=None, synthetic=False):
        self.root = Path(root)
        require(self.root.is_absolute() and self.root.resolve() == self.root, 'canonical project root required')
        require(type(synthetic) is bool, 'explicit synthetic flag')
        require(self.root != PROJECT and not self.root.is_relative_to(PROJECT) if synthetic else self.root == PROJECT,
                'fixture/live root separation')
        self.synthetic = synthetic
        self.pack = canonical_path(self.root, str(PACK_REL))
        self.live, self.control = self.pack / 'live', self.pack / 'control'
        self.base = self.pack / 'repair-r1/recovery'
        self.activation = self.base / 'activation'
        self.contract_path, self.acceptance_path = Path(contract_path), Path(acceptance_path)
        require(self.contract_path == self.base / 'contract.json'
                and self.acceptance_path == self.base / 'START-ACCEPTANCE.json', 'fixed supplemental contract paths')
        self.contract_sha = checksum(self.contract_path)
        self.acceptance_sha = checksum(self.acceptance_path)
        self.contract = read(self.contract_path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.original_guard, self.auditor = original_guard, auditor
        self.original_start_guard = original_start_guard
        require(all(callable(c) for c in (original_guard, original_start_guard, auditor)),
                'original start/dispatch guards and actual auditor required')
        self.current = None
        self.current_call_sha = None
        self.returned = False
        self.latest = None

    def moment(self):
        result = utc(self.clock())
        require(self.latest is None or result >= self.latest, 'clock moved backwards')
        self.latest = result
        return result

    def bound_path(self, name):
        return canonical_path(self.pack, name)

    def common(self, *, deep=False):
        self.original_guard()
        require(checksum(self.contract_path) == self.contract_sha
                and checksum(self.acceptance_path) == self.acceptance_sha, 'supplemental release changed')
        contract, accepted = self.contract, read(self.acceptance_path)
        require(contract.get('schema') == 'z42-pilot-recovery/v1' and contract.get('status') == 'ready_for_separate_acceptance'
                and contract.get('phase_root') == str(self.pack) and contract.get('synthetic') is self.synthetic,
                'unready contract or wrong phase root')
        require((contract.get('phase_id'), contract.get('work_item'), contract.get('author_decision'))
                == (PHASE_ID, 'Z42-PILOT', 'D-059'), 'phase authority differs')
        require(accepted.get('status') == 'passed_N1_N5_offline_review'
                and accepted.get('contract_sha256') == self.contract_sha
                and set(accepted.get('criteria', {})) == REQUIRED_CRITERIA
                and all(v == 'passed' for v in accepted['criteria'].values())
                and accepted.get('reviewer') and accepted.get('reviewer') != accepted.get('implementer'),
                'separate concrete N1-N5 acceptance missing')
        check_files(self.root, accepted['evidence'])
        check_files(self.root, contract['source_files'])
        require(contract.get('preactivation_backup') in contract['source_files'],
                'preactivation backup receipt is not bound by the accepted contract')
        require(str(self.contract_path.relative_to(self.root)) not in contract['source_files'], 'contract cannot bind itself')
        required = {'operate.py', 'independent-audit/audit.py', 'calendar-r2/preparation/contract.json',
                    'calendar-r2/START-ACCEPTANCE.json', 'calendar-r2/preparation/calendar.json',
                    'repair-r1/audit/audit.py'}
        require({str(PACK_REL / p) for p in required} <= set(contract['source_files']), 'original/new sources not bound')
        require({'eval-harness/eval/communication_pruning/pilot_execution.py',
                 'eval-harness/eval/communication_pruning/pilot_recovery_execution.py',
                 'eval-harness/eval/communication_pruning/pilot_recovery_guard.py',
                 str(PACK_REL / 'repair-r1/recovery/operate.py')} <= set(contract['source_files']),
                'execution source binding incomplete')
        if not self.synthetic:
            require(contract['anchors'] == ANCHORS and contract['budget_prefix'] == PREFIX
                    and contract['expected_cost_usd'] == '0.0030033', 'specific live stop binding differs')
        check_files(self.pack, contract['anchors'])
        check_files(self.pack, contract['preserved_files'])
        prefix = contract['budget_prefix']
        raw = self.bound_path('live/budget.jsonl').read_bytes()
        original = raw[:prefix['bytes']]
        require(len(original) == prefix['bytes'] and original.endswith(b'\n')
                and len(original.splitlines()) == prefix['lines']
                and sha256(original).hexdigest() == prefix['sha256'], 'original budget prefix changed')
        last = strict_json(original.splitlines()[-1])
        require(last['sequence'] == prefix['last_sequence'] and last['sha256'] == prefix['last_chain'],
                'original budget chain endpoint changed')
        self.plan = read(self.bound_path('calendar-r2/preparation/calendar.json'))
        require(read(self.bound_path('live/plan.json')) == self.plan, 'saved calendar changed')
        claim = read(self.bound_path(CLAIM))
        require(claim.get('output') == str(self.live) and claim.get('plan_sha256') == self.plan['sha256']
                and claim.get('phase_id') == PHASE_ID and claim.get('synthetic') is self.synthetic, 'claim differs')
        require(self.plan['pairs'][1]['pair_id'] == 'P0002'
                and self.plan['pairs'][1]['slot_ids'] == ['S0003', 'S0004'], 'next pair differs')
        # Known old failures remain. Any additional failure or unknown invocation blocks.
        for folder in (self.live, self.pack / 'window-evidence', self.base):
            for p in folder.rglob('*'):
                require(not p.is_symlink(), 'symlink in operational tree')
                if p.is_file() and (p.name == 'STOP.json' or p.name == 'halted.json' or p.parent.name == 'errors'):
                    require(str(p.relative_to(self.pack)) in contract['anchors'], 'new stop requires separate review')
        calls = list((self.pack / 'window-evidence').glob('*/CALL.json'))
        require({str(p.relative_to(self.pack)) for p in calls} == {OLD_CALL}, 'unknown original outer invocation')
        require(not (self.bound_path(OLD_CALL).parent / 'RETURN.json').exists(), 'old failed call cannot acquire RETURN')
        for p in (self.base / 'attempts').glob('*'):
            require(p.is_dir() and (p / 'CALL.json').is_file(), 'incomplete recovery invocation')
            if p == self.current and not self.returned:
                require(checksum(p / 'CALL.json') == self.current_call_sha, 'current outer invocation changed')
            else:
                require((p / 'RETURN.json').is_file() and (p / 'snapshot/VERIFICATION.json').is_file(),
                        'unresolved recovery invocation')
                required = [str((p / 'RETURN.json').relative_to(self.root))]
                window_id = read(p / 'CALL.json')['window']
                require(p.name == window_id and window_id in {w['window_id'] for w in self.plan['windows']},
                        'unknown recovery window')
                internal = self.live / 'checkpoints' / (window_id + '-complete.json')
                proof = read(internal)
                external = self.base / 'checkpoints' / (window_id + '-complete') / 'VERIFICATION.json'
                require(proof['stage'] == window_id + '-complete' and proof['plan_sha256'] == self.plan['sha256']
                        and proof['receipt']['sha256'] == checksum(external), 'completed checkpoint receipt changed')
                required.extend([str(internal.relative_to(self.root)), str((p / 'CALL.json').relative_to(self.root))])
                verify_snapshot(self.root, external, verify_archive=deep)
                verify_snapshot(self.root, p / 'snapshot/VERIFICATION.json', required, verify_archive=deep)
        return self.plan

    def initial(self):
        self.original_start_guard()
        plan = self.common(deep=True)
        require_pair_start(plan['windows'][0], self.moment())
        require(not self.activation.exists() and not self.bound_path(CHECKPOINT).exists(), 'activation already attempted')
        require(not (self.base / 'attempts').exists(), 'continuation attempted before activation')
        actual = {str(p.relative_to(self.pack)) for folder in (self.live, self.control, self.pack / 'window-evidence')
                  for p in folder.rglob('*') if p.is_file() and p.name != PHASE_ID + '.lock'}
        require(actual == set(self.contract['preserved_files']) | {'live/budget.jsonl'},
                'first-pair file inventory changed')
        budget = self.read_budget()
        require(budget.calls == 12 and budget.cost == Decimal(self.contract['expected_cost_usd'])
                and budget.pending is None and not budget.poisoned, 'first pair budget differs')
        require(self.bound_path('live/budget.jsonl').stat().st_size == self.contract['budget_prefix']['bytes'],
                'extra budget attempts before activation')
        require({p.name for p in (self.live / 'pairs').iterdir()} == {'P0001-started.json', 'P0001-complete.json'},
                'first pair is not the only begun pair')
        state = read(self.bound_path(OLD_STATE))
        require(state['completed_pairs'] == 1 and state['completed_slots'] == 2
                and state['stage'] == 'W01-first-pair' and state['plan_sha256'] == plan['sha256']
                and state['budget'] == budget.snapshot(), 'first pair checkpoint state differs')
        pair = read(self.live / 'pairs/P0001-complete.json')
        require(pair['pair'] == plan['pairs'][0] and pair['budget'] == budget.snapshot(), 'P0001 receipt differs')
        check_files(self.live, pair['evidence'])
        check_files(self.live, state['evidence'])
        required_backup = [str(PACK_REL / name) for name in self.contract['preserved_files']]
        required_backup.append(str(PACK_REL / 'live/budget.jsonl'))
        verify_snapshot(self.root, canonical_path(self.root, self.contract['preactivation_backup']), required_backup)
        return state

    def read_budget(self):
        return PhaseBudget.read_completed(self.live / 'budget.jsonl', cap=Decimal('4.00'), reserve=Decimal('0.14'),
                                          max_calls=4320, binding=self.plan['sha256'], allow_synthetic=self.synthetic)

    def snapshot_paths(self):
        paths = []
        for folder in (self.live, self.control, self.pack / 'window-evidence', self.base):
            paths.extend(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                         and not any(part in ('hold-snapshot', 'activation-snapshot', 'snapshot', 'test-runs', 'source-archives', 'preactivation-backup', 'stop-snapshots')
                                     for part in p.relative_to(folder).parts))
        return paths

    def stop(self, error):
        """Called under the existing phase lock. Never overwrites the old halt."""
        save(self.base / 'errors' / (uuid4().hex + '.json'), {
            'schema': 'z42-recovery-error/v1', 'utc': datetime.now(timezone.utc).isoformat(),
            'error_type': type(error).__name__, 'reason': str(error), 'automatic_retry': False,
            'original_stop_sha256': self.contract['anchors']['live/halted.json'],
            'audit_report': getattr(error, 'report', None)})

    def backup_stop(self):
        """Run after the final error/report write, while the phase lock is held.

        A backup failure must not replace the original exception. Its own
        additive marker documents that the requested stop backup is incomplete.
        """
        try:
            snapshot(self.root, self.base / 'stop-snapshots' / uuid4().hex,
                     self.snapshot_paths(), lambda: datetime.now(timezone.utc))
        except BaseException as backup_error:
            save(self.base / 'errors' / (uuid4().hex + '.json'), {
                'schema': 'z42-recovery-stop-backup-failed/v1', 'utc': datetime.now(timezone.utc).isoformat(),
                'error_type': type(backup_error).__name__, 'reason': str(backup_error),
                'original_error_preserved': True, 'automatic_retry': False})

    def activate(self):
        require(self.control.is_dir() and (self.control / (PHASE_ID + '.lock')).is_file(), 'existing phase lock missing')
        with pilot_lock(self.control):
            self.initial()  # failed eligibility is read-only; no activation attempt was begun
            self.activation.mkdir(exist_ok=False)
            try:
                save(self.activation / 'INTENT.json', {'utc': self.moment().isoformat(), 'contract_sha256': self.contract_sha,
                     'original_errors': self.contract['anchors'], 'next_pair': 'P0002', 'first_new_call': 13})
                state = read(self.bound_path(OLD_STATE))
                audit = self.auditor(self.plan, self.live, state)
                require(audit.get('verified') is True and audit.get('plan_sha256') == self.plan['sha256'], 'fresh reaudit failed')
                save(self.activation / 'AUDIT.json', {'utc': self.moment().isoformat(), 'result': audit,
                     'state_sha256': checksum(self.bound_path(OLD_STATE)),
                     'auditor_sha256': checksum(self.bound_path('repair-r1/audit/audit.py'))})
                self.common()
                require_pair_start(self.plan['windows'][0], self.moment())
                save(self.activation / 'CONTROL-HOLD.json', {'utc': self.moment().isoformat(), 'stage': 'W01-first-pair',
                     'original_state_sha256': checksum(self.bound_path(OLD_STATE)), 'original_errors': self.contract['anchors'],
                     'audit_sha256': checksum(self.activation / 'AUDIT.json'), 'budget': self.read_budget().snapshot(),
                     'note': 'Actual later control hold; original callback failed and stays failed.'})
                first = snapshot(self.root, self.activation / 'hold-snapshot', self.snapshot_paths(), self.clock)
                save(self.bound_path(CHECKPOINT), {'stage': 'W01-first-pair', 'plan_sha256': self.plan['sha256'],
                     'state_sha256': digest(state), 'receipt': {'verified': True, 'sha256': checksum(first)},
                     'utc': self.moment().isoformat(), 'recovery_control_hold_sha256': checksum(self.activation / 'CONTROL-HOLD.json')})
                second = snapshot(self.root, self.activation / 'activation-snapshot', self.snapshot_paths(), self.clock)
                self.common()
                require_pair_start(self.plan['windows'][0], self.moment())
                save(self.activation / 'ACTIVATED.json', {'utc': self.moment().isoformat(), 'contract_sha256': self.contract_sha,
                     'acceptance_sha256': self.acceptance_sha, 'checkpoint_sha256': checksum(self.bound_path(CHECKPOINT)),
                     'hold_sha256': checksum(self.activation / 'CONTROL-HOLD.json'), 'audit_sha256': checksum(self.activation / 'AUDIT.json'),
                     'intent_sha256': checksum(self.activation / 'INTENT.json'), 'backup_sha256': checksum(second),
                     'original_errors': self.contract['anchors'], 'next_pair': 'P0002', 'first_new_call': 13})
            except BaseException as error:
                self.stop(error)
                self.backup_stop()
                raise

    def guard(self, *, deep=False):
        self.common(deep=deep)
        marker = read(self.activation / 'ACTIVATED.json')
        require(marker['contract_sha256'] == self.contract_sha and marker['acceptance_sha256'] == self.acceptance_sha,
                'activation release differs')
        require(marker['original_errors'] == self.contract['anchors']
                and marker['next_pair'] == 'P0002' and marker['first_new_call'] == 13, 'activation scope differs')
        entries = {'checkpoint_sha256': self.bound_path(CHECKPOINT), 'hold_sha256': self.activation / 'CONTROL-HOLD.json',
                   'audit_sha256': self.activation / 'AUDIT.json', 'intent_sha256': self.activation / 'INTENT.json',
                   'backup_sha256': self.activation / 'activation-snapshot/VERIFICATION.json'}
        require(all(checksum(path) == marker[key] for key, path in entries.items()), 'activation evidence changed')
        verify_snapshot(self.root, entries['backup_sha256'], [str(path.relative_to(self.root)) for key, path in entries.items()
                                                            if key != 'backup_sha256'], verify_archive=deep)
        verify_snapshot(self.root, self.activation / 'hold-snapshot/VERIFICATION.json',
                        [str((self.activation / 'CONTROL-HOLD.json').relative_to(self.root))], verify_archive=deep)
        proof = read(self.bound_path(CHECKPOINT))
        require(proof['receipt']['sha256'] == checksum(self.activation / 'hold-snapshot/VERIFICATION.json'), 'checkpoint proof differs')
        self.moment()

    def begin_window(self, window_id):
        self.original_start_guard()
        self.guard(deep=True)
        window = next((w for w in self.plan['windows'] if w['window_id'] == window_id), None)
        require(window is not None, 'unknown window')
        require_pair_start(window, self.moment())
        if not (self.base / 'attempts').exists():
            budget = self.read_budget()
            require(window_id == 'W01' and budget.calls == 12
                    and budget.cost == Decimal(self.contract['expected_cost_usd']), 'first continuation differs')
        require(self.current is None, 'same session reused for another invocation')
        path = self.base / 'attempts' / window_id
        path.mkdir(parents=True, exist_ok=False)
        self.current = path
        save(path / 'CALL.json', {'utc': self.moment().isoformat(), 'window': window_id,
             'contract_sha256': self.contract_sha, 'automatic_retry': False,
             'activation_sha256': checksum(self.activation / 'ACTIVATED.json')})
        self.current_call_sha = checksum(path / 'CALL.json')

    def finish_window(self, report):
        self.guard()
        require(report['status'] == 'completed_window', 'incomplete recovered window')
        save(self.current / 'RETURN.json', {'utc': self.moment().isoformat(), 'result': report})
        snapshot(self.root, self.current / 'snapshot', self.snapshot_paths(), self.clock)
        self.returned = True
