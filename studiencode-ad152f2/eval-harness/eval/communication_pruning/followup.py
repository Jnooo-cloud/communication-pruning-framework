"""Z08: settled prior evidence and explicit release for the same technical tasks."""
import argparse
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path

from .configurations import bank
from .contracts import Message, Request, TaskInput
from .journal import read_journal
from .musique_probe import sha, validate_release
from .openrouter import (LIMIT, RESERVE, ProbeStop, decode_billing, encoded, now, payload, save_new)
from .probe import ROOT, verify_sources
from .technical import verify_prior

REQUIRED = ("eval-harness/eval/communication_pruning/followup.py",
            "eval-harness/eval/communication_pruning/musique_probe.py")
RELEASE = "project/dsr/Z08-RELEASE.json"


def audit_costs(folder, trace, *, require_billed=True):
    """Check all received costs, even for unfinished execution; never accept text."""
    folder = Path(folder)
    public = trace["task"]
    task = TaskInput(public["task_id"], public["question"], tuple(public["paragraphs"]))
    starts = [e for e in trace["events"] if e["kind"] == "started"]
    ledger = [json.loads(line) for line in (folder / "provider-ledger.jsonl").read_text().splitlines()]
    seen, total, tokens = set(), Decimal(0), Decimal(0)
    cursor = 0
    finishes = []
    for slot, start in enumerate(starts, 1):
        request = Request(start["attempt_id"], task, start["role"], start["round"], start["instruction"],
                          tuple(Message(**m) for m in start["messages"]), start["max_output_tokens"])
        request_path, response_path = folder / f"{slot:02}-request.json", folder / f"{slot:02}-response.json"
        if request_path.read_bytes() != encoded(payload(request, producer_limit=trace.get("output_limits", {}).get("producer", 512))):
            raise ProbeStop("accounting request differs from execution")
        usage, generation = decode_billing(response_path.read_bytes())
        if generation in seen:
            raise ProbeStop("duplicate generation in cost evidence")
        seen.add(generation)
        reserved, received = ledger[cursor:cursor+2]
        cursor += 2
        if (reserved["kind"] != "reserved" or reserved["slot"] != slot
                or reserved["attempt_id"] != start["attempt_id"] or reserved["request_sha256"] != sha(request_path)
                or reserved["reservation_usd"] != str(RESERVE)
                or received["kind"] != "received" or received["slot"] != slot
                or received["http_status"] != 200 or received["response_sha256"] != sha(response_path)):
            raise ProbeStop("accounting receipt binding mismatch")
        if require_billed:
            billed = ledger[cursor]
            cursor += 1
            if (billed["kind"] != "billed" or billed["slot"] != slot
                    or billed["attempt_id"] != start["attempt_id"] or billed["generation_id"] != generation
                    or billed["response_sha256"] != sha(response_path) or billed["usage"] != usage.to_dict()):
                raise ProbeStop("durable accounting record mismatch")
        terminal = ledger[cursor]
        cursor += 1
        if terminal["slot"] != slot or terminal["kind"] not in ("accepted", "stopped"):
            raise ProbeStop("missing provider terminal")
        if terminal["kind"] == "accepted":
            if terminal["generation_id"] != generation or terminal["usage"] != usage.to_dict():
                raise ProbeStop("accepted billing mismatch")
        elif slot != len(starts) or (require_billed and terminal["cost_status"] != "provider"):
            raise ProbeStop("call after provider stop or unknown durable cost")
        total += usage.cost_usd
        tokens += usage.input_tokens * Decimal(".0000001") + usage.output_tokens * Decimal(".0000004")
        response = json.loads(response_path.read_bytes())
        finishes.append(response.get("choices", [{}])[0].get("finish_reason") if response.get("choices") else None)
    if cursor != len(ledger):
        raise ProbeStop("extra accounting events")
    return {"calls": len(starts), "known_cost_subtotal_usd": str(total), "total_cost_usd": str(total),
            "undiscounted_token_price_usd": str(tokens), "generation_ids": sorted(seen),
            "finish_reasons": finishes, "cost_coverage": 1 if starts else None}


def prior_cost(root):
    root = Path(root)
    z06 = verify_prior(root)
    receipt = json.loads((root / "project/dsr/Z07-LIVE-001.json").read_bytes())
    folder = root / receipt["evidence_folder"]
    if (receipt["run_id"] != "Z07-OPENROUTER-001" or receipt["calls_reserved"] != 6
            or not receipt["source_unchanged"]
            or json.loads((folder / "result.json").read_bytes()) != receipt):
        raise ProbeStop("Z07 prior run differs")
    for name, digest in receipt["files_sha256"].items():
        if sha(folder / name) != digest:
            raise ProbeStop("Z07 prior evidence changed")
    source = json.loads((root / "project/dsr/Z07-RUN-002.json").read_bytes())
    if sha(root / source["source_bundle"]) != source["source_bundle_sha256"]:
        raise ProbeStop("old source archive changed")
    subtotal, seen, count = Decimal(0), set(), 0
    for index in (1, 2):
        task_folder = folder / f"task-{index:02}"
        checked = read_journal(task_folder / "execution.jsonl", expected_config=bank()[0])
        cost = audit_costs(task_folder, checked["trace"], require_billed=False)
        if seen.intersection(cost["generation_ids"]):
            raise ProbeStop("duplicate prior generation across tasks")
        seen.update(cost["generation_ids"])
        subtotal += Decimal(cost["total_cost_usd"])
        count += cost["calls"]
    reconciliation = json.loads((root / "project/dsr/Z07-RECONCILIATION.json").read_bytes())
    total = Decimal(z06["prior_cost_usd"]) + subtotal
    if (count != 6 or subtotal != Decimal(reconciliation["provider_reported_cost_usd"])
            or total != Decimal(reconciliation["combined_z06_z07_provider_reported_cost_usd"])):
        raise ProbeStop("prior reconciliation mismatch")
    maximum = total + 10 * RESERVE
    if maximum > LIMIT:
        raise ProbeStop("combined technical budget exhausted")
    return {"prior_cost_usd": str(total), "new_reservation_usd": str(10 * RESERVE),
            "maximum_combined_usd": str(maximum), "authorization_limit_usd": str(LIMIT)}


def bindings(root):
    return {name: sha(root / name) for name in (
        "project/dsr/Z07-SELECTION.json", "project/dsr/Z07-RELEASE.json",
        "project/dsr/Z07-LIVE-001.json", "project/dsr/Z07-RECONCILIATION.json",
        "project/dsr/Z08-PLAN.md", "project/DATENEXPOSITIONSREGISTER.md")}


def prepare(root, source_receipt):
    root = Path(root)
    selection, _ = validate_release(root)
    source_hash = verify_sources(root, root / source_receipt, cycle="Z08", required_files=REQUIRED)
    receipt = {"created_at": now(), "authorization": ["D-046", "D-047", "D-048"],
               "cycle": "Z08", "source_receipt": source_receipt, "source_receipt_sha256": source_hash,
               "bindings": bindings(root), "selected": selection["selected"], "phase": "technical",
               "producer_limit": 1024, "aggregator_limit": 128, "budget": prior_cost(root),
               "scope": "same exposed two Z07 tasks; new technical runs after known failure; no holdout"}
    save_new(root / RELEASE, encoded(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt


def validate(root):
    root = Path(root)
    receipt = json.loads((root / RELEASE).read_bytes())
    selection, manifest = validate_release(root)
    if (receipt["cycle"] != "Z08" or receipt["phase"] != "technical"
            or receipt["selected"] != selection["selected"] or receipt["bindings"] != bindings(root)
            or receipt["producer_limit"] != 1024 or receipt["aggregator_limit"] != 128
            or receipt["authorization"] != ["D-046", "D-047", "D-048"]
            or receipt["budget"] != prior_cost(root)
            or verify_sources(root, root / receipt["source_receipt"], cycle="Z08", required_files=REQUIRED) != receipt["source_receipt_sha256"]):
        raise ProbeStop("Z08 release changed or incomplete")
    return receipt, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run"))
    parser.add_argument("--source-receipt")
    parser.add_argument("--execute-authorized-z08", action="store_true")
    args = parser.parse_args()
    if args.mode == "prepare":
        if not args.source_receipt:
            parser.error("source receipt required")
        prepare(ROOT, args.source_receipt)
        return 0
    if not args.execute_authorized_z08:
        parser.error("explicit Z08 authorization required")
    from .musique_probe import run
    return run(ROOT, cycle="Z08")


if __name__ == "__main__":
    raise SystemExit(main())
