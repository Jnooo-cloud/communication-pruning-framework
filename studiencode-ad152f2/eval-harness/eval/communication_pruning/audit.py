"""Separate trace reconstruction; never calls the execution implementation."""

from .failure_policy import F01, REASONS, CONTEXT, RESERVE
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
from .contracts import Configuration, INSTRUCTIONS


class AuditError(ValueError):
    pass


def audit(trace: dict, expected_config: Configuration) -> dict:
    """Check a JSON trace against a trusted config; totals are not provider verification."""
    return _audit(trace, expected_config, partial=False)


def audit_prefix(trace: dict, expected_config: Configuration) -> dict:
    """Validate an unfinished event prefix without inferring execution or retrying."""
    return _audit(trace, expected_config, partial=True)


def _audit(trace, expected_config, *, partial):
    def require(condition, message):
        if not condition:
            raise AuditError(message)

    try:
        require(type(trace["schema"]) is int and trace["schema"] in (1, 2, 3), "unsupported schema")
        producer_limit = 512
        if trace["schema"] in (2, 3):
            require(trace.get("output_limits") == {"producer": 1024, "aggregator": 128}
                    and all(type(v) is int for v in trace["output_limits"].values()), "invalid limit contract")
            producer_limit = 1024
        else:
            require("output_limits" not in trace, "legacy limits cannot be overridden")
        policy = trace.get("failure_policy")
        require(policy == F01 if trace["schema"] == 3 else "failure_policy" not in trace, "failure policy/schema mismatch")
        config = json.loads(json.dumps(asdict(expected_config)))
        require(trace["configuration"] == config, "configuration changed")
        rounds, suppressed = trace["rounds"], trace["failed_role"]
        require(type(rounds) is int and rounds in (1, 2), "invalid rounds")
        require(suppressed is None or suppressed in config["roles"], "invalid suppression")
        require(isinstance(trace["run_id"], str) and bool(trace["run_id"]), "invalid run ID")
        task = trace["task"]
        require(set(task) == {"task_id", "question", "paragraphs"}, "unexpected task fields")
        require(isinstance(task["task_id"], str) and bool(task["task_id"])
                and isinstance(task["question"], str)
                and isinstance(task["paragraphs"], list)
                and all(isinstance(p, str) for p in task["paragraphs"]), "invalid public task")
        require(isinstance(trace["events"], list), "events must be a list")
        events = iter(trace["events"])
        exhausted = object()
        seen = set()
        calls = failures = unknown = synthetic = 0
        known = Decimal(0)
        pending = []

        def report(schedule_complete=False):
            result = {"calls": calls, "failed_calls": failures, "unknown_cost_calls": unknown,
                      "synthetic_cost_calls": synthetic, "known_cost_subtotal_usd": str(known),
                      "total_cost_usd": None if unknown or partial else str(known),
                      "cost_coverage": (calls - unknown) / len(seen) if seen else None}
            if partial:
                result.update(started_attempts=len(seen), unresolved_attempt_ids=pending[:],
                              schedule_complete=schedule_complete)
            return result

        outputs = {}
        expected_steps = [(r, role) for r in range(1, rounds + 1) for role in config["roles"]]
        expected_steps.append((rounds + 1, "aggregator"))
        for round_no, role in expected_steps:
            start = next(events, exhausted)
            if start is exhausted:
                require(partial, "missing scheduled event")
                return report()
            if role == suppressed:
                require(start == {"kind": "suppressed", "role": role, "round": round_no}, "invalid suppression event")
                continue
            attempt_id = f'{trace["run_id"]}:{round_no}:{role}:1'
            require(attempt_id not in seen, "duplicate attempt")
            seen.add(attempt_id)
            expected_messages = []
            for source in config["roles"]:
                prior = outputs.get((round_no - 1, source))
                allowed = role == "aggregator" or source == role or [source, role] in config["edges"]
                if prior is not None and allowed:
                    expected_messages.append(prior)
            require(start == {"kind": "started", "attempt_id": attempt_id,
                              "role": role, "round": round_no, "instruction": INSTRUCTIONS[role],
                              "max_output_tokens": 128 if role == "aggregator" else producer_limit,
                              "messages": expected_messages}, "invalid call or message visibility")
            pending = [attempt_id]
            terminal = next(events, exhausted)
            if terminal is exhausted:
                require(partial, "missing terminal event")
                return report()
            require(terminal["attempt_id"] == attempt_id, "terminal attempt mismatch")
            require(terminal["kind"] in (("completed", "model_failed") if policy == F01 else ("completed", "failed")), "missing terminal event")
            calls += 1
            usage = terminal["usage"]
            require(set(usage) == {"input_tokens", "output_tokens", "cost_usd", "cost_source", "price_version"}, "invalid usage fields")
            for name in ("input_tokens", "output_tokens"):
                require(usage[name] is None or (type(usage[name]) is int and usage[name] >= 0), "invalid token count")
            source, amount = usage["cost_source"], usage["cost_usd"]
            require(source in {"unknown", "synthetic", "provider", "token_price"}, "invalid cost source")
            if amount is None:
                require(source == "unknown", "unknown cost mislabeled")
                unknown += 1
            else:
                require(isinstance(amount, str) and source != "unknown", "known cost missing provenance")
                value = Decimal(amount)
                require(value.is_finite() and value >= 0, "invalid cost")
                known += value
                synthetic += source == "synthetic"
            if source == "token_price":
                require(bool(usage["price_version"]) and usage["input_tokens"] is not None
                        and usage["output_tokens"] is not None, "missing price metadata")
            if policy == F01:
                require(source in ("provider", "synthetic") and amount is not None
                        and unknown == 0 and value <= RESERVE
                        and type(usage["input_tokens"]) is int and usage["input_tokens"] <= CONTEXT
                        and type(usage["output_tokens"]) is int
                        and usage["output_tokens"] <= start["max_output_tokens"], "invalid F-01 usage")
            if terminal["kind"] == "model_failed":
                require(set(terminal) == {"kind", "attempt_id", "reason", "usage"}
                        and terminal["reason"] in REASONS, "invalid model failure")
                failures += 1
                pending = []
                require(next(events, exhausted) is exhausted, "events after model failure")
                if not partial:
                    require(trace["status"] == "model_failed" and trace["answer"] is None,
                            "model failure must close the task without an answer")
                result = report()
                result["policy_terminal"] = True
                return result
            if terminal["kind"] == "completed":
                require(set(terminal) == {"kind", "attempt_id", "text", "usage"}
                        and isinstance(terminal["text"], str)
                        and (policy != F01 or bool(terminal["text"].strip())), "invalid output")
                outputs[(round_no, role)] = {"attempt_id": attempt_id, "role": role,
                                            "round": round_no, "text": terminal["text"]}
            else:
                require(set(terminal) == {"kind", "attempt_id", "error", "usage"}
                        and isinstance(terminal["error"], str), "invalid failure")
                failures += 1
            pending = []
        require(next(events, exhausted) is exhausted, "unexpected trailing event")
        if partial:
            return report(schedule_complete=True)
        final = outputs.get((rounds + 1, "aggregator"))
        require(trace["answer"] == (None if final is None else final["text"]), "answer mismatch")
        require(trace["status"] == ("incomplete" if failures else "completed"), "status mismatch")
        return report(schedule_complete=True)
    except AuditError:
        raise
    except (KeyError, TypeError, StopIteration, ValueError, InvalidOperation) as error:
        raise AuditError(f"malformed or incomplete trace: {error}") from error
