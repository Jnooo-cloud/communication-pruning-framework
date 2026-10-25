"""Z07: metadata preparation, explicit data release, then one technical batch.

Import does not read data or contact a model. Preparation parses source records
but retains structural metadata only; it prints no questions, contexts or answers.
"""

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from .configurations import bank
from .data import canonical, index_file, load_task, read_manifest
from .evaluation import read_result
from .execution import execute
from .journal import read_journal
from .openrouter import (MODEL, PROVIDER, RESERVE, ProbeAdapter, ProbeStop, Transport,
                         encoded, load_key, now, number, parse_json, save_new, validate_endpoint)
from .probe import ROOT, audit_provider, verify_sources
from .technical import DATA_PATH, SEED, SOURCE_HASHES, exposed_ids, select_technical, verify_prior

PREP = "eval-harness/eval/runs/Z07-PREPARE"
LIVE = "eval-harness/eval/runs/Z07-OPENROUTER-001"
REQUIRED = ("eval-harness/eval/communication_pruning/musique_probe.py",
            "eval-harness/eval/communication_pruning/technical.py")


def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def prepare(root, source_receipt):
    root = Path(root)
    source_hash = verify_sources(root, root / source_receipt, cycle="Z07", required_files=REQUIRED)
    budget = verify_prior(root)
    register = root / "project/DATENEXPOSITIONSREGISTER.md"
    excluded = exposed_ids(register.read_text())
    rows = tuple(row for split, digest in SOURCE_HASHES.items()
                 for row in index_file(root / DATA_PATH / f"musique_ans_v1.0_{split}.jsonl", split, digest))
    selected, manifest = select_technical(rows, excluded, SOURCE_HASHES)
    folder = root / PREP
    folder.mkdir(mode=0o700)
    save_new(folder / "manifest.json", canonical(manifest))
    receipt = {"schema": 1, "created_at": now(), "mode": "metadata_only_pre_content",
               "source_receipt": source_receipt, "source_receipt_sha256": source_hash,
               "register_before_sha256": sha(register), "seed": SEED, "selected": selected,
               "manifest_path": f"{PREP}/manifest.json", "manifest_file_sha256": sha(folder / "manifest.json"),
               "manifest_content_sha256": manifest["sha256"], "budget": budget,
               "reserved_family_tasks": sum(len(x["members"]) for x in selected),
               "selection_plan_sha256": sha(root / "project/dsr/Z07-PLAN.md")}
    save_new(root / "project/dsr/Z07-SELECTION.json", encoded(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt


def prepared(root):
    root = Path(root)
    receipt = json.loads((root / "project/dsr/Z07-SELECTION.json").read_bytes())
    path = root / receipt["manifest_path"]
    if sha(path) != receipt["manifest_file_sha256"]:
        raise ProbeStop("selected manifest bytes changed")
    manifest = read_manifest(path)
    if manifest["sha256"] != receipt["manifest_content_sha256"] or manifest["source_hashes"] != SOURCE_HASHES:
        raise ProbeStop("manifest content or sources changed")
    selected = receipt["selected"]
    if len(selected) != 2 or [x["hop"] for x in selected] != [2, 4] or len({x["family_id"] for x in selected}) != 2:
        raise ProbeStop("not the planned two independent cases")
    for x in selected:
        entries = [e for e in manifest["entries"] if e["family_id"] == x["family_id"]]
        if (sorted(e["task_id"] for e in entries) != x["members"]
                or not all(e["split"] == "train" and e["phase"] == "technical" for e in entries)
                or not any(e["task_id"] == x["task_id"] and e["hop"] == x["hop"] for e in entries)):
            raise ProbeStop("selected family rights mismatch")
    technical = {e["family_id"] for e in manifest["entries"] if e["phase"] == "technical"}
    if technical != {x["family_id"] for x in selected}:
        raise ProbeStop("unplanned technical family")
    return receipt, manifest


def release(root):
    root = Path(root)
    selection, _ = prepared(root)
    register = root / "project/DATENEXPOSITIONSREGISTER.md"
    if not {x["task_id"] for x in selection["selected"]} <= exposed_ids(register.read_text()):
        raise ProbeStop("register must exclude selected technical families before exposure")
    receipt = {"created_at": now(), "authorization": ["D-046", "D-047", "Continue with Z07 technical probe"],
               "selection_sha256": sha(root / "project/dsr/Z07-SELECTION.json"),
               "register_sha256": sha(register), "phase": "technical",
               "scope": "two selected train tasks only; no holdout or selector training"}
    save_new(root / "project/dsr/Z07-RELEASE.json", encoded(receipt))
    print(json.dumps(receipt, indent=2))


def validate_release(root):
    root = Path(root)
    release = json.loads((root / "project/dsr/Z07-RELEASE.json").read_bytes())
    if (release["phase"] != "technical"
            or sha(root / "project/dsr/Z07-SELECTION.json") != release["selection_sha256"]
            or sha(root / "project/DATENEXPOSITIONSREGISTER.md") != release["register_sha256"]):
        raise ProbeStop("selection or exposure register changed after release")
    return prepared(root)


def run(root, *, cycle="Z07"):
    root = Path(root)
    if cycle not in ("Z07", "Z08"):
        raise ProbeStop("unplanned cycle")
    if cycle == "Z08":
        from .followup import validate, audit_costs, REQUIRED as required
        selection, manifest = validate(root)
        budget = selection["budget"]
    else:
        selection, manifest = validate_release(root)
        budget = verify_prior(root)
        required = REQUIRED
    producer_limit = 1024 if cycle == "Z08" else 512
    live = f"eval-harness/eval/runs/{cycle}-OPENROUTER-001"
    source = root / selection["source_receipt"]
    source_digest = verify_sources(root, source, cycle=cycle, required_files=required)
    if source_digest != selection["source_receipt_sha256"]:
        raise ProbeStop("selection and execution source receipts differ")
    key = load_key(root / ".env", source="file")
    transport = Transport(key)
    folder = root / live
    folder.mkdir(mode=0o700)  # No resume or second batch for this release.
    result = {"run_id": f"{cycle}-OPENROUTER-001", "started_at": now(), "status": "stopped",
              "mode": "technical_musique_train_not_study", "tasks": [], "calls_reserved": 0,
              "known_cost_subtotal_usd": "0", "total_cost_usd": None, "budget": budget,
              "release_sha256": sha(root / f"project/dsr/{cycle}-RELEASE.json"),
              "producer_limit": producer_limit, "aggregator_limit": 128,
              "source_receipt_sha256": source_digest, "evidence_folder": live}
    save_new(folder / "start.json", encoded(result))
    adapters = []
    generations = set()
    try:
        status, raw = transport("models/google/gemini-2.5-flash-lite/endpoints")
        save_new(folder / "endpoints.json", raw)
        if status != 200:
            raise ProbeStop("catalog unavailable")
        validate_endpoint(raw)
        status, raw = transport("key")
        if status != 200:
            raise ProbeStop("project key authentication failed")
        data = parse_json(raw)["data"]
        remaining = data.get("limit_remaining")
        allowed = remaining is None or number(remaining) >= Decimal(budget["new_reservation_usd"])
        save_new(folder / "access.json", encoded({"authenticated": True, "key_limit_covers_reservation": allowed,
                                                  "is_free_tier": data.get("is_free_tier")}))
        if not allowed or data.get("is_free_tier") is not False:
            raise ProbeStop("paid access or remaining limit not established")
        for index, selected in enumerate(selection["selected"], 1):
            task_folder = folder / f"task-{index:02}"
            task_folder.mkdir(mode=0o700)
            # Save intent before import, including if the process dies during load.
            save_new(task_folder / "import-intent.json", encoded({"task_id": selected["task_id"],
                     "family_id": selected["family_id"], "phase": "technical", "time": now()}))
            task, reference = load_task(root / DATA_PATH / "musique_ans_v1.0_train.jsonl",
                                        selected["task_id"], manifest, phase="technical")
            save_new(task_folder / "public-input.json", encoded(asdict(task)))
            save_new(task_folder / "answer-reference.json", encoded(asdict(reference)))
            adapter = ProbeAdapter(task_folder, transport, producer_limit=producer_limit)
            adapter.generations = generations
            adapters.append(adapter)
            trace = execute(task, bank()[0], adapter, run_id=f"{cycle}-task-{index:02}",
                            journal_path=task_folder / "execution.jsonl", producer_limit=producer_limit)
            checked = read_journal(task_folder / "execution.jsonl", expected_config=bank()[0])
            if not checked["sealed"] or checked["trace"] != trace:
                raise ProbeStop("execution journal mismatch")
            provider = audit_provider(task_folder, trace, task=task)
            scored = read_result(task_folder / "execution.jsonl", bank()[0], task, reference,
                                 family_id=selected["family_id"], phase="technical", repeat=1)
            summary = {"task_id": task.task_id, "original_id": selected["task_id"], "hop": selected["hop"],
                       "family_id": selected["family_id"], "paragraph_count": len(task.paragraphs),
                       "context_words": sum(len(p.split()) for p in task.paragraphs),
                       "context_characters": sum(len(p) for p in task.paragraphs),
                       "em": scored.em, "f1": scored.f1, "provider_audit": provider}
            save_new(task_folder / "summary.json", encoded(summary))
            result["tasks"].append(summary)
        result["status"] = "completed"
    except Exception as error:
        result["stop_type"] = type(error).__name__
        result["stop_reason"] = str(error) if isinstance(error, ProbeStop) else "technical failure; inspect local evidence"
    finally:
        calls = sum(a.calls for a in adapters)
        known = sum((a.cost for a in adapters), Decimal("0"))
        billed = sum(a.billed_calls for a in adapters)
        result.update(calls_reserved=calls, known_cost_subtotal_usd=str(known),
                      billed_calls=billed, unknown_cost_calls=calls-billed,
                      cost_coverage=billed/calls if calls else None,
                      conservative_reservation_usd=str(calls * RESERVE), ended_at=now())
        costs_verified = billed == calls
        if cycle == "Z08" and costs_verified:
            try:
                checks = [audit_costs(a.folder, read_journal(a.folder / "execution.jsonl", expected_config=bank()[0])["trace"]) for a in adapters]
                ids = [g for c in checks for g in c["generation_ids"]]
                if (len(ids) != len(set(ids)) or sum(c["calls"] for c in checks) != calls
                        or sum((Decimal(c["total_cost_usd"]) for c in checks), Decimal(0)) != known):
                    raise ProbeStop("batch accounting mismatch")
                result["accounting_audit"] = checks
            except Exception:
                costs_verified = False
                result.update(status="stopped", accounting_audit_error="saved cost evidence requires review")
        if costs_verified:
            result["total_cost_usd"] = str(known)
            result["combined_technical_cost_usd"] = str(known + Decimal(budget["prior_cost_usd"]))
        result["source_unchanged"] = verify_sources(root, source, cycle=cycle, required_files=required) == source_digest
        result["files_sha256"] = {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}
        save_new(folder / "result.json", encoded(result))
        save_new(root / f"project/dsr/{cycle}-LIVE-001.json", encoded(result))
    print(json.dumps({k: v for k, v in result.items() if k != "files_sha256"}, indent=2))
    return 0 if result["status"] == "completed" else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["prepare", "release", "run"])
    p.add_argument("--source-receipt")
    p.add_argument("--execute-authorized-z07", action="store_true")
    args = p.parse_args()
    if args.mode == "prepare":
        if not args.source_receipt:
            p.error("source receipt required before preparation")
        prepare(ROOT, args.source_receipt)
    elif args.mode == "release":
        release(ROOT)
    else:
        if not args.execute_authorized_z07:
            p.error("explicit execution authorization flag required")
        return run(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
