"""Concrete clean R87 session. Construction never initializes clients or encoders."""
from copy import deepcopy
from pathlib import Path
import time
from uuid import uuid4

from communication_pruning.study import file_hash
from . import final_r_clean_resume as resume, final_preflight as gate
from .final_operator import Session as OriginalSession
from .final_resources import ProcessObservation, validate_observation


class Session(OriginalSession):
    def __init__(self, candidate_path, binding_path):
        super().__init__(candidate_path)
        self.binding_path = Path(binding_path).resolve()
        self.binding = gate.read_json(self.binding_path)
        self.folder = Path(self.binding['folder'])
        self.control = Path(self.binding['control'])
        # The sealed scientific candidate stays byte-identical; only this local
        # session view receives the explicitly bound operational directories.
        self.settings = deepcopy(self.settings)
        self.settings['output_directory'] = self.binding['folder']
        self.operation = self.folder.parent / 'operation'
        self.settings['operation_directory'] = str(self.operation)

    def metadata_gate(self):
        if self.candidate.get('mode') != 'authorized_execution' or self.candidate.get('test_authorized') is not False:
            raise gate.StudyStop('real R recovery requires explicit author activation')
        resume._check_binding(self.binding, self.candidate, self.plan,
            folder=self.folder, control=self.control, clock=time.time)
        for name in ('original_manifest', 'provision_manifest', 'analysis_binding'):
            item = self.settings[name]
            gate.evidence_file(item)
            if self.candidate['source_files'].get(item['path']) != item['sha256']:
                raise gate.StudyStop('original operator metadata missing')
        if self.binding['source_files'].get(str(Path(__file__).resolve())) != file_hash(__file__):
            raise gate.StudyStop('R recovery operator changed')
        manifest = gate.read_json(self.settings['original_manifest']['path'])
        if self.settings['dev_source']['sha256'] != manifest['source_hashes']['dev']:
            raise gate.StudyStop('Dev metadata binding changed')
        if self.settings['output_directory'] != self.binding['folder']:
            raise gate.StudyStop('operator output differs from canonical recovery claim')
        if self.operation.resolve() != self.folder.parent / 'operation':
            raise gate.StudyStop('operator metadata must use the bound recovery operation directory')
        self._operation_outside_inventory()
        return manifest

    def create_execution(self):
        self.metadata_gate()
        return resume.initialize(self.binding, self.candidate, self.plan,
            folder=self.folder, control=self.control, clock=time.time, checkpoint=self.checkpoint)

    def run(self, section_end, *, coverage):
        observation, run_id = ProcessObservation(), uuid4().hex
        state = error = None
        self._last_checkpoint = self.last_resource_evidence = None
        encoder_at_start = self.encoder
        self._encoder_initialization_event = None
        try:
            self.metadata_gate()
            resume.pre_dispatch(self.binding, self.candidate, self.plan,
                folder=self.folder, control=self.control, clock=time.time,
                section_end=section_end, coverage=coverage)
            self.initialize()
            state = resume.run_section(self.binding, self.candidate, self.plan,
                folder=self.folder, control=self.control, section_end=section_end, coverage=coverage,
                loader=self.loader, spatial_selector=self.spatial.select, temporal_selector=self.temporal.select,
                transport=self.transport, checkpoint=self.checkpoint, clock=time.time)
            return state
        except BaseException as failure:
            error = failure
            raise
        finally:
            try:
                metrics = observation.finish()
                validate_observation(metrics, require_complete=False)
                record = {'schema': 'z52-clean-R87-session-resources/v1', 'binding_sha256': self.binding['sha256'],
                    'section_end': section_end, 'state_sha256': state['state_sha256'] if state else None,
                    'error_type': type(error).__name__ if error else None,
                    'safe_diagnostic': resume.safe_exception_chain(error, time.time) if error else None,
                    'process_observation': metrics,
                    'encoder_preexisting': encoder_at_start is not None,
                    'encoder_initialization': self._encoder_initialization_event,
                    'scope': 'new initialization, clean continuation and checkpoint; excludes this archive',
                    'continuous_original_D_latency_available': False,
                    'replay_is_new_model_work': False, 'peak_RSS_values_are_not_additive': True}
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                validate_observation(metrics, require_complete=True)
            except Exception as recording_error:
                self._ready = False
                if error is None:
                    raise gate.StudyStop('recovery session resource evidence incomplete') from recording_error
                error.add_note('recovery resource evidence incomplete: ' + type(recording_error).__name__)
