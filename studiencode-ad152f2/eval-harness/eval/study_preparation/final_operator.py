"""Concrete Z50 successor with repeatable backup and observed process resources.

There is no entry point that launches a study. The coordinator must supply the
separately authorized candidate and the next exact section end to Session.run.
The preserved original is runs/Z50-STUDIENSTART-001/coordination/study_operator.py.
The existing loader decodes preceding Dev records internally; only the requested
task and its local reference are returned. This is not memory isolation.
"""
from dataclasses import replace
import os
from pathlib import Path
import time
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED

from communication_pruning.data import load_task
from communication_pruning.openrouter import Transport, load_key, encoded, save_new
from communication_pruning.semantic_selection import FrozenMiniLM, SemanticSelector
from communication_pruning.study import file_hash
from study_preparation import final_execution as execution, final_preflight as gate
from study_preparation.final_analysis import analyze_panel
from study_preparation.final_plan import canonical_hash
from study_preparation.final_resources import ProcessObservation, validate_observation
from study_preparation.temporal import TemporalSelector


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    save_new(path, encoded(value))


def _archive(folder, path, members):
    """Create once, or reread every member of an existing exact archive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise gate.StudyStop("archive must be a regular local file")
    if not path.exists():
        try:
            with ZipFile(path, "x", compression=ZIP_DEFLATED) as archive:
                for name in members:
                    archive.write(folder / name, name)
        except FileExistsError:
            # Another writer cannot pass the study lock. If a file did appear,
            # it still has to pass the same complete verification below.
            pass
    try:
        proof = {"path": str(path.resolve()), "sha256": file_hash(path), "members": dict(members)}
        gate.verify_archive(proof, members)
    except (OSError, BadZipFile, KeyError, RuntimeError) as error:
        raise gate.StudyStop("checkpoint archive failed complete verification; original preserved") from error
    return proof


class Session:
    def __init__(self, candidate_path):
        self.candidate_path = Path(candidate_path).resolve()
        self.candidate = gate.read_json(self.candidate_path)
        self.plan = gate.read_json(gate.evidence_file(self.candidate["plan_evidence"]))
        self.settings = self.candidate["operator"]
        self.folder = Path(self.settings["output_directory"])
        self.operation = Path(self.settings["operation_directory"])
        self.control = Path(self.candidate["control_directory"])
        self.client = self.encoder = self.spatial = self.temporal = None
        self.loaded = []
        self._ready = False
        self._session_id = uuid4().hex
        self._last_checkpoint = None
        self._encoder_initialization_event = None
        self.last_resource_evidence = None

    def _operation_outside_inventory(self):
        if self.folder.resolve() == self.operation.resolve() or self.operation.resolve().is_relative_to(self.folder.resolve()):
            raise gate.StudyStop("operator metadata must stay outside phase inventory")

    def metadata_gate(self):
        if self.candidate.get("mode") != "authorized_execution" or self.candidate.get("test_authorized") is not False:
            raise gate.StudyStop("the concrete live operator requires an actual author release")
        gate.preflight(self.candidate, self.plan, control=self.control, clock=time.time)
        for name in ("original_manifest", "provision_manifest", "analysis_binding"):
            item = self.settings[name]
            gate.evidence_file(item)
            if self.candidate["source_files"].get(item["path"]) != item["sha256"]:
                raise gate.StudyStop("operator metadata absent from source binding")
        if self.candidate["source_files"].get(str(Path(__file__).resolve())) != file_hash(__file__):
            raise gate.StudyStop("operator source changed")
        manifest = gate.read_json(self.settings["original_manifest"]["path"])
        if self.settings["dev_source"]["sha256"] != manifest["source_hashes"]["dev"]:
            raise gate.StudyStop("Dev source differs from original metadata")
        self._operation_outside_inventory()
        return manifest

    def initialize(self):
        self._ready = False
        self.manifest = self.metadata_gate()  # Before encoder, credentials or content.
        if self.encoder is None:
            provision = gate.read_json(self.settings["provision_manifest"]["path"])
            os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
            model_dir = Path(self.settings["provision_manifest"]["path"]).parent / provision["model_dir_relative"]
            encoder = FrozenMiniLM(model_dir, files=provision["files"], runtime=provision["runtime"])
            # Preserve this completed constructor even when a selector then
            # fails. run() resets the event before each new invocation.
            self._encoder_initialization_event = {"status": "initialized_this_run",
                                                  "duration_ns": getattr(encoder, "initialization_ns", None)}
            spatial = SemanticSelector.from_dict(gate.read_json(self.candidate["documents"]["spatial_q"]["path"]), encoder=encoder)
            temporal = TemporalSelector.from_dict(gate.read_json(self.candidate["documents"]["temporal_qst"]["path"]), encoder=encoder)
            self.encoder, self.spatial, self.temporal = encoder, spatial, temporal
        self._ready = True

    def loader(self, task_id):
        if not self._ready:
            raise gate.StudyStop("live operator has not passed initialization")
        gate.runtime_guard(self.candidate, clock=time.time)
        if task_id not in {row["task_id"] for row in self.plan["frame"]}:
            raise gate.StudyStop("task outside frozen frame")
        task, reference = load_task(self.settings["dev_source"]["path"], task_id, self.manifest, phase="holdout")
        opaque = execution.public_task_id(self.plan, task_id)
        self.loaded.append(task_id)
        return replace(task, task_id=opaque), replace(reference, task_id=opaque)

    def transport(self, endpoint, body=None):
        if not self._ready:
            raise gate.StudyStop("live operator has not passed initialization")
        gate.runtime_guard(self.candidate, clock=time.time)
        if endpoint != "chat/completions" or body is None:
            raise gate.StudyStop("only the bound study request is allowed")
        if self.client is None:
            self.client = Transport(load_key(self.settings["credential_file"], source="file"))
        return self.client(endpoint, body)

    def checkpoint(self, state):
        """Back up the exact core-validated complete prefix without overwriting."""
        if (not isinstance(state, dict) or state.get("state_sha256") != canonical_hash(
                {key: value for key, value in state.items() if key != "state_sha256"})):
            raise gate.StudyStop("checkpoint state identity changed")
        members = state.get("evidence")
        if not isinstance(members, dict) or not members:
            raise gate.StudyStop("checkpoint requires a complete evidence inventory")
        for name, checksum in members.items():
            if (not isinstance(name, str) or Path(name).is_absolute()
                    or ".." in Path(name).parts or Path(name).as_posix() != name
                    or not Path(name).parts or Path(name).parts[0] == "receipts"):
                raise gate.StudyStop("checkpoint evidence path outside the exact inventory")
            if file_hash(self.folder / name) != checksum:
                raise gate.StudyStop("checkpoint evidence changed before backup")
        path = self.folder / "receipts" / (state["state_sha256"] + ".zip")
        proof = _archive(self.folder, path, members)
        self._last_checkpoint = {"state_sha256": state["state_sha256"], "backup": proof}
        return proof

    def _save_resource_record(self, run_id, record):
        self._operation_outside_inventory()
        directory = self.operation / "sessions" / self._session_id / run_id
        directory.mkdir(parents=True, exist_ok=False)
        archive_path = directory / "EVIDENCE.zip"
        save(directory / "RESOURCE.json", record)
        members = {"RESOURCE.json": file_hash(directory / "RESOURCE.json")}
        manifest = {"schema": "z50-session-resource-manifest/v1", "session_id": self._session_id,
                    "run_id": run_id, "archive_path": str(archive_path.resolve()), "files": dict(members)}
        save(directory / "MANIFEST.json", manifest)
        members["MANIFEST.json"] = file_hash(directory / "MANIFEST.json")
        proof = _archive(directory, archive_path, members)
        backup = {"schema": "z50-session-resource-backup/v1", "backup": proof}
        save(directory / "BACKUP.json", backup)
        if gate.read_json(directory / "BACKUP.json") != backup:
            raise gate.StudyStop("session resource receipt failed reread")
        return {"path": str((directory / "BACKUP.json").resolve()),
                "sha256": file_hash(directory / "BACKUP.json"), "backup": proof}

    def run(self, section_end):
        observation = ProcessObservation()
        run_id = uuid4().hex
        self._last_checkpoint = None
        self.last_resource_evidence = None
        encoder_at_start = self.encoder
        self._encoder_initialization_event = None
        initialization_completed = False
        state = None
        failure = None
        try:
            self.initialize()
            initialization_completed = True
            state = execution.run_section(self.candidate, self.plan, folder=self.folder, control=self.control,
                        section_end=section_end, loader=self.loader, spatial_selector=self.spatial.select,
                        temporal_selector=self.temporal.select, transport=self.transport,
                        checkpoint=self.checkpoint, clock=time.time)
            return state
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                metrics = observation.finish()
                validate_observation(metrics, require_complete=False)
                encoder_event = self._encoder_initialization_event or {
                    "status": "reused" if initialization_completed and encoder_at_start is not None
                              and self.encoder is encoder_at_start else "not_initialized",
                    "duration_ns": None}
                record = {"schema": "z50-session-process-resources/v1", "session_id": self._session_id,
                          "run_id": run_id, "section_end": section_end,
                          "candidate_path": str(self.candidate_path), "candidate_sha256": self.candidate.get("sha256"),
                          "plan_hash": self.plan["plan_hash"], "operator_source_sha256": file_hash(__file__),
                          "outcome": "raised" if failure is not None else "returned",
                          "error_type": type(failure).__name__ if failure is not None else None,
                          "state_sha256": state["state_sha256"] if state is not None else None,
                          "checkpoint": self._last_checkpoint,
                          "encoder_initialization_status": encoder_event["status"],
                          "encoder_initialization_ns": encoder_event["duration_ns"],
                          "encoder_initialization_scope": "completed constructor in this run only; reuse has no new initialization time",
                          "process_observation": metrics,
                          "scope": "one Session.run including initialization, execution and study checkpoint; excludes this resource backup",
                          "limits": ["Process peak memory is not isolated arm consumption.",
                                     "Forced process termination may prevent finalization; catchable failures are recorded.",
                                     "Missing earlier measurements are never reconstructed."]}
                self.last_resource_evidence = self._save_resource_record(run_id, record)
                validate_observation(metrics, require_complete=True)
            except Exception as evidence_error:
                self._ready = False
                if failure is None:
                    raise gate.StudyStop("session process measurement is incomplete or its evidence was not safely stored") from evidence_error
                failure.add_note("Session process evidence incomplete or not safely stored: "
                                 + type(evidence_error).__name__ + "; retained files remain under " + str(self.operation))


def analyze_saved_panel(candidate_path, panel, output_path):
    """Only the prebound seed; complete validated panel and create-only output."""
    session = Session(candidate_path)
    binding = session.settings["analysis_binding"]
    gate.evidence_file(binding)
    if session.candidate["source_files"].get(binding["path"]) != binding["sha256"]:
        raise gate.StudyStop("analysis binding absent from frozen source manifest")
    contract = gate.read_json(session.settings["analysis_binding"]["path"])
    if (contract["study_id"] != session.plan["study_id"] or contract["seed_base"] != session.plan["seed_base"]
            or contract["bootstrap_repetitions"] != 19999 or contract["secondary_costs"] != "descriptive_only"):
        raise gate.StudyStop("analysis differs from frozen contract")
    # Only audit a historically authorized completed panel, without live clients.
    evidence_epoch = session.candidate["calendar"]["end_epoch"]
    rows = execution.collect_panel(session.candidate, session.plan, panel,
                     folder=session.folder, control=session.control, clock=lambda: evidence_epoch)
    result = analyze_panel(session.plan, panel, rows, bootstrap_seed=contract["primary_bootstrap_seed"])
    save(output_path, {"analysis_binding_sha256": binding["sha256"],
                       "read_only_evidence_clock": evidence_epoch, "report": result})
    return result
