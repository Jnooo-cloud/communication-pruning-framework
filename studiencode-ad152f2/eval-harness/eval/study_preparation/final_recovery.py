"""Z51 offline preservation and replay of original P-panel calls only.

This is NOT a continuation operator. It has no transport, key lookup, ledger
writer, settlement repair, provider-import API, or live-activation output.
Unknown calls remain unknown, including their original 0.14 USD reservation.

Trust boundary: the caller supplies the independently retained original file
inventory and last audited checkpoint, plus their externally checked hashes.
Computing those hashes from newly invented evidence does not prove provenance.
The local checks prove byte preservation and consistency with those anchors;
they do not authenticate an account/provider or replace the earlier score audit.
Only the actual original adapter's request/binding/response/received/billing
chain is accepted. A reconstructed provider response needs a separately reviewed
import contract; a cost assertion or a fabricated HTTP 200 is never imported.

The deliberately narrow format accepts an intact P prefix and at most its next
partially executed P block. Other recovery cases fail closed. Original files
are read only; all outputs use new, exclusive paths outside the original tree.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path, PurePosixPath
import re

from communication_pruning.contracts import Message, Request, TaskInput, Usage
from communication_pruning.data import digest
from communication_pruning.failure_policy import F01, decode_outcome, strict_json
from communication_pruning.journal import read_journal
from communication_pruning.openrouter import decode_billing, encoded, payload, save_new
from .final_execution import (_blocks, _check_selection_measurement, _configuration,
                              _terminal, public_task_id)
from .final_plan import ARMS, canonical_hash, validate_plan
from .final_preflight import MAX_CALLS, budget_view, execution_binding, money


class RecoveryStop(RuntimeError):
    """Evidence is unresolved or inconsistent; no replacement call is possible."""


def _require(condition, message):
    if not condition:
        raise RecoveryStop(message)


def _hash(raw):
    return sha256(raw).hexdigest()


def _plain_path(path):
    path = Path(path).absolute()
    _require(".." not in path.parts, "parent traversal in evidence or output path")
    _require(not any(p.is_symlink() for p in (path, *path.parents)),
             "symlinked evidence or output path")
    return path


def _relative(name):
    _require(isinstance(name, str), "non-string inventory path")
    path = PurePosixPath(name)
    _require(name == path.as_posix() and not path.is_absolute()
             and bool(path.parts) and all(p not in (".", "..") for p in path.parts),
             "unsafe inventory path")
    return path


def _read(folder, name):
    relative = _relative(name)
    path = _plain_path(Path(folder).joinpath(*relative.parts))
    _require(path.is_file(), "missing original evidence file")
    return path.read_bytes()


def _json(folder, name):
    return strict_json(_read(folder, name))


def original_inventory(folder):
    """Read every original file, including receipts; no manifest is self-authority.

    Useful when checking an independently retained archive inventory. A freshly
    computed value alone must not replace the external provenance anchor.
    """
    folder = _plain_path(folder)
    _require(folder.is_dir(), "missing original directory")
    result = {}
    for path in sorted(folder.rglob("*")):
        _require(not path.is_symlink(), "symlink in original evidence")
        if path.is_dir():
            continue
        _require(path.is_file(), "nonregular original evidence")
        result[path.relative_to(folder).as_posix()] = _hash(path.read_bytes())
    _require(bool(result), "empty original inventory")
    return result


def _verify_inventory(folder, inventory, expected_hash):
    _require(type(inventory) is dict and bool(inventory)
             and canonical_hash(inventory) == expected_hash,
             "external original inventory binding differs")
    for name, checksum in inventory.items():
        _relative(name)
        _require(isinstance(checksum, str) and re.fullmatch("[0-9a-f]{64}", checksum),
                 "invalid original file hash")
    _require(original_inventory(folder) == inventory,
             "original file set or bytes changed; no replay")


def _budget_header(candidate, plan):
    available = budget_view(candidate, {p: Decimal(0) for p in ARMS})["available_usd"]
    cap = min(money(available["overall"]), money(available["main"]) + money(available["secondary"]))
    return {"kind": "header", "cap_usd": str(cap), "reserve_usd": "0.14",
            "max_calls": sum(MAX_CALLS[p] * plan["counts"][p] for p in ARMS),
            "binding": execution_binding(candidate),
            "allow_synthetic": candidate["mode"] == "artificial_only"}


def _ledger(raw, expected_header):
    """Inspect the original chain, retaining its final unresolved reservation."""
    _require(bool(raw) and raw.endswith(b"\n"), "missing or partial ledger line")
    rows, previous = [], "0" * 64
    for sequence, line in enumerate(raw.splitlines()):
        record = strict_json(line)
        _require(type(record) is dict and {"sequence", "previous", "time", "sha256"} <= set(record),
                 "invalid ledger envelope")
        checksum = record.pop("sha256")
        _require(type(record["sequence"]) is int and record["sequence"] == sequence
                 and record["previous"] == previous and digest(record) == checksum,
                 "original ledger chain differs")
        previous = checksum
        rows.append({k: v for k, v in record.items() if k not in ("sequence", "previous", "time")})
    _require(rows[0] == expected_header, "original budget/calendar/source binding differs")
    known, calls, ids = Decimal(0), [], set()
    reserve, cap = Decimal("0.14"), money(expected_header["cap_usd"])
    for offset in range(1, len(rows), 2):
        reserved = rows[offset]
        attempt = reserved.get("attempt_id")
        _require(isinstance(attempt, str) and bool(attempt) and attempt not in ids
                 and len(calls) < expected_header["max_calls"] and known + reserve <= cap
                 and reserved == {"kind": "reserved", "attempt_id": attempt,
                                  "reservation_usd": "0.14", "known_before_usd": str(known)},
                 "duplicate, foreign or uncovered original reservation")
        ids.add(attempt)
        settled = rows[offset + 1] if offset + 1 < len(rows) else None
        unresolved = settled is None or settled.get("usage") == Usage().to_dict()
        if unresolved:
            _require(offset + 2 >= len(rows) and (settled is None or settled == {
                "kind": "settled", "attempt_id": attempt, "usage": Usage().to_dict(),
                "failed": True, "over_reservation": False}),
                "unresolved dispatch followed by another call or ambiguous settlement")
        else:
            value = settled.get("usage", {})
            usage = Usage(**{**value, "cost_usd": money(value.get("cost_usd"))})
            _require(usage.cost_usd <= reserve
                     and usage.cost_source == ("synthetic" if expected_header["allow_synthetic"] else "provider")
                     and settled == {"kind": "settled", "attempt_id": attempt, "usage": usage.to_dict(),
                                     "failed": False, "over_reservation": False},
                     "failed, ambiguous or unpriced original settlement")
            known += usage.cost_usd
        calls.append({"attempt_id": attempt, "usage": None if unresolved else usage.to_dict()})
    pending = calls[-1]["attempt_id"] if calls and calls[-1]["usage"] is None else None
    return calls, {"calls": len(calls), "known_cost_usd": str(known),
                   "total_cost_usd": None if pending else str(known),
                   "held_reservation_usd": "0.14" if pending else "0", "pending": pending,
                   "reservation_is_expense": False, "original_ledger_sha256": _hash(raw)}


def _checkpoint(candidate, plan, folder, inventory, checkpoint, expected_hash, raw_ledger):
    _require(type(checkpoint) is dict and checkpoint.get("state_sha256") == expected_hash
             and canonical_hash({k: v for k, v in checkpoint.items() if k != "state_sha256"}) == expected_hash,
             "external checkpoint binding differs")
    count = checkpoint["completed_blocks"]
    _require(type(count) is int and 0 < count <= plan["counts"]["P"]
             and checkpoint["execution_binding_sha256"] == execution_binding(candidate)
             and checkpoint["plan_hash"] == plan["plan_hash"], "checkpoint is not this study's P prefix")
    budget = checkpoint["budget"]
    _require(budget["pending"] is None and budget["poisoned"] is False
             and money(budget["held_reservation_usd"]) == 0
             and budget["total_cost_usd"] == budget["known_cost_usd"],
             "checkpoint did not close all original reservations")
    call_count = budget["calls"]
    _require(type(call_count) is int and call_count > 0, "invalid checkpoint call count")
    prefix_bytes = b"".join(raw_ledger.splitlines(keepends=True)[:1 + 2 * call_count])
    # Hash the original byte prefix; never create or rewrite a shortened ledger.
    for name, checksum in checkpoint["evidence"].items():
        _relative(name)
        actual = _hash(prefix_bytes) if name == "budget.jsonl" else inventory.get(name)
        _require(actual == checksum, "original checkpoint evidence was replaced or truncated")
    _require("budget.jsonl" in checkpoint["evidence"], "checkpoint lacks original ledger binding")
    prefix_calls, prefix_budget = _ledger(prefix_bytes, _budget_header(candidate, plan))
    _require(len(prefix_calls) == call_count and prefix_budget["pending"] is None
             and prefix_budget["known_cost_usd"] == budget["known_cost_usd"],
             "checkpoint call/cost count differs from its original ledger bytes")
    return count, call_count


@dataclass(frozen=True)
class _OriginalCall:
    request: Request
    outcome: dict | None
    block_number: int


def _requests(candidate, plan, folder, inventory, checkpoint, count):
    """Bind original MAS attempts to the frozen P block/slot order without gold."""
    blocks = _blocks(plan)
    started = sorted(name for name in inventory if re.fullmatch(r"blocks/\d{6}/started\.json", name))
    complete = sorted(name for name in inventory if re.fullmatch(r"blocks/\d{6}/complete\.json", name))
    _require(len(started) in (count, count + 1) and len(complete) == count
             and started == [f"blocks/{i:06d}/started.json" for i in range(len(started))]
             and complete == [f"blocks/{i:06d}/complete.json" for i in range(count)],
             "only one next partial P block is supported")
    requests, rows, seen, claimed = [], [], set(), set(checkpoint["evidence"])
    unfinished = False
    for number in range(len(started)):
        block, directory = blocks[number], f"blocks/{number:06d}"
        _require(block["panel"] == "P", "recovery is limited to the original P panel")
        _require(_json(folder, f"{directory}/started.json") == {"block": block, "plan_hash": plan["plan_hash"]},
                 "block identity or frozen study order differs")
        public = _json(folder, f"{directory}/public.json")
        task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
        _require(strict_json(encoded(asdict(task))) == public
                 and task.task_id == public_task_id(plan, block["task_id"]), "foreign original public task")
        selection = _json(folder, f"{directory}/selection.json")
        _require(set(selection) == {"spatial_q", "temporal_qst"} and selection["temporal_qst"] is None,
                 "changed selection contract")
        _check_selection_measurement(_json(folder, f"{directory}/spatial-measurement.json"),
                                     candidate, plan, block, "spatial", selection["spatial_q"])
        claimed.update(f"{directory}/{name}" for name in (
            "started.json", "public.json", "reference.json", "selection.json", "spatial-measurement.json"))
        if number < count:
            proof = _json(folder, f"{directory}/complete.json")
            _require(proof["block"] == block and proof["plan_hash"] == plan["plan_hash"]
                     and all(inventory.get(name) == checksum for name, checksum in proof["evidence"].items()),
                     "completed block proof differs")
            rows.extend(proof["rows"])
        for slot in block["slots"]:
            sd = f"{directory}/{slot['arm']}"
            journal = f"{sd}/journal.jsonl"
            if journal not in inventory:
                _require(number == count, "complete prefix is missing an original slot")
                unfinished = True
                continue
            _require(not unfinished, "later slot after an incomplete original slot")
            config, rounds, failed = _configuration(candidate, block, slot["arm"], selection)
            _require(config is not None and slot["arm"] in ARMS["P"], "unsupported direct/fault recovery")
            checked = read_journal(Path(folder) / journal, config)
            trace = checked["trace"]
            _require(trace["task"] == public and trace["rounds"] == rounds
                     and trace["failed_role"] == failed and trace["failure_policy"] == F01
                     and trace["run_id"] == plan["plan_hash"][:16] + ":" + slot["slot_id"],
                     "original journal task/run/policy binding differs")
            terminal = {e["attempt_id"]: e for e in trace["events"] if e["kind"] in ("completed", "model_failed")}
            for event in trace["events"]:
                if event["kind"] != "started":
                    continue
                request = Request(event["attempt_id"], task, event["role"], event["round"], event["instruction"],
                                  tuple(Message(**m) for m in event["messages"]), event["max_output_tokens"])
                _require(request.attempt_id not in seen, "duplicate original journal attempt")
                seen.add(request.attempt_id)
                requests.append(_OriginalCall(request, terminal.get(request.attempt_id), number))
            claimed.add(journal)
            if f"{sd}/result.json" in inventory:
                _require(checked["sealed"], "numeric result for an unsealed original slot")
                claimed.add(f"{sd}/result.json")
            if not checked["sealed"]:
                _require(number == count, "unfinished slot inside confirmed checkpoint")
                unfinished = True
    _require(rows == checkpoint["rows"], "original checkpoint rows changed or were dropped")
    return requests, claimed


def _inspect(candidate, plan, folder, manifest):
    _require(canonical_hash(candidate) == manifest["candidate_sha256"]
             and canonical_hash(plan) == manifest["plan_sha256"],
             "candidate, calendar, budget, sources or frozen plan changed")
    validate_plan(plan)
    _require((candidate["mode"], plan["mode"]) in (
        ("artificial_only", "artificial_only"), ("authorized_execution", "live_candidate"))
        and candidate["plan_hash"] == plan["plan_hash"] and candidate["bindings"] == plan["bindings"],
        "candidate/plan mode or scientific binding mismatch")
    _require(candidate.get("sha256") == canonical_hash({k: v for k, v in candidate.items() if k != "sha256"}),
             "candidate seal differs")
    inventory = manifest["original_inventory"]
    _verify_inventory(folder, inventory, manifest["original_inventory_sha256"])
    raw = _read(folder, "budget.jsonl")
    calls, budget = _ledger(raw, _budget_header(candidate, plan))
    checkpoint = manifest["checkpoint"]
    count, prefix_calls = _checkpoint(candidate, plan, folder, inventory, checkpoint,
                                     manifest["checkpoint_sha256"], raw)
    requests, claimed = _requests(candidate, plan, folder, inventory, checkpoint, count)
    _require(len(requests) == len(calls) and len(calls) >= prefix_calls,
             "original journal starts do not match dispatch reservations")
    generations, replayable = set(), []
    for index, (call, saved) in enumerate(zip(calls, requests), 1):
        request = saved.request
        _require(request.attempt_id == call["attempt_id"], "dispatch order/attempt identity differs")
        names = {part: f"provider/{index:05d}-{part}.json" for part in
                 ("request", "binding", "response", "received", "billing")}
        body = _read(folder, names["request"])
        _require(body == encoded(payload(request, producer_limit=1024))
                 and _json(folder, names["binding"]) == {
                     "attempt_id": request.attempt_id, "request_sha256": _hash(body),
                     "mode": "synthetic" if candidate["mode"] == "artificial_only" else "live"},
                 "original request bytes or attempt binding differ")
        claimed.update((names["request"], names["binding"]))
        if call["usage"] is None:
            _require(index == len(calls) and saved.outcome is None
                     and not any(names[part] in inventory for part in ("response", "received", "billing")),
                     "unknown dispatch has partial/ambiguous provider evidence; no reconstruction import")
            continue
        response_raw = _read(folder, names["response"])
        strict_json(response_raw)
        usage, generation = decode_billing(response_raw)
        response = decode_outcome(response_raw, request.max_output_tokens, F01)
        if candidate["mode"] == "artificial_only":
            usage = replace(usage, cost_source="synthetic")
            response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
        _require(generation not in generations and usage.to_dict() == call["usage"]
                 and _terminal(request.attempt_id, response) == saved.outcome
                 and _json(folder, names["received"]) == {"http_status": 200, "response_sha256": _hash(response_raw)}
                 and _json(folder, names["billing"]) == {"generation_id": generation,
                     "usage": call["usage"], "response_sha256": _hash(response_raw)},
                 "original response, generation, billing, receipt or journal outcome differs")
        generations.add(generation)
        claimed.update(names.values())
        replayable.append({"call_index": index, "attempt_id": request.attempt_id,
                           "generation_id": generation, "original_cost_usd": call["usage"]["cost_usd"],
                           "request_sha256": _hash(body), "response_sha256": _hash(response_raw),
                           "billing_sha256": inventory[names["billing"]]})
    non_receipts = {name for name in inventory if not name.startswith("receipts/")}
    _require(non_receipts == claimed, "unclaimed files, duplicate dispatch files or missing originals")
    _require(sorted(r["generation_id"] for r in replayable[:prefix_calls]) == checkpoint["generation_ids"],
             "checkpoint generations differ")
    _verify_inventory(folder, inventory, manifest["original_inventory_sha256"])
    report = {"schema": "z51-offline-recovery-status/v1", "recovery_id": manifest["recovery_id"],
              "scope": "offline_original_P_calls_only", "completed_blocks_preserved": count,
              "checkpoint_calls_preserved": prefix_calls, "original_file_count": len(inventory),
              "original_inventory_sha256": manifest["original_inventory_sha256"],
              "checkpoint_sha256": manifest["checkpoint_sha256"], "budget": budget,
              "replayable_calls": replayable, "unresolved_attempts": [budget["pending"]] if budget["pending"] else [],
              "live_continuation_allowed": False, "new_provider_calls": 0, "new_cost_usd": "0",
              "provider_reconstruction_import_supported": False,
              "remaining_step": "Resolve original missing response and billing, then separately bind and review a continuation operator."
              if budget["pending"] else "This component only replays originals; it does not activate continuation."}
    return report, requests


def prepare_recovery(candidate, plan, *, original_folder, output, recovery_id,
                     inventory, expected_inventory_sha256, checkpoint, expected_checkpoint_sha256):
    """Create a separate immutable manifest/report from externally bound originals.

    A valid report may retain one unresolved last call. It is never a release.
    No output is created for inconsistent evidence. Partial output from a disk
    failure remains in its unique directory and cannot be silently overwritten.
    """
    original_folder, output = _plain_path(original_folder), _plain_path(output)
    _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", recovery_id) is not None,
             "explicit safe recovery identifier required")
    _require(output != original_folder and original_folder not in output.parents
             and output not in original_folder.parents, "recovery output must be separate from originals")
    _require(not output.exists() and output.parent.is_dir(), "new recovery directory required")
    manifest = {"schema": "z51-offline-recovery-manifest/v1", "recovery_id": recovery_id,
                "original_folder": str(original_folder), "candidate_sha256": canonical_hash(candidate),
                "plan_sha256": canonical_hash(plan), "original_inventory": deepcopy(inventory),
                "original_inventory_sha256": expected_inventory_sha256,
                "checkpoint": deepcopy(checkpoint), "checkpoint_sha256": expected_checkpoint_sha256,
                "authority": "Externally verified original inventory and checkpoint; no new execution rights."}
    report, _ = _inspect(candidate, plan, original_folder, manifest)
    output.mkdir()
    raw_manifest = encoded(manifest)
    save_new(output / "ORIGINALS.json", raw_manifest)
    report["manifest_sha256"] = _hash(raw_manifest)
    save_new(output / "PREPARATION.json", encoded(report))
    return report


def inspect_recovery(candidate, plan, *, recovery_folder, expected_manifest_sha256):
    """Read and revalidate preparation; no files or budget state are updated."""
    folder = _plain_path(recovery_folder)
    raw = _read(folder, "ORIGINALS.json")
    _require(_hash(raw) == expected_manifest_sha256, "externally bound recovery manifest changed")
    manifest = strict_json(raw)
    _require(manifest.get("schema") == "z51-offline-recovery-manifest/v1", "unknown recovery schema")
    report, _ = _inspect(candidate, plan, _plain_path(manifest["original_folder"]), manifest)
    report["manifest_sha256"] = expected_manifest_sha256
    _require(_json(folder, "PREPARATION.json") == report, "recovery preparation report changed")
    return report


class OfflineReplay:
    """Single-consumer, sequential local replay; a stop poisons this session.

    ``scope='partial_block'`` begins after the preserved checkpoint. The optional
    ``all_original_calls`` scope proves an intact prefix on synthetic fixtures.
    No transport can be supplied and no Response is made from a cost assertion.
    There is deliberately no session-resume or new-attempt API.
    """
    def __init__(self, candidate, plan, *, recovery_folder, expected_manifest_sha256,
                 scope="partial_block"):
        _require(scope in ("partial_block", "all_original_calls"), "unknown offline replay scope")
        self._candidate, self._plan = deepcopy(candidate), deepcopy(plan)
        self._folder = _plain_path(recovery_folder)
        self._manifest_hash = expected_manifest_sha256
        report = inspect_recovery(candidate, plan, recovery_folder=self._folder,
                                  expected_manifest_sha256=expected_manifest_sha256)
        self._manifest = _json(self._folder, "ORIGINALS.json")
        self._original = _plain_path(self._manifest["original_folder"])
        _, self._requests = _inspect(candidate, plan, self._original, self._manifest)
        self._report = report
        self._index = report["checkpoint_calls_preserved"] if scope == "partial_block" else 0
        self._poisoned = False
        self._events = self._folder / "replay"
        # Atomic directory creation is the exclusive, persistent consumer claim.
        self._events.mkdir()
        save_new(self._events / "CLAIM.json", encoded({"scope": scope,
                 "manifest_sha256": expected_manifest_sha256, "live_continuation_allowed": False}))

    def __call__(self, request):
        _require(not self._poisoned, "offline replay already stopped; no retry")
        self._poisoned = True
        try:
            inspect_recovery(self._candidate, self._plan, recovery_folder=self._folder,
                             expected_manifest_sha256=self._manifest_hash)
            _require(self._index < len(self._requests), "no further original call; no network fallback")
            saved = self._requests[self._index]
            _require(type(request) is Request and request == saved.request,
                     "replay request differs from the exact original attempt")
            _require(saved.outcome is not None, "original response or billing unresolved; reservation remains held")
            index = self._index + 1
            record = self._report["replayable_calls"][self._index]
            body = _read(self._original, f"provider/{index:05d}-request.json")
            _require(body == encoded(payload(request, producer_limit=1024)), "replay wire body differs")
            raw = _read(self._original, f"provider/{index:05d}-response.json")
            _require(_hash(raw) == record["response_sha256"], "original response changed during replay")
            response = decode_outcome(raw, request.max_output_tokens, F01)
            if self._candidate["mode"] == "artificial_only":
                response = replace(response, usage=replace(response.usage, cost_source="synthetic"))
            _require(_terminal(request.attempt_id, response) == saved.outcome, "replay outcome differs")
            save_new(self._events / f"{index:05d}-replayed.json", encoded({
                "kind": "offline_replay", "recovery_id": self._manifest["recovery_id"],
                "manifest_sha256": self._manifest_hash, **record,
                "new_provider_calls": 0, "new_cost_usd": "0", "reservation_released": False}))
            self._index += 1
            self._poisoned = False
            return response
        except Exception:
            save_new(self._events / "STOP.json", encoded({"kind": "offline_replay_stopped",
                     "next_original_call_index": self._index + 1, "new_provider_calls": 0,
                     "reservation_released": False, "live_continuation_allowed": False}))
            raise
