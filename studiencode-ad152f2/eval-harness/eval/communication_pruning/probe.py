"""One authorized Z06 run; no import-time network and no retry command."""

import argparse
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from .configurations import bank
from .contracts import Message, Request, TaskInput
from .execution import execute
from .journal import read_journal
from .openrouter import (MODEL, PROVIDER, MAX_CALLS, RESERVE, ProbeAdapter, ProbeStop,
                         Transport, decode_response, encoded, load_key, now, number,
                         parse_json, payload, save_new, validate_endpoint)

ROOT = Path(__file__).resolve().parents[3]
RUN_ID = "Z06-OPENROUTER-002"
TASK = TaskInput("synthetic-z06-neral", "What city was the inventor of the Neral lamp born in?",
                 ("The Neral lamp was invented by Ada Venn.",
                  "Ada Venn was born in the city of Linden.",
                  "The unrelated Orin clock was manufactured in Port Vale."))


def audit_provider(folder, trace, *, task=TASK):
    """Rebuild request bodies from independently checked execution events."""
    folder = Path(folder)
    if encoded(trace["task"]) != encoded(asdict(task)):
        raise ProbeStop("execution public task does not match expected task")
    starts = [e for e in trace["events"] if e["kind"] == "started"]
    ends = [e for e in trace["events"] if e["kind"] == "completed"]
    ledger = [json.loads(line) for line in (folder / "provider-ledger.jsonl").read_text().splitlines()]
    if trace["status"] != "completed" or len(starts) != MAX_CALLS or len(ends) != MAX_CALLS:
        raise ProbeStop("not the complete planned provider sequence")
    width = 4 if any(e["kind"] == "billed" for e in ledger) else 3
    if len(ledger) != width * MAX_CALLS:
        raise ProbeStop("provider ledger incomplete or extra events")
    total, undiscounted, seen = Decimal("0"), Decimal("0"), set()
    for slot, (start, end) in enumerate(zip(starts, ends), 1):
        request = Request(start["attempt_id"], task, start["role"], start["round"],
                          start["instruction"], tuple(Message(**m) for m in start["messages"]),
                          start["max_output_tokens"])
        body, raw = (folder / f"{slot:02}-request.json").read_bytes(), (folder / f"{slot:02}-response.json").read_bytes()
        response, generation = decode_response(raw, request.max_output_tokens)
        group = ledger[(slot - 1) * width:slot * width]
        reserved, received, accepted = group[0], group[1], group[-1]
        if width == 4:
            billed = group[2]
            if (billed["kind"] != "billed" or billed["slot"] != slot
                    or billed["attempt_id"] != start["attempt_id"] or billed["generation_id"] != generation
                    or billed["response_sha256"] != sha256(raw).hexdigest()
                    or billed["usage"] != response.usage.to_dict()):
                raise ProbeStop("billing evidence mismatch")
        if (body != encoded(payload(request, producer_limit=trace.get("output_limits", {}).get("producer", 512))) or end["attempt_id"] != start["attempt_id"]
                or end["text"] != response.text or end["usage"] != response.usage.to_dict()
                or generation in seen or reserved["kind"] != "reserved"
                or reserved["attempt_id"] != start["attempt_id"] or reserved["slot"] != slot
                or reserved["reservation_usd"] != str(RESERVE)
                or reserved["request_sha256"] != sha256(body).hexdigest()
                or received["kind"] != "received" or received["slot"] != slot
                or received["http_status"] != 200 or received["response_sha256"] != sha256(raw).hexdigest()
                or accepted["kind"] != "accepted" or accepted["slot"] != slot
                or accepted["generation_id"] != generation or accepted["usage"] != end["usage"]):
            raise ProbeStop("provider/execution evidence mismatch")
        seen.add(generation)
        total += response.usage.cost_usd
        undiscounted += (Decimal(response.usage.input_tokens) * Decimal("0.0000001")
                        + Decimal(response.usage.output_tokens) * Decimal("0.0000004"))
    return {"calls": MAX_CALLS, "cost_usd": str(total), "cost_source": "OpenRouter usage.cost",
            "undiscounted_token_price_usd": str(undiscounted),
            "charged_minus_undiscounted_usd": str(total - undiscounted),
            "crosscheck": "request_response_execution_binding_not_independent_billing_audit"}


def verify_sources(root, receipt_path, *, cycle="Z06", required_files=()):
    r = json.loads(receipt_path.read_text())
    if r["cycle"] != cycle or not r["source_unchanged_during_run"] or any(x["returncode"] != 0 for x in r["runs"]):
        raise ProbeStop("passing matching cycle source receipt required")
    if not set(required_files) <= set(r["files_sha256"]):
        raise ProbeStop("required cycle source files not covered")
    if not any(p.endswith("/openrouter.py") for p in r["files_sha256"]) or not any(p.endswith("/probe.py") for p in r["files_sha256"]):
        raise ProbeStop("provider sources not covered")
    for name, digest in r["files_sha256"].items():
        if sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ProbeStop("source changed since tests")
    if sha256((root / r["source_bundle"]).read_bytes()).hexdigest() != r["source_bundle_sha256"]:
        raise ProbeStop("source archive mismatch")
    return sha256(receipt_path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-authorized-z06", action="store_true")
    parser.add_argument("--source-receipt", required=True)
    args = parser.parse_args()
    if not args.execute_authorized_z06:
        parser.error("explicit authorized execution flag required")
    source_receipt = ROOT / args.source_receipt
    source_digest = verify_sources(ROOT, source_receipt)
    key = load_key(ROOT / ".env", source="file")
    transport = Transport(key)
    folder = ROOT / "eval-harness/eval/runs" / RUN_ID
    folder.parent.mkdir(parents=True, exist_ok=True)
    # Global identity for this authorization: existing directory is a hard stop.
    folder.mkdir(mode=0o700)
    started = now()
    save_new(folder / "plan.json", encoded({"run_id": RUN_ID, "started_at": started,
             "authorization": ["D-046", "D-047"], "model": MODEL, "provider": PROVIDER,
             "credential_source": "project .env explicitly; no environment override",
             "max_calls": MAX_CALLS, "reservation_per_call_usd": str(RESERVE),
             "user_limit_usd": "2", "task": asdict(TASK), "configuration": asdict(bank()[0]),
             "rounds": 2, "source_receipt": str(source_receipt.relative_to(ROOT)),
             "source_receipt_sha256": source_digest,
             "cycle_plan_sha256": sha256((ROOT / "project/dsr/Z06-PLAN.md").read_bytes()).hexdigest()}))
    adapter = None
    result = {"run_id": RUN_ID, "started_at": started, "mode": "technical_synthetic_input_real_model",
              "status": "stopped", "calls_reserved": 0, "known_cost_subtotal_usd": "0",
              "total_cost_usd": None, "model": MODEL, "requested_provider": PROVIDER}
    try:
        status, raw = transport("models/google/gemini-2.5-flash-lite/endpoints")
        save_new(folder / "endpoints.json", raw)
        if status != 200:
            raise ProbeStop("catalog unavailable")
        validate_endpoint(raw)
        status, raw = transport("key")
        # Save only necessary status, never key labels or unrelated account usage.
        if status != 200:
            raise ProbeStop("OpenRouter authentication failed")
        data = parse_json(raw)["data"]
        remaining = data.get("limit_remaining")
        allowed = remaining is None or number(remaining) >= MAX_CALLS * RESERVE
        save_new(folder / "access.json", encoded({"authenticated": True,
                 "key_limit_covers_reservation": allowed, "is_free_tier": data.get("is_free_tier")}))
        if not allowed or data.get("is_free_tier") is not False:
            raise ProbeStop("key limit or paid access not established")
        adapter = ProbeAdapter(folder, transport)
        trace = execute(TASK, bank()[0], adapter, run_id=RUN_ID, journal_path=folder / "execution.jsonl")
        checked = read_journal(folder / "execution.jsonl", expected_config=bank()[0])
        if not checked["sealed"] or checked["trace"] != trace:
            raise ProbeStop("execution journal mismatch")
        provider = audit_provider(folder, trace)
        result.update(status="completed", total_cost_usd=provider["cost_usd"], provider_audit=provider,
                      answer=trace["answer"], expected_answer="Linden",
                      exact_technical_answer=trace["answer"].strip() == "Linden")
    except Exception as error:
        result["stop_type"] = type(error).__name__
        # Exceptions can contain provider text; do not print arbitrary messages.
        result["stop_reason"] = str(error) if isinstance(error, ProbeStop) else "technical failure; inspect local evidence"
    finally:
        if adapter is not None:
            result.update(calls_reserved=adapter.calls, known_cost_subtotal_usd=str(adapter.cost),
                          conservative_reservation_usd=str(adapter.calls * RESERVE))
        else:
            result["total_cost_usd"] = "0"
        result["ended_at"] = now()
        result["files_sha256"] = {p.name: sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}
        result["source_unchanged"] = verify_sources(ROOT, source_receipt) == source_digest
        result["evidence_folder"] = str(folder.relative_to(ROOT))
        save_new(folder / "result.json", encoded(result))
        save_new(ROOT / "project/dsr/Z06-LIVE-002.json", encoded(result))
    print(json.dumps({k: v for k, v in result.items() if k != "files_sha256"}, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
