"""Explicit session for operating renewal; no change to scientific callbacks."""
from . import final_technical_resume_operator as technical
from .final_operating_renewal import OperatingContext
import math
import os
import shutil
import subprocess


def probe_storage_power(proof, folder, *, executor, clock):
    """Fresh presection observation; never reads or prints process arguments."""
    def require(condition, message):
        if not condition:
            raise technical.gate.StudyStop(message)
    now = clock()
    wake = technical.gate.read_json(technical.gate.evidence_file(proof['wake_process']))
    require(proof.get('accepted') is True and proof.get('executor') == executor
            and wake.get('executor') == executor, 'foreign operating observation')
    require(all(type(value) in (int, float) and math.isfinite(value)
                for value in (now, proof.get('checked_epoch'), proof.get('valid_until_epoch'),
                              wake.get('checked_epoch'))), 'invalid operating observation time')
    command = wake.get('command')
    require(isinstance(command, list) and len(command) == 5
            and command[:4] == ['/usr/bin/caffeinate', '-i', '-s', '-t']
            and isinstance(command[4], str) and command[4].isdigit(), 'unbound wake command')
    require(wake['checked_epoch'] <= now, 'future owned wake observation')
    require(proof['checked_epoch'] <= now <= proof['valid_until_epoch']
            <= wake['checked_epoch'] + int(command[4]), 'stale operating observation')
    pid = wake.get('pid')
    require(type(pid) is int and pid > 0, 'invalid owned wake pid')
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError) as error:
        raise technical.gate.StudyStop('owned wake process unavailable') from error
    power = subprocess.run(['pmset', '-g', 'batt'], check=True, capture_output=True,
                           text=True, timeout=5).stdout
    require("'AC Power'" in power, 'AC power unavailable')
    assertions = subprocess.run(['pmset', '-g', 'assertions'], check=True, capture_output=True,
                                text=True, timeout=5).stdout
    own = [line for line in assertions.splitlines() if line.strip().startswith(f'pid {pid}(caffeinate):')]
    require(any('PreventUserIdleSystemSleep' in line for line in own)
            and any('PreventSystemSleep' in line for line in own), 'owned wake assertions unavailable')
    return {'origin': 'actual_presection_observation', 'observed_epoch': now, 'ac_power': True,
            'owned_wake_pid': pid, 'owned_wake_assertions_verified': True,
            'disk_free_bytes': shutil.disk_usage(folder).free,
            'scope': 'Current observation only; no claim about future power or capacity.'}


class Session(technical.Session):
    def __init__(self, candidate_path, binding_path, *, context, expected_tip=None):
        super().__init__(candidate_path, binding_path)
        self.operating = OperatingContext(context, expected_tip=expected_tip)

    def create_execution(self):
        raise technical.gate.StudyStop('operating renewal cannot initialize a study')

    def metadata_gate(self):
        if self.candidate.get('mode') != 'authorized_execution' or self.candidate.get('test_authorized') is not False:
            raise technical.gate.StudyStop('real technical R203 recovery requires explicit author activation')
        self.operating._check_binding(self.binding, self.candidate, self.plan, folder=self.folder, control=self.control, clock=technical.time.time)
        for name in ('original_manifest', 'provision_manifest', 'analysis_binding'):
            item = self.settings[name]
            technical.gate.evidence_file(item)
            if self.candidate['source_files'].get(item['path']) != item['sha256']:
                raise technical.gate.StudyStop('original operator metadata missing')
        if self.binding['source_files'].get(str(technical.Path(technical.__file__).resolve())) != technical.file_hash(technical.__file__):
            raise technical.gate.StudyStop('technical R203 recovery operator changed')
        manifest = technical.gate.read_json(self.settings['original_manifest']['path'])
        if self.settings['dev_source']['sha256'] != manifest['source_hashes']['dev']:
            raise technical.gate.StudyStop('Dev metadata binding changed')
        if self.settings['output_directory'] != self.binding['folder']:
            raise technical.gate.StudyStop('operator output differs from canonical recovery claim')
        if self.operation.resolve() != self.folder.parent / 'operation':
            raise technical.gate.StudyStop('operator metadata must use the bound recovery operation directory')
        self._operation_outside_inventory()
        return manifest

    def run(self, section_end, *, coverage):
        observation, run_id = (technical.ProcessObservation(), technical.uuid4().hex)
        state = error = None
        self._last_checkpoint = self.last_resource_evidence = None
        encoder_at_start = self.encoder
        self._encoder_initialization_event = None
        try:
            self.metadata_gate()
            self.operating.pre_dispatch(self.binding, self.candidate, self.plan, folder=self.folder, control=self.control, clock=technical.time.time, section_end=section_end, coverage=coverage)
            self.initialize()
            state = self.operating.run_section(self.binding, self.candidate, self.plan, folder=self.folder, control=self.control, section_end=section_end, coverage=coverage, loader=self.loader, spatial_selector=self.spatial.select, temporal_selector=self.temporal.select, transport=self.transport, checkpoint=self.checkpoint, clock=technical.time.time, sleep=technical.time.sleep)
            return state
        except BaseException as failure:
            error = failure
            raise
        finally:
            try:
                metrics = observation.finish()
                technical.validate_observation(metrics, require_complete=False)
                record = {'schema': 'z52-technical R203-session-resources/v1', 'binding_sha256': self.binding['sha256'], 'section_end': section_end, 'state_sha256': state['state_sha256'] if state else None, 'error_type': type(error).__name__ if error else None, 'safe_diagnostic': technical.resume.safe_exception_chain(error, technical.time.time) if error else None, 'process_observation': metrics, 'encoder_preexisting': encoder_at_start is not None, 'encoder_initialization': self._encoder_initialization_event, 'scope': 'new initialization, retained-answer replay, all physical attempts, retry waits and checkpoint; excludes this archive', 'continuous_original_F_latency_available': False, 'historical_timing_gaps_repaired': False, 'replay_is_new_model_work': False, 'peak_RSS_values_are_not_additive': True, 'operating_context': self.operating.context_ref, 'operating_renewal_tip': self.operating.expected_tip}
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                technical.validate_observation(metrics, require_complete=True)
            except Exception as recording_error:
                self._ready = False
                if error is None:
                    raise technical.gate.StudyStop('technical R203 session resource evidence incomplete') from recording_error
                error.add_note('technical R203 resource evidence incomplete: ' + type(recording_error).__name__)
