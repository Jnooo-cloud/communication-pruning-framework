"""Explicit secondary session; construction is inert and never starts a process.

Uses the frozen Session loader/transport/checkpoint/selector initialization.
The only override in that initialization is its additive accounting/activation
gate. No credentials, content or encoders are opened before this gate succeeds.
"""
from pathlib import Path
import time
from uuid import uuid4

from communication_pruning.study import file_hash
from . import final_secondary as secondary, final_preflight as gate
from .final_operator import Session as OriginalSession
from .final_resources import ProcessObservation, validate_observation


class Session(OriginalSession):
    def __init__(self, candidate_path, binding_path):
        super().__init__(candidate_path)
        self.binding_path = Path(binding_path).resolve()
        self.binding = gate.read_json(self.binding_path)
        self.folder = Path(self.binding["folder"])
        self.control = Path(self.binding["control"])

    def metadata_gate(self):
        if self.candidate.get("mode") != "authorized_execution" or self.candidate.get("test_authorized") is not False:
            raise gate.StudyStop("live secondary Session requires explicit real activation")
        secondary._check_binding(self.binding, self.candidate, self.plan,
            folder=self.folder, control=self.control, clock=time.time)
        for name in ("original_manifest", "provision_manifest", "analysis_binding"):
            item = self.settings[name]
            gate.evidence_file(item)
            if self.candidate["source_files"].get(item["path"]) != item["sha256"]:
                raise gate.StudyStop("original operator source metadata missing")
        if self.binding["source_files"].get(str(Path(__file__).resolve())) != file_hash(__file__):
            raise gate.StudyStop("secondary operator source changed")
        manifest = gate.read_json(self.settings["original_manifest"]["path"])
        if self.settings["dev_source"]["sha256"] != manifest["source_hashes"]["dev"]:
            raise gate.StudyStop("Dev source differs from original metadata")
        if self.settings["output_directory"] != self.binding["folder"]:
            raise gate.StudyStop("operator output differs from secondary claim")
        self._operation_outside_inventory()
        return manifest

    def create_execution(self):
        """No provider action. Claim/witness only after complete activation gates."""
        self.metadata_gate()
        return secondary.initialize(self.binding, self.candidate, self.plan,
            folder=self.folder, control=self.control, clock=time.time)

    def run(self, section_end, *, coverage):
        observation = ProcessObservation()
        run_id = uuid4().hex
        state = None
        error = None
        self._last_checkpoint = None
        self.last_resource_evidence = None
        try:
            self.initialize()  # frozen selectors, overridden metadata gate first
            state = secondary.run_section(self.binding, self.candidate, self.plan,
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
                record = {"schema": "z52-secondary-session-resources/v1", "binding_sha256": self.binding["sha256"],
                    "section_end": section_end, "state_sha256": state["state_sha256"] if state else None,
                    "error_type": type(error).__name__ if error else None, "process_observation": metrics,
                    "scope": "initialization, original native arms and checkpoint; excludes this resource archive"}
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                validate_observation(metrics, require_complete=True)
            except Exception as recording_error:
                self._ready = False
                if error is None:
                    raise gate.StudyStop("secondary session resource evidence incomplete") from recording_error
                error.add_note("secondary resource evidence incomplete: " + type(recording_error).__name__)


def activation_inputs():
    """Exact missing inputs, not an activation decision or a readiness claim."""
    return {
        "schema": "z52-secondary-activation/v1", "live_enabled_by_this_function": False,
        "required": ["sealed operational candidate retaining original scientific bindings; budget.unresolved=true",
            "original reviewed P closeout, old claim/control snapshot and four unknowns",
            "unchanged scientific plan 50d4c906a74daf4810511ddaec90218d26dd9897ccd9c9fb5f9cf1b532d23539",
            "exact author_release for execution_binding and R/T/F; exact activation for connection_hash",
            "sole executor; unchanged shared calendar; data_rights and secondary backup_rights",
            "source_review, runtime_review, storage_power_review, initial_backup with exact file hashes and validity",
            "extension_backup: every additive source and installed witness dependency locally reread, exact separate remote reread receipt",
            "unchanged ARCH-05 installation hash; additive source archive and separate review",
            "current provider/tariff observation and account coverage for next whole block",
            "separate hold review plus remote reread before next original hold; panel analysis/review/backup before next panel"],
        "limits": ["No network, credential lookup, process start or live evidence is produced here.",
            "FileWitness cannot detect whole-machine rollback or a hostile filesystem owner.",
            "Recovery is fail-closed only; no admitted/incomplete section is resumed or retried."],
    }
