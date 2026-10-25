"""The bound Q-sem spatial candidate; raw selection and diagnostic advice stay separate.

Only visible TaskInput text enters features. Families identify externally bound folds,
never features. Optional numerical/model dependencies are imported only when needed.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
from time import perf_counter_ns

from .contracts import TaskInput
from .selection import CONFIG_IDS, EPSILON, TOL, Observation, choose, features, means

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
DIMENSION = 388
ALPHAS = (1, 10, 100)
_PARAMETERS = {"alphas": list(ALPHAS), "solver": "svd", "fit_intercept": True,
               "standard_deviation_divisor": "n", "constant_columns": "zero",
               "epsilon": EPSILON, "tie_tolerance": TOL, "score_clipping": False}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return sha256(_json(value).encode()).hexdigest()


def _hashes(value):
    if not isinstance(value, dict) or not value:
        raise ValueError("nonempty externally bound SHA256 mapping required")
    for key, digest in value.items():
        if (not isinstance(key, str) or not key or not isinstance(digest, str)
                or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("invalid external SHA256 binding")


def encoder_identity(files, runtime):
    """Build the exact identity carried by both loaded encoder and selector export."""
    _hashes(files)
    required = {"config.json", "tokenizer.json", "tokenizer_config.json",
                "special_tokens_map.json", "vocab.txt"}
    if not required <= set(files) or sum(f in files for f in ("model.safetensors", "pytorch_model.bin")) != 1:
        raise ValueError("complete tokenizer/configuration and exactly one weight file required")
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("model files must have normalized relative paths")
    if not isinstance(runtime, dict) or not runtime:
        raise ValueError("explicit runtime binding required")
    _json(runtime)
    return {"model_id": MODEL_ID, "revision": REVISION, "tokenizer_id": MODEL_ID,
            "tokenizer_revision": REVISION, "input": "unchanged_question",
            "max_wordpieces": 256, "embedding_dimension": 384, "dimension": DIMENSION,
            "pooling": "attention_mask_mean", "normalization": "l2", "device": "cpu",
            "threads": 1, "frozen": True, "files": dict(files), "runtime": deepcopy(runtime)}


def _identity(value):
    if not isinstance(value, dict) or value != encoder_identity(value.get("files"), value.get("runtime")):
        raise ValueError("incomplete or conflicting encoder identity")


class FrozenMiniLM:
    """Offline-only, exact local model files; no remote code, downloads or fine-tuning."""
    def __init__(self, model_dir, *, files, runtime):
        start = perf_counter_ns()
        self.identity = encoder_identity(files, runtime)
        self.model_dir = Path(model_dir).resolve()
        actual = {str(p.relative_to(self.model_dir)) for p in self.model_dir.rglob("*") if p.is_file()}
        if actual != set(files):
            raise ValueError("model directory must equal its complete file binding")
        for name, expected in files.items():
            path = self.model_dir / name
            if path.is_symlink() or not path.resolve().is_relative_to(self.model_dir):
                raise ValueError("model file escapes bound directory")
            if sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError("model file hash differs: " + name)
        import importlib.metadata
        import platform
        import sys
        expected_runtime = {"python", "packages", "platform", "machine", "interpreter_sha256",
                            "provision_binding_sha256", "device", "threads", "weights_format"}
        if (set(runtime) != expected_runtime or runtime["python"] != platform.python_version()
                or runtime["platform"] != platform.platform() or runtime["machine"] != platform.machine()
                or runtime["interpreter_sha256"] != sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()
                or runtime["device"] != "cpu" or runtime["threads"] != 1
                or runtime["weights_format"] != "safetensors" or "model.safetensors" not in files):
            raise ValueError("current Python/platform/encoder format differs from runtime binding")
        _hashes({"provision": runtime["provision_binding_sha256"]})
        packages = runtime["packages"]
        if not isinstance(packages, dict) or not {"torch", "numpy", "transformers", "scikit-learn"} <= set(packages):
            raise ValueError("complete exact numerical runtime package binding required")
        for distribution, version in packages.items():
            if importlib.metadata.version(distribution) != version:
                raise ValueError("runtime package differs: " + distribution)
        import torch
        from transformers import AutoModel, AutoTokenizer
        torch.set_num_threads(1)
        if torch.get_num_interop_threads() != 1:
            torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir), local_files_only=True,
                                                       trust_remote_code=False)
        self.model = AutoModel.from_pretrained(str(self.model_dir), local_files_only=True,
                                               trust_remote_code=False, use_safetensors=True).to("cpu").eval()
        self.model.requires_grad_(False)
        if self.model.config.hidden_size != 384:
            raise ValueError("wrong encoder hidden dimension")
        self.initialization_ns = perf_counter_ns() - start

    def encode_questions(self, questions):
        if not isinstance(questions, (list, tuple)) or not questions or any(not isinstance(q, str) for q in questions):
            raise ValueError("nonempty unmodified question strings required")
        start = perf_counter_ns()
        lengths = [len(self.tokenizer(q, truncation=False, add_special_tokens=True)["input_ids"]) for q in questions]
        vectors = []
        # Fixed order and bounded batches; no stochastic sampling or padding-dependent pool.
        for offset in range(0, len(questions), 32):
            tokens = self.tokenizer(list(questions[offset:offset + 32]), padding=True, truncation=True,
                                    max_length=256, return_tensors="pt")
            with self._torch.no_grad():
                hidden = self.model(**tokens).last_hidden_state
                mask = tokens["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                pooled = self._torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.cpu().tolist())
        return vectors, {"encoder_ns": perf_counter_ns() - start, "questions": len(questions),
                         "token_lengths_before_truncation": lengths,
                         "truncated_questions": sum(n > 256 for n in lengths)}


def _matrix(tasks, encoder):
    import numpy as np
    if any(not isinstance(t, TaskInput) for t in tasks):
        raise ValueError("only public TaskInput values are feature inputs")
    _identity(encoder.identity)
    vectors, metadata = encoder.encode_questions([t.question for t in tasks])
    embedded = np.asarray(vectors, dtype=float)
    if embedded.shape != (len(tasks), 384) or not np.isfinite(embedded).all():
        raise ValueError("encoder must return finite 384-dimensional rows")
    norms = np.linalg.norm(embedded, axis=1)
    if not np.allclose(norms, 1.0, rtol=0, atol=1e-5):
        raise ValueError("encoder vectors must be L2-normalized")
    return np.concatenate((embedded, np.asarray([features(t) for t in tasks])), axis=1), metadata


def choose_scores(scores, costs):
    """Select from finite, deliberately unbounded scores using the bound tie rule."""
    if len(scores) != len(CONFIG_IDS) or len(costs) != len(CONFIG_IDS):
        raise ValueError("complete 14-head vectors required")
    if any(type(q) not in (int, float) or not math.isfinite(q) for q in scores):
        raise ValueError("finite scores required")
    if any(not isinstance(c, Decimal) or not c.is_finite() or c < 0 for c in costs):
        raise ValueError("known nonnegative Decimal costs required")
    eligible = [i for i, score in enumerate(scores) if score >= max(scores) - EPSILON - TOL]
    return min(eligible, key=lambda i: (costs[i], CONFIG_IDS[i]))


def _rows(observations):
    rows = list(observations)
    if not rows or any(not isinstance(r, Observation) for r in rows):
        raise ValueError("nonempty spatial Observation rows required")
    if len({r.task.task_id for r in rows}) != len(rows):
        raise ValueError("repetitions must be aggregated before fitting")
    return sorted(rows, key=lambda r: r.task.task_id)


def _folds(rows, folds):
    """Accept the saved plan's five task lists or an exact family-to-fold mapping."""
    ids = {r.task.task_id for r in rows}
    families = {r.family_id for r in rows}
    if isinstance(folds, dict):
        if set(folds) != families or any(type(f) is not int or f not in range(5) for f in folds.values()):
            raise ValueError("exact family fold mapping required")
        lists = [sorted(r.task.task_id for r in rows if folds[r.family_id] == f) for f in range(5)]
    else:
        if (not isinstance(folds, (list, tuple)) or len(folds) != 5
                or any(not isinstance(f, (list, tuple)) for f in folds)):
            raise ValueError("the five prebound folds are required")
        lists = [sorted(f) for f in folds]
    flat = [t for fold in lists for t in fold]
    if any(not f for f in lists) or len(flat) != len(ids) or set(flat) != ids:
        raise ValueError("folds must cover each task exactly once")
    by_task = {t: f for f, tasks in enumerate(lists) for t in tasks}
    if any(len({by_task[r.task.task_id] for r in rows if r.family_id == family}) != 1 for family in families):
        raise ValueError("family crosses validation folds")
    return lists


def fit_ridge(rows, matrix, *, alpha):
    """Fit only supplied training rows; matrix is in the same row order."""
    import numpy as np
    from sklearn.linear_model import Ridge
    if type(alpha) is not int or alpha not in ALPHAS:
        raise ValueError("alpha must be one of the prebound three values")
    rows = list(rows)
    if not rows or any(not isinstance(r, Observation) for r in rows):
        raise ValueError("training observations required")
    x = np.asarray(matrix, dtype=float)
    if x.shape != (len(rows), DIMENSION) or not np.isfinite(x).all():
        raise ValueError("finite 388-dimensional training matrix required")
    mean = x.mean(axis=0)
    scale = x.std(axis=0, ddof=0)
    constant = np.ptp(x, axis=0) == 0
    # Exact constant detection prevents tiny summation roundoff from creating a feature.
    scale[constant] = 1.0
    z = (x - mean) / scale
    z[:, constant] = 0.0
    estimator = Ridge(alpha=alpha, fit_intercept=True, solver="svd")
    estimator.fit(z, np.asarray([r.quality for r in rows], dtype=float))
    estimator.coef_[:, constant] = 0.0
    quality, costs = means(rows)
    return {"alpha": alpha, "mean": mean.tolist(), "scale": scale.tolist(),
            "constant": constant.tolist(), "coefficients": estimator.coef_.tolist(),
            "intercepts": estimator.intercept_.tolist(), "costs": [str(c) for c in costs],
            "fixed_index": choose(quality, costs), "training_quality": list(quality),
            "training_task_ids": [r.task.task_id for r in rows]}


def predict_scores(model, matrix):
    import numpy as np
    x = np.asarray(matrix, dtype=float)
    if x.ndim != 2 or x.shape[1] != DIMENSION or not np.isfinite(x).all():
        raise ValueError("finite 388-dimensional input required")
    z = (x - np.asarray(model["mean"])) / np.asarray(model["scale"])
    z[:, np.asarray(model["constant"], dtype=bool)] = 0.0
    scores = z @ np.asarray(model["coefficients"]).T + np.asarray(model["intercepts"])
    if not np.isfinite(scores).all():
        raise ValueError("nonfinite fitted scores")
    return scores.tolist()


def _validate_model(model):
    def vector(v, size, *, positive=False):
        return (isinstance(v, list) and len(v) == size and
                all(type(a) in (int, float) and math.isfinite(a) and (not positive or a > 0) for a in v))
    expected = {"alpha", "mean", "scale", "constant", "coefficients", "intercepts", "costs",
                "fixed_index", "training_quality", "training_task_ids"}
    if not isinstance(model, dict) or set(model) != expected:
        raise ValueError("incomplete model export")
    if type(model["alpha"]) is not int or model["alpha"] not in ALPHAS:
        raise ValueError("invalid exported alpha")
    if (not vector(model["mean"], DIMENSION) or not vector(model["scale"], DIMENSION, positive=True)
            or not isinstance(model["constant"], list) or len(model["constant"]) != DIMENSION
            or any(type(b) is not bool for b in model["constant"])
            or not isinstance(model["coefficients"], list) or len(model["coefficients"]) != 14
            or any(not vector(v, DIMENSION) for v in model["coefficients"])
            or not vector(model["intercepts"], 14)):
        raise ValueError("invalid model dimensions or numeric values")
    if any(c and (model["scale"][i] != 1 or any(row[i] != 0 for row in model["coefficients"]))
           for i, c in enumerate(model["constant"])):
        raise ValueError("constant feature must remain zero")
    costs = tuple(Decimal(c) for c in model["costs"])
    if type(model["fixed_index"]) is not int or model["fixed_index"] != choose(model["training_quality"], costs):
        raise ValueError("fixed reference differs from training means")
    ids = model["training_task_ids"]
    if not isinstance(ids, list) or not ids or any(not isinstance(t, str) or not t for t in ids) or len(set(ids)) != len(ids):
        raise ValueError("unique training identities required")


def _select_alpha(reports):
    best = max(r["quality"] for r in reports)
    eligible = [r for r in reports if r["quality"] >= best - EPSILON - TOL]
    return min(eligible, key=lambda r: (Decimal(r["cost_usd"]), -r["alpha"]))["alpha"]


def fit_semantic_selector(observations, *, encoder, folds, bindings):
    """Task-weighted five-fold model choice; always fit and return the raw candidate."""
    _hashes(bindings)
    rows = _rows(observations)
    folds = _folds(rows, folds)
    matrix, encoding = _matrix([r.task for r in rows], encoder)
    start = perf_counter_ns()
    reports = []
    for alpha in ALPHAS:
        evaluated, fold_reports = [], []
        for fold, heldout in enumerate(folds):
            train_ids = [i for i, r in enumerate(rows) if r.task.task_id not in heldout]
            valid_ids = [i for i, r in enumerate(rows) if r.task.task_id in heldout]
            model = fit_ridge([rows[i] for i in train_ids], matrix[train_ids], alpha=alpha)
            predicted = predict_scores(model, matrix[valid_ids])
            costs = tuple(Decimal(c) for c in model["costs"])
            outcomes = []
            for i, scores in zip(valid_ids, predicted):
                selected = choose_scores(scores, costs)
                r = rows[i]
                outcomes.append({"task_id": r.task.task_id, "fold": fold, "selected_index": selected,
                                 "scores": scores, "quality": r.quality[selected],
                                 "cost_usd": str(r.costs[selected]),
                                 "fixed_index": model["fixed_index"],
                                 "fixed_quality": r.quality[model["fixed_index"]],
                                 "fixed_cost_usd": str(r.costs[model["fixed_index"]])})
            evaluated.extend(outcomes)
            fold_reports.append({"fold": fold, "validation_task_ids": list(heldout), "model": model})
        reports.append({"alpha": alpha, "quality": math.fsum(r["quality"] for r in evaluated) / len(rows),
                        "cost_usd": str(sum((Decimal(r["cost_usd"]) for r in evaluated), Decimal(0)) / len(rows)),
                        "fixed_quality": math.fsum(r["fixed_quality"] for r in evaluated) / len(rows),
                        "fixed_cost_usd": str(sum((Decimal(r["fixed_cost_usd"]) for r in evaluated), Decimal(0)) / len(rows)),
                        "outcomes": sorted(evaluated, key=lambda r: r["task_id"]), "folds": fold_reports})
    alpha = _select_alpha(reports)
    chosen = next(r for r in reports if r["alpha"] == alpha)
    final_model = fit_ridge(rows, matrix, alpha=alpha)
    admitted = chosen["quality"] >= chosen["fixed_quality"] - EPSILON - TOL
    final_choices = [choose_scores(q, tuple(Decimal(c) for c in final_model["costs"]))
                     for q in predict_scores(final_model, matrix)]
    payload = {"schema": "semantic-selector/v1", "config_ids": list(CONFIG_IDS),
               "parameters": deepcopy(_PARAMETERS), "encoder": deepcopy(encoder.identity),
               "bindings": dict(bindings), "folds": folds, "chosen_alpha": alpha,
               "task_families": {r.task.task_id: r.family_id for r in rows},
               "training_selections": [CONFIG_IDS[i] for i in final_choices],
               "model": final_model, "cross_validation": reports,
               "diagnosis": {"admitted": admitted, "quality_difference": chosen["quality"] - chosen["fixed_quality"],
                             "recommended_rule": "raw_Q" if admitted else "F_star",
                             "raw_candidate_preserved": True, "constant_on_training_inputs": len(set(final_choices)) == 1,
                             "independent_effect_evidence": False},
               "timing": {"initialization_ns": getattr(encoder, "initialization_ns", None),
                          "encoding": encoding, "fit_and_cv_ns": perf_counter_ns() - start}}
    return SemanticSelector(payload, encoder=encoder)


class SemanticSelector:
    def __init__(self, payload, *, encoder):
        _identity(encoder.identity)
        self._payload = deepcopy(payload)
        self.encoder = encoder
        self.selection_timings_ns = []
        self.selection_records = []
        self._validate()

    def _validate(self):
        p = self._payload
        expected = {"schema", "config_ids", "parameters", "encoder", "bindings", "folds", "chosen_alpha",
                    "model", "cross_validation", "diagnosis", "timing", "task_families", "training_selections"}
        if set(p) != expected or p["schema"] != "semantic-selector/v1" or p["config_ids"] != list(CONFIG_IDS):
            raise ValueError("invalid semantic selector identity")
        if p["parameters"] != _PARAMETERS or p["encoder"] != self.encoder.identity:
            raise ValueError("selector and bound encoder/parameters differ")
        _hashes(p["bindings"])
        _validate_model(p["model"])
        reports = p["cross_validation"]
        if not isinstance(reports, list) or [r["alpha"] for r in reports] != list(ALPHAS):
            raise ValueError("complete alpha grid results required")
        tasks = p["model"]["training_task_ids"]
        folds = p["folds"]
        if (not isinstance(folds, list) or len(folds) != 5 or any(not isinstance(f, list) or not f for f in folds)
                or sorted(t for f in folds for t in f) != sorted(tasks)):
            raise ValueError("invalid exported fold coverage")
        mapping = p["task_families"]
        if (not isinstance(mapping, dict) or set(mapping) != set(tasks)
                or any(not isinstance(f, str) or not f for f in mapping.values())):
            raise ValueError("missing exported task-family binding")
        by_task = {t: index for index, ids in enumerate(folds) for t in ids}
        if any(len({by_task[t] for t in tasks if mapping[t] == family}) != 1
               for family in set(mapping.values())):
            raise ValueError("exported family crosses folds")
        for report in reports:
            if len(report["folds"]) != 5 or [f["fold"] for f in report["folds"]] != list(range(5)):
                raise ValueError("incomplete fold models")
            for index, f in enumerate(report["folds"]):
                _validate_model(f["model"])
                if (f["validation_task_ids"] != folds[index] or f["model"]["alpha"] != report["alpha"]
                        or set(f["model"]["training_task_ids"]) != set(tasks) - set(folds[index])):
                    raise ValueError("fold fit identities disagree")
            outcomes = report["outcomes"]
            if sorted(r["task_id"] for r in outcomes) != sorted(tasks):
                raise ValueError("missing or duplicate out-of-fold outcomes")
            for r in outcomes:
                fold = r["fold"]
                if type(fold) is not int or fold not in range(5) or r["task_id"] not in folds[fold]:
                    raise ValueError("outcome fold differs")
                model = report["folds"][fold]["model"]
                if (type(r["selected_index"]) is not int or type(r["fixed_index"]) is not int
                        or r["selected_index"] != choose_scores(r["scores"], tuple(Decimal(c) for c in model["costs"]))
                        or r["fixed_index"] != model["fixed_index"]):
                    raise ValueError("outcome selection differs")
                for key in ("quality", "fixed_quality"):
                    if type(r[key]) not in (int, float) or not math.isfinite(r[key]) or not 0 <= r[key] <= 1:
                        raise ValueError("invalid validation quality")
                for key in ("cost_usd", "fixed_cost_usd"):
                    cost = Decimal(r[key])
                    if not cost.is_finite() or cost < 0:
                        raise ValueError("invalid validation cost")
            for key in ("quality", "fixed_quality"):
                if report[key] != math.fsum(r[key] for r in outcomes) / len(tasks):
                    raise ValueError("validation quality mean differs")
            for key in ("cost_usd", "fixed_cost_usd"):
                if Decimal(report[key]) != sum((Decimal(r[key]) for r in outcomes), Decimal(0)) / len(tasks):
                    raise ValueError("validation cost mean differs")
        if p["chosen_alpha"] != _select_alpha(reports) or p["chosen_alpha"] != p["model"]["alpha"]:
            raise ValueError("selected alpha differs from preserved CV")
        chosen = next(r for r in reports if r["alpha"] == p["chosen_alpha"])
        admitted = chosen["quality"] >= chosen["fixed_quality"] - EPSILON - TOL
        diagnosis = p["diagnosis"]
        selections = p["training_selections"]
        if not isinstance(selections, list) or len(selections) != len(tasks) or any(c not in CONFIG_IDS for c in selections):
            raise ValueError("complete raw training selections required")
        if (diagnosis["admitted"] is not admitted or diagnosis["recommended_rule"] != ("raw_Q" if admitted else "F_star")
                or diagnosis["raw_candidate_preserved"] is not True or diagnosis["independent_effect_evidence"] is not False
                or type(diagnosis["constant_on_training_inputs"]) is not bool
                or diagnosis["constant_on_training_inputs"] != (len(set(selections)) == 1)
                or diagnosis["quality_difference"] != chosen["quality"] - chosen["fixed_quality"]):
            raise ValueError("diagnosis contradicts raw candidate or CV")

    def scores(self, task):
        if self.encoder.identity != self._payload["encoder"]:
            raise ValueError("encoder identity changed since selector binding")
        matrix, _ = _matrix([task], self.encoder)
        return tuple(predict_scores(self._payload["model"], matrix)[0])

    def select(self, task):
        start = perf_counter_ns()
        if self.encoder.identity != self._payload["encoder"]:
            raise ValueError("encoder identity changed since selector binding")
        matrix, encoding = _matrix([task], self.encoder)
        after_encoding = perf_counter_ns()
        scores = predict_scores(self._payload["model"], matrix)[0]
        index = choose_scores(scores, tuple(Decimal(c) for c in self._payload["model"]["costs"]))
        end = perf_counter_ns()
        self.selection_timings_ns.append(end - start)
        self.selection_records.append({"encoding": encoding, "feature_and_encoder_ns": after_encoding - start,
                                       "score_and_choice_ns": end - after_encoding, "total_ns": end - start})
        return CONFIG_IDS[index]

    def to_dict(self):
        p = deepcopy(self._payload)
        return dict(p, sha256=_hash(p))

    def save(self, path):
        with Path(path).open("x", encoding="utf-8") as stream:
            stream.write(_json(self.to_dict()) + "\n")

    @classmethod
    def from_dict(cls, value, *, encoder):
        p = deepcopy(value)
        checksum = p.pop("sha256", None)
        if checksum != _hash(p):
            raise ValueError("selector checksum differs")
        return cls(p, encoder=encoder)

    @classmethod
    def load(cls, path, *, encoder):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), encoder=encoder)


def evaluate_learning_curves(observations, *, encoder, curves, bindings):
    """Evaluate each saved subset with its own saved folds; never choose a checkpoint."""
    rows = _rows(observations)
    by_id = {r.task.task_id: r for r in rows}
    if not isinstance(curves, list) or [c["target"] for c in curves] != [100, 200, 300]:
        raise ValueError("the three prebound learning-curve descriptions required")
    exports, previous = [], set()
    for curve in curves:
        ids = curve["task_ids"]
        if (not isinstance(ids, list) or len(ids) != len(set(ids)) or curve["n"] != len(ids)
                or len(ids) < curve["target"] or not previous <= set(ids) or not set(ids) <= set(by_id)):
            raise ValueError("invalid nested learning subset")
        chosen = [by_id[t] for t in ids]
        selected_families = {r.family_id for r in chosen}
        if {r.task.task_id for r in rows if r.family_id in selected_families} != set(ids):
            raise ValueError("learning subset splits a family")
        selector = fit_semantic_selector(chosen, encoder=encoder, folds=curve["folds"], bindings=bindings)
        exports.append({"target": curve["target"], "n": curve["n"], "selector": selector.to_dict()})
        previous = set(ids)
    if previous != set(by_id):
        raise ValueError("last learning subset must contain the full development matrix")
    return {"schema": "semantic-learning-curves/v1", "checkpoint_selection": False, "curves": exports}
