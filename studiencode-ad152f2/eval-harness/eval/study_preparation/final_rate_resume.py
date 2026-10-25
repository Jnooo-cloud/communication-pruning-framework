"""D-071: additive P continuation with visible, bounded zero-cost 429 attempts.

The D-069 segment, its failed settlement and the original 100-pair segment are
read-only. This module does not reactivate their adapters or rewrite a ledger.
An accepted physical envelope may have outcome ``rate_limited``; it is never a
scientific answer. Each such envelope has separate immutable provider evidence.
Only its zero-cost classification permits another identical physical request.
The original unknown 01073 charge remains a separate 0.14 USD reservation.

External inventory, author and backup assertions remain coordinator trust
boundaries. Canonical activation hashes differ from hashes of saved file bytes.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import math
import re
import time

from communication_pruning.configurations import bank
from communication_pruning.contracts import Message, Request, TaskInput, Usage
from communication_pruning.data import AnswerReference, digest
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, strict_json
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import decode_billing, encoded, payload, save_new
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.rate_limit import classify
from communication_pruning.study import FileGuard, file_hash
from . import final_execution as fe, final_preflight as fp, final_recovery as fr, final_resume as previous
from .final_analysis import validate_rows
from .final_plan import canonical_hash

SCHEMA = "z51-rate-resume-activation/v1"
MANIFEST_SCHEMA = "z51-rate-resume-originals/v1"
CLAIM_NAME = fp.NAMESPACE + ".rate-resume.claim.json"
POLICY = {"author_decision": "D-071", "maximum_retries_per_logical_request": 3,
          "wait_seconds": [30, 60, 120], "eligible": "structured_choice_429_zero_tokens_zero_provider_cost",
          "prior_elapsed_time_counts": True, "physical_outcomes_are_preserved": True}
COPY_NAMES, RESERVE = previous.COPY_NAMES, previous.RESERVE
_need, _levels, _checkpoint = previous._need, previous._levels, previous._checkpoint
PARTS = ("request", "binding", "response", "received", "billing", "outcome")


def _epoch(value):
    stamp = datetime.fromisoformat(value)
    _need(stamp.tzinfo is not None, "timezone required for inherited failure time")
    return stamp.timestamp()


def _finite_time(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _typed_usage(value):
    return Usage(**{**value, "cost_usd": fp.money(value["cost_usd"])})


def _classify(candidate, status, raw, limit):
    # Frozen strict_json/decode_billing validate duplicate fields, provider/model,
    # explicit non-BYOK usage, token counts and identifiable provider generation.
    outcome, response, usage, generation = classify(status, raw, limit)
    if candidate["mode"] == "artificial_only":
        usage = replace(usage, cost_source="synthetic")
        if response is not None:
            response = replace(response, usage=usage)
    return outcome, response, usage, generation


def _old_ledger(raw, header):
    """Read the prior ledger, accepting only its final, durably billed zero failure."""
    _need(bool(raw) and raw.endswith(b"\n"), "partial previous ledger")
    rows, chain = [], "0" * 64
    for sequence, line in enumerate(raw.splitlines()):
        row = strict_json(line)
        checksum = row.pop("sha256")
        _need(type(row["sequence"]) is int and row["sequence"] == sequence
              and row["previous"] == chain and digest(row) == checksum, "previous ledger chain differs")
        _need(_finite_time(_epoch(row["time"])), "invalid previous ledger time")
        chain = checksum
        rows.append(row)
    clean = lambda row: {k: v for k, v in row.items() if k not in ("sequence", "previous", "time")}
    _need(clean(rows[0]) == header and len(rows) >= 3 and len(rows) % 2 == 1, "previous ledger header/open call")
    calls, ids, known = [], set(), Decimal(0)
    for offset in range(1, len(rows), 2):
        reserved, settled = rows[offset:offset + 2]
        aid = reserved["attempt_id"]
        _need(isinstance(aid, str) and aid and aid not in ids and len(calls) < header["max_calls"]
              and known + RESERVE <= fp.money(header["cap_usd"])
              and clean(reserved) == {"kind": "reserved", "attempt_id": aid,
                  "reservation_usd": str(RESERVE), "known_before_usd": str(known)}, "invalid previous reservation")
        usage = _typed_usage(settled["usage"])
        last = offset == len(rows) - 2
        _need(usage.cost_usd <= RESERVE
              and usage.cost_source == ("synthetic" if header["allow_synthetic"] else "provider")
              and clean(settled) == {"kind": "settled", "attempt_id": aid, "usage": usage.to_dict(),
                                     "failed": last, "over_reservation": False}, "unexpected prior failed settlement")
        _need(not last or usage.cost_usd == usage.input_tokens == usage.output_tokens == 0,
              "prior failed request is not explicitly free")
        ids.add(aid)
        known += usage.cost_usd
        calls.append({"attempt_id": aid, "usage": usage.to_dict(), "settled_epoch": _epoch(settled["time"])})
    return calls, known


def _block(candidate, plan, folder, number, *, complete, origin=None):
    """Read scientific identities in frozen order; no new selection or fit."""
    block = plan["panels"]["P"][number]
    directory = Path(folder) / "blocks" / f"{number:06d}"
    _need(fp.read_json(directory / "started.json") == {"block": block, "plan_hash": plan["plan_hash"]},
          "block order or plan differs")
    public = fp.read_json(directory / "public.json")
    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
    _need(strict_json(encoded(asdict(task))) == public and task.task_id == fe.public_task_id(plan, block["task_id"]),
          "public task identity differs")
    selection = fp.read_json(directory / "selection.json")
    _need(set(selection) == {"spatial_q", "temporal_qst"} and selection["temporal_qst"] is None
          and selection["spatial_q"] in {c.config_id for c in bank()}, "changed selection")
    fe._check_selection_measurement(fp.read_json(directory / "spatial-measurement.json"),
                                   candidate, plan, block, "spatial", selection["spatial_q"])
    files = {str((directory / name).relative_to(folder)) for name in COPY_NAMES}
    requests, rows, unfinished = [], [], False
    for slot in block["slots"]:
        sd = directory / slot["arm"]
        journal = sd / "journal.jsonl"
        if not journal.exists():
            _need(not complete, "missing completed slot")
            unfinished = True
            continue
        _need(not unfinished, "later journal after incomplete slot")
        config, rounds, failed = fe._configuration(candidate, block, slot["arm"], selection)
        checked = read_journal(journal, config)
        trace = checked["trace"]
        run_id = plan["plan_hash"][:16] + ":" + slot["slot_id"]
        _need(trace["task"] == public and trace["rounds"] == rounds and trace["failed_role"] == failed
              and trace["failure_policy"] == F01 and trace["run_id"] == run_id, "journal identity differs")
        terminals = {e["attempt_id"]: e for e in trace["events"] if e["kind"] in ("completed", "model_failed")}
        for event in trace["events"]:
            if event["kind"] == "started":
                request = Request(event["attempt_id"], task, event["role"], event["round"], event["instruction"],
                                  tuple(Message(**m) for m in event["messages"]), event["max_output_tokens"])
                requests.append(fr._OriginalCall(request, terminals.get(request.attempt_id), number))
        files.add(str(journal.relative_to(folder)))
        if checked["sealed"]:
            private = fp.read_json(directory / "reference.json")
            reference = AnswerReference(private["task_id"], tuple(private["answers"]))
            _need(reference.task_id == task.task_id, "reference identity differs")
            result, _ = fe._mas_result(journal, config, task, reference, block)
            row = fe._row(candidate, block, slot, result, config, rounds, failed, run_id)
            if origin is not None:
                row = origin(row, number)
            _need(fp.read_json(sd / "result.json") == row, "saved result differs from frozen reconstruction")
            files.add(str((sd / "result.json").relative_to(folder)))
            rows.append(row)
        else:
            _need(not complete and not (sd / "result.json").exists(), "unsealed completed result")
            unfinished = True
    _need(not complete or len(rows) == 2 and all(r.outcome is not None for r in requests), "incomplete P block")
    return requests, rows, files


def _inspect_previous(candidate, plan, manifest, clock):
    _need(manifest.get("schema") == MANIFEST_SCHEMA and manifest["candidate_sha256"] == canonical_hash(candidate)
          and manifest["plan_sha256"] == canonical_hash(plan), "previous scientific contract changed")
    folder = fr._plain_path(manifest["previous_folder"])
    inventory = manifest["previous_inventory"]
    fr._verify_inventory(folder, inventory, manifest["previous_inventory_sha256"])
    activation = fr._json(folder, "ACTIVATION.json")
    old_hash = manifest["previous_activation_sha256"]
    old_manifest, old_report, old_requests = previous._gate(candidate, plan, activation, old_hash,
        folder, candidate["control_directory"], clock)
    previous._claim(activation, old_hash, candidate["control_directory"])
    _need(fr._read(folder, "ORIGINALS.json") == fr._read(activation["recovery_folder"], "ORIGINALS.json"),
          "prior original manifest changed")
    available = _levels(candidate, fp.money(old_report["budget"]["known_cost_usd"]), Decimal(0))["available_usd"]
    prefix = old_report["completed_blocks_preserved"]
    header = {"kind": "header", "cap_usd": str(min(fp.money(available[k]) for k in ("overall", "main"))),
              "reserve_usd": "0.14", "max_calls": fp.MAX_CALLS["P"] * (plan["counts"]["P"] - prefix) - 1,
              "binding": old_hash, "allow_synthetic": candidate["mode"] == "artificial_only"}
    calls, cost = _old_ledger(fr._read(folder, "budget.jsonl"), header)
    complete_names = sorted(n for n in inventory if re.fullmatch(r"blocks/\d{6}/complete\.json", n))
    count = prefix + len(complete_names)
    _need(count < plan["counts"]["P"] and complete_names == [f"blocks/{i:06d}/complete.json" for i in range(prefix, count)],
          "previous completed prefix differs")
    started = sorted(n for n in inventory if re.fullmatch(r"blocks/\d{6}/started\.json", n))
    _need(started == [f"blocks/{i:06d}/started.json" for i in range(prefix, count + 1)], "exactly one next partial block required")
    stop = fr._json(folder, "STOP.json")
    _need(stop == {"schema": "z51-resume-stop/v1", "activation_sha256": old_hash, "block_number": count,
                  "stage": "scientific_execution", "adapter_stage": "new_dispatch_or_billing",
                  "exception_type": "BudgetStop", "retry_allowed": False}, "prior stop differs")
    claimed = {"ACTIVATION.json", "ORIGINALS.json", "budget.jsonl", "STOP.json"}
    rows = [previous._row_origin(r, activation, old_hash, "original_checkpoint", r["draw_index"])
            for r in old_manifest["checkpoint"]["rows"]]
    requests, block_files, proofs = [], {}, {}
    origin = lambda row, number: previous._row_origin(row, activation, old_hash, "resumed_segment", number)
    for number in range(prefix, count + 1):
        current, block_rows, files = _block(candidate, plan, folder, number, complete=number < count, origin=origin)
        if number == prefix:
            for name in COPY_NAMES:
                relative = f"blocks/{number:06d}/{name}"
                _need(fr._read(folder, relative) == fr._read(activation["original_folder"], relative), "old partial metadata changed")
        block_files[number] = files
        requests.extend(current)
        if number < count:
            proof = fr._json(folder, f"blocks/{number:06d}/complete.json")
            _need(proof["block"] == plan["panels"]["P"][number] and proof["plan_hash"] == plan["plan_hash"]
                  and proof["rows"] == block_rows, "previous completed rows differ")
            proofs[number] = proof
            rows.extend(block_rows)
            claimed.add(f"blocks/{number:06d}/complete.json")
    _need(len(requests) == len(calls) + 1 and len({r.request.attempt_id for r in requests}) == len(requests),
          "previous logical/physical counts differ")
    generations = {r["generation_id"] for r in old_report["replayable_calls"]}
    seeds = []
    for index, saved in enumerate(requests):
        request, number = saved.request, saved.block_number
        if index == 0:
            old = old_requests[old_report["checkpoint_calls_preserved"]]
            _need(request == old.request and saved.outcome == old.outcome, "original replay changed")
            mapping = previous._mapping(activation, old_hash, request, "preserved_original",
                                        original_index=old_report["checkpoint_calls_preserved"] + 1)
        else:
            _need(index != 1 or request == old_requests[-1].request, "old 01073 replacement changed")
            _need(index <= 1 or request.attempt_id not in {r.request.attempt_id for r in old_requests}, "original request repeated")
            mapping = previous._mapping(activation, old_hash, request, "replacement" if index == 1 else "new_regular",
                new_index=index, original_index=old_report["checkpoint_calls_preserved"] + 2 if index == 1 else None)
            call, names = calls[index - 1], fe._provider_files(folder, index)
            raw = names["response"].read_bytes()
            outcome, response, usage, generation = _classify(candidate, 200, raw, request.max_output_tokens)
            _need(call["attempt_id"] == mapping["physical_attempt_id"] and usage.to_dict() == call["usage"]
                  and generation not in generations and names["request"].read_bytes() == encoded(payload(request, producer_limit=1024))
                  and fp.read_json(names["binding"]) == {"attempt_id": mapping["physical_attempt_id"],
                      "request_sha256": mapping["request_sha256"], "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"}
                  and fp.read_json(names["received"]) == {"http_status": 200, "response_sha256": fr._hash(raw)}
                  and fp.read_json(names["billing"]) == {"generation_id": generation, "usage": usage.to_dict(), "response_sha256": fr._hash(raw)},
                  "previous request/response/provider/billing identity differs")
            last = index == len(requests) - 1
            _need((last and outcome == "rate_limited" and saved.outcome is None and number == count)
                  or (not last and response is not None and fe._terminal(request.attempt_id, response) == saved.outcome),
                  "only the final explicit zero 429 may lack an answer")
            generations.add(generation)
            block_files[number].update(str(p.relative_to(folder)) for p in names.values())
            if number == count:
                seeds.append({"logical_id": request.attempt_id, "output_limit": request.max_output_tokens,
                    "request": {"path": str(names["request"]), "sha256": file_hash(names["request"])},
                    "response": {"path": str(names["response"]), "sha256": fr._hash(raw)},
                    "received": {"path": str(names["received"]), "sha256": file_hash(names["received"])},
                    "billing": {"path": str(names["billing"]), "sha256": file_hash(names["billing"])},
                    "binding": {"path": str(names["binding"]), "sha256": file_hash(names["binding"])},
                    "received_at": call["settled_epoch"], "retry": 0, "origin": mapping["physical_attempt_id"]})
        map_name = f"mapping/{index + 1:06d}.json"
        _need(fr._json(folder, map_name) == mapping, "previous mapping changed")
        block_files[number].add(map_name)
    for number, files in block_files.items():
        if number in proofs:
            _need(proofs[number]["evidence"] == {n: inventory[n] for n in files}, "previous block evidence incomplete")
        claimed.update(files)
    _need({n for n in inventory if not n.startswith("receipts/")} == claimed, "unclaimed previous evidence")
    partial = [r for r in requests if r.block_number == count]
    _need(len(seeds) == len(partial) and partial and partial[-1].outcome is None
          and all(r.outcome is not None for r in partial[:-1]), "invalid partial replay sequence")
    known = fp.money(old_report["budget"]["known_cost_usd"]) + cost
    partial_cost = sum((_classify(candidate, 200, Path(s["response"]["path"]).read_bytes(), s["output_limit"])[2].cost_usd
                        for s in seeds), Decimal(0))
    _need(sum((fp.money(r["cost_usd"]) for r in rows), Decimal(0)) + partial_cost == known,
          "previous completed/partial costs are not conserved")
    report = {"schema": "z51-rate-resume-preparation/v1", "recovery_id": manifest["recovery_id"],
              "completed_blocks_preserved": count, "preserved_rows": len(rows), "preserved_rows_sha256": canonical_hash(rows),
              "partial_successful_calls": len(partial) - 1, "rate_limited_attempt_id": partial[-1].request.attempt_id,
              "rate_limited_request_sha256": fr._hash(encoded(payload(partial[-1].request, producer_limit=1024))),
              "budget": {"calls": old_report["budget"]["calls"] + len(calls), "known_cost_usd": str(known),
                         "held_reservation_usd": "0.14", "pending": old_report["budget"]["pending"], "reservation_is_expense": False},
              "partial_known_cost_usd": str(partial_cost), "previous_inventory_sha256": manifest["previous_inventory_sha256"],
              "new_model_calls": 0}
    protected = {s.request.attempt_id for s in old_requests + requests if s.block_number < count}
    return report, {"rows": rows, "partial": partial, "seeds": seeds, "generations": sorted(generations),
                    "protected_ids": sorted(protected),
                    "previous_activation": activation, "old_manifest": old_manifest}


def prepare_recovery(candidate, plan, *, previous_folder, expected_previous_activation_sha256,
                     inventory, expected_inventory_sha256, output, recovery_id, clock=time.time):
    folder, output = fr._plain_path(previous_folder), fr._plain_path(output)
    _need(not output.exists() and output.parent.is_dir() and folder != output and folder not in output.parents
          and output not in folder.parents, "separate create-only preparation required")
    manifest = {"schema": MANIFEST_SCHEMA, "recovery_id": recovery_id,
                "candidate_sha256": canonical_hash(candidate), "plan_sha256": canonical_hash(plan),
                "previous_folder": str(folder), "previous_activation_sha256": expected_previous_activation_sha256,
                "previous_inventory": deepcopy(inventory), "previous_inventory_sha256": expected_inventory_sha256}
    report, _ = _inspect_previous(candidate, plan, manifest, clock)
    raw = encoded(manifest)
    report["manifest_sha256"] = fr._hash(raw)
    output.mkdir()
    save_new(output / "ORIGINALS.json", raw)
    fe._save(output / "PREPARATION.json", report)
    return report


def _originals(candidate, plan, folder, expected_hash, clock):
    raw = fr._read(folder, "ORIGINALS.json")
    _need(fr._hash(raw) == expected_hash, "rate recovery manifest changed")
    manifest = strict_json(raw)
    report, context = _inspect_previous(candidate, plan, manifest, clock)
    report["manifest_sha256"] = expected_hash
    _need(fr._json(folder, "PREPARATION.json") == report, "rate preparation changed")
    return manifest, report, context


def source_members(source_files):
    return {f"rate-source-{i:04d}": sha for i, (_, sha) in enumerate(sorted(source_files.items()))}


def make_activation(candidate, plan, *, folder, control, recovery_folder, expected_manifest_sha256,
                    resume_id, source_files, source_backup, checkpoint, approval_reference,
                    support_declined=True, clock=time.time):
    manifest, report, context = _originals(candidate, plan, recovery_folder, expected_manifest_sha256, clock)
    old = context["previous_activation"]
    return {"schema": SCHEMA, "resume_id": resume_id, "candidate_sha256": canonical_hash(candidate),
        "plan_sha256": canonical_hash(plan), "execution_binding_sha256": fp.execution_binding(candidate),
        "folder": str(fr._plain_path(folder)), "control_directory": str(fr._plain_path(control)),
        "recovery_folder": str(fr._plain_path(recovery_folder)), "recovery_manifest_sha256": expected_manifest_sha256,
        "previous_folder": manifest["previous_folder"], "previous_activation_sha256": manifest["previous_activation_sha256"],
        "previous_inventory_sha256": manifest["previous_inventory_sha256"], "original_folder": old["original_folder"],
        "checkpoint_sha256": old["checkpoint_sha256"], "unknown_attempt_id": old["unknown_attempt_id"],
        "author_assumption": deepcopy(old["author_assumption"]), "held_original_reservation_usd": "0.14",
        "preserved_completed_blocks": report["completed_blocks_preserved"],
        "rate_limited_attempt_id": report["rate_limited_attempt_id"],
        "rate_limited_request_sha256": report["rate_limited_request_sha256"],
        "rate_policy": deepcopy(POLICY), "rate_authorization": {"author": "Jannik", "decision": "D-071",
            "approval_reference": approval_reference, "explicit_resumption_authorization": True},
        "panels": ["P"], "support_declined": support_declined, "source_files": deepcopy(source_files),
        "source_backup": deepcopy(source_backup), "dependency_bindings": {"checkpoint": fp.dependency_identity(checkpoint)}}


def _gate(candidate, plan, activation, expected_hash, folder, control, clock, dependencies=None):
    folder, control = fr._plain_path(folder), fr._plain_path(control)
    fp.preflight(candidate, plan, control=control, clock=clock)
    _need(canonical_hash(activation) == expected_hash and activation.get("schema") == SCHEMA
          and activation.get("rate_policy") == POLICY and activation.get("panels") == ["P"]
          and activation.get("support_declined") is True and activation.get("folder") == str(folder)
          and activation.get("control_directory") == str(control)
          and activation.get("candidate_sha256") == canonical_hash(candidate) and activation.get("plan_sha256") == canonical_hash(plan)
          and activation.get("execution_binding_sha256") == fp.execution_binding(candidate)
          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", activation.get("resume_id", "")), "rate activation differs")
    authorization = activation["rate_authorization"]
    _need(set(authorization) == {"author", "decision", "approval_reference", "explicit_resumption_authorization"}
          and authorization["author"] == "Jannik" and authorization["decision"] == "D-071"
          and authorization["explicit_resumption_authorization"] is True
          and isinstance(authorization["approval_reference"], str) and authorization["approval_reference"].strip(),
          "missing explicit D-071 authorization")
    files = activation["source_files"]
    from communication_pruning import rate_limit
    required = {str(Path(p).resolve()) for p in (__file__, previous.__file__, fr.__file__, rate_limit.__file__,
                Path(__file__).resolve().parents[1] / "tests/test_final_rate_resume.py")}
    _need(isinstance(files, dict) and required <= set(files) and all(str(fr._plain_path(p)) == p for p in files),
          "complete additional sources required")
    FileGuard(files)()
    fp.verify_archive(activation["source_backup"], source_members(files))
    manifest, report, context = _originals(candidate, plan, activation["recovery_folder"], activation["recovery_manifest_sha256"], clock)
    old = context["previous_activation"]
    for original in (manifest["previous_folder"], old["original_folder"]):
        path = fr._plain_path(original)
        _need(path != folder and path not in folder.parents and folder not in path.parents, "new output overlaps originals")
    expected = {"previous_folder": manifest["previous_folder"], "previous_activation_sha256": manifest["previous_activation_sha256"],
        "previous_inventory_sha256": manifest["previous_inventory_sha256"], "original_folder": old["original_folder"],
        "checkpoint_sha256": old["checkpoint_sha256"], "unknown_attempt_id": old["unknown_attempt_id"],
        "author_assumption": old["author_assumption"], "held_original_reservation_usd": "0.14",
        "preserved_completed_blocks": report["completed_blocks_preserved"], "rate_limited_attempt_id": report["rate_limited_attempt_id"],
        "rate_limited_request_sha256": report["rate_limited_request_sha256"]}
    _need(all(activation.get(k) == v for k, v in expected.items()), "preserved prefix/unknown charge/429 identity differs")
    if dependencies is not None:
        _need(set(dependencies) == {"loader", "spatial_selector", "transport", "checkpoint"}, "missing P dependency")
        for name in ("loader", "spatial_selector", "transport"):
            identity = fp.dependency_identity(dependencies[name])
            _need(candidate["dependency_bindings"][name] == identity and candidate["source_files"].get(identity["path"]) == identity["sha256"],
                  "frozen scientific dependency changed")
        identity = fp.dependency_identity(dependencies["checkpoint"])
        _need(activation["dependency_bindings"] == {"checkpoint": identity}
              and (files | candidate["source_files"]).get(identity["path"]) == identity["sha256"], "checkpoint changed")
        if candidate["mode"] != "artificial_only":
            from communication_pruning.semantic_selection import SemanticSelector
            method = dependencies["spatial_selector"]
            obj = getattr(method, "__self__", None)
            _need(type(obj) is SemanticSelector and method.__func__ is SemanticSelector.select
                  and obj.to_dict() == fp.read_json(candidate["documents"]["spatial_q"]["path"]), "live Q differs")
    return manifest, report, context


def _claim(activation, checksum, control, *, create=False):
    expected = {"schema": "z51-rate-resume-claim/v1", "activation_sha256": checksum,
        "execution_binding_sha256": activation["execution_binding_sha256"], "folder": activation["folder"],
        "previous_activation_sha256": activation["previous_activation_sha256"],
        "recovery_manifest_sha256": activation["recovery_manifest_sha256"]}
    path = Path(control) / CLAIM_NAME
    if create:
        fe._save(path, expected)
    else:
        _need(fp.read_json(fr._plain_path(path)) == expected, "rate claim changed or duplicate segment")


def _budget(candidate, plan, folder, checksum, report, *, existing):
    available = _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), Decimal(0))["available_usd"]
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "provider/budget.jsonl", cap=min(fp.money(available[k]) for k in ("overall", "main")),
        reserve=RESERVE, max_calls=4 * fp.MAX_CALLS["P"] * (plan["counts"]["P"] - report["completed_blocks_preserved"]),
        binding=checksum, allow_synthetic=candidate["mode"] == "artificial_only")


def _files(folder, number):
    return {part: Path(folder) / "provider" / f"{number:06d}-{part}.json" for part in PARTS}


class RateSend:
    """D-071 physical evidence and logical replay; caller holds the original lock."""
    def __init__(self, candidate, activation, checksum, folder, budget, context, *, transport=None,
                 clock=time.time, sleep=time.sleep, guard=lambda: None):
        self.candidate, self.activation, self.checksum = candidate, activation, checksum
        self.folder, self.budget, self.transport = Path(folder), budget, transport
        self.clock, self.sleep, self.guard = clock, sleep, guard
        self.wait_clock = clock if candidate["mode"] == "artificial_only" else time.monotonic
        self.protected_ids = set(context["protected_ids"])
        self.states, self.records, self.generations, self.seen = {}, [], set(context["generations"]), set()
        self.poisoned, self.stage = False, "before_dispatch"
        self.seed_files = {v["path"]: v["sha256"] for s in context["seeds"] for k, v in s.items()
                           if k in ("request", "response", "received", "billing", "binding")}
        for seed in context["seeds"]:
            for name in ("request", "response", "received", "billing", "binding"):
                _need(file_hash(seed[name]["path"]) == seed[name]["sha256"], "seed evidence changed")
            raw = Path(seed["response"]["path"]).read_bytes()
            outcome, response, usage, generation = _classify(candidate, 200, raw, seed["output_limit"])
            _need(seed["logical_id"] not in self.states and generation in self.generations and seed["retry"] == 0,
                  "duplicate or incorrectly counted inherited attempt")
            self.states[seed["logical_id"]] = {"body": Path(seed["request"]["path"]).read_bytes(),
                "output_limit": seed["output_limit"], "outcome": outcome, "response": response,
                "usage": usage.to_dict(), "generation": generation, "retry": 0,
                "received": seed["received_at"], "origin": seed["origin"]}
        self._restore()

    def _binding(self, request_id, body, limit, number, prior, dispatched, waited):
        retry = 0 if prior is None else prior["retry"] + 1
        deadline = None if prior is None else prior["received"] + POLICY["wait_seconds"][retry - 1] if retry <= 3 else None
        return {"schema": "z51-D071-dispatch/v1", "activation_sha256": self.checksum,
            "logical_attempt_id": request_id, "physical_attempt_id": self.activation["resume_id"] + f":physical:{number:06d}",
            "request_sha256": fr._hash(body), "output_limit": limit, "retry": retry,
            "not_before": deadline, "dispatched_at": dispatched,
            "wait_elapsed_seconds": waited,
            "previous_physical_attempt_id": None if prior is None else prior["origin"],
            "previous_received_at": None if prior is None else prior["received"]}

    def _accept(self, binding, body, received, outcome, response, usage, generation):
        self.generations.add(generation)
        self.states[binding["logical_attempt_id"]] = {"body": body, "output_limit": binding["output_limit"],
            "outcome": outcome, "response": response, "usage": usage.to_dict(), "generation": generation,
            "retry": binding["retry"], "received": received["received_at"], "origin": binding["physical_attempt_id"]}
        self.records.append({"binding": binding, "received": received, "outcome": outcome,
                             "usage": usage.to_dict(), "generation_id": generation})

    def _restore(self):
        expected = {"provider/budget.jsonl"}
        for number, (physical, billed) in enumerate(self.budget.settlements if hasattr(self.budget, "settlements") else [], 1):
            names = _files(self.folder, number)
            body, raw = names["request"].read_bytes(), names["response"].read_bytes()
            binding, received = fp.read_json(names["binding"]), fp.read_json(names["received"])
            prior = self.states.get(binding["logical_attempt_id"])
            _need(prior is None or prior["outcome"] == "rate_limited" and prior["body"] == body
                  and prior["output_limit"] == binding["output_limit"] and prior["retry"] < 3, "invalid retry ancestry")
            target = self._binding(binding["logical_attempt_id"], body, binding["output_limit"], number, prior,
                                   binding["dispatched_at"], binding["wait_elapsed_seconds"])
            _need(binding == target and binding["physical_attempt_id"] == physical and _finite_time(binding["dispatched_at"])
                  and (binding["not_before"] is None or binding["dispatched_at"] >= binding["not_before"])
                  and _finite_time(binding["wait_elapsed_seconds"]) and (prior is not None or binding["wait_elapsed_seconds"] == 0)
                  and _finite_time(received["received_at"]) and received["received_at"] >= binding["dispatched_at"]
                  and received == {"http_status": received["http_status"], "received_at": received["received_at"],
                                   "response_sha256": fr._hash(raw)}, "dispatch or wait evidence changed")
            outcome, response, usage, generation = _classify(self.candidate, received["http_status"], raw, binding["output_limit"])
            _need(generation not in self.generations and usage.to_dict() == billed
                  and fp.read_json(names["billing"]) == {"generation_id": generation, "usage": billed, "response_sha256": fr._hash(raw)}
                  and fp.read_json(names["outcome"]) == {"outcome": outcome, "generation_id": generation, "usage": billed},
                  "changed generation, classification or billing")
            self._accept(binding, body, received, outcome, response, usage, generation)
            expected.update(str(p.relative_to(self.folder)) for p in names.values())
        actual = {str(p.relative_to(self.folder)) for p in (self.folder / "provider").iterdir() if p.is_file()}
        _need(actual == expected and all(p.is_file() and not p.is_symlink() for p in (self.folder / "provider").iterdir()),
              "orphan/missing provider evidence")

    def __call__(self, request):
        _need(not self.poisoned and type(request) is Request and request.attempt_id not in self.seen
              and request.attempt_id not in self.protected_ids,
              "stopped or duplicate logical request")
        self.seen.add(request.attempt_id)
        body = encoded(payload(request, producer_limit=1024))
        while True:
            self.guard()
            prior = self.states.get(request.attempt_id)
            _need(prior is None or prior["body"] == body and prior["output_limit"] == request.max_output_tokens,
                  "logical replay/retry input changed")
            if prior is not None and prior["outcome"] != "rate_limited":
                FileGuard(self.seed_files)()
                return prior["response"]
            _need(self.transport is not None and (prior is None or prior["retry"] < 3), "D-071 retry bound exhausted")
            retry = 0 if prior is None else prior["retry"] + 1
            deadline = None if prior is None else prior["received"] + POLICY["wait_seconds"][retry - 1]
            _need(deadline is None or deadline <= self.candidate["calendar"]["end_epoch"], "retry wait exceeds original calendar")
            waited = 0.0
            while deadline is not None and self.clock() < deadline:
                self.guard()
                before = self.clock()
                wait_start = self.wait_clock()
                self.sleep(min(30, deadline - before))
                wait_end = self.wait_clock()
                _need(_finite_time(wait_start) and _finite_time(wait_end) and wait_end >= wait_start, "invalid measured wait time")
                waited += wait_end - wait_start
                _need(self.clock() > before, "wait clock did not advance")
            self.guard()
            FileGuard(self.seed_files)()
            self.poisoned, self.stage = True, "physical_dispatch"
            number = self.budget.calls + 1
            binding = self._binding(request.attempt_id, body, request.max_output_tokens, number, prior, self.clock(), waited)
            _need(_finite_time(binding["dispatched_at"]), "invalid dispatch clock")
            names = _files(self.folder, number)
            save_new(names["request"], body)
            fe._save(names["binding"], binding)
            self.budget.start(binding["physical_attempt_id"])
            usage = Usage()
            try:
                status, raw = self.transport("chat/completions", body)
                save_new(names["response"], raw)
                received = {"http_status": status, "received_at": self.clock(), "response_sha256": fr._hash(raw)}
                fe._save(names["received"], received)
                decoded, generation = decode_billing(raw)
                _need(generation not in self.generations, "duplicate provider generation")
                usage = replace(decoded, cost_source="synthetic") if self.candidate["mode"] == "artificial_only" else decoded
                fe._save(names["billing"], {"generation_id": generation, "usage": usage.to_dict(), "response_sha256": fr._hash(raw)})
                outcome, response, usage, generation = _classify(self.candidate, status, raw, request.max_output_tokens)
                _need(_finite_time(received["received_at"]) and received["received_at"] >= binding["dispatched_at"], "invalid receipt clock")
                fe._save(names["outcome"], {"outcome": outcome, "generation_id": generation, "usage": usage.to_dict()})
            except Exception:
                self.budget.settle(usage, failed=True)
                raise
            # This settles a classified physical envelope, not a valid answer.
            self.budget.settle(usage)
            self._accept(binding, body, received, outcome, response, usage, generation)
            self.poisoned, self.stage = False, "recorded_physical_outcome"
            if response is not None:
                return response


def _row_origin(row, activation, checksum, number):
    result = deepcopy(row)
    result["rate_resume_provenance"] = {"activation_sha256": checksum,
        "recovery_manifest_sha256": activation["recovery_manifest_sha256"], "origin": "D-071-segment",
        "delayed_partial_block": number == activation["preserved_completed_blocks"],
        "old_unknown_cost_condition": "D-069 assumption remains; not provider-confirmed zero"}
    return result


def _map(activation, checksum, request, saved, number):
    return {"schema": "z51-D071-logical-map/v1", "activation_sha256": checksum,
            "logical_attempt_id": request.attempt_id, "block_number": number,
            "request_sha256": fr._hash(encoded(payload(request, producer_limit=1024))),
            "response_generation_id": saved["generation"], "response_origin": saved["origin"],
            "final_retry": saved["retry"], "response_usage": saved["usage"]}


def _inspect(candidate, plan, folder, activation, checksum, manifest, report, context):
    folder = Path(folder)
    _need(not (folder / "STOP.json").exists(), "new segment has permanent stop; no restart resets retries")
    _need(fr._hash(fr._read(folder, "ORIGINALS.json")) == activation["recovery_manifest_sha256"], "saved originals changed")
    budget = _budget(candidate, plan, folder, checksum, report, existing=True)
    sender = RateSend(candidate, activation, checksum, folder, budget, context)
    prefix = report["completed_blocks_preserved"]
    started = sorted((folder / "blocks").glob("*/started.json"))
    complete = sorted((folder / "blocks").glob("*/complete.json"))
    _need(len(started) == len(complete) and prefix + len(complete) <= plan["counts"]["P"], "partial new block cannot restart")
    expected = {"ACTIVATION.json", "ORIGINALS.json", "provider/budget.jsonl"}
    rows, logical, seen = deepcopy(context["rows"]), [], set()
    by_logical = {}
    for index, record in enumerate(sender.records, 1):
        by_logical.setdefault(record["binding"]["logical_attempt_id"], []).append(index)
    for number, path in enumerate(complete, prefix):
        directory = folder / "blocks" / f"{number:06d}"
        _need(path == directory / "complete.json" and started[number - prefix] == directory / "started.json", "new prefix order differs")
        origin = lambda row, n: _row_origin(row, activation, checksum, n)
        calls, block_rows, files = _block(candidate, plan, folder, number, complete=True, origin=origin)
        if number == prefix:
            for name in COPY_NAMES:
                relative = f"blocks/{number:06d}/{name}"
                _need(fr._read(folder, relative) == fr._read(manifest["previous_folder"], relative), "preserved partial metadata differs")
        for saved in calls:
            request = saved.request
            _need(request.attempt_id not in seen and request.attempt_id in sender.states, "missing or repeated new logical outcome")
            seen.add(request.attempt_id)
            state = sender.states[request.attempt_id]
            _need(state["response"] is not None and state["body"] == encoded(payload(request, producer_limit=1024))
                  and fe._terminal(request.attempt_id, state["response"]) == saved.outcome, "logical answer differs from physical evidence")
            index = len(logical) + 1
            map_name = f"mapping/{index:06d}.json"
            _need(fr._json(folder, map_name) == _map(activation, checksum, request, state, number), "logical mapping differs")
            logical.append(saved)
            files.add(map_name)
            for i in by_logical.get(request.attempt_id, []):
                files.update(str(p.relative_to(folder)) for p in _files(folder, i).values())
        proof = fp.read_json(path)
        _need(proof == {"block": plan["panels"]["P"][number], "plan_hash": plan["plan_hash"], "rows": block_rows,
                        "evidence": {name: file_hash(folder / name) for name in files}}, "new complete evidence differs")
        expected.update(files)
        expected.add(str(path.relative_to(folder)))
        rows.extend(block_rows)
    partial = context["partial"]
    if complete:
        _need([s.request for s in logical[:len(partial)]] == [s.request for s in partial]
              and [s.outcome for s in logical[:len(partial) - 1]] == [s.outcome for s in partial[:-1]], "partial answers were replaced")
    _need(all(r["binding"]["logical_attempt_id"] in seen for r in sender.records), "unclaimed physical attempt")
    known = fp.money(report["budget"]["known_cost_usd"]) + budget.cost
    if complete:
        _need(sum((fp.money(r["cost_usd"]) for r in rows), Decimal(0)) == known, "joined known costs differ")
    else:
        _need(budget.calls == 0, "new physical work without complete block")
    evidence = {n: h for n, h in fr.original_inventory(folder).items() if not n.startswith("receipts/")}
    _need(set(evidence) == expected, "unclaimed segment files")
    state = {"schema": "z51-rate-resume-state/v1", "activation_sha256": checksum,
        "execution_binding_sha256": fp.execution_binding(candidate), "plan_hash": plan["plan_hash"],
        "completed_blocks": prefix + len(complete), "complete": prefix + len(complete) == plan["counts"]["P"],
        "original_completed_blocks": prefix, "panel": "P", "rows": rows, "new_budget": budget.snapshot(),
        "budget": {"calls": report["budget"]["calls"] + budget.calls, "new_calls": budget.calls,
            "known_cost_usd": str(known), "total_cost_usd": None, "held_reservation_usd": "0.14",
            "pending": report["budget"]["pending"], "poisoned": False, "reservation_is_expense": False},
        "levels": _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), budget.cost),
        "rate_policy": deepcopy(POLICY), "physical_attempts": sender.records,
        "additional_rate_retries": sum(r["binding"]["retry"] > 0 for r in sender.records),
        "rate_summary": {"inherited_physical_attempts": report["budget"]["calls"],
            "new_physical_attempts": budget.calls, "total_physical_attempts": report["budget"]["calls"] + budget.calls,
            "inherited_zero_cost_429_attempts": 1,
            "new_zero_cost_429_attempts": sum(r["outcome"] == "rate_limited" for r in sender.records),
            "total_zero_cost_429_attempts": 1 + sum(r["outcome"] == "rate_limited" for r in sender.records),
            "new_retry_attempts": sum(r["binding"]["retry"] > 0 for r in sender.records),
            "new_wait_elapsed_seconds": math.fsum(r["binding"]["wait_elapsed_seconds"] for r in sender.records),
            "wait_scope": "monotonic elapsed inside new sleep calls, including scheduler delay; inherited downtime excluded; artificial mode uses injected clock"},
        "generation_ids": sorted(sender.generations), "cost_assumption": deepcopy(activation["author_assumption"]),
        "evidence": evidence}
    state["state_sha256"] = canonical_hash(state)
    return state, budget, sender


def _load(candidate, plan, folder, control, checksum, clock, dependencies=None):
    activation = fr._json(folder, "ACTIVATION.json")
    context = _gate(candidate, plan, activation, checksum, folder, control, clock, dependencies)
    _claim(activation, checksum, control)
    return activation, context


def initialize_resume(candidate, plan, *, folder, control, recovery_folder, expected_manifest_sha256,
                      activation, expected_activation_sha256, clock):
    folder = fr._plain_path(folder)
    _need(activation["recovery_folder"] == str(fr._plain_path(recovery_folder))
          and activation["recovery_manifest_sha256"] == expected_manifest_sha256, "preparation arguments differ")
    with fe.study_lock(control):
        context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock)
        _need(not folder.exists() and folder.parent.is_dir(), "new create-only segment required")
        _claim(activation, expected_activation_sha256, control, create=True)
        folder.mkdir()
        for name in ("blocks", "provider", "mapping", "receipts"):
            (folder / name).mkdir()
        fe._save(folder / "ACTIVATION.json", activation)
        save_new(folder / "ORIGINALS.json", fr._read(recovery_folder, "ORIGINALS.json"))
        _budget(candidate, plan, folder, expected_activation_sha256, context[1], existing=False)
        return _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]


def inspect_resume(candidate, plan, *, folder, control, expected_activation_sha256, clock):
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock)
        return _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]


def checkpoint_resume(candidate, plan, *, folder, control, expected_activation_sha256, clock, checkpoint):
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock)
        _need(activation["dependency_bindings"] == {"checkpoint": fp.dependency_identity(checkpoint)}, "checkpoint differs")
        state = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]
        _checkpoint(Path(folder), state, checkpoint)
        return state


def run_section(candidate, plan, *, folder, control, expected_activation_sha256, section_end,
                loader, spatial_selector, transport, checkpoint, clock, sleep=time.sleep):
    folder = fr._plain_path(folder)
    _need(candidate["mode"] == "artificial_only" or sleep is time.sleep, "live waits must use time.sleep")
    dependencies = dict(loader=loader, spatial_selector=spatial_selector, transport=transport, checkpoint=checkpoint)
    with fe.study_lock(control):
        activation, context = _load(candidate, plan, folder, control, expected_activation_sha256, clock, dependencies)
        manifest, report, originals = context
        state, budget, sender = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)
        prefix, completed = report["completed_blocks_preserved"], state["completed_blocks"]
        ends = sorted({prefix + 1, *(e for e in candidate["section_ends"] if prefix < e <= plan["counts"]["P"])})
        later = [e for e in ends if e > completed]
        _need(type(section_end) is int and later and section_end == later[0], "only next original hold may execute")
        fe._verify_receipt(folder, state)
        def guard():
            fp.runtime_guard(candidate, clock=clock, panel="P")
            FileGuard(activation["source_files"])()
            _need(fp.read_json(folder / "ACTIVATION.json") == activation, "activation changed during run")
            _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), budget.cost, reserve_calls=1)
        sender.transport, sender.clock, sender.sleep, sender.guard = transport, clock, sleep, guard
        sender.wait_clock = clock if candidate["mode"] == "artificial_only" else time.monotonic
        stage, current = "before_block", completed
        logical_count = len(list((folder / "mapping").glob("*.json")))
        try:
            for number in range(completed, section_end):
                current, stage = number, "block_guard"
                guard()
                preserved = report["partial_successful_calls"] if number == prefix else 0
                _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), budget.cost,
                        reserve_calls=fp.MAX_CALLS["P"] - preserved)
                directory = folder / "blocks" / f"{number:06d}"
                directory.mkdir()
                first_call, first_map = budget.calls + 1, logical_count + 1
                if number == prefix:
                    for name in COPY_NAMES:
                        relative = f"blocks/{number:06d}/{name}"
                        raw = fr._read(manifest["previous_folder"], relative)
                        _need(fr._hash(raw) == manifest["previous_inventory"][relative], "previous partial changed")
                        save_new(directory / name, raw)
                    public, private = fp.read_json(directory / "public.json"), fp.read_json(directory / "reference.json")
                    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
                    reference = AnswerReference(private["task_id"], tuple(private["answers"]))
                    selection = fp.read_json(directory / "selection.json")
                else:
                    block = plan["panels"]["P"][number]
                    fe._save(directory / "started.json", {"block": block, "plan_hash": plan["plan_hash"]})
                    task, reference = loader(block["task_id"])
                    _need(type(task) is TaskInput and type(reference) is AnswerReference
                          and task.task_id == fe.public_task_id(plan, block["task_id"]) and reference.task_id == task.task_id, "foreign task/reference")
                    fe._save(directory / "public.json", asdict(task))
                    fe._save(directory / "reference.json", asdict(reference))
                    q = fe._select_observed(spatial_selector, task, candidate=candidate, plan=plan, block=block, kind="spatial", directory=directory)
                    selection = {"spatial_q": q, "temporal_qst": None}
                    fe._save(directory / "selection.json", selection)
                block, block_rows = plan["panels"]["P"][number], []
                partial_position = 0
                def send(request):
                    nonlocal logical_count, partial_position
                    if number == prefix and partial_position < len(originals["partial"]):
                        _need(request == originals["partial"][partial_position].request, "partial replay order/input differs")
                        partial_position += 1
                    response = sender(request)
                    logical_count += 1
                    fe._save(folder / "mapping" / f"{logical_count:06d}.json",
                             _map(activation, expected_activation_sha256, request, sender.states[request.attempt_id], number))
                    return response
                for slot in block["slots"]:
                    stage = "scientific_execution"
                    guard()
                    arm, run_id = slot["arm"], plan["plan_hash"][:16] + ":" + slot["slot_id"]
                    sd = directory / arm
                    sd.mkdir()
                    config, rounds, failed = fe._configuration(candidate, block, arm, selection)
                    execute(task, config, send, rounds=rounds, failed_role=failed, run_id=run_id,
                            journal_path=sd / "journal.jsonl", producer_limit=1024, failure_policy=F01)
                    result, _ = fe._mas_result(sd / "journal.jsonl", config, task, reference, block)
                    row = _row_origin(fe._row(candidate, block, slot, result, config, rounds, failed, run_id), activation, expected_activation_sha256, number)
                    fe._save(sd / "result.json", row)
                    block_rows.append(row)
                files = [p for p in directory.rglob("*") if p.is_file()]
                files.extend(folder / "mapping" / f"{i:06d}.json" for i in range(first_map, logical_count + 1))
                for i in range(first_call, budget.calls + 1):
                    files.extend(_files(folder, i).values())
                fe._save(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": block_rows,
                    "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
            stage = "full_inspection"
            context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock, dependencies)
            state = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]
        except BaseException as error:
            if not (folder / "STOP.json").exists():
                fe._save(folder / "STOP.json", {"schema": "z51-rate-resume-stop/v1", "activation_sha256": expected_activation_sha256,
                    "block_number": current, "stage": stage, "adapter_stage": sender.stage, "exception_type": type(error).__name__,
                    "retry_allowed": False, "physical_calls": budget.calls})
            raise
        _checkpoint(folder, state, checkpoint)
        return state


def collect_panel(candidate, plan, panel="P", *, folder, control, expected_activation_sha256, clock):
    _need(panel == "P", "D-071 does not activate secondary panels")
    state = inspect_resume(candidate, plan, folder=folder, control=control, expected_activation_sha256=expected_activation_sha256, clock=clock)
    fe._verify_receipt(Path(folder), state)
    return validate_rows(plan, "P", state["rows"])
