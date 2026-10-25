"""Z51's separately bound, one-time P continuation after one lost response.

The original candidate, ledger, 100-pair checkpoint, partial journal and provider
files remain read-only. A new ledger records only new physical attempts. Exactly
one already billed partial response is replayed; the following unknown attempt
may be replaced once. The original 0.14 USD reservation is never an expense or
a provider-confirmed zero. All scientific execution and scoring use frozen code.

Activation hashes are canonical_hash(activation), WITHOUT a self-hash field.
The SHA256 of the saved ACTIVATION.json bytes is a separate archive identity.
The author/review/external-backup assertions are the coordinator's trust boundary;
this module checks their binding, not the identity of a human or remote account.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
import re

from communication_pruning.configurations import bank
from communication_pruning.contracts import Message, Request, TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, decode_outcome, strict_json
from communication_pruning.openrouter import decode_billing, encoded, payload, save_new
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import FileGuard, StudyAdapter, file_hash
from . import final_execution as fe, final_preflight as fp, final_recovery as fr
from .final_analysis import validate_rows
from .final_plan import ARMS, canonical_hash


RESERVE = Decimal("0.14")
SCHEMA = "z51-resume-activation/v1"
CLAIM_NAME = fp.NAMESPACE + ".resume.claim.json"
COPY_NAMES = ("started.json", "public.json", "reference.json", "selection.json", "spatial-measurement.json")


def _need(condition, message):
    if not condition:
        raise fp.StudyStop(message)


def _originals(candidate, plan, recovery_folder, expected_manifest_sha256):
    recovery_folder = fr._plain_path(recovery_folder)
    raw = fr._read(recovery_folder, "ORIGINALS.json")
    _need(fr._hash(raw) == expected_manifest_sha256, "bound recovery manifest changed")
    manifest = strict_json(raw)
    _need(manifest.get("schema") == "z51-offline-recovery-manifest/v1", "unknown recovery manifest")
    original = fr._plain_path(manifest["original_folder"])
    report, requests = fr._inspect(candidate, plan, original, manifest)
    report["manifest_sha256"] = expected_manifest_sha256
    _need(fr._json(recovery_folder, "PREPARATION.json") == report, "original recovery report changed")
    prefix = report["checkpoint_calls_preserved"]
    partial = requests[prefix:]
    _need(len(partial) == 2 and partial[0].outcome is not None and partial[1].outcome is None
          and partial[0].block_number == partial[1].block_number == report["completed_blocks_preserved"]
          and report["unresolved_attempts"] == [partial[1].request.attempt_id]
          and report["budget"]["held_reservation_usd"] == "0.14",
          "only one preserved partial response followed by one unknown attempt is authorized")
    return manifest, report, requests


def source_members(source_files):
    """Archive members for additional source files, sorted by absolute path."""
    return {f"resume-source-{i:04d}": checksum for i, (_, checksum) in enumerate(sorted(source_files.items()))}


def make_activation(candidate, plan, *, folder, control, recovery_folder, expected_manifest_sha256,
                    resume_id, source_files, source_backup, checkpoint, approval_reference,
                    support_declined=True):
    """Build reviewable technical data; this helper does not grant execution rights.

    The caller archives source_files with source_members() before using this
    helper. Pass canonical_hash(returned_dict) to all execution entry points.
    The original loader, spatial selector and transport stay candidate-bound;
    only the checkpoint callback may have a separately bound implementation.
    """
    manifest, report, requests = _originals(candidate, plan, recovery_folder, expected_manifest_sha256)
    unknown = requests[-1].request
    return {
        "schema": SCHEMA, "resume_id": resume_id,
        "candidate_sha256": canonical_hash(candidate), "plan_sha256": canonical_hash(plan),
        "execution_binding_sha256": fp.execution_binding(candidate),
        "folder": str(fr._plain_path(folder)), "control_directory": str(fr._plain_path(control)),
        "original_folder": manifest["original_folder"],
        "recovery_folder": str(fr._plain_path(recovery_folder)),
        "recovery_manifest_sha256": expected_manifest_sha256,
        "original_inventory_sha256": manifest["original_inventory_sha256"],
        "checkpoint_sha256": manifest["checkpoint_sha256"],
        "preserved_completed_blocks": report["completed_blocks_preserved"],
        "unknown_attempt_id": unknown.attempt_id,
        "unknown_request_sha256": fr._hash(encoded(payload(unknown, producer_limit=1024))),
        "held_original_reservation_usd": "0.14", "maximum_extra_physical_attempts": 1,
        "panels": ["P"], "support_declined": support_declined,
        "author_assumption": {"author": "Jannik", "decision": "D-069",
            "approval_reference": approval_reference, "explicit_resumption_authorization": True,
            "additional_original_cost_assumed_usd": "0", "provider_cost_confirmed": False},
        "source_files": deepcopy(source_files), "source_backup": deepcopy(source_backup),
        "dependency_bindings": {"checkpoint": fp.dependency_identity(checkpoint)},
    }


def _gate(candidate, plan, activation, expected_hash, folder, control, clock, dependencies=None):
    _need(canonical_hash(activation) == expected_hash, "external activation binding differs")
    folder, control = fr._plain_path(folder), fr._plain_path(control)
    fp.preflight(candidate, plan, control=control, clock=clock)
    _need(activation.get("schema") == SCHEMA
          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", activation.get("resume_id", "")) is not None
          and activation.get("candidate_sha256") == canonical_hash(candidate)
          and activation.get("plan_sha256") == canonical_hash(plan)
          and activation.get("execution_binding_sha256") == fp.execution_binding(candidate)
          and activation.get("folder") == str(folder)
          and activation.get("control_directory") == str(control)
          and activation.get("panels") == ["P"] and activation.get("support_declined") is True
          and activation.get("held_original_reservation_usd") == "0.14"
          and type(activation.get("maximum_extra_physical_attempts")) is int
          and activation["maximum_extra_physical_attempts"] == 1,
          "resume scope, source, candidate or budget binding differs")
    assumption = activation.get("author_assumption", {})
    _need(set(assumption) == {"author", "decision", "approval_reference", "explicit_resumption_authorization",
                             "additional_original_cost_assumed_usd", "provider_cost_confirmed"}
          and assumption["author"] == "Jannik" and assumption["decision"] == "D-069"
          and assumption["explicit_resumption_authorization"] is True
          and assumption["additional_original_cost_assumed_usd"] == "0"
          and assumption["provider_cost_confirmed"] is False
          and isinstance(assumption["approval_reference"], str) and bool(assumption["approval_reference"].strip()),
          "separate author assumption is missing or falsely confirms provider costs")
    files = activation["source_files"]
    required = {str(Path(__file__).resolve()), str(Path(fr.__file__).resolve()),
                str(Path(__file__).resolve().parents[1] / "tests" / "test_final_resume.py")}
    _need(isinstance(files, dict) and required <= set(files)
          and all(str(fr._plain_path(p)) == p for p in files), "additional recoverable sources required")
    FileGuard(files)()
    fp.verify_archive(activation["source_backup"], source_members(files))
    manifest, report, requests = _originals(candidate, plan, activation["recovery_folder"],
                                           activation["recovery_manifest_sha256"])
    original = fr._plain_path(manifest["original_folder"])
    _need(original != folder and original not in folder.parents and folder not in original.parents,
          "new segment must be separate from original files")
    _need(activation["original_folder"] == str(original)
          and activation["original_inventory_sha256"] == manifest["original_inventory_sha256"]
          and activation["checkpoint_sha256"] == manifest["checkpoint_sha256"]
          and activation["preserved_completed_blocks"] == report["completed_blocks_preserved"]
          and activation["unknown_attempt_id"] == requests[-1].request.attempt_id
          and activation["unknown_request_sha256"] == fr._hash(encoded(payload(requests[-1].request, producer_limit=1024))),
          "original prefix or exact replacement request differs")
    fe._claim(candidate, plan, original, control)
    if dependencies is not None:
        _need(set(dependencies) == {"loader", "spatial_selector", "transport", "checkpoint"},
              "all P continuation dependencies required")
        for key in ("loader", "spatial_selector", "transport"):
            identity = fp.dependency_identity(dependencies[key])
            _need(candidate["dependency_bindings"][key] == identity
                  and candidate["source_files"].get(identity["path"]) == identity["sha256"],
                  "original scientific dependency changed")
        identity = fp.dependency_identity(dependencies["checkpoint"])
        _need(activation["dependency_bindings"] == {"checkpoint": identity}
              and (files | candidate["source_files"]).get(identity["path"]) == identity["sha256"],
              "new checkpoint dependency changed")
        if candidate["mode"] != "artificial_only":
            from communication_pruning.semantic_selection import SemanticSelector
            method = dependencies["spatial_selector"]
            obj = getattr(method, "__self__", None)
            _need(type(obj) is SemanticSelector and method.__func__ is SemanticSelector.select
                  and obj.to_dict() == fp.read_json(candidate["documents"]["spatial_q"]["path"]),
                  "live Q must be the unchanged frozen selector")
    return manifest, report, requests


def _claim(activation, expected_hash, control, *, create=False):
    expected = {"schema": "z51-resume-claim/v1", "activation_sha256": expected_hash,
                "execution_binding_sha256": activation["execution_binding_sha256"],
                "recovery_manifest_sha256": activation["recovery_manifest_sha256"],
                "folder": activation["folder"], "original_folder": activation["original_folder"]}
    path = Path(control) / CLAIM_NAME
    if create:
        fe._save(path, expected)  # exclusive even when an identical claim already exists
    else:
        _need(fp.read_json(fr._plain_path(path)) == expected, "resume claim differs or belongs to another segment")


def _levels(candidate, original_cost, new_cost, *, reserve_calls=0):
    known = {p: Decimal(0) for p in ARMS}
    known["P"] = original_cost + new_cost
    result = fp.budget_view(candidate, known)
    available = {key: fp.money(value) for key, value in result["available_usd"].items()}
    for key in ("overall", "main"):
        available[key] -= RESERVE
    _need(min(available.values()) >= 0 and min(available["overall"], available["main"]) >= RESERVE * reserve_calls,
          "new calls and original unknown reservation exceed shared budget")
    result.update(available_usd={k: str(v) for k, v in available.items()},
                  held_original_reservation_usd="0.14", block_reservation_usd=str(RESERVE * reserve_calls),
                  reservation_is_expense=False)
    return result


def _budget(candidate, plan, folder, activation_hash, report, *, existing):
    available = _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), Decimal(0))["available_usd"]
    cap = min(fp.money(available["overall"]), fp.money(available["main"]))
    maximum = fp.MAX_CALLS["P"] * (plan["counts"]["P"] - report["completed_blocks_preserved"]) - 1
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "budget.jsonl", cap=cap, reserve=RESERVE, max_calls=maximum,
                   binding=activation_hash, allow_synthetic=candidate["mode"] == "artificial_only")


def _row_origin(row, activation, activation_hash, origin, number):
    result = deepcopy(row)
    result["recovery_provenance"] = {
        "activation_sha256": activation_hash, "recovery_manifest_sha256": activation["recovery_manifest_sha256"],
        "checkpoint_sha256": activation["checkpoint_sha256"], "origin": origin,
        "original_row_sha256": canonical_hash(row) if origin == "original_checkpoint" else None,
        "delayed_partial_block": number == activation["preserved_completed_blocks"],
        "cost_condition": "additional_original_unknown_cost_assumed_zero_not_provider_confirmed",
    }
    return result


def _mapping(activation, activation_hash, request, origin, *, new_index=None, original_index=None):
    return {"schema": "z51-attempt-mapping/v1", "activation_sha256": activation_hash,
            "logical_attempt_id": request.attempt_id,
            "physical_attempt_id": request.attempt_id if origin == "preserved_original" else
                request.attempt_id + ":" + activation["resume_id"],
            "origin": origin, "new_call_index": new_index, "original_call_index": original_index,
            "request_sha256": fr._hash(encoded(payload(request, producer_limit=1024)))}


def _decode_original(candidate, original, index, request, saved):
    body = fr._read(original, f"provider/{index:05d}-request.json")
    raw = fr._read(original, f"provider/{index:05d}-response.json")
    _need(body == encoded(payload(request, producer_limit=1024)), "preserved request bytes differ")
    response = decode_outcome(raw, request.max_output_tokens, F01)
    if candidate["mode"] == "artificial_only":
        response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
    _need(fe._terminal(request.attempt_id, response) == saved.outcome, "preserved response differs")
    return response


class _ResumeSend:
    """One in-memory consumer; every persisted partial/failed block stops forever."""
    def __init__(self, candidate, activation, activation_hash, folder, report, requests, adapter, clock, *, first):
        self.candidate, self.activation, self.activation_hash = candidate, activation, activation_hash
        self.folder, self.report, self.adapter, self.clock = folder, report, adapter, clock
        self.original = Path(activation["original_folder"])
        self.partial = requests[report["checkpoint_calls_preserved"]:]
        self.old_ids = {saved.request.attempt_id for saved in requests}
        self.position = 0 if first else 2
        self.poisoned, self.seen, self.stage = False, set(), "before_dispatch"

    def __call__(self, request):
        _need(not self.poisoned, "resume adapter already stopped; no retry")
        self.poisoned = True
        self.stage = "request_binding"
        _need(type(request) is Request and request.attempt_id not in self.seen, "duplicate or untyped logical attempt")
        fp.runtime_guard(self.candidate, clock=self.clock, panel="P")
        FileGuard(self.activation["source_files"])()
        _need(fp.read_json(self.folder / "ACTIVATION.json") == self.activation, "activation changed during execution")
        self.seen.add(request.attempt_id)
        prefix_calls = self.report["checkpoint_calls_preserved"]
        if self.position == 0:
            saved = self.partial[0]
            _need(request == saved.request, "partial replay request differs from original")
            index = prefix_calls + 1
            for part in ("request", "response", "binding", "received", "billing"):
                name = f"provider/{index:05d}-{part}.json"
                # Exact five original files were checked at section entry; check
                # their bytes again when this response is actually consumed.
                _need(file_hash(self.original / name) == self.report_inventory[name], "partial provider evidence changed")
            response = _decode_original(self.candidate, self.original, index, request, saved)
            record = _mapping(self.activation, self.activation_hash, request, "preserved_original", original_index=index)
            fe._save(self.folder / "mapping" / "000001.json", record)
            self.position = 1
        else:
            replacement = self.position == 1
            if replacement:
                _need(request == self.partial[1].request and self.adapter.budget.calls == 0
                      and fr._hash(encoded(payload(request, producer_limit=1024))) == self.activation["unknown_request_sha256"],
                      "only the exact first unknown request may be replaced once")
            else:
                _need(request.attempt_id not in self.old_ids, "original call cannot be repeated")
            _levels(self.candidate, fp.money(self.report["budget"]["known_cost_usd"]),
                    self.adapter.budget.cost, reserve_calls=1)
            new_index = self.adapter.budget.calls + 1
            record = _mapping(self.activation, self.activation_hash, request,
                              "replacement" if replacement else "new_regular", new_index=new_index,
                              original_index=prefix_calls + 2 if replacement else None)
            fe._save(self.folder / "mapping" / f"{new_index + 1:06d}.json", record)
            self.stage = "new_dispatch_or_billing"
            response = self.adapter(replace(request, attempt_id=record["physical_attempt_id"]))
            self.position = 2
        self.poisoned = False
        self.stage = "returned_billed_response"
        return response


def _inspect(candidate, plan, folder, activation, activation_hash, manifest, report, requests):
    """Check all new science/evidence and join the independently audited old prefix."""
    folder = Path(folder)
    _need(not (folder / "STOP.json").exists(), "new segment has a permanent technical stop")
    _need(fr._hash(fr._read(folder, "ORIGINALS.json")) == activation["recovery_manifest_sha256"],
          "retained original inventory binding changed")
    budget = _budget(candidate, plan, folder, activation_hash, report, existing=True)
    prefix = report["completed_blocks_preserved"]
    original = Path(activation["original_folder"])
    blocks = plan["panels"]["P"]
    started = sorted((folder / "blocks").glob("*/started.json"))
    complete = sorted((folder / "blocks").glob("*/complete.json"))
    _need(len(started) == len(complete) and prefix + len(complete) <= len(blocks), "new partial block cannot continue")
    expected_files = {"budget.jsonl", "ACTIVATION.json", "ORIGINALS.json"}
    attempts, segment_rows = [], []
    rows = [_row_origin(row, activation, activation_hash, "original_checkpoint", row["draw_index"])
            for row in manifest["checkpoint"]["rows"]]
    for number, complete_path in enumerate(complete, prefix):
        block, directory = blocks[number], folder / "blocks" / f"{number:06d}"
        _need(complete_path == directory / "complete.json" and started[number - prefix] == directory / "started.json"
              and fp.read_json(directory / "started.json") == {"block": block, "plan_hash": plan["plan_hash"]},
              "new blocks are not the unchanged contiguous P order")
        proof = fp.read_json(complete_path)
        _need(proof["block"] == block and proof["plan_hash"] == plan["plan_hash"], "complete block binding differs")
        for name, checksum in proof["evidence"].items():
            _need(fr._hash(fr._read(folder, name)) == checksum, "new complete evidence changed")
        expected_files.update(str((directory / name).relative_to(folder)) for name in COPY_NAMES)
        expected_files.add(str(complete_path.relative_to(folder)))
        if number == prefix:
            for name in COPY_NAMES:
                _need(fr._read(folder, f"blocks/{number:06d}/{name}") == fr._read(original, f"blocks/{number:06d}/{name}"),
                      "partial task, reference, selection or original measurement changed")
        public, private = fp.read_json(directory / "public.json"), fp.read_json(directory / "reference.json")
        task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
        reference = AnswerReference(private["task_id"], tuple(private["answers"]))
        _need(task.task_id == fe.public_task_id(plan, block["task_id"]) and reference.task_id == task.task_id,
              "new public/reference identity differs")
        selection = fp.read_json(directory / "selection.json")
        _need(set(selection) == {"spatial_q", "temporal_qst"} and selection["temporal_qst"] is None
              and selection["spatial_q"] in {c.config_id for c in bank()}, "invalid saved spatial decision")
        fe._check_selection_measurement(fp.read_json(directory / "spatial-measurement.json"),
                                        candidate, plan, block, "spatial", selection["spatial_q"])
        block_rows, block_files = [], set(str(p.relative_to(folder)) for p in directory.rglob("*") if p.is_file() and p.name != "complete.json")
        before_attempts = len(attempts)
        for slot in block["slots"]:
            arm, run_id = slot["arm"], plan["plan_hash"][:16] + ":" + slot["slot_id"]
            sd = directory / arm
            config, rounds, failed = fe._configuration(candidate, block, arm, selection)
            result, trace = fe._mas_result(sd / "journal.jsonl", config, task, reference, block)
            _need(trace["run_id"] == run_id and trace["rounds"] == rounds and trace["failed_role"] == failed
                  and trace["failure_policy"] == F01, "new MAS run/round/policy differs")
            pending = None
            for event in trace["events"]:
                if event["kind"] == "started":
                    _need(pending is None, "overlapping new MAS requests")
                    pending = Request(event["attempt_id"], task, event["role"], event["round"], event["instruction"],
                                      tuple(Message(**m) for m in event["messages"]), event["max_output_tokens"])
                elif event["kind"] in ("completed", "model_failed"):
                    _need(pending is not None and event["attempt_id"] == pending.attempt_id, "new request terminal differs")
                    attempts.append((pending, event))
                    pending = None
            _need(pending is None, "new journal contains unresolved request")
            row = _row_origin(fe._row(candidate, block, slot, result, config, rounds, failed, run_id),
                              activation, activation_hash, "resumed_segment", number)
            _need(fp.read_json(sd / "result.json") == row, "new numeric result differs")
            block_rows.append(row)
            expected_files.update(str((sd / name).relative_to(folder)) for name in ("journal.jsonl", "result.json"))
        _need(block_rows == proof["rows"], "new block result rows differ")
        # A complete proof binds precisely its own files, maps and provider calls.
        for logical_index in range(before_attempts + 1, len(attempts) + 1):
            block_files.add(f"mapping/{logical_index:06d}.json")
            if logical_index > 1:
                block_files.update(str(p.relative_to(folder)) for p in fe._provider_files(folder, logical_index - 1).values())
        _need(set(proof["evidence"]) == block_files, "block proof omits or claims unrelated evidence")
        segment_rows.extend(block_rows)
        rows.extend(block_rows)
    _need(len(attempts) == budget.calls + (1 if complete else 0), "new ledger and logical call counts differ")
    seen, generations = set(), {r["generation_id"] for r in report["replayable_calls"]}
    prefix_calls = report["checkpoint_calls_preserved"]
    for index, (request, event) in enumerate(attempts):
        _need(request.attempt_id not in seen, "duplicate logical call in new segment")
        seen.add(request.attempt_id)
        if index == 0:
            _need(request == requests[prefix_calls].request and event == requests[prefix_calls].outcome,
                  "new journal did not exactly replay original partial response")
            mapping = _mapping(activation, activation_hash, request, "preserved_original", original_index=prefix_calls + 1)
        else:
            if index == 1:
                _need(request == requests[-1].request, "replacement journal request differs")
            else:
                _need(request.attempt_id not in {r.request.attempt_id for r in requests}, "duplicate original request in new segment")
            mapping = _mapping(activation, activation_hash, request, "replacement" if index == 1 else "new_regular",
                               new_index=index, original_index=prefix_calls + 2 if index == 1 else None)
            physical, usage = budget.settlements[index - 1]
            names = fe._provider_files(folder, index)
            raw = names["response"].read_bytes()
            strict_json(raw)
            billed, generation = decode_billing(raw)
            response = decode_outcome(raw, request.max_output_tokens, F01)
            if candidate["mode"] == "artificial_only":
                response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
                billed = replace(billed, cost_source="synthetic")
            _need(physical == mapping["physical_attempt_id"]
                  and names["request"].read_bytes() == encoded(payload(request, producer_limit=1024))
                  and fe._terminal(request.attempt_id, response) == event and generation not in generations
                  and billed.to_dict() == usage
                  and fp.read_json(names["binding"]) == {"attempt_id": physical, "request_sha256": mapping["request_sha256"],
                      "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"}
                  and fp.read_json(names["billing"]) == {"generation_id": generation, "usage": usage, "response_sha256": file_hash(names["response"])}
                  and fp.read_json(names["received"]) == {"http_status": 200, "response_sha256": file_hash(names["response"])},
                  "new provider request, physical mapping, billing or response differs")
            generations.add(generation)
            expected_files.update(str(p.relative_to(folder)) for p in names.values())
        map_name = f"mapping/{index + 1:06d}.json"
        _need(fr._json(folder, map_name) == mapping, "logical/physical attempt mapping differs")
        expected_files.add(map_name)
    known_original = fp.money(report["budget"]["known_cost_usd"])
    known = known_original + budget.cost
    if complete:
        _need(sum((fp.money(row["cost_usd"]) for row in rows), Decimal(0)) == known,
              "joined rows double count or omit known costs")
    else:
        _need(budget.calls == 0 and budget.cost == 0, "calls exist before first complete resumed block")
    evidence = {name: checksum for name, checksum in fr.original_inventory(folder).items() if not name.startswith("receipts/")}
    _need(set(evidence) == expected_files, "unclaimed new files or duplicate dispatch files")
    completed = prefix + len(complete)
    state = {"schema": "z51-resume-state/v1", "activation_sha256": activation_hash,
        "execution_binding_sha256": fp.execution_binding(candidate), "plan_hash": plan["plan_hash"],
        "completed_blocks": completed, "complete": completed == plan["counts"]["P"], "panel": "P",
        "original_completed_blocks": prefix, "rows": rows, "new_budget": budget.snapshot(),
        "budget": {"calls": report["budget"]["calls"] + budget.calls, "new_calls": budget.calls,
            "known_cost_usd": str(known), "total_cost_usd": None,
            "held_reservation_usd": "0.14", "pending": report["budget"]["pending"],
            "poisoned": False, "reservation_is_expense": False},
        "levels": _levels(candidate, known_original, budget.cost),
        "cost_assumption": deepcopy(activation["author_assumption"]),
        "original_inventory_sha256": manifest["original_inventory_sha256"],
        "original_checkpoint_sha256": manifest["checkpoint_sha256"],
        "generation_ids": sorted(generations), "evidence": evidence}
    state["state_sha256"] = canonical_hash(state)
    return state, budget


def _load(candidate, plan, folder, control, expected_activation_sha256, clock, dependencies=None):
    folder = fr._plain_path(folder)
    activation = fr._json(folder, "ACTIVATION.json")
    context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock, dependencies)
    _claim(activation, expected_activation_sha256, control)
    return activation, context


def initialize_resume(candidate, plan, *, folder, control, recovery_folder, expected_manifest_sha256,
                      activation, expected_activation_sha256, clock):
    """Create once under the original exclusive lock; never dispatch a model call."""
    folder = fr._plain_path(folder)
    _need(activation["recovery_folder"] == str(fr._plain_path(recovery_folder))
          and activation["recovery_manifest_sha256"] == expected_manifest_sha256, "activation/recovery arguments differ")
    with fe.study_lock(control):
        context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock)
        _need(not folder.exists() and folder.parent.is_dir(), "new create-only segment required")
        manifest, report, requests = context
        _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), Decimal(0), reserve_calls=fp.MAX_CALLS["P"] - 1)
        _claim(activation, expected_activation_sha256, control, create=True)
        folder.mkdir()
        for name in ("blocks", "provider", "mapping", "receipts"):
            (folder / name).mkdir()
        fe._save(folder / "ACTIVATION.json", activation)
        save_new(folder / "ORIGINALS.json", fr._read(recovery_folder, "ORIGINALS.json"))
        _budget(candidate, plan, folder, expected_activation_sha256, report, existing=False)
        return _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]


def inspect_resume(candidate, plan, *, folder, control, expected_activation_sha256, clock):
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock)
        return _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]


def _checkpoint(folder, state, callback):
    path = fe._receipt_path(folder, state)
    if path.exists():
        fe._verify_receipt(folder, state)
        return
    proof = callback(deepcopy(state))
    fp.verify_archive(proof, state["evidence"])
    fe._save(path, {"state_sha256": state["state_sha256"], "backup": proof})


def checkpoint_resume(candidate, plan, *, folder, control, expected_activation_sha256, clock, checkpoint):
    """Back up a complete prefix after an interrupted backup, without dispatch."""
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock)
        identity = fp.dependency_identity(checkpoint)
        _need(activation["dependency_bindings"] == {"checkpoint": identity}, "checkpoint callback changed")
        state, _ = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)
        _checkpoint(folder, state, checkpoint)
        return state


def run_section(candidate, plan, *, folder, control, expected_activation_sha256, section_end,
                loader, spatial_selector, transport, checkpoint, clock):
    """Run exactly to 101 first, then the unchanged original later P control holds."""
    folder = fr._plain_path(folder)
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, transport=transport, checkpoint=checkpoint)
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock, dependencies)
        manifest, report, requests = context
        state, budget = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)
        prefix, completed = report["completed_blocks_preserved"], state["completed_blocks"]
        ends = sorted({prefix + 1, *(end for end in candidate["section_ends"] if prefix < end <= plan["counts"]["P"])})
        later = [end for end in ends if end > completed]
        _need(type(section_end) is int and later and section_end == later[0], "only next unchanged P control hold may run")
        if completed > prefix:
            fe._verify_receipt(folder, state)
        adapter = StudyAdapter(folder / "provider", transport, budget,
                               synthetic=candidate["mode"] == "artificial_only", failure_policy=F01)
        adapter.generations.update(state["generation_ids"])
        send = _ResumeSend(candidate, activation, expected_activation_sha256, folder, report, requests,
                           adapter, clock, first=completed == prefix)
        send.report_inventory = manifest["original_inventory"]
        stage, current_number = "before_block", completed
        try:
            for number in range(completed, section_end):
                current_number, stage = number, "block_guard"
                fp.runtime_guard(candidate, clock=clock, panel="P")
                _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), budget.cost,
                        reserve_calls=fp.MAX_CALLS["P"] - (1 if number == prefix else 0))
                _need(budget.calls + fp.MAX_CALLS["P"] - (1 if number == prefix else 0) <= budget.max_calls,
                      "complete next P block exceeds remaining new call count")
                block = plan["panels"]["P"][number]
                directory = folder / "blocks" / f"{number:06d}"
                directory.mkdir()
                first_call = budget.calls + 1
                first_map = 1 if number == prefix else budget.calls + 2
                stage = "task_and_selection"
                if number == prefix:
                    for name in COPY_NAMES:
                        source = f"blocks/{number:06d}/{name}"
                        raw = fr._read(activation["original_folder"], source)
                        _need(fr._hash(raw) == manifest["original_inventory"][source], "original partial block changed")
                        save_new(directory / name, raw)
                    public, private = fp.read_json(directory / "public.json"), fp.read_json(directory / "reference.json")
                    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
                    reference = AnswerReference(private["task_id"], tuple(private["answers"]))
                    selection = fp.read_json(directory / "selection.json")
                else:
                    fe._save(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"]})
                    task, reference = loader(block["task_id"])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference
                          and task.task_id == fe.public_task_id(plan, block["task_id"]) and reference.task_id == task.task_id,
                          "loader returned foreign task/reference")
                    fe._save(directory / "public.json", asdict(task))
                    fe._save(directory / "reference.json", asdict(reference))
                    q = fe._select_observed(spatial_selector, task, candidate=candidate, plan=plan,
                                           block=block, kind="spatial", directory=directory)
                    _need(q in {c.config_id for c in bank()}, "selector returned outside frozen bank")
                    selection = {"spatial_q": q, "temporal_qst": None}
                    fe._save(directory / "selection.json", selection)
                block_rows = []
                for slot in block["slots"]:
                    stage = "scientific_execution"
                    fp.runtime_guard(candidate, clock=clock, panel="P")
                    arm, run_id = slot["arm"], plan["plan_hash"][:16] + ":" + slot["slot_id"]
                    sd = directory / arm
                    sd.mkdir()
                    config, rounds, failed = fe._configuration(candidate, block, arm, selection)
                    execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id,
                            journal_path=sd / "journal.jsonl", producer_limit=1024, failure_policy=F01)
                    result, _ = fe._mas_result(sd / "journal.jsonl", config, task, reference, block)
                    row = _row_origin(fe._row(candidate, block, slot, result, config, rounds, failed, run_id),
                                      activation, expected_activation_sha256, "resumed_segment", number)
                    fe._save(sd / "result.json", row)
                    block_rows.append(row)
                files = [p for p in directory.rglob("*") if p.is_file()]
                files.extend(folder / "mapping" / f"{i:06d}.json" for i in range(first_map, budget.calls + 2))
                for index in range(first_call, budget.calls + 1):
                    files.extend(fe._provider_files(folder, index).values())
                fe._save(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": block_rows,
                    "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
            stage = "full_inspection"
            # Revalidate all original bytes at the section boundary, not per model call.
            context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock, dependencies)
            state, _ = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)
        except BaseException as error:
            if not (folder / "STOP.json").exists():
                fe._save(folder / "STOP.json", {"schema": "z51-resume-stop/v1", "activation_sha256": expected_activation_sha256,
                    "block_number": current_number, "stage": stage, "adapter_stage": send.stage,
                    "exception_type": type(error).__name__, "retry_allowed": False})
            raise
        # A backup-only failure leaves a complete auditable prefix. It can only be
        # checkpointed separately; run_section still requires the verified receipt.
        _checkpoint(folder, state, checkpoint)
        return state


def collect_panel(candidate, plan, panel="P", *, folder, control, expected_activation_sha256, clock):
    """Return a full original-size P panel with explicit recovery/cost provenance."""
    _need(panel == "P", "this continuation does not activate secondary panels")
    state = inspect_resume(candidate, plan, folder=folder, control=control,
                           expected_activation_sha256=expected_activation_sha256, clock=clock)
    fe._verify_receipt(folder, state)
    return validate_rows(plan, "P", state["rows"])
