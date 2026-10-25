"""Typed evidence records and conservative transitive information permissions.

These records document assertions, not proof of their truth or author identity.
Code never infers human permission from free-form text or a review verdict.
"""
import hashlib
import copy
import json
import os
import re
from pathlib import Path, PurePosixPath


class ControlError(ValueError):
    pass


KINDS = {"source", "work_order", "finding", "claim", "change_request",
         "decision_reference", "review", "manuscript", "coverage"}
COUNTER = {"not_reviewed", "partial", "found", "not_found_in_scope", "blocked", "not_applicable"}
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ControlError("invalid_json") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ControlError("invalid_identifier")
    return value


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ControlError("invalid_path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise ControlError("invalid_path")
    return value


def safe_path(root, value):
    root = Path(root).absolute()
    relative(value)
    if root.is_symlink():
        raise ControlError("symlink_root")
    for p in (root, *root.parents):
        if p.is_symlink():
            raise ControlError("symlink_parent")
    p = root
    for part in value.split("/"):
        p = p / part
        if p.is_symlink():
            raise ControlError("symlink_path")
    return p


def strings(value, empty=False):
    if not isinstance(value, list) or (not empty and not value):
        raise ControlError("invalid_string_list")
    if any(not isinstance(x, str) or not x for x in value) or len(set(value)) != len(value):
        raise ControlError("invalid_string_list")
    return value


def validate_record(record):
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise ControlError("record_schema")
    identifier(record.get("id"))
    if record.get("kind") not in KINDS:
        raise ControlError("record_kind")
    if type(record.get("version")) is not int or record["version"] < 1:
        raise ControlError("record_version")
    strings(record.get("inputs"), empty=True)
    if any(not isinstance(x, str) or not x for x in record.get("inputs", [])):
        raise ControlError("invalid_inputs")
    rights = record.get("rights")
    if not isinstance(rights, dict):
        raise ControlError("missing_rights")
    for key in ("recipients", "purposes"):
        strings(rights.get(key))
    if not isinstance(rights.get("basis"), str) or not rights["basis"].strip():
        raise ControlError("missing_rights_basis")
    strings(rights.get("exposures"), empty=True)
    if not isinstance(record.get("body"), dict):
        raise ControlError("record_body")
    if not isinstance(record.get("limitations"), list):
        raise ControlError("record_limits")
    strings(record["limitations"], empty=True)
    if record["kind"] in {"finding", "claim"}:
        counter = record["body"].get("counterevidence", {})
        if counter.get("status") not in COUNTER:
            raise ControlError("counterevidence_status_required")
        if counter["status"] == "not_found_in_scope":
            if counter.get("coverage_ref") not in record["inputs"] or not valid_hash(counter.get("coverage_sha256")):
                raise ControlError("negative_claim_requires_coverage")
    if record["kind"] == "coverage":
        if any(not isinstance(record["body"].get(field), str) or not record["body"][field].strip()
               for field in ("scope", "method", "searched_at")):
            raise ControlError("coverage_scope_required")
    if record["kind"] == "review":
        body = record["body"]
        if not body.get("subjects") or not isinstance(body.get("subjects"), dict):
            raise ControlError("review_subject_hashes_required")
        if body.get("outcome") not in {"passed", "failed", "partial", "not_reviewed"}:
            raise ControlError("review_outcome")
        if not body.get("criteria") or not body.get("reviewer"):
            raise ControlError("review_scope_required")
        if not set(body["subjects"]) <= set(record["inputs"]) or any(not valid_hash(h) for h in body["subjects"].values()):
            raise ControlError("review_subject_binding_required")
    if record["kind"] == "decision_reference":
        body = record["body"]
        if body.get("status") not in {"unresolved", "documented_accepted", "documented_rejected", "superseded"}:
            raise ControlError("decision_status")
        if body["status"] != "unresolved" and not body.get("original_ref"):
            raise ControlError("decision_original_required")
    if "workflow" in record["body"]:
        from .workflow import validate_workflow_record
        validate_workflow_record(record)
    canonical(record)
    return record


def key(record):
    return f"{record['id']}@{record['version']}"


def valid_hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class EvidenceGraph:
    def __init__(self, records):
        self._records = {}
        for record in records:
            record = copy.deepcopy(record)
            validate_record(record)
            k = key(record)
            if k in self._records:
                raise ControlError("duplicate_record_version")
            self._records[k] = record

    @property
    def records(self):
        return copy.deepcopy(self._records)

    def accessible(self, record_key, recipient, purpose, exposures=()):
        """Unknown links/cycles/rights deny without revealing excluded record text."""
        def visit(k, trail):
            if k in trail or k not in self._records:
                return False
            record = self._records[k]
            counter = record["body"].get("counterevidence", {})
            if counter.get("status") == "not_found_in_scope":
                coverage = self._records.get(counter["coverage_ref"])
                if not coverage or coverage["kind"] != "coverage" or digest(coverage) != counter["coverage_sha256"]:
                    return False
            rights = record["rights"]
            if recipient not in rights["recipients"] or purpose not in rights["purposes"]:
                return False
            if not set(rights["exposures"]) <= set(exposures):
                return False
            return all(visit(i, trail | {k}) for i in record["inputs"])
        return visit(record_key, set())

    def context(self, requested, recipient, purpose, exposures=()):
        # Denial never returns excluded keys, titles, counts, or upstream explanations.
        if any(not self.accessible(k, recipient, purpose, exposures) for k in requested):
            raise ControlError("context_not_authorized_or_incomplete")
        result = {}
        def visit(k):
            if k in result:
                return
            result[k] = self._records[k]
            for parent in self._records[k]["inputs"]:
                visit(parent)
        for k in requested:
            visit(k)
        return copy.deepcopy([result[k] for k in sorted(result)])

    def review_status(self, review_key):
        review = self._records[review_key]
        if review["kind"] != "review":
            raise ControlError("not_review")
        if "workflow" in review["body"]:
            from .workflow import review_status
            return review_status(self, review_key)
        subjects = review["body"]["subjects"]
        if any(k not in self._records or digest(self._records[k]) != h for k, h in subjects.items()):
            return "version_mismatch"
        return review["body"]["outcome"]

    def impact(self, changed):
        affected = set(changed)
        while True:
            found = {k for k, r in self._records.items() if set(r["inputs"]) & affected}
            if found <= affected:
                break
            affected |= found
        unknown = []
        for k, r in self._records.items():
            if r["kind"] == "manuscript":
                coverage = r["body"].get("binding_coverage", {})
                text = r["body"].get("text")
                h = r["body"].get("content_sha256")
                spans = coverage.get("spans", [])
                cursor = 0
                bound = isinstance(spans, list) and bool(spans)
                for span in spans if bound else []:
                    if (not isinstance(span, dict) or type(span.get("start")) is not int or
                        type(span.get("end")) is not int or span["start"] != cursor or span["end"] <= cursor or
                        not isinstance(span.get("inputs"), list) or not set(span["inputs"]) <= set(r["inputs"]) or
                        any(i not in self._records for i in span["inputs"])):
                        bound = False
                        break
                    cursor = span["end"]
                if (coverage.get("status") != "complete" or not valid_hash(h) or
                    not isinstance(text, str) or sha(text.encode()) != h or coverage.get("content_sha256") != h or
                    not bound or cursor != len(text)):
                    unknown.append(k)
        return {"known_affected": sorted(affected & self._records.keys()),
                "impact_unknown": sorted(unknown), "scope": "registered_dependencies_only"}


def write_immutable(path, data):
    """No overwrite; partial writes are retained and cannot be treated as success."""
    path = Path(path)
    safe_path(path.parent, path.name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
