"""Bounded multi-target CART and family-disjoint selection, no model clients.

Inputs are one mean per task and configuration, never repeated-run rows.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import math
import re

from .configurations import bank
from .contracts import TaskInput


CONFIG_IDS = tuple(c.config_id for c in bank())
EPSILON = 0.01
TOL = 1e-12


def features(task: TaskInput):
    words = lambda text: re.findall(r"[a-z0-9]+", text.lower())
    question = words(task.question)
    context = [words(p) for p in task.paragraphs]
    qset = set(question)
    overlap = []
    for tokens in context:
        pset = set(tokens)
        union = qset | pset
        overlap.append(len(qset & pset) / len(union) if union else 0.0)
    best = sorted(overlap, reverse=True) + [0.0, 0.0]
    return (float(len(question)), float(sum(map(len, context))), best[0], best[0] - best[1])


def choose(quality, costs):
    if len(quality) != len(CONFIG_IDS) or len(costs) != len(CONFIG_IDS):
        raise ValueError("complete 14-configuration vectors required")
    if any(type(q) not in (int, float) or not math.isfinite(q) or not 0 <= q <= 1 for q in quality):
        raise ValueError("finite quality in [0,1] required")
    if any(not isinstance(c, Decimal) or not c.is_finite() or c < 0 for c in costs):
        raise ValueError("known nonnegative Decimal costs required")
    best = max(quality)
    eligible = [i for i, q in enumerate(quality) if q >= best - EPSILON - TOL]
    return min(eligible, key=lambda i: (costs[i], CONFIG_IDS[i]))


@dataclass(frozen=True)
class Observation:
    task: TaskInput
    family_id: str
    phase: str
    quality: tuple[float, ...]
    costs: tuple[Decimal, ...]

    def __post_init__(self):
        if not isinstance(self.task, TaskInput) or not isinstance(self.family_id, str) or not self.family_id:
            raise ValueError("task and family required")
        if self.phase != "spatial":
            raise ValueError("selector training accepts only spatial development data")
        if not isinstance(self.quality, tuple) or not isinstance(self.costs, tuple):
            raise ValueError("immutable task-level vectors required")
        choose(self.quality, self.costs)


def _rows(observations):
    rows = sorted(observations, key=lambda row: row.task.task_id)
    if not rows or len({r.task.task_id for r in rows}) != len(rows):
        raise ValueError("nonempty unique task-level observations required")
    if any(not isinstance(r, Observation) or r.phase != "spatial" for r in rows):
        raise ValueError("invalid training observations")
    return rows


def means(rows):
    n = len(rows)
    quality = tuple(math.fsum(r.quality[i] for r in rows) / n for i in range(len(CONFIG_IDS)))
    costs = tuple(sum((r.costs[i] for r in rows), Decimal(0)) / n for i in range(len(CONFIG_IDS)))
    return quality, costs


def family_partition(task_families, *, seed, folds=5):
    """The existing size-balanced fold rule using only task/family metadata."""
    if (not isinstance(task_families, dict) or not task_families
            or any(not isinstance(t, str) or not t or not isinstance(f, str) or not f
                   for t, f in task_families.items())):
        raise ValueError("nonempty task-family mapping required")
    if not isinstance(seed, str) or not seed or type(folds) is not int or folds < 2:
        raise ValueError("explicit seed and at least two folds required")
    groups = {}
    for task, family in task_families.items():
        groups.setdefault(family, []).append(task)
    if len(groups) < folds:
        raise ValueError("not enough distinct families for requested folds")
    def key(family):
        return (-len(groups[family]), sha256((seed + "\0" + family).encode()).hexdigest(), family)
    counts = [0] * folds
    assignment = {}
    for family in sorted(groups, key=key):
        index = min(range(folds), key=lambda f: (counts[f], f))
        counts[index] += len(groups[family])
        assignment[family] = index
    return assignment


def family_folds(observations, *, seed, folds=5):
    rows = _rows(observations)
    assignment = family_partition({r.task.task_id: r.family_id for r in rows}, seed=seed, folds=folds)
    return tuple(tuple(r for r in rows if assignment[r.family_id] == f) for f in range(folds))


def fit_tree(observations, *, depth, min_leaf=40):
    rows = _rows(observations)
    if type(depth) is not int or depth not in (1, 2) or type(min_leaf) is not int or min_leaf < 1:
        raise ValueError("bounded depth and positive leaf size required")
    x = [features(r.task) for r in rows]
    y = [r.quality for r in rows]
    width = len(CONFIG_IDS)

    def build(indices, remaining):
        n = len(indices)
        sums = [math.fsum(y[j][k] for j in indices) for k in range(width)]
        squares = math.fsum(value * value for j in indices for value in y[j])
        leaf = {"n": n, "values": [s / n for s in sums]}
        if remaining == 0 or n < 2 * min_leaf:
            return leaf
        base_loss = squares - math.fsum(s*s/n for s in sums)
        best = None
        for feature in range(4):
            order = sorted(indices, key=lambda j: (x[j][feature], rows[j].task.task_id))
            left_sums = [0.0] * width
            for pos in range(1, n):
                for k in range(width):
                    left_sums[k] += y[order[pos-1]][k]
                left_value, right_value = x[order[pos-1]][feature], x[order[pos]][feature]
                if pos < min_leaf or n-pos < min_leaf or left_value == right_value:
                    continue
                loss = squares - math.fsum(left_sums[k]**2/pos + (sums[k]-left_sums[k])**2/(n-pos)
                                           for k in range(width))
                threshold = (left_value + right_value) / 2
                if base_loss - loss <= TOL:
                    continue
                if best is None or loss < best[0]-TOL or (abs(loss-best[0]) <= TOL and
                                                         (feature, threshold) < (best[1], best[2])):
                    best = (loss, feature, threshold, order[:pos], order[pos:])
        if best is None:
            return leaf
        _, feature, threshold, left, right = best
        return {"n": n, "feature": feature, "threshold": threshold,
                "left": build(left, remaining-1), "right": build(right, remaining-1)}
    return build(list(range(len(rows))), depth)


def predict_tree(tree, task):
    vector = features(task)
    while "feature" in tree:
        tree = tree["left"] if vector[tree["feature"]] <= tree["threshold"] else tree["right"]
    return tuple(tree["values"])


@dataclass(frozen=True)
class Selector:
    fixed_index: int
    costs: tuple[Decimal, ...]
    tree: dict | None
    report: dict

    def select(self, task):
        index = self.fixed_index if self.tree is None else choose(predict_tree(self.tree, task), self.costs)
        return CONFIG_IDS[index]

    def to_dict(self):
        return {"schema": 1, "config_ids": list(CONFIG_IDS), "fixed_index": self.fixed_index,
                "costs": [str(c) for c in self.costs], "tree": self.tree, "report": self.report}


def fit_selector(observations, *, seed, min_leaf=40):
    rows = _rows(observations)
    quality, costs = means(rows)
    fixed = choose(quality, costs)
    report = {"seed": seed, "epsilon_select": EPSILON, "min_leaf": min_leaf,
              "candidates": [], "folds": [], "training_task_ids": [r.task.task_id for r in rows]}
    if not isinstance(seed, str) or not seed or type(min_leaf) is not int or min_leaf < 1:
        raise ValueError("explicit seed and positive leaf size required")
    if len({r.family_id for r in rows}) < 5:
        report["fallback_reason"] = "fewer_than_five_families"
        return Selector(fixed, costs, None, report)
    folds = family_folds(rows, seed=seed)
    splits = []
    for heldout in folds:
        ids = {r.task.task_id for r in heldout}
        train = [r for r in rows if r.task.task_id not in ids]
        train_quality, train_costs = means(train)
        fold_fixed = choose(train_quality, train_costs)
        splits.append((train, heldout, train_costs, fold_fixed))
        report["folds"].append({"training_ids": [r.task.task_id for r in train],
                                "validation_ids": sorted(ids), "fixed": CONFIG_IDS[fold_fixed],
                                "training_costs": [str(c) for c in train_costs]})
    eligible = []
    for depth in (1, 2):
        quality_sum = delta_sum = 0.0
        cost_sum = Decimal(0)
        valid = True
        for train, heldout, train_costs, fold_fixed in splits:
            tree = fit_tree(train, depth=depth, min_leaf=min_leaf)
            if "feature" not in tree:
                valid = False
                break
            for row in heldout:
                selected = choose(predict_tree(tree, row.task), train_costs)
                quality_sum += row.quality[selected]
                delta_sum += row.quality[selected] - row.quality[fold_fixed]
                cost_sum += row.costs[selected]
        candidate = {"depth": depth, "valid": valid}
        if valid:
            q, delta, cost = quality_sum/len(rows), delta_sum/len(rows), cost_sum/len(rows)
            candidate.update(quality=q, quality_difference=delta, cost_usd=str(cost),
                             eligible=delta >= -EPSILON-TOL)
            if candidate["eligible"]:
                eligible.append((cost, -q, depth))
        report["candidates"].append(candidate)
    if not eligible:
        report["fallback_reason"] = "no_admissible_tree"
        return Selector(fixed, costs, None, report)
    _, _, depth = min(eligible)
    tree = fit_tree(rows, depth=depth, min_leaf=min_leaf)
    report["chosen_depth"] = depth
    return Selector(fixed, costs, tree, report)
