"""Z50's narrow, offline study gate. An unsigned candidate never grants rights.

Only metadata is read here. Model/input loaders are injected by the caller after
this gate. Hashes and local receipts detect changed evidence; they are not a
cryptographic authentication of the human author or an account-wide spend lock.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import importlib.metadata
import inspect
import math
import platform
import sys

from communication_pruning.failure_policy import strict_json
from communication_pruning.openrouter import validate_endpoint
from communication_pruning.study import FileGuard, file_hash
from .final_plan import ARMS, canonical_hash, validate_plan

NAMESPACE = "final-study-v1"
PROTECTED = {"planning-reserve": "20.00", "old-reserve-028": "0.28", "old-reserve-014": "0.14"}
MAX_CALLS = {"P": 14, "R": 36, "T": 14, "F": 24}
DIRECT_INSTRUCTION = "Answer the question using only the supplied paragraphs. Return only the short answer, without explanation."
DOCUMENTS = ("design", "analysis_contract", "source_manifest", "frame_metadata",
             "exposure_metadata", "spatial_q", "spatial_f", "temporal_qst", "temporal_qtf")
DEPENDENCIES = ("loader", "spatial_selector", "temporal_selector", "transport", "checkpoint")
CORE_FILES = ("contracts.py", "configurations.py", "data.py", "evaluation.py", "execution.py",
              "failure_policy.py", "journal.py", "audit.py", "phase_budget.py", "study.py", "openrouter.py",
              "selection.py", "spatial_plan.py", "semantic_selection.py")


class StudyStop(RuntimeError):
    pass


def seal(value):
    result = deepcopy(value)
    result.pop("sha256", None)
    result["sha256"] = canonical_hash(result)
    return result


def _check_seal(value):
    if not isinstance(value, dict) or value.get("sha256") != canonical_hash({k: v for k, v in value.items() if k != "sha256"}):
        raise StudyStop("changed study candidate")


def money(value):
    try:
        result = Decimal(value) if isinstance(value, str) else Decimal("NaN")
    except InvalidOperation:
        raise StudyStop("explicit decimal amount required") from None
    if not result.is_finite() or result < 0:
        raise StudyStop("finite nonnegative decimal string required")
    return result


def runtime_identity():
    """No model/package imports or network; distribution metadata only."""
    versions = {}
    for name in ("numpy", "scikit-learn", "torch", "transformers"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"python": sys.version, "implementation": platform.python_implementation(),
            "platform": platform.platform(), "packages": versions}


def dependency_identity(callback):
    target = callback if inspect.isfunction(callback) or inspect.ismethod(callback) else type(callback)
    path = inspect.getsourcefile(target)
    if not callable(callback) or path is None:
        raise StudyStop("explicit Python dependency with recoverable source required")
    return {"module": target.__module__, "qualname": target.__qualname__,
            "path": str(Path(path).resolve()), "sha256": file_hash(path)}


def prepare_candidate(plan, *, source_files):
    """Create a metadata proposal; all live gates intentionally remain absent."""
    validate_plan(plan)
    return seal({"schema": "z50-execution/v1", "namespace": NAMESPACE,
                 "mode": "not_authorized", "test_authorized": False,
                 "plan_hash": plan["plan_hash"], "bindings": deepcopy(plan["bindings"]),
                 "source_files": dict(source_files), "documents": {}, "source_backup": None, "plan_evidence": None,
                 "provider_evidence": None, "runtime_manifest": None, "budget_evidence": None,
                 "provider_observation": None,
                 "dependency_bindings": {}, "control_directory": None,
                 "calendar": None, "section_ends": [], "author_release": None,
                 "fixed_config_id": None, "fixed_rounds": None,
                 "direct_prompt": DIRECT_INSTRUCTION,
                 "budget": {"overall_cap_usd": "120.00", "main_cap_usd": "40.00",
                            "secondary_cap_usd": "55.88", "per_call_reserve_usd": "0.14",
                            "positions_excluding_study": None, "unresolved": True}})


def execution_binding(candidate):
    """Stable across a later explicit phase release and additive backup receipt."""
    return canonical_hash({k: v for k, v in candidate.items()
                           if k not in ("sha256", "source_backup", "author_release")})


def read_json(path):
    return strict_json(Path(path).read_bytes())


def evidence_file(value):
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not Path(value["path"]).is_absolute()):
        raise StudyStop("absolute evidence path and exact hash required")
    FileGuard({value["path"]: value["sha256"]})()
    return value["path"]


def verify_archive(evidence, expected):
    if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256", "members"}
            or evidence["members"] != expected or file_hash(evidence["path"]) != evidence["sha256"]):
        raise StudyStop("archive binding changed or missing")
    with ZipFile(evidence["path"]) as archive:
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected):
            raise StudyStop("archive member set differs")
        for name, checksum in expected.items():
            if sha256(archive.read(name)).hexdigest() != checksum:
                raise StudyStop("archive failed complete reread")


def budget_view(candidate, known, *, panel=None, reserve_calls=0):
    """Known study money is added once; old positions contain remaining commitments."""
    b = candidate["budget"]
    if (b.get("overall_cap_usd") != "120.00" or b.get("main_cap_usd") != "40.00"
            or b.get("secondary_cap_usd") != "55.88" or b.get("per_call_reserve_usd") != "0.14"
            or b.get("unresolved") is not False):
        raise StudyStop("changed caps or unresolved shared accounting")
    if set(known) != set(ARMS) or any(not isinstance(v, Decimal) or not v.is_finite() or v < 0 for v in known.values()):
        raise StudyStop("complete known panel accounting required")
    if type(reserve_calls) is not int or reserve_calls < 0 or (reserve_calls and panel not in ARMS):
        raise StudyStop("invalid complete block reservation")
    positions = b["positions_excluding_study"]
    if not isinstance(positions, list):
        raise StudyStop("actual shared budget positions missing")
    ids, protected = set(), {}
    other = {"overall": Decimal(0), "main": Decimal(0), "secondary": Decimal(0)}
    for p in positions:
        if (set(p) != {"id", "bucket", "known_usd", "remaining_commitment_usd", "protected"}
                or not isinstance(p["id"], str) or not p["id"] or p["id"] in ids or p["id"] == NAMESPACE
                or p["bucket"] not in ("overall_only", "main", "secondary") or type(p["protected"]) is not bool):
            raise StudyStop("nonoverlapping external budget positions required")
        ids.add(p["id"])
        amount = money(p["known_usd"]) + money(p["remaining_commitment_usd"])
        other["overall"] += amount
        if p["bucket"] != "overall_only":
            other[p["bucket"]] += amount
        if p["protected"]:
            protected[p["id"]] = p
    if set(protected) != set(PROTECTED):
        raise StudyStop("all protected reserves must remain explicit")
    for key, amount in PROTECTED.items():
        p = protected[key]
        if p["bucket"] != "overall_only" or money(p["known_usd"]) != 0 or money(p["remaining_commitment_usd"]) != Decimal(amount):
            raise StudyStop("protected reserve cannot be spent or moved")
    available = {"overall": Decimal("120.00") - other["overall"] - sum(known.values()),
                 "main": Decimal("40.00") - other["main"] - known["P"],
                 "secondary": Decimal("55.88") - other["secondary"] - sum(known[p] for p in ("R", "T", "F"))}
    if any(v < 0 for v in available.values()):
        raise StudyStop("shared budget exhausted")
    reserve = reserve_calls * Decimal("0.14")
    if reserve and min(available["overall"], available["main" if panel == "P" else "secondary"]) < reserve:
        raise StudyStop("complete maximum block has insufficient headroom")
    return {"known_by_panel_usd": {p: str(v) for p, v in known.items()},
            "available_usd": {k: str(v) for k, v in available.items()},
            "block_reservation_usd": str(reserve), "reservation_is_expense": False}


def required_source_paths():
    root = Path(__file__).resolve().parent.parent
    return {str(root / "communication_pruning" / name) for name in CORE_FILES} | {
        str(root / "study_preparation" / name) for name in
        ("final_plan.py", "final_analysis.py", "final_preflight.py", "final_execution.py",
         "final_operator.py", "final_resources.py", "intervals.py", "temporal.py")}


def source_members(candidate):
    files = dict(candidate["source_files"])
    for value in candidate["documents"].values():
        files[value["path"]] = value["sha256"]
    for key in ("provider_evidence", "runtime_manifest", "budget_evidence", "plan_evidence"):
        value = candidate[key]
        files[value["path"]] = value["sha256"]
    if candidate["author_release"] is not None:
        value = candidate["author_release"]
        files[value["path"]] = value["sha256"]
    return {f"source-{i:04d}": h for i, (_, h) in enumerate(sorted(files.items()))}


def _release(candidate, panel):
    if candidate["mode"] == "artificial_only":
        return
    release = read_json(evidence_file(candidate["author_release"]))
    if (release.get("author") != "Jannik" or release.get("explicit_authorization") is not True
            or release.get("study_frozen") is not True or release.get("send_enabled") is not True
            or not isinstance(release.get("approval_reference"), str) or not release["approval_reference"].strip()
            or release.get("execution_binding_sha256") != execution_binding(candidate)
            or not isinstance(release.get("panels"), list) or not release["panels"]
            or len(set(release["panels"])) != len(release["panels"])
            or not set(release["panels"]) <= set(ARMS) or panel is not None and panel not in release["panels"]):
        raise StudyStop("specific author release and freeze do not bind this panel")


def runtime_guard(candidate, *, clock, panel=None):
    _check_seal(candidate)
    _release(candidate, panel)
    cal = candidate["calendar"]
    now = clock()
    if type(now) not in (int, float) or not math.isfinite(now) or not cal["start_epoch"] <= now <= cal["end_epoch"]:
        raise StudyStop("outside the unchanged calendar binding")
    FileGuard(candidate["source_files"])()
    for value in candidate["documents"].values():
        evidence_file(value)
    for key in ("provider_evidence", "runtime_manifest", "budget_evidence", "plan_evidence"):
        evidence_file(candidate[key])


def preflight(candidate, plan, *, control, clock, dependencies=None):
    """Complete gate before any content loader/selector/transport is invoked."""
    validate_plan(plan)
    _check_seal(candidate)
    artificial = candidate.get("mode") == "artificial_only"
    if (candidate.get("schema") != "z50-execution/v1" or candidate.get("namespace") != NAMESPACE
            or candidate.get("plan_hash") != plan["plan_hash"] or candidate.get("bindings") != plan["bindings"]
            or candidate.get("direct_prompt") != DIRECT_INSTRUCTION
            or candidate.get("control_directory") != str(Path(control).resolve())):
        raise StudyStop("study, prompt, metadata or control binding differs")
    if artificial:
        if (candidate.get("test_authorized") is not True or plan["mode"] != "artificial_only"
                or candidate.get("author_release") is not None
                or any(not r["task_id"].startswith("synthetic-") for r in plan["frame"])):
            raise StudyStop("artificial-only explicit test binding required")
    elif candidate.get("mode") != "authorized_execution" or candidate.get("test_authorized") is not False or plan["mode"] != "live_candidate":
        raise StudyStop("no specific execution authorization")
    files = candidate["source_files"]
    if not isinstance(files, dict) or not required_source_paths() <= set(files) or any(not Path(p).is_absolute() for p in files):
        raise StudyStop("complete recoverable execution/analysis source binding required")
    documents = candidate["documents"]
    if not isinstance(documents, dict) or set(documents) != set(DOCUMENTS):
        raise StudyStop("all rule/design/frame/exposure documents required")
    for key, value in documents.items():
        evidence_file(value)
        if not artificial or key in plan["bindings"]:
            if plan["bindings"].get(key) != value["sha256"]:
                raise StudyStop("external plan/document hash differs")
    if read_json(documents["source_manifest"]["path"]) != {"files": files}:
        raise StudyStop("source manifest does not bind exactly these files")
    if read_json(evidence_file(candidate["plan_evidence"])) != plan:
        raise StudyStop("recoverable saved plan differs")
    if read_json(documents["frame_metadata"]["path"]) != plan["frame"]:
        raise StudyStop("metadata frame differs from the drawn frame")
    exposures = read_json(documents["exposure_metadata"]["path"])
    if (exposures.get("schema") != "z50-exposure-metadata/v1"
            or not isinstance(exposures.get("all_documented_exposed_task_ids"), list)
            or not isinstance(exposures.get("all_documented_exposed_family_ids"), list)
            or exposures.get("holdout_task_overlap") != [] or exposures.get("holdout_family_overlap") != []
            or set(exposures["all_documented_exposed_task_ids"]) & {r["task_id"] for r in plan["frame"]}
            or set(exposures["all_documented_exposed_family_ids"]) & {r["family_id"] for r in plan["frame"]}):
        raise StudyStop("current exposure review does not clear this exact frame")
    inputs = exposures.get("input_sha256")
    if not isinstance(inputs, dict) or not artificial and not inputs:
        raise StudyStop("exposure original bindings missing")
    project = Path(__file__).resolve().parents[3]
    for name, checksum in inputs.items():
        path = str((project / name).resolve())
        if files.get(path) != checksum:
            raise StudyStop("exposure original missing from source/archive binding")
    runtime = read_json(evidence_file(candidate["runtime_manifest"]))
    if runtime != runtime_identity():
        raise StudyStop("runtime differs from frozen manifest")
    validate_endpoint(Path(evidence_file(candidate["provider_evidence"])).read_bytes())
    if candidate["fixed_config_id"] not in {f"C{i:02}" for i in range(1, 15)} or type(candidate["fixed_rounds"]) is not int or candidate["fixed_rounds"] not in (1, 2):
        raise StudyStop("bound fixed spatial/time rules required")
    for key, expected in (("spatial_f", {"config_id": candidate["fixed_config_id"]}),
                          ("temporal_qtf", {"rounds": candidate["fixed_rounds"]})):
        rule = read_json(documents[key]["path"])
        if not all(rule.get(k) == v for k, v in expected.items()):
            raise StudyStop("fixed rule differs from retained rule artifact")
    if not artificial:
        fixed_time = read_json(documents["temporal_qtf"]["path"])
        if (fixed_time.get("raw_q_sha256") != documents["spatial_q"]["sha256"]
                or fixed_time.get("temporal_selector_sha256") != documents["temporal_qst"]["sha256"]):
            raise StudyStop("fixed temporal rule does not bind these exact Q rules")
    cal = candidate["calendar"]
    if (not isinstance(cal, dict) or set(cal) != {"start_epoch", "end_epoch", "maximum_duration_seconds", "origin"}
            or cal["origin"] != ("artificial_clock" if artificial else "author_bound")
            or any(type(cal[k]) not in (int, float) or not math.isfinite(cal[k]) for k in ("start_epoch", "end_epoch", "maximum_duration_seconds"))
            or not 0 < cal["end_epoch"] - cal["start_epoch"] <= cal["maximum_duration_seconds"]):
        raise StudyStop("absolute finite operating interval required")
    observed = candidate["provider_observation"]
    if (not isinstance(observed, dict) or set(observed) != {"origin", "observed_epoch"}
            or observed["origin"] != ("artificial_fixture" if artificial else "current_preflight")
            or type(observed["observed_epoch"]) not in (int, float) or not math.isfinite(observed["observed_epoch"])
            or not cal["start_epoch"] <= observed["observed_epoch"] <= clock() <= cal["end_epoch"]):
        raise StudyStop("current provider/tariff metadata observation missing")
    total = sum(plan["counts"].values())
    ends = candidate["section_ends"]
    if not isinstance(ends, list) or not ends or any(type(v) is not int or not 0 < v <= total for v in ends) or ends != sorted(set(ends)) or ends[-1] != total:
        raise StudyStop("complete prebound section limits required")
    budget = read_json(evidence_file(candidate["budget_evidence"]))
    if budget != {"complete_nonoverlapping": True, "budget": candidate["budget"],
                  "origin": "artificial_fixture" if artificial else "current_preflight"}:
        raise StudyStop("shared budget differs from bound cost evidence")
    budget_view(candidate, {p: Decimal(0) for p in ARMS})
    if dependencies is not None:
        if set(dependencies) != set(DEPENDENCIES) or set(candidate["dependency_bindings"]) != set(DEPENDENCIES):
            raise StudyStop("all explicit dependency bindings required")
        for key, callback in dependencies.items():
            identity = dependency_identity(callback)
            if candidate["dependency_bindings"][key] != identity or files.get(identity["path"]) != identity["sha256"]:
                raise StudyStop("injected dependency differs from bound source")
        if not artificial:
            # Live Q rules must use the already implemented frozen selectors.
            from communication_pruning.semantic_selection import SemanticSelector
            from .temporal import TemporalSelector
            for key, cls, doc in (("spatial_selector", SemanticSelector, "spatial_q"),
                                 ("temporal_selector", TemporalSelector, "temporal_qst")):
                method = dependencies[key]
                obj = getattr(method, "__self__", None)
                if type(obj) is not cls or method.__func__ is not cls.select or obj.to_dict() != read_json(documents[doc]["path"]):
                    raise StudyStop("live Q must be the unchanged frozen selector")
    runtime_guard(candidate, clock=clock)
    verify_archive(candidate["source_backup"], source_members(candidate))
    return {"mode": candidate["mode"], "execution_binding_sha256": execution_binding(candidate),
            "live_evidence": not artificial, "study_frozen": not artificial}
