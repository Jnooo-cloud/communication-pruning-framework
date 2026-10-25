"""Concrete technical R203 session using the original frozen scientific operator.

Construction reads bound metadata only. No client, encoder, data loader or
credential is initialized until the metadata and next-section gates pass.
"""
from copy import deepcopy
from pathlib import Path
import time
import errno
import urllib.request
import urllib.error
from uuid import uuid4

from communication_pruning.study import file_hash
from . import final_technical_resume as resume, final_preflight as gate
from .final_operator import Session as OriginalSession
from .final_resources import ProcessObservation, validate_observation
from communication_pruning.openrouter import Transport, BASE, ProbeStop, load_key


class HeaderTransport(Transport):
    """Same fixed endpoint, proxy/redirect exclusion and size/key guards.

    Preserve only Retry-After, and a sanitized exception cause classification.
    No change to request body, model, provider, key source or 45-second timeout.
    """
    def __call__(self,endpoint,body=None):
        if endpoint!='chat/completions' or body is None:
            raise ProbeStop('only bound study request allowed')
        request=urllib.request.Request(BASE+endpoint,data=body,
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self._key})
        try:
            with self._opener.open(request,timeout=45) as response:
                status,raw=response.status,response.read(2_000_001)
                retry_after=response.headers.get('Retry-After')
        except urllib.error.HTTPError as error:
            status,raw=error.code,error.read(2_000_001)
            retry_after=error.headers.get('Retry-After')
        except (OSError,ValueError) as error:
            reason=getattr(error,'reason',error)
            transient=isinstance(reason,(TimeoutError,ConnectionError)) or getattr(reason,'errno',None) in (
                errno.ETIMEDOUT,errno.ECONNRESET,errno.ECONNREFUSED,errno.EPIPE,errno.ENETUNREACH,errno.EHOSTUNREACH)
            if transient:raise ConnectionError('temporary transport interruption; cost unknown') from None
            raise ProbeStop('nontransient transport failure; cost unknown') from None
        if len(raw)>2_000_000 or self._key.encode() in raw:
            raise ProbeStop('response cannot be safely recorded')
        if retry_after is not None and (len(retry_after)>200 or self._key in retry_after):
            raise ProbeStop('header cannot be safely recorded')
        return status,raw,({'Retry-After':retry_after} if retry_after is not None else {})


class DeferredHeaderTransport:
    """The frozen Session.transport entrypoint retains its dependency identity."""
    def __init__(self,session):self.session,self.client=session,None
    def __call__(self,endpoint,body=None):
        if not self.session._ready:raise gate.StudyStop('operator not initialized')
        if self.client is None:
            self.client=HeaderTransport(load_key(self.session.settings['credential_file'],source='file'))
        return self.client(endpoint,body)


def _canonical_file(value):
    path = Path(value)
    if not path.is_absolute() or path != path.resolve() or path.is_symlink() or not path.is_file():
        raise gate.StudyStop('canonical absolute metadata file required')
    return path


class Session(OriginalSession):
    def __init__(self, candidate_path, binding_path):
        candidate_path, binding_path = _canonical_file(candidate_path), _canonical_file(binding_path)
        super().__init__(candidate_path)
        self.binding_path = binding_path
        self.binding = gate.read_json(binding_path)
        self.folder = Path(self.binding['folder'])
        self.control = Path(self.binding['control'])
        # Preserve the scientific candidate; this view binds only new outputs.
        self.settings = deepcopy(self.settings)
        self.settings['output_directory'] = self.binding['folder']
        self.operation = self.folder.parent / 'operation'
        self.settings['operation_directory'] = str(self.operation)
        # Explicit source-bound transport extension; the scientific callback
        # identity, key source, body, endpoint and runtime guards remain native.
        self.client = DeferredHeaderTransport(self)

    def metadata_gate(self):
        if self.candidate.get('mode') != 'authorized_execution' or self.candidate.get('test_authorized') is not False:
            raise gate.StudyStop('real technical R203 recovery requires explicit author activation')
        resume._check_binding(self.binding, self.candidate, self.plan,
            folder=self.folder, control=self.control, clock=time.time)
        for name in ('original_manifest', 'provision_manifest', 'analysis_binding'):
            item = self.settings[name]
            gate.evidence_file(item)
            if self.candidate['source_files'].get(item['path']) != item['sha256']:
                raise gate.StudyStop('original operator metadata missing')
        if self.binding['source_files'].get(str(Path(__file__).resolve())) != file_hash(__file__):
            raise gate.StudyStop('technical R203 recovery operator changed')
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
                transport=self.transport, checkpoint=self.checkpoint, clock=time.time, sleep=time.sleep)
            return state
        except BaseException as failure:
            error = failure
            raise
        finally:
            try:
                metrics = observation.finish()
                validate_observation(metrics, require_complete=False)
                record = {'schema': 'z52-technical R203-session-resources/v1', 'binding_sha256': self.binding['sha256'],
                    'section_end': section_end, 'state_sha256': state['state_sha256'] if state else None,
                    'error_type': type(error).__name__ if error else None,
                    'safe_diagnostic': resume.safe_exception_chain(error, time.time) if error else None,
                    'process_observation': metrics,
                    'encoder_preexisting': encoder_at_start is not None,
                    'encoder_initialization': self._encoder_initialization_event,
                    'scope': 'new initialization, retained-answer replay, all physical attempts, retry waits and checkpoint; excludes this archive',
                    'continuous_original_F_latency_available': False,
                    'historical_timing_gaps_repaired': False,
                    'replay_is_new_model_work': False, 'peak_RSS_values_are_not_additive': True}
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                validate_observation(metrics, require_complete=True)
            except Exception as recording_error:
                self._ready = False
                if error is None:
                    raise gate.StudyStop('technical R203 session resource evidence incomplete') from recording_error
                error.add_note('technical R203 resource evidence incomplete: ' + type(recording_error).__name__)


OperatorSession = Session
