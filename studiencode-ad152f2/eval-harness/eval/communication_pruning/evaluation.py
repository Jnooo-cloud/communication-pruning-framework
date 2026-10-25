"""Separate answer scoring and strict task-level aggregation.

Normalization/EM/F1 follow the already inspected MuSiQue answer metric:
https://github.com/StonyBrookNLP/musique/blob/922ac98f19a201998dbdae6d7f2887a5258dbdeb/metrics/answer.py
Own implementation; empty generated answers are failures under our study rule.
No model clients, heuristic answer extraction, or silently dropped observations.
"""

from .failure_policy import F01, REASONS
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import string

from .contracts import TaskInput
from .data import AnswerReference
from .journal import read_journal
from .selection import CONFIG_IDS, Observation


def normalize_answer(text):
    if not isinstance(text, str):
        raise ValueError("answer must be text")
    cleaned = text.lower().translate(str.maketrans("", "", string.punctuation))
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", cleaned).split())


def score_answer(answer, reference: AnswerReference):
    if not isinstance(answer, str) or not isinstance(reference, AnswerReference):
        raise ValueError("generated text and a separate reference required")
    if not reference.answers or any(not isinstance(a, str) or not a.strip() for a in reference.answers):
        raise ValueError("nonempty answer references required")
    if not answer.strip():
        return {"em": 0.0, "f1": 0.0}
    predicted = normalize_answer(answer)
    pred_tokens = predicted.split()
    exact, best_f1 = 0.0, 0.0
    for gold in reference.answers:
        gold = normalize_answer(gold)
        tokens = gold.split()
        exact = max(exact, float(predicted == gold))
        overlap = sum((Counter(pred_tokens) & Counter(tokens)).values())
        if not tokens or not pred_tokens:
            f1 = float(tokens == pred_tokens)
        else:
            f1 = 2 * overlap / (len(tokens) + len(pred_tokens))
        best_f1 = max(best_f1, f1)
    return {"em": exact, "f1": best_f1}


@dataclass(frozen=True)
class RunResult:
    run_id: str
    task_id: str
    family_id: str
    phase: str
    config_id: str
    repeat: int
    status: str
    em: float | None
    f1: float | None
    cost_usd: Decimal | None
    known_subtotal_usd: Decimal
    synthetic_cost_calls: int
    journal_sha256: str
    failure_policy: str | None = None
    failure_reason: str | None = None
    failure_role: str | None = None


def read_result(path, config, task, reference, *, family_id, phase, repeat):
    if (type(repeat) is not int or repeat < 1 or not family_id
            or phase not in {"technical", "spatial", "temporal", "pilot", "analysis", "holdout"}):
        raise ValueError("explicit family, phase and positive repeat ID required")
    if reference.task_id != task.task_id:
        raise ValueError("reference belongs to another task")
    initial_hash = sha256(Path(path).read_bytes()).hexdigest()
    saved = read_journal(path, config)
    if sha256(Path(path).read_bytes()).hexdigest() != initial_hash:
        raise ValueError("journal changed during read")
    if not saved["sealed"]:
        raise ValueError("unclosed journal is not a scored observation")
    trace, report = saved["trace"], saved["audit"]
    if trace["task"] != json.loads(json.dumps(asdict(task))):
        raise ValueError("public task differs from planned input")
    scores = score_answer(trace["answer"], reference) if trace["status"] == "completed" else {"em": None, "f1": None}
    if trace["status"] == "model_failed":
        scores = {"em": 0.0, "f1": 0.0}
    cost = report["total_cost_usd"]
    return RunResult(trace["run_id"], task.task_id, family_id, phase, config.config_id, repeat,
                     trace["status"], scores["em"], scores["f1"], None if cost is None else Decimal(cost),
                     Decimal(report["known_cost_subtotal_usd"]), report["synthetic_cost_calls"], initial_hash, trace.get("failure_policy"),
                     trace["events"][-1]["reason"] if trace["status"] == "model_failed" else None,
                     trace["events"][-2]["role"] if trace["status"] == "model_failed" else None)


@dataclass(frozen=True)
class PlannedTask:
    task: TaskInput
    family_id: str
    phase: str
    repeats: tuple[int, ...]

    def __post_init__(self):
        if not self.family_id or self.phase != "spatial":
            raise ValueError("spatial task plan with family required")
        if (not isinstance(self.repeats, tuple) or not self.repeats
                or len(set(self.repeats)) != len(self.repeats)
                or any(type(r) is not int or r < 1 for r in self.repeats)):
            raise ValueError("unique positive repeat IDs required")


def _usable(result):
    if result.failure_policy not in (None, F01):
        raise ValueError("unknown result policy")
    if result.status == "model_failed":
        if (result.failure_policy != F01 or result.failure_reason not in REASONS
                or result.failure_role not in ("evidence", "linking", "draft", "checking", "aggregator")
                or result.em != 0 or result.f1 != 0):
            raise ValueError("model failure requires bound policy and zero scores")
    elif result.failure_reason is not None or result.failure_role is not None:
        raise ValueError("failure metadata on nonfailure result")
    if (result.status not in ("completed", "model_failed") or type(result.em) not in (int, float)
            or type(result.f1) not in (int, float) or not math.isfinite(result.em)
            or not math.isfinite(result.f1) or not 0 <= result.em <= 1 or not 0 <= result.f1 <= 1):
        raise ValueError("unscored or invalid observation; preserve and resolve explicitly")
    if not isinstance(result.cost_usd, Decimal) or not result.cost_usd.is_finite() or result.cost_usd < 0:
        raise ValueError("unknown or invalid costs; aggregation cannot assume zero")


def development_observations(results, plan):
    plan = list(plan)
    by_task = {p.task.task_id: p for p in plan}
    if not plan or len(by_task) != len(plan):
        raise ValueError("unique planned tasks required")
    expected = {(p.task.task_id, c, r) for p in plan for c in CONFIG_IDS for r in p.repeats}
    actual, run_ids = {}, set()
    total_cost = Decimal(0)
    for result in results:
        key = (result.task_id, result.config_id, result.repeat)
        if key not in expected or key in actual or result.run_id in run_ids:
            raise ValueError("extra or duplicate slot/run ID")
        task = by_task[result.task_id]
        if result.family_id != task.family_id or result.phase != task.phase:
            raise ValueError("phase or family differs from plan")
        _usable(result)
        actual[key] = result
        run_ids.add(result.run_id)
        total_cost += result.cost_usd
    if set(actual) != expected:
        raise ValueError("missing planned slots; no partial training table")
    if len({r.failure_policy for r in actual.values()}) != 1:
        raise ValueError("mixed failure policies in development")
    observations = []
    for task_id in sorted(by_task):
        task = by_task[task_id]
        n = len(task.repeats)
        q = tuple(math.fsum(actual[(task_id, c, r)].em for r in task.repeats)/n for c in CONFIG_IDS)
        costs = tuple(sum((actual[(task_id, c, r)].cost_usd for r in task.repeats), Decimal(0))/n for c in CONFIG_IDS)
        observations.append(Observation(task.task, task.family_id, task.phase, q, costs))
    return {"observations": tuple(observations), "executed_cost_usd": total_cost,
            "executed_runs": len(actual), "task_count": len(plan)}


def paired_task_rows(fixed, adaptive, *, expected_slots, phase):
    """Validate complete paired runs and average repetitions within each task."""
    if (not isinstance(expected_slots, (set, frozenset)) or not expected_slots
            or any(not isinstance(k, tuple) or len(k) != 2 or not isinstance(k[0], str)
                   or not k[0] or type(k[1]) is not int or k[1] < 1 for k in expected_slots)
            or phase not in {"technical", "spatial", "temporal", "pilot", "analysis", "holdout"}):
        raise ValueError("explicit complete slot set and single data phase required")
    def collect(results):
        slots, runs = {}, set()
        for result in results:
            _usable(result)
            if not isinstance(result.family_id, str) or not result.family_id:
                raise ValueError("nonempty family ID required")
            if result.phase != phase:
                raise ValueError("observation outside declared analysis phase")
            key = (result.task_id, result.repeat)
            if key in slots or result.run_id in runs:
                raise ValueError("duplicate paired observation")
            slots[key] = result
            runs.add(result.run_id)
        return slots, runs
    fixed, fixed_runs = collect(fixed)
    adaptive, adaptive_runs = collect(adaptive)
    if set(fixed) != expected_slots or set(adaptive) != expected_slots or fixed_runs & adaptive_runs:
        raise ValueError("arms require distinct runs on identical task/repeat slots")
    if len({r.failure_policy for r in [*fixed.values(), *adaptive.values()]}) != 1:
        raise ValueError("mixed failure policies in paired comparison")
    grouped = defaultdict(list)
    for key, left in fixed.items():
        right = adaptive[key]
        if (left.family_id, left.phase) != (right.family_id, right.phase):
            raise ValueError("unpaired family or phase")
        grouped[left.task_id].append((left, right))
    task_rows = []
    for task_id, pairs in sorted(grouped.items()):
        if len({left.family_id for left, _ in pairs}) != 1 or len({left.phase for left, _ in pairs}) != 1:
            raise ValueError("task identity changes across repetitions")
        n = len(pairs)
        task_rows.append({"task_id": task_id, "family_id": pairs[0][0].family_id,
                          "quality_difference": math.fsum(b.em-a.em for a, b in pairs)/n,
                          "cost_fixed": sum((a.cost_usd for a, _ in pairs), Decimal(0))/n,
                          "cost_adaptive": sum((b.cost_usd for _, b in pairs), Decimal(0))/n})
    return task_rows


def paired_summary(fixed, adaptive, *, expected_slots, phase):
    """Task-weighted point estimates only; no confidence or hypothesis claim."""
    task_rows = paired_task_rows(fixed, adaptive, expected_slots=expected_slots, phase=phase)
    total_fixed = sum((r["cost_fixed"] for r in task_rows), Decimal(0))
    if total_fixed == 0:
        raise ValueError("cost ratio undefined at zero reference cost")
    total_adaptive = sum((r["cost_adaptive"] for r in task_rows), Decimal(0))
    return {"tasks": len(task_rows), "families": len({r["family_id"] for r in task_rows}),
            "phase": phase,
            "quality_difference": math.fsum(r["quality_difference"] for r in task_rows)/len(task_rows),
            "cost_ratio": str(total_adaptive/total_fixed),
            "mean_cost_fixed_usd": str(total_fixed/len(task_rows)),
            "mean_cost_adaptive_usd": str(total_adaptive/len(task_rows)),
            "inference": "point_estimates_only_no_interval_or_threshold_decision"}
