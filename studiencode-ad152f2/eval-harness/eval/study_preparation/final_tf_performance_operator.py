"""Explicit T/F entrypoint retaining the original loader, selectors and transport."""
from pathlib import Path
import time
from uuid import uuid4
from . import final_tf_performance as resume, final_preflight as gate
from . import final_rate_stop_resume_operator as previous
from .final_resources import ProcessObservation, validate_observation


class Session(previous.Session):
    def __init__(self, candidate_path, binding_path, version_path):
        super().__init__(candidate_path, binding_path)
        path = Path(version_path)
        if not path.is_absolute() or path != path.resolve() or path.is_symlink() or not path.is_file():
            raise gate.StudyStop('canonical T/F version file required')
        self.version = gate.read_json(path)
        self.runtime_context = resume.RuntimeContext(self.version)

    def metadata_gate(self):
        manifest = super().metadata_gate()
        resume.check_version(self.version, self.binding, self.candidate, self.plan)
        return manifest

    def create_execution(self):
        raise gate.StudyStop('T/F uses explicit zero-call panel handoff; native initialization is forbidden')

    def run(self, section_end, *, coverage):
        observation, run_id = (ProcessObservation(), uuid4().hex)
        state = error = None
        self._last_checkpoint = self.last_resource_evidence = None
        encoder_at_start = self.encoder
        self._encoder_initialization_event = None
        try:
            self.metadata_gate()
            resume.pre_dispatch(self.version, self.binding, self.candidate, self.plan, folder=self.folder, control=self.control, clock=time.time, section_end=section_end, coverage=coverage)
            self.initialize()
            state = resume.run_section(self.version, self.binding, self.candidate, self.plan, folder=self.folder, control=self.control, section_end=section_end, coverage=coverage, loader=self.loader, spatial_selector=self.spatial.select, temporal_selector=self.temporal.select, transport=self.transport, checkpoint=self.checkpoint, clock=time.time, sleep=time.sleep, context=self.runtime_context)
            return state
        except BaseException as failure:
            error = failure
            raise
        finally:
            try:
                metrics = observation.finish()
                validate_observation(metrics, require_complete=False)
                record = dict(schema='z52-tf-performance-session-resources/v1', tf_version_sha256=self.version['sha256'], binding_sha256=self.binding['sha256'], section_end=section_end, state_sha256=state['state_sha256'] if state else None, error_type=type(error).__name__ if error else None, safe_diagnostic=previous.resume.safe_exception_chain(error, time.time) if error else None, process_observation=metrics, encoder_preexisting=encoder_at_start is not None, encoder_initialization=self._encoder_initialization_event, scope='new initialization, bound local terminal replays, suffix attempts, retry waits and checkpoint; excludes this archive', continuous_original_F_latency_available=False, continuous_original_Q_latency_available=False, historical_timing_gaps_repaired=False, replay_is_new_model_work=False, peak_RSS_values_are_not_additive=True, predecessor_binding_sha256=self.binding['inner_binding']['sha256'])
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                validate_observation(metrics, require_complete=True)
            except Exception as recording_error:
                self._ready = False
                if error is None:
                    raise gate.StudyStop('rate-stop session resource evidence incomplete') from recording_error
                error.add_note('rate-stop resource evidence incomplete: ' + type(recording_error).__name__)


OperatorSession = Session
