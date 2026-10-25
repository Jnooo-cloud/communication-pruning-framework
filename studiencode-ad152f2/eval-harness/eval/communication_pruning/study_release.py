"""Explicit live boundary. A prepared candidate is never an author release.

The release document records an external human decision, not a cryptographic
proof of consent. This module never creates that decision or runs automatically.
"""
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

from .openrouter import Transport, load_key
from .study import FileGuard, StudyStop, file_hash, run_spatial
from .technical import DATA_PATH
from .failure_policy import F01
from .data import digest
from .spatial_plan import (ITERATION_ID, make_iteration_plan,
                           validate_iteration_contract, iteration_bindings)


Z19 = "eval-harness/eval/runs/Z19-PREPARE-001"
Z19_RECEIPT = "f81b46e8bef53626b4f0cb9c73c1ec5366b1d8aa98df25ef3d43d4beaede2bbf"


def json_file(path):
    return json.loads(Path(path).read_bytes())


def bound_metadata(root):
    root = Path(root)
    receipt_path = root / Z19 / "receipt.json"
    if file_hash(receipt_path) != Z19_RECEIPT:
        raise StudyStop("Z19 receipt changed")
    receipt = json_file(receipt_path)
    files = {str(receipt_path): Z19_RECEIPT}
    for name in ("source.zip", "source-manifest.json", "spatial-plan.json"):
        files[str(root / Z19 / name)] = receipt["evidence_sha256"][name]
    FileGuard(files)()
    old_sources = json_file(root / Z19 / "source-manifest.json")
    binding_path = root / "project/dsr/Z18-DATENBINDUNG.json"
    files[str(binding_path)] = old_sources["project/dsr/Z18-DATENBINDUNG.json"]
    FileGuard(files)()
    binding = json_file(binding_path)
    for obj in [*binding["files"].values(), binding["verification"]]:
        files[str(root / obj["path"])] = obj["sha256"]
    files[str(root / "project/DATENEXPOSITIONSREGISTER.md")] = binding["exposure_register_sha256"]
    FileGuard(files)()
    plan = json_file(root / Z19 / "spatial-plan.json")
    allocation = json_file(root / binding["files"]["allocation.json"]["path"])
    manifest = json_file(root / binding["files"]["manifest.json"]["path"])
    repeats = json_file(root / binding["files"]["spatial-repeat.json"]["path"])["task_ids"]
    bindings = {"source": receipt["source_sha256"],
                "allocation": binding["files"]["allocation.json"]["sha256"],
                "repetition": binding["files"]["spatial-repeat.json"]["sha256"]}
    return plan, manifest, allocation["panels"]["spatial"], repeats, bindings, files


def candidate(root, source_zip, source_manifest):
    root = Path(root).resolve()
    plan, _, _, _, _, files = bound_metadata(root)
    sources = json_file(source_manifest)
    required = {str(p.relative_to(root)) for folder in ("communication_pruning", "tests")
                for p in (root / "eval-harness/eval" / folder).glob("*.py")}
    if not required <= set(sources):
        raise StudyStop("source package omits code or tests")
    with ZipFile(source_zip) as archive:
        from hashlib import sha256
        for name, expected in sources.items():
            if sha256(archive.read(name)).hexdigest() != expected:
                raise StudyStop("source archive mismatch")
            files[str(root / name)] = expected
    files[str(Path(source_zip).resolve())] = file_hash(source_zip)
    files[str(Path(source_manifest).resolve())] = file_hash(source_manifest)
    FileGuard(files)()
    return {"schema": "spatial-release/v1", "status": "prepared_not_authorized",
            "author_decision": None, "backup_evidence": None,
            "plan_sha256": plan["sha256"], "phase_cap_usd": "36.12",
            "failure_policy": F01, "failure_policy_decision": "D-052",
            "execution_plan_sha256": digest({"plan_sha256": plan["sha256"], "failure_policy": F01}),
            "source_zip": str(Path(source_zip).resolve()),
            "source_manifest": str(Path(source_manifest).resolve()),
            "files": files}


def run_live(root, release_path, folder, *, resume_from=None, stop_after_slots=None):
    """Explicitly invoked only after external release; fixed plan and claim root."""
    root, release_path = Path(root).resolve(), Path(release_path).resolve()
    release = json_file(release_path)
    if (release.get("status") != "authorized_by_author"
            or not isinstance(release.get("author_decision"), str) or not release["author_decision"].strip()
            or not isinstance(release.get("backup_evidence"), dict)):
        raise StudyStop("external author decision and backup evidence required before input or key loading")
    # Compare every execution field with the prepared, current source package.
    expected = candidate(root, release["source_zip"], release["source_manifest"])
    expected.update(status=release["status"], author_decision=release["author_decision"],
                    backup_evidence=release["backup_evidence"])
    if release != expected:
        raise StudyStop("release differs from execution candidate")
    backup = release["backup_evidence"]
    external = (set(backup) == {"path", "sha256", "external_location_description"}
                and isinstance(backup["external_location_description"], str)
                and bool(backup["external_location_description"].strip()))
    local = (set(backup) == {"path", "sha256", "location_kind", "location_description", "author_decision"}
             and backup["location_kind"] == "local"
             and isinstance(backup["location_description"], str)
             and bool(backup["location_description"].strip())
             and backup["author_decision"] == release["author_decision"])
    if not (external or local):
        raise StudyStop("explicit external backup or author-bound local backup evidence required")
    FileGuard({backup["path"]: backup["sha256"]})()
    plan, manifest, tasks, repeats, bindings, _ = bound_metadata(root)
    files = {**release["files"], str(release_path): file_hash(release_path),
             backup["path"]: backup["sha256"]}
    guard = FileGuard(files)
    guard()
    # No client construction or credential reading on an unapproved path.
    client = None
    def transport(endpoint, body=None):
        nonlocal client
        if client is None:
            client = Transport(load_key(root / ".env", source="file"))
        return client(endpoint, body)
    return run_spatial(plan, manifest, tasks, repeats, bindings=bindings,
                       source_path=root / DATA_PATH / "musique_ans_v1.0_train.jsonl",
                       folder=folder, control=root / "eval-harness/eval/study-control/spatial",
                       transport=transport, guard=guard, synthetic=False, resume_from=resume_from,
                       failure_policy=release.get("failure_policy"), slot_limit=stop_after_slots,
                       checkpoint=stop_after_slots is not None)


def _evidence_path(root, entry, files):
    """Resolve retained project files without permitting outside-root aliases."""
    from .spatial_plan import _sha
    if (not isinstance(entry, dict) or set(entry) != {"path", "sha256"}
            or not isinstance(entry["path"], str) or not _sha(entry["sha256"])):
        raise StudyStop("invalid retained evidence reference")
    relative = Path(entry["path"])
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise StudyStop("evidence must remain inside the project")
    name = str(path)
    if name in files and files[name] != entry["sha256"]:
        raise StudyStop("conflicting evidence identities")
    files[name] = entry["sha256"]
    return path


def _iteration_metadata(root, contract_path):
    """Read retained metadata and source archives only; never task JSONL/keys."""
    from .openrouter import MODEL, PROVIDER, validate_endpoint
    root = Path(root).resolve()
    contract_path = Path(contract_path).resolve()
    if not contract_path.is_relative_to(root):
        raise StudyStop("iteration contract must be retained inside the project")
    contract = validate_iteration_contract(json_file(contract_path))
    files = {str(contract_path): file_hash(contract_path)}
    paths = {role: _evidence_path(root, entry, files)
             for role, entry in contract["evidence"].items()}
    FileGuard(files)()
    manifest, allocation = json_file(paths["manifest"]), json_file(paths["allocation"])
    tasks = allocation["panels"]["spatial"]
    repeats = json_file(paths["repetition"])["task_ids"]
    legacy_plan = json_file(paths["ordering"])
    data_binding = json_file(paths["data_binding"])
    for role, name in (("manifest", "manifest.json"), ("allocation", "allocation.json"),
                       ("repetition", "spatial-repeat.json")):
        old = data_binding["files"][name]
        if (old["path"] != contract["evidence"][role]["path"]
                or old["sha256"] != contract["evidence"][role]["sha256"]):
            raise StudyStop("iteration panel differs from retained data allocation")
    plan = make_iteration_plan(manifest, tasks, repeats, contract=contract, legacy_plan=legacy_plan)

    sources = json_file(paths["source_manifest"])
    if not isinstance(sources, dict):
        raise StudyStop("source manifest must map retained paths to hashes")
    required = {str(p.relative_to(root)) for folder in ("communication_pruning", "tests")
                for p in (root / "eval-harness/eval" / folder).glob("*.py")}
    needed = {"eval-harness/eval/communication_pruning/" + name for name in (
        "semantic_selection.py", "spatial_plan.py", "study.py", "study_resume.py", "study_release.py")}
    if not required or not (required | needed) <= set(sources):
        raise StudyStop("iteration source package omits current code or tests")
    with ZipFile(paths["source"]) as archive:
        for name, expected in sources.items():
            _evidence_path(root, {"path": name, "sha256": expected}, files)
            if sha256(archive.read(name)).hexdigest() != expected:
                raise StudyStop("iteration source archive mismatch")

    prompt = json_file(paths["prompt"])
    prompt_required = {"eval-harness/eval/communication_pruning/" + name for name in (
        "openrouter.py", "execution.py", "configurations.py", "contracts.py")}
    if (prompt.get("schema") != "spatial-prompt/v1" or prompt.get("correction") != "Z30"
            or prompt.get("administrative_message_ids_in_model_input") is not False
            or not isinstance(prompt.get("files"), dict)
            or not prompt_required <= set(prompt["files"])):
        raise StudyStop("new Z30 prompt evidence required")
    if any(sources.get(name) != expected for name, expected in prompt["files"].items()):
        raise StudyStop("prompt evidence differs from current source package")

    endpoint = validate_endpoint(paths["provider_catalog"].read_bytes())
    tariff = json_file(paths["tariff"])
    if (tariff.get("schema") != "spatial-tariff/v1" or tariff.get("model") != MODEL
            or tariff.get("provider") != PROVIDER or tariff.get("currency") != "USD"
            or tariff.get("catalog_sha256") != contract["evidence"]["provider_catalog"]["sha256"]
            or tariff.get("pricing") != endpoint["pricing"]):
        raise StudyStop("tariff evidence differs from bound endpoint")
    try:
        retrieved = datetime.fromisoformat(tariff["retrieved_utc"].replace("Z", "+00:00"))
        if retrieved.utcoffset() is None or retrieved.utcoffset().total_seconds() != 0:
            raise ValueError("not UTC")
    except (KeyError, TypeError, AttributeError, ValueError):
        raise StudyStop("explicit UTC catalog retrieval time required") from None

    exposure = json_file(paths["exposure"])
    if (exposure.get("schema") != "spatial-exposure-clearance/v1"
            or exposure.get("iteration_id") != ITERATION_ID or exposure.get("stage") != "pre_execution"
            or exposure.get("task_ids") != tasks or exposure.get("repeat_ids") != repeats
            or exposure.get("allowed_fields") != ["question", "paragraphs"]
            or exposure.get("references") != "scoring_only" or exposure.get("no_other_panels") is not True
            or not isinstance(exposure.get("prior_exposure"), list) or not exposure["prior_exposure"]):
        raise StudyStop("current exposure clearance must name exactly the selected panel")
    for entry in [exposure.get("register"), *exposure["prior_exposure"]]:
        _evidence_path(root, entry, files)
    FileGuard(files)()
    return contract, plan, manifest, tasks, repeats, iteration_bindings(contract), files


def iteration_candidate(root, contract_path):
    """Prepare Z38 from explicit current evidence, without granting a release."""
    contract, plan, _, _, _, _, files = _iteration_metadata(root, contract_path)
    return {"schema": "spatial-release/v2", "status": "prepared_not_authorized",
            "author_decision": None, "backup_evidence": None,
            "iteration_id": ITERATION_ID, "iteration_contract_sha256": contract["sha256"],
            "plan_sha256": plan["sha256"], "phase_cap_usd": contract["phase_cap_usd"],
            "failure_policy": contract["failure_policy"], "failure_policy_decision": "D-052",
            "retry_policy": contract["retry_policy"],
            "execution_plan_sha256": digest({"plan_sha256": plan["sha256"], "failure_policy": F01}),
            "contract_path": str(Path(contract_path).resolve()), "files": files}


def run_iteration_live(root, contract_path, release_path, folder, *, resume_from=None, stop_after_slots=None):
    """Explicit new release only. Historical Z26 approvals do not enter here."""
    root, release_path = Path(root).resolve(), Path(release_path).resolve()
    release = json_file(release_path)
    if (release.get("schema") != "spatial-release/v2" or release.get("iteration_id") != ITERATION_ID
            or release.get("status") != "authorized_by_author"
            or not isinstance(release.get("author_decision"), str) or not release["author_decision"].strip()
            or not isinstance(release.get("backup_evidence"), dict)):
        raise StudyStop("new explicit iteration release required before inputs, keys or client")
    expected = iteration_candidate(root, contract_path)
    expected.update(status=release["status"], author_decision=release["author_decision"],
                    backup_evidence=release["backup_evidence"])
    if release != expected:
        raise StudyStop("iteration release differs from current bound candidate")
    backup = release["backup_evidence"]
    external = (set(backup) == {"path", "sha256", "external_location_description"}
                and isinstance(backup["external_location_description"], str)
                and bool(backup["external_location_description"].strip()))
    local = (set(backup) == {"path", "sha256", "location_kind", "location_description", "author_decision"}
             and backup["location_kind"] == "local"
             and isinstance(backup["location_description"], str) and bool(backup["location_description"].strip())
             and backup["author_decision"] == release["author_decision"])
    if not (external or local):
        raise StudyStop("current external or explicitly author-bound local backup required")
    FileGuard({backup["path"]: backup["sha256"]})()
    contract, plan, manifest, tasks, repeats, bindings, files = _iteration_metadata(root, contract_path)
    files.update({str(release_path): file_hash(release_path), backup["path"]: backup["sha256"]})
    guard = FileGuard(files)
    guard()
    client = None
    def transport(endpoint, body=None):
        nonlocal client
        if client is None:
            client = Transport(load_key(root / ".env", source="file"))
        return client(endpoint, body)
    return run_spatial(plan, manifest, tasks, repeats, bindings=bindings,
        source_path=root / DATA_PATH / "musique_ans_v1.0_train.jsonl", folder=folder,
        control=root / "eval-harness/eval/study-control/spatial", transport=transport,
        guard=guard, synthetic=False, resume_from=resume_from, failure_policy=F01,
        slot_limit=stop_after_slots, checkpoint=stop_after_slots is not None,
        iteration_contract=contract)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Explicit released spatial execution; no automatic release or resume")
    parser.add_argument("--root", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--resume-from", help="Token from offline complete-prefix inspection")
    parser.add_argument("--stop-after-slots", type=int, help="Explicit complete-prefix checkpoint in the original plan")
    args = parser.parse_args()
    print(json.dumps(run_live(args.root, args.release, args.output, resume_from=args.resume_from,
                              stop_after_slots=args.stop_after_slots)))
