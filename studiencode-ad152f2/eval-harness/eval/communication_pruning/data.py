"""Metadata-only family manifests and phase-checked, label-separated loading.

Not a security sandbox: callers retain their operating-system file permissions.
"""

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
import re

from .contracts import TaskInput


TRAIN_PHASES = {"technical", "spatial", "temporal", "pilot", "analysis"}
PHASES = TRAIN_PHASES | {"holdout", "unused", "excluded"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return sha256(canonical(value)).hexdigest()


@dataclass(frozen=True)
class TaskMeta:
    task_id: str
    split: str
    hop: int
    subquestions: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.task_id, str) or not self.task_id or self.split not in {"train", "dev"}:
            raise ValueError("invalid task identity or source split")
        if type(self.hop) is not int or self.hop not in (2, 3, 4):
            raise ValueError("invalid hop metadata")
        if (not isinstance(self.subquestions, tuple) or not self.subquestions
                or any(not isinstance(s, str) or not s for s in self.subquestions)
                or len(set(self.subquestions)) != len(self.subquestions)):
            raise ValueError("nonempty unique subquestion IDs required")


def structure(record, split):
    """Extract only structural fields; never print raw content in errors."""
    try:
        task_id = record["id"]
        match = re.fullmatch(r"([234])hop\d*__[0-9_]+", task_id)
        if match is None:
            raise ValueError("unsupported MuSiQue task ID")
        parts = record["question_decomposition"]
        if not isinstance(parts, list) or any(type(p["id"]) not in (str, int) for p in parts):
            raise ValueError("invalid decomposition IDs")
        return TaskMeta(task_id, split, int(match[1]), tuple(str(p["id"]) for p in parts))
    except (KeyError, TypeError) as error:
        raise ValueError("malformed structural record") from error


def index_file(path, split, expected_sha256):
    data = Path(path).read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise ValueError("dataset hash mismatch")
    try:
        return tuple(structure(json.loads(line), split) for line in data.splitlines())
    except (ValueError, UnicodeError) as error:
        raise ValueError("invalid metadata input; content suppressed") from error


def families(metadata):
    rows = sorted(metadata, key=lambda row: row.task_id)
    if len({r.task_id for r in rows}) != len(rows):
        raise ValueError("duplicate task ID")
    parents = {r.task_id: r.task_id for r in rows}
    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key
    owner = {}
    for row in rows:
        for subquestion in row.subquestions:
            if subquestion in owner:
                left, right = find(row.task_id), find(owner[subquestion])
                parents[max(left, right)] = min(left, right)
            else:
                owner[subquestion] = row.task_id
    groups = {}
    for row in rows:
        groups.setdefault(find(row.task_id), []).append(row.task_id)
    return {task: "family-" + digest(tasks) for tasks in groups.values() for task in tasks}


def make_manifest(metadata, *, exposed_ids, assignments, seed, source_hashes):
    """Assign whole families explicitly; unspecified eligible families stay unused.

    Seed is bound provenance for upstream selection, not an implicit random draw.
    """
    rows = sorted(metadata, key=lambda row: row.task_id)
    if not rows or not isinstance(seed, str) or not seed:
        raise ValueError("nonempty metadata and explicit seed required")
    if (set(source_hashes) != {r.split for r in rows}
            or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v)
                   for v in source_hashes.values())):
        raise ValueError("pinned hash for each source split required")
    by_id = {r.task_id: r for r in rows}
    mapping = families(rows)
    exposed = sorted(set(exposed_ids))
    if set(exposed) - set(by_id):
        raise ValueError("exposure IDs missing from complete metadata index")
    excluded = {mapping[t] for t in exposed}
    if set(assignments) - set(mapping.values()):
        raise ValueError("unknown family assignment")
    entries = []
    for row in rows:
        family = mapping[row.task_id]
        phase = assignments.get(family, "unused")
        if family in excluded:
            if phase not in {"unused", "excluded"}:
                raise ValueError("exposed family cannot be used")
            phase = "excluded"
        elif phase == "excluded":
            raise ValueError("exclusion requires an exposure reason")
        if phase not in PHASES or (phase == "holdout" and row.split != "dev") or (
                phase in TRAIN_PHASES and row.split != "train"):
            raise ValueError("phase violates source split; cross-split family must stay unused")
        entry = asdict(row)
        entry.update(family_id=family, phase=phase)
        entries.append(entry)
    body = json.loads(canonical({"schema": 1, "seed": seed, "source_hashes": source_hashes,
                                "exposed_ids": exposed, "entries": entries}))
    return dict(body, sha256=digest(body))


def validate_manifest(manifest):
    try:
        if set(manifest) != {"schema", "seed", "source_hashes", "exposed_ids", "entries", "sha256"}:
            raise ValueError("invalid manifest fields")
        if type(manifest["schema"]) is not int or manifest["schema"] != 1:
            raise ValueError("unsupported manifest schema")
        rows, assignments = [], {}
        for entry in manifest["entries"]:
            if set(entry) != {"task_id", "split", "hop", "subquestions", "family_id", "phase"}:
                raise ValueError("invalid manifest entry")
            rows.append(TaskMeta(entry["task_id"], entry["split"], entry["hop"], tuple(entry["subquestions"])))
            family, phase = entry["family_id"], entry["phase"]
            if family in assignments and assignments[family] != phase:
                raise ValueError("mixed phases inside family")
            assignments[family] = phase
        expected = make_manifest(rows, exposed_ids=manifest["exposed_ids"], assignments=assignments,
                                 seed=manifest["seed"], source_hashes=manifest["source_hashes"])
        if manifest != expected:
            raise ValueError("manifest changed or inconsistent")
        return manifest
    except (KeyError, TypeError) as error:
        raise ValueError("malformed manifest") from error


def save_manifest(path, manifest):
    validate_manifest(manifest)
    with open(path, "xb") as output:
        output.write(canonical(manifest) + b"\n")


def read_manifest(path):
    return validate_manifest(json.loads(Path(path).read_bytes()))


@dataclass(frozen=True)
class AnswerReference:
    task_id: str
    answers: tuple[str, ...]


def load_task(path, task_id, manifest, *, phase):
    """Return (public input, private reference), never a raw benchmark record.

    Call only after the phase's external release decision. This checks declared
    roles, not author approval; passing 'holdout' does not constitute a freeze.
    """
    validate_manifest(manifest)
    if phase not in TRAIN_PHASES | {"holdout"}:
        raise ValueError("phase is not usable")
    entry = next((e for e in manifest["entries"] if e["task_id"] == task_id), None)
    if entry is None or entry["phase"] != phase:
        raise ValueError("task not assigned to requested phase")
    data = Path(path).read_bytes()
    if sha256(data).hexdigest() != manifest["source_hashes"][entry["split"]]:
        raise ValueError("dataset hash mismatch before content import")
    try:
        for line in data.splitlines():
            record = json.loads(line)
            if record["id"] != task_id:
                continue
            meta = structure(record, entry["split"])
            if json.loads(canonical(asdict(meta))) != {k: entry[k] for k in asdict(meta)}:
                raise ValueError("record differs from bound metadata")
            if record.get("answerable") is not True:
                raise ValueError("answerable task required")
            paragraphs = record["paragraphs"]
            if not isinstance(paragraphs, list) or not paragraphs:
                raise ValueError("nonempty context required")
            texts = []
            for paragraph in paragraphs:
                title, text = paragraph["title"], paragraph["paragraph_text"]
                if not isinstance(title, str) or not isinstance(text, str):
                    raise ValueError("invalid paragraph")
                texts.append(title + "\n" + text)
            answers = (record["answer"], *record["answer_aliases"])
            if (not isinstance(record["answer_aliases"], list)
                    or any(not isinstance(a, str) or not a.strip() for a in answers)):
                raise ValueError("invalid answer references")
            opaque = "task-" + digest([manifest["source_hashes"][entry["split"]], task_id])
            return TaskInput(opaque, record["question"], tuple(texts)), AnswerReference(opaque, answers)
    except (KeyError, TypeError, ValueError, UnicodeError) as error:
        raise ValueError("invalid selected record; content suppressed") from error
    raise ValueError("task absent from bound source")
