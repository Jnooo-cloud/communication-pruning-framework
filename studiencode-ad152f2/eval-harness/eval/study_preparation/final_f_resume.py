"""D-073: replace exactly the authorized lost F request 011355 once.

Four predecessor segments and all three unknown original charges remain
immutable evidence. D-072 dispatch, replay and row provenance are reconstructed
under their original binding. Only the newly authorized F request receives a
replacement; D-071 zero-cost 429 ordinals and waits continue across segments.
No receipt or zero expense is invented for any unknown original.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import math
import re
import time

from communication_pruning.contracts import Request, TaskInput
from communication_pruning.data import AnswerReference
from communication_pruning.execution import execute
from communication_pruning.failure_policy import F01, strict_json
from communication_pruning.openrouter import encoded, payload, save_new
from communication_pruning.phase_budget import PhaseBudget
from communication_pruning.study import FileGuard, file_hash
from . import final_execution as fe, final_preflight as fp, final_recovery as fr
from . import final_rate_resume as rate, final_resume as previous
from . import final_lost_resume as lost
from .final_analysis import validate_rows
from .final_plan import canonical_hash

SCHEMA = "z51-f-resume-activation/v1"
MANIFEST_SCHEMA = "z51-f-resume-originals/v1"
CLAIM_NAME = fp.NAMESPACE + ".lost-011355-resume.claim.json"
RESERVE = Decimal("0.14")
HELD = Decimal("0.42")
COPY_NAMES, POLICY = rate.COPY_NAMES, rate.POLICY
_need, _checkpoint = previous._need, previous._checkpoint
LIVE = {
    "activation_sha256": "fd36534b8ddc6dc37220287cd7ac4e1b5ec1b9b45799f67e6c632f5de944bbdb",
    "stop_sha256": "c8079b6ef36dc9b0ff1644e3807fce601732d34bc799101c59f7bcf826f64bde",
    "request_sha256": "8012fae5f28d93c04b9be7a3bcae6fd33efb38c71512fba019d3dd38c2dd7af1",
    "physical_attempt_id": "z51-D072-resume-001:physical:011355",
    "logical_attempt_id": "50d4c906a74daf48:Z50-STUDY-v1:P:05579:F:1:linking:1",
    "completed_blocks": 5579, "partial_successful_calls": 1, "physical_calls": 11355,
    "retry": 0, "known_cost_usd": "16.56177745",
}


class _StoppedSender(lost.LostSend):
    """Read D-072 evidence, including its authorized replacement, without writing."""
    def _restore(self):
        self.states.update(deepcopy(self.inherited_states))
        self.seed_files.update(self.inherited_files)
        FileGuard(self.seed_files)()
        # The frozen stopped-reader calls self._binding: D-072 stays authoritative.
        lost._StoppedSender._restore(self)


def _inspect_previous(candidate, plan, manifest, clock):
    _need(manifest.get("schema") == MANIFEST_SCHEMA
          and manifest["candidate_sha256"] == canonical_hash(candidate)
          and manifest["plan_sha256"] == canonical_hash(plan), "lost recovery scientific binding differs")
    folder = fr._plain_path(manifest["previous_folder"])
    inventory = manifest["previous_inventory"]
    fr._verify_inventory(folder, inventory, manifest["previous_inventory_sha256"])
    checksum = manifest["previous_activation_sha256"]
    activation, (old_manifest, old_report, old_context) = lost._load(
        candidate, plan, folder, candidate["control_directory"], checksum, clock)
    _need(fr._hash(fr._read(folder, "ORIGINALS.json")) == activation["recovery_manifest_sha256"],
          "stopped originals manifest differs")
    prefix = old_report["completed_blocks_preserved"]
    available = lost._levels(candidate, fp.money(old_report["budget"]["known_cost_usd"]),
                                 Decimal(0))["available_usd"]
    header = {"kind": "header", "cap_usd": str(min(fp.money(available[k]) for k in ("overall", "main"))),
              "reserve_usd": "0.14", "max_calls": 4 * fp.MAX_CALLS["P"] * (plan["counts"]["P"] - prefix),
              "binding": checksum, "allow_synthetic": candidate["mode"] == "artificial_only"}
    calls, ledger = fr._ledger(fr._read(folder, "provider/budget.jsonl"), header)
    _need(calls and calls[-1]["usage"] is None and ledger["pending"] == calls[-1]["attempt_id"],
          "exactly one final unknown D-072 attempt required")
    sender = _StoppedSender(candidate, activation, checksum, folder,
        SimpleNamespace(settlements=[(c["attempt_id"], c["usage"]) for c in calls[:-1]]), old_context)
    lost_files = rate._files(folder, len(calls))
    body, binding = lost_files["request"].read_bytes(), fp.read_json(lost_files["binding"])
    prior = sender.states.get(binding["logical_attempt_id"])
    _need(prior is None or prior["outcome"] == "rate_limited" and prior["body"] == body
          and prior["output_limit"] == binding["output_limit"] and prior["retry"] < 3,
          "lost request has invalid retry ancestry")
    expected = sender._binding(binding["logical_attempt_id"], body, binding["output_limit"], len(calls), prior,
                               binding["dispatched_at"], binding["wait_elapsed_seconds"])
    _need(binding == expected and binding["physical_attempt_id"] == ledger["pending"]
          and rate._finite_time(binding["dispatched_at"])
          and rate._finite_time(binding["wait_elapsed_seconds"])
          and (prior is not None or binding["wait_elapsed_seconds"] == 0)
          and (binding["not_before"] is None or binding["dispatched_at"] >= binding["not_before"])
          and binding["retry"] < 3, "lost attempt identity differs or physical retry allowance exhausted")
    complete_names = sorted(n for n in inventory if re.fullmatch(r"blocks/\d{6}/complete\.json", n))
    count = prefix + len(complete_names)
    _need(count < plan["counts"]["P"] and complete_names == [f"blocks/{i:06d}/complete.json" for i in range(prefix, count)],
          "stopped completed prefix differs")
    _need(sorted(n for n in inventory if re.fullmatch(r"blocks/\d{6}/started\.json", n)) ==
          [f"blocks/{i:06d}/started.json" for i in range(prefix, count + 1)], "one next stopped partial block required")
    stop = fr._json(folder, "STOP.json")
    _need(stop == {"schema": "z51-lost-resume-stop/v1", "activation_sha256": checksum,
                  "block_number": count, "stage": "scientific_execution", "adapter_stage": "physical_dispatch",
                  "exception_type": "BudgetStop", "retry_allowed": False, "physical_calls": len(calls)},
          "unrecognized stopped D-072 event")
    expected_files = {"ACTIVATION.json", "ORIGINALS.json", "provider/budget.jsonl", "STOP.json"}
    rows, logical, seen, by_logical = deepcopy(old_context["rows"]), [], set(), {}
    for i, record in enumerate(sender.records, 1):
        by_logical.setdefault(record["binding"]["logical_attempt_id"], []).append(i)
    partial = []
    for number in range(prefix, count + 1):
        current, block_rows, files = rate._block(candidate, plan, folder, number, complete=number < count,
            origin=lambda row, n: lost._row_origin(row, activation, checksum, n))
        if number == prefix:
            for name in COPY_NAMES:
                relative = f"blocks/{number:06d}/{name}"
                _need(fr._read(folder, relative) == fr._read(old_manifest["previous_folder"], relative),
                      "old partial metadata changed")
        for saved in current:
            request = saved.request
            _need(request.attempt_id not in seen and request.attempt_id not in old_context["protected_ids"],
                  "duplicate or protected inherited request")
            seen.add(request.attempt_id)
            logical.append(saved)
            if saved.outcome is None:
                _need(number == count and request.attempt_id == binding["logical_attempt_id"]
                      and encoded(payload(request, producer_limit=1024)) == body, "foreign unresolved request")
                files.update(str(lost_files[k].relative_to(folder)) for k in ("request", "binding"))
            else:
                state = sender.states.get(request.attempt_id)
                _need(state is not None and state["response"] is not None
                      and state["body"] == encoded(payload(request, producer_limit=1024))
                      and fe._terminal(request.attempt_id, state["response"]) == saved.outcome,
                      "inherited logical answer differs from provider evidence")
                name = f"mapping/{len(logical):06d}.json"
                _need(fr._json(folder, name) == lost._map(activation, checksum, request, state, number),
                      "inherited logical mapping differs")
                files.add(name)
            for i in by_logical.get(request.attempt_id, []):
                files.update(str(p.relative_to(folder)) for p in rate._files(folder, i).values())
        if number < count:
            proof = fr._json(folder, f"blocks/{number:06d}/complete.json")
            _need(proof == {"block": plan["panels"]["P"][number], "plan_hash": plan["plan_hash"],
                           "rows": block_rows, "evidence": {n: inventory[n] for n in files}},
                  "stopped completed pair evidence differs")
            rows.extend(block_rows)
            files.add(f"blocks/{number:06d}/complete.json")
        else:
            partial = current
        expected_files.update(files)
    original_partial = old_context["partial"]
    _need([r.request for r in logical[:len(original_partial)]] == [r.request for r in original_partial]
          and [r.outcome for r in logical[:len(original_partial) - 1]] == [r.outcome for r in original_partial[:-1]],
          "earlier D-072 recovery replay changed")
    _need(partial and partial[-1].outcome is None and all(r.outcome is not None for r in partial[:-1])
          and all(r["binding"]["logical_attempt_id"] in seen for r in sender.records), "partial order/physical attribution differs")
    _need(set(n for n in inventory if not n.startswith("receipts/")) == expected_files, "unclaimed stopped evidence")
    known = fp.money(old_report["budget"]["known_cost_usd"]) + fp.money(ledger["known_cost_usd"])
    partial_cost = sum((fp.money(sender.states[r.request.attempt_id]["usage"]["cost_usd"])
                        for r in partial[:-1]), Decimal(0))
    _need(sum((fp.money(r["cost_usd"]) for r in rows), Decimal(0)) + partial_cost == known,
          "stopped completed/partial known costs are not conserved")
    actual = {"activation_sha256": checksum, "stop_sha256": inventory["STOP.json"],
              "request_sha256": fr._hash(body), "physical_attempt_id": binding["physical_attempt_id"],
              "logical_attempt_id": binding["logical_attempt_id"], "completed_blocks": count,
              "partial_successful_calls": len(partial) - 1, "physical_calls": len(calls),
              "retry": binding["retry"], "known_cost_usd": str(known)}
    _need(candidate["mode"] == "artificial_only" or actual == LIVE, "D-073 authorizes only the exact live F 011355 stop")
    _need(len(old_report["unknown_attempts"]) == 2
          and [u["arm"] for u in old_report["unknown_attempts"]] == ["Q", "Q"],
          "two inherited unknown Q originals required")
    unknowns = deepcopy(old_report["unknown_attempts"]) + [
        {"physical_attempt_id": binding["physical_attempt_id"],
         "logical_attempt_id": binding["logical_attempt_id"], "reservation_usd": "0.14",
         "provider_cost_usd": None, "arm": "F", "authority": "D-073"}]
    _need(":F:" in binding["logical_attempt_id"] and len(partial) == 2,
          "exactly one successful F partial answer before the authorized lost request required")
    original_folders = [str(folder), old_manifest["previous_folder"],
                        old_context["previous_activation"]["previous_folder"],
                        old_context["previous_activation"]["original_folder"]]
    _need(len(set(original_folders)) == 4, "four distinct predecessor segments required")
    report = {"schema": "z51-f-resume-preparation/v1", "recovery_id": manifest["recovery_id"],
              "completed_blocks_preserved": count, "preserved_rows": len(rows), "preserved_rows_sha256": canonical_hash(rows),
              "partial_successful_calls": len(partial) - 1, "partial_known_cost_usd": str(partial_cost),
              "lost": actual, "unknown_attempts": unknowns, "previous_inventory_sha256": manifest["previous_inventory_sha256"],
              "budget": {"calls": old_report["budget"]["calls"] + len(calls), "known_cost_usd": str(known),
                         "total_cost_usd": None, "held_reservation_usd": "0.42",
                         "pending": [u["physical_attempt_id"] for u in unknowns], "reservation_is_expense": False},
              "rate_summary": {"zero_cost_429_attempts": old_report["rate_summary"]["zero_cost_429_attempts"] + sum(r["outcome"] == "rate_limited" for r in sender.records),
                  "retry_attempts": old_report["rate_summary"]["retry_attempts"] + sum(r["binding"]["retry"] > 0 for r in sender.records),
                  "wait_elapsed_seconds": math.fsum([old_report["rate_summary"]["wait_elapsed_seconds"],
                      *(r["binding"]["wait_elapsed_seconds"] for r in sender.records)])},
              "new_model_calls": 0}
    partial_states = {r.request.attempt_id: sender.states[r.request.attempt_id] for r in partial[:-1]}
    protected = set(old_context["protected_ids"]) | {r.request.attempt_id for r in logical if r.block_number < count}
    partial_provider_files = {str(lost_files[k].relative_to(folder)) for k in ("request", "binding")}
    for logical_id in partial_states:
        for index in by_logical.get(logical_id, []):
            partial_provider_files.update(str(p.relative_to(folder)) for p in rate._files(folder, index).values())
    seed_files = {str(folder / n): inventory[n] for n in expected_files
                  if n.startswith(f"blocks/{count:06d}/") or n in partial_provider_files}
    return report, {"rows": rows, "partial": partial, "partial_states": partial_states,
                    "generations": sorted(sender.generations), "protected_ids": sorted(protected),
                    "seed_files": seed_files, "lost": actual, "previous_activation": activation,
                    "original_folders": original_folders}


def prepare_recovery(candidate, plan, *, previous_folder, expected_previous_activation_sha256,
                     inventory, expected_inventory_sha256, output, recovery_id, clock=time.time):
    folder, output = fr._plain_path(previous_folder), fr._plain_path(output)
    _need(not output.exists() and output.parent.is_dir() and folder != output and folder not in output.parents
          and output not in folder.parents, "separate create-only lost preparation required")
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
    _need(fr._hash(raw) == expected_hash, "lost recovery manifest changed")
    manifest = strict_json(raw)
    report, context = _inspect_previous(candidate, plan, manifest, clock)
    report["manifest_sha256"] = expected_hash
    _need(fr._json(folder, "PREPARATION.json") == report, "lost preparation changed")
    return manifest, report, context


def source_members(source_files):
    return {f"f-source-{i:04d}": sha for i, (_, sha) in enumerate(sorted(source_files.items()))}


def make_activation(candidate, plan, *, folder, control, recovery_folder, expected_manifest_sha256,
                    resume_id, source_files, source_backup, checkpoint, approval_reference,
                    support_declined=True, clock=time.time):
    manifest, report, context = _originals(candidate, plan, recovery_folder, expected_manifest_sha256, clock)
    return {"schema": SCHEMA, "resume_id": resume_id, "candidate_sha256": canonical_hash(candidate),
        "plan_sha256": canonical_hash(plan), "execution_binding_sha256": fp.execution_binding(candidate),
        "folder": str(fr._plain_path(folder)), "control_directory": str(fr._plain_path(control)),
        "recovery_folder": str(fr._plain_path(recovery_folder)), "recovery_manifest_sha256": expected_manifest_sha256,
        "previous_folder": manifest["previous_folder"], "previous_activation_sha256": manifest["previous_activation_sha256"],
        "previous_inventory_sha256": manifest["previous_inventory_sha256"],
        "preserved_completed_blocks": report["completed_blocks_preserved"], "lost": deepcopy(report["lost"]),
        "unknown_attempts": deepcopy(report["unknown_attempts"]), "held_original_reservation_usd": "0.42",
        "author_assumption": {"author": "Jannik", "decision": "D-073", "provider_cost_confirmed": False,
            "additional_charge_assumed_zero_for": list(report["budget"]["pending"]),
            "cost_inference": "conditional on no additional charge for ALL THREE retained unknown attempts across Q and F",
            "later_attributable_costs": "add once; never silently discard", "reservation_is_proven_cost_upper_bound": False},
        "lost_authorization": {"author": "Jannik", "decision": "D-073", "approval_reference": approval_reference,
            "explicit_resumption_authorization": True, "maximum_unknown_replacements": 1},
        "rate_policy": deepcopy(POLICY), "panels": ["P"], "support_declined": support_declined,
        "source_files": deepcopy(source_files), "source_backup": deepcopy(source_backup),
        "dependency_bindings": {"checkpoint": fp.dependency_identity(checkpoint)}}


def _gate(candidate, plan, activation, expected_hash, folder, control, clock, dependencies=None):
    folder, control = fr._plain_path(folder), fr._plain_path(control)
    fp.preflight(candidate, plan, control=control, clock=clock)
    _need(canonical_hash(activation) == expected_hash and activation.get("schema") == SCHEMA
          and activation.get("rate_policy") == POLICY and activation.get("panels") == ["P"]
          and activation.get("support_declined") is True and activation.get("folder") == str(folder)
          and activation.get("control_directory") == str(control)
          and activation.get("candidate_sha256") == canonical_hash(candidate)
          and activation.get("plan_sha256") == canonical_hash(plan)
          and activation.get("execution_binding_sha256") == fp.execution_binding(candidate)
          and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", activation.get("resume_id", "")), "lost activation differs")
    authorization = activation["lost_authorization"]
    _need(set(authorization) == {"author", "decision", "approval_reference", "explicit_resumption_authorization", "maximum_unknown_replacements"}
          and authorization["author"] == "Jannik" and authorization["decision"] == "D-073"
          and authorization["explicit_resumption_authorization"] is True and authorization["maximum_unknown_replacements"] == 1
          and isinstance(authorization["approval_reference"], str) and authorization["approval_reference"].strip(),
          "missing exact D-073 authorization")
    files = activation["source_files"]
    required = {str(Path(p).resolve()) for p in (__file__, lost.__file__, rate.__file__, previous.__file__, fr.__file__,
                Path(__file__).resolve().parents[1] / "tests/test_final_f_resume.py")}
    _need(isinstance(files, dict) and required <= set(files)
          and all(str(fr._plain_path(p)) == p for p in files), "complete additive lost sources required")
    FileGuard(files)()
    fp.verify_archive(activation["source_backup"], source_members(files))
    manifest, report, context = _originals(candidate, plan, activation["recovery_folder"],
                                          activation["recovery_manifest_sha256"], clock)
    for original in context["original_folders"]:
        path = fr._plain_path(original)
        _need(path != folder and path not in folder.parents and folder not in path.parents, "lost output overlaps originals")
    expected = {"previous_folder": manifest["previous_folder"], "previous_activation_sha256": manifest["previous_activation_sha256"],
        "previous_inventory_sha256": manifest["previous_inventory_sha256"], "preserved_completed_blocks": report["completed_blocks_preserved"],
        "lost": report["lost"], "unknown_attempts": report["unknown_attempts"], "held_original_reservation_usd": "0.42"}
    _need(all(activation.get(k) == v for k, v in expected.items()), "lost prefix or unknown identities differ")
    assumption = activation["author_assumption"]
    _need(assumption == {"author": "Jannik", "decision": "D-073", "provider_cost_confirmed": False,
        "additional_charge_assumed_zero_for": list(report["budget"]["pending"]),
        "cost_inference": "conditional on no additional charge for ALL THREE retained unknown attempts across Q and F",
        "later_attributable_costs": "add once; never silently discard", "reservation_is_proven_cost_upper_bound": False},
        "all three unknown charges require the explicit conditional assumption")
    if dependencies is not None:
        _need(set(dependencies) == {"loader", "spatial_selector", "transport", "checkpoint"}, "missing lost P dependency")
        for name in ("loader", "spatial_selector", "transport"):
            identity = fp.dependency_identity(dependencies[name])
            _need(candidate["dependency_bindings"][name] == identity
                  and candidate["source_files"].get(identity["path"]) == identity["sha256"], "frozen scientific dependency differs")
        identity = fp.dependency_identity(dependencies["checkpoint"])
        _need(activation["dependency_bindings"] == {"checkpoint": identity}
              and (files | candidate["source_files"]).get(identity["path"]) == identity["sha256"], "lost checkpoint differs")
        if candidate["mode"] != "artificial_only":
            from communication_pruning.semantic_selection import SemanticSelector
            method = dependencies["spatial_selector"]
            obj = getattr(method, "__self__", None)
            _need(type(obj) is SemanticSelector and method.__func__ is SemanticSelector.select
                  and obj.to_dict() == fp.read_json(candidate["documents"]["spatial_q"]["path"]), "live Q differs")
    return manifest, report, context


def _claim(activation, checksum, control, *, create=False):
    expected = {"schema": "z51-f-resume-claim/v1", "activation_sha256": checksum,
        "execution_binding_sha256": activation["execution_binding_sha256"], "folder": activation["folder"],
        "previous_activation_sha256": activation["previous_activation_sha256"],
        "recovery_manifest_sha256": activation["recovery_manifest_sha256"], "lost": activation["lost"]}
    path = Path(control) / CLAIM_NAME
    if create:
        fe._save(path, expected)
    else:
        _need(fp.read_json(fr._plain_path(path)) == expected, "lost claim changed or duplicate segment")


def _levels(candidate, original_cost, new_cost, *, reserve_calls=0):
    result = lost._levels(candidate, original_cost, new_cost)
    available = {k: fp.money(v) for k, v in result["available_usd"].items()}
    for key in ("overall", "main"):
        available[key] -= RESERVE
    _need(min(available.values()) >= 0 and min(available["overall"], available["main"]) >= RESERVE * reserve_calls,
          "new calls and ALL THREE unknown reservations exceed shared budget")
    result.update(available_usd={k: str(v) for k, v in available.items()}, held_original_reservation_usd="0.42",
                  held_unknown_reservations_usd=["0.14", "0.14", "0.14"], block_reservation_usd=str(RESERVE * reserve_calls))
    return result


def _budget(candidate, plan, folder, checksum, report, *, existing):
    available = _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), Decimal(0))["available_usd"]
    factory = PhaseBudget.read_completed if existing else PhaseBudget
    return factory(Path(folder) / "provider/budget.jsonl", cap=min(fp.money(available[k]) for k in ("overall", "main")),
        reserve=RESERVE, max_calls=4 * fp.MAX_CALLS["P"] * (plan["counts"]["P"] - report["completed_blocks_preserved"]),
        binding=checksum, allow_synthetic=candidate["mode"] == "artificial_only")


class LostSend(rate.RateSend):
    """Unchanged D-071 dispatch with one exact D-073 initial binding exception."""
    def __init__(self, candidate, activation, checksum, folder, budget, context, **kwargs):
        self.inherited_states, self.inherited_files = context["partial_states"], context["seed_files"]
        self.lost = context["lost"]
        super().__init__(candidate, activation, checksum, folder, budget,
                         {**context, "seeds": []}, **kwargs)

    def _restore(self):
        self.states.update(deepcopy(self.inherited_states))
        self.seed_files.update(self.inherited_files)
        FileGuard(self.seed_files)()
        super()._restore()

    def _binding(self, request_id, body, limit, number, prior, dispatched, waited):
        result = super()._binding(request_id, body, limit, number, prior, dispatched, waited)
        result.update(schema="z51-D073-dispatch/v1", replacement_of_unknown=None,
                      replacement_authorization_sha256=None)
        if request_id == self.lost["logical_attempt_id"] and prior is None:
            _need(fr._hash(body) == self.lost["request_sha256"] and self.lost["retry"] < 3,
                  "replacement differs or inherited retry allowance exhausted")
            result.update(retry=self.lost["retry"] + 1,
                previous_physical_attempt_id=self.lost["physical_attempt_id"],
                previous_received_at=None, not_before=None,
                replacement_of_unknown=self.lost["physical_attempt_id"],
                replacement_authorization_sha256=canonical_hash(self.activation["lost_authorization"]))
        return result

    def __call__(self, request):
        if type(request) is Request and request.attempt_id == self.lost["logical_attempt_id"]:
            _need(fr._hash(encoded(payload(request, producer_limit=1024))) == self.lost["request_sha256"],
                  "exact authorized lost request bytes required")
        return super().__call__(request)


def _row_origin(row, activation, checksum, number):
    result = deepcopy(row)
    result["f_resume_provenance"] = {"activation_sha256": checksum,
        "recovery_manifest_sha256": activation["recovery_manifest_sha256"], "origin": "D-073-segment",
        "delayed_partial_block": number == activation["preserved_completed_blocks"],
        "unknown_attempts": [u["physical_attempt_id"] for u in activation["unknown_attempts"]],
        "cost_condition": "additional billing for all three unknown Q and F attempts assumed zero; not provider-confirmed"}
    return result


def _map(activation, checksum, request, saved, number):
    result = rate._map(activation, checksum, request, saved, number)
    result["schema"] = "z51-D073-logical-map/v1"
    result["replacement_of_unknown"] = (activation["lost"]["physical_attempt_id"]
        if request.attempt_id == activation["lost"]["logical_attempt_id"] else None)
    return result


def _inspect(candidate, plan, folder, activation, checksum, manifest, report, context):
    folder = Path(folder)
    _need(not (folder / "STOP.json").exists(), "new lost segment permanently stopped; no unknown retry")
    _need(fr._hash(fr._read(folder, "ORIGINALS.json")) == activation["recovery_manifest_sha256"], "lost originals changed")
    budget = _budget(candidate, plan, folder, checksum, report, existing=True)
    sender = LostSend(candidate, activation, checksum, folder, budget, context)
    prefix = report["completed_blocks_preserved"]
    started, complete = sorted((folder / "blocks").glob("*/started.json")), sorted((folder / "blocks").glob("*/complete.json"))
    _need(len(started) == len(complete) and prefix + len(complete) <= plan["counts"]["P"], "partial lost block cannot restart")
    expected = {"ACTIVATION.json", "ORIGINALS.json", "provider/budget.jsonl"}
    rows, logical, seen, by_logical = deepcopy(context["rows"]), [], set(), {}
    for index, record in enumerate(sender.records, 1):
        by_logical.setdefault(record["binding"]["logical_attempt_id"], []).append(index)
    for number, path in enumerate(complete, prefix):
        directory = folder / "blocks" / f"{number:06d}"
        _need(path == directory / "complete.json" and started[number - prefix] == directory / "started.json",
              "lost segment prefix order differs")
        calls, block_rows, files = rate._block(candidate, plan, folder, number, complete=True,
            origin=lambda row, n: _row_origin(row, activation, checksum, n))
        if number == prefix:
            for name in COPY_NAMES:
                relative = f"blocks/{number:06d}/{name}"
                _need(fr._read(folder, relative) == fr._read(manifest["previous_folder"], relative), "lost partial metadata differs")
        for saved in calls:
            request = saved.request
            _need(request.attempt_id not in seen and request.attempt_id in sender.states, "missing/duplicate new logical outcome")
            seen.add(request.attempt_id)
            state = sender.states[request.attempt_id]
            _need(state["response"] is not None and state["body"] == encoded(payload(request, producer_limit=1024))
                  and fe._terminal(request.attempt_id, state["response"]) == saved.outcome, "lost logical/physical outcome differs")
            logical.append(saved)
            name = f"mapping/{len(logical):06d}.json"
            _need(fr._json(folder, name) == _map(activation, checksum, request, state, number), "lost logical mapping differs")
            files.add(name)
            for i in by_logical.get(request.attempt_id, []):
                files.update(str(p.relative_to(folder)) for p in rate._files(folder, i).values())
        _need(fp.read_json(path) == {"block": plan["panels"]["P"][number], "plan_hash": plan["plan_hash"],
              "rows": block_rows, "evidence": {n: file_hash(folder / n) for n in files}}, "new lost complete evidence differs")
        expected.update(files)
        expected.add(str(path.relative_to(folder)))
        rows.extend(block_rows)
    partial = context["partial"]
    replacements = [r for r in sender.records if r["binding"]["replacement_of_unknown"] is not None]
    if complete:
        _need([r.request for r in logical[:len(partial)]] == [r.request for r in partial]
              and [r.outcome for r in logical[:len(partial) - 1]] == [r.outcome for r in partial[:-1]]
              and len(replacements) == 1, "lost partial replay or single replacement differs")
    _need(all(r["binding"]["logical_attempt_id"] in seen for r in sender.records), "unclaimed new physical attempt")
    known = fp.money(report["budget"]["known_cost_usd"]) + budget.cost
    if complete:
        _need(sum((fp.money(r["cost_usd"]) for r in rows), Decimal(0)) == known, "joined lost known costs differ")
    else:
        _need(budget.calls == 0, "new physical work without complete lost block")
    evidence = {n: h for n, h in fr.original_inventory(folder).items() if not n.startswith("receipts/")}
    _need(set(evidence) == expected, "unclaimed lost segment files")
    inherited_rates = report["rate_summary"]["zero_cost_429_attempts"]
    new_rates = sum(r["outcome"] == "rate_limited" for r in sender.records)
    state = {"schema": "z51-f-resume-state/v1", "activation_sha256": checksum,
        "execution_binding_sha256": fp.execution_binding(candidate), "plan_hash": plan["plan_hash"],
        "completed_blocks": prefix + len(complete), "complete": prefix + len(complete) == plan["counts"]["P"],
        "original_completed_blocks": prefix, "panel": "P", "rows": rows, "new_budget": budget.snapshot(),
        "budget": {"calls": report["budget"]["calls"] + budget.calls, "new_calls": budget.calls,
            "known_cost_usd": str(known), "total_cost_usd": None, "held_reservation_usd": "0.42",
            "pending": report["budget"]["pending"], "unknown_attempts": deepcopy(report["unknown_attempts"]),
            "poisoned": False, "reservation_is_expense": False},
        "levels": _levels(candidate, fp.money(report["budget"]["known_cost_usd"]), budget.cost),
        "rate_policy": deepcopy(POLICY), "physical_attempts": sender.records,
        "additional_rate_retries": sum(r["binding"]["retry"] > 0 and r["binding"]["replacement_of_unknown"] is None for r in sender.records),
        "rate_summary": {"inherited_physical_attempts": report["budget"]["calls"],
            "new_physical_attempts": budget.calls, "total_physical_attempts": report["budget"]["calls"] + budget.calls,
            "inherited_zero_cost_429_attempts": inherited_rates, "new_zero_cost_429_attempts": new_rates,
            "total_zero_cost_429_attempts": inherited_rates + new_rates,
            "new_retry_attempts": sum(r["binding"]["retry"] > 0 for r in sender.records),
            "authorized_unknown_replacements": len(replacements),
            "new_wait_elapsed_seconds": math.fsum(r["binding"]["wait_elapsed_seconds"] for r in sender.records),
            "inherited_wait_elapsed_seconds": report["rate_summary"]["wait_elapsed_seconds"],
            "wait_scope": "same D-071 measured active sleep; authorized unknown replacement has no fabricated response/wait anchor"},
        "generation_ids": sorted(sender.generations), "unknown_attempts": deepcopy(report["unknown_attempts"]),
        "cost_assumption": deepcopy(activation["author_assumption"]), "evidence": evidence}
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
          and activation["recovery_manifest_sha256"] == expected_manifest_sha256, "lost preparation arguments differ")
    with fe.study_lock(control):
        context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock)
        _need(not folder.exists() and folder.parent.is_dir(), "new create-only lost segment required")
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
        _need(activation["dependency_bindings"] == {"checkpoint": fp.dependency_identity(checkpoint)}, "lost checkpoint differs")
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
        _need(type(section_end) is int and later and section_end == later[0], "only next bound lost/original hold may execute")
        fe._verify_receipt(folder, state)
        def guard():
            fp.runtime_guard(candidate, clock=clock, panel="P")
            FileGuard(activation["source_files"])()
            _need(fp.read_json(folder / "ACTIVATION.json") == activation, "lost activation changed during run")
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
                        _need(fr._hash(raw) == manifest["previous_inventory"][relative], "lost partial changed")
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
                          and task.task_id == fe.public_task_id(plan, block["task_id"])
                          and reference.task_id == task.task_id, "foreign task/reference")
                    fe._save(directory / "public.json", asdict(task))
                    fe._save(directory / "reference.json", asdict(reference))
                    q = fe._select_observed(spatial_selector, task, candidate=candidate, plan=plan, block=block,
                                           kind="spatial", directory=directory)
                    selection = {"spatial_q": q, "temporal_qst": None}
                    fe._save(directory / "selection.json", selection)
                block, block_rows = plan["panels"]["P"][number], []
                partial_position = 0
                def send(request):
                    nonlocal logical_count, partial_position
                    if number == prefix and partial_position < len(originals["partial"]):
                        _need(request == originals["partial"][partial_position].request, "lost partial order/input differs")
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
                    row = _row_origin(fe._row(candidate, block, slot, result, config, rounds, failed, run_id),
                                      activation, expected_activation_sha256, number)
                    fe._save(sd / "result.json", row)
                    block_rows.append(row)
                files = [p for p in directory.rglob("*") if p.is_file()]
                files.extend(folder / "mapping" / f"{i:06d}.json" for i in range(first_map, logical_count + 1))
                for i in range(first_call, budget.calls + 1):
                    files.extend(rate._files(folder, i).values())
                fe._save(directory / "complete.json", {"block": block, "plan_hash": plan["plan_hash"], "rows": block_rows,
                    "evidence": {str(p.relative_to(folder)): file_hash(p) for p in files}})
            stage = "full_inspection"
            context = _gate(candidate, plan, activation, expected_activation_sha256, folder, control, clock, dependencies)
            state = _inspect(candidate, plan, folder, activation, expected_activation_sha256, *context)[0]
        except BaseException as error:
            if not (folder / "STOP.json").exists():
                fe._save(folder / "STOP.json", {"schema": "z51-f-resume-stop/v1", "activation_sha256": expected_activation_sha256,
                    "block_number": current, "stage": stage, "adapter_stage": sender.stage,
                    "exception_type": type(error).__name__, "retry_allowed": False, "physical_calls": budget.calls})
            raise
        _checkpoint(folder, state, checkpoint)
        return state


def collect_panel(candidate, plan, panel="P", *, folder, control, expected_activation_sha256, clock):
    _need(panel == "P", "D-073 does not authorize secondary panels")
    state = inspect_resume(candidate, plan, folder=folder, control=control,
                           expected_activation_sha256=expected_activation_sha256, clock=clock)
    fe._verify_receipt(Path(folder), state)
    return validate_rows(plan, "P", state["rows"])
