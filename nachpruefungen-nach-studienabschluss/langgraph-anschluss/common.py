"""Z56 V3 shared bootstrap and helpers. Import first: no bytecode, network lock, paths."""
import sys

sys.dont_write_bytecode = True

from pathlib import Path  # noqa: E402

V3 = Path(__file__).resolve().parent
RUN = V3.parent
EVAL = RUN.parents[1]
ROOT = EVAL.parents[1]
for extra in (str(EVAL), str(V3)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

import netguard  # noqa: E402

netguard.install()

from dataclasses import asdict  # noqa: E402
from decimal import Decimal  # noqa: E402
from hashlib import sha256  # noqa: E402
import json  # noqa: E402

from communication_pruning.configurations import bank, dense  # noqa: E402
from communication_pruning.contracts import TaskInput  # noqa: E402

import os  # noqa: E402

OUT = Path(os.environ.get("Z56_V3_OUT", str(V3 / "out")))   # smoke tests write to the scratchpad
SMOKE = os.environ.get("Z56_V3_SMOKE") == "1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False, default=str).encode()


def sha(data):
    return sha256(data).hexdigest()


def file_sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as out:
        json.dump(value, out, indent=1, ensure_ascii=False, allow_nan=False, default=str)
        out.write("\n")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True, ensure_ascii=True, allow_nan=False, default=str) + "\n")


def tree_hashes(root, *, skip=()):
    root = Path(root)
    return {str(p.relative_to(root)): file_sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and not any(part in skip for part in p.relative_to(root).parts)}


def configurations(with_dense=True):
    configs = list(bank())
    configs = configs + [dense()] if with_dense else configs
    return [configs[0], configs[-1]] if SMOKE else configs


def synthetic_tasks(n=12):
    """Invented public tasks; no benchmark text, no holdout data."""
    tasks = []
    for i in range(2 if SMOKE else n):
        paragraphs = tuple(f"Künstlicher Absatz {i}-{j}: Behälter {chr(65 + (i + j) % 26)} enthält Marke {i * 7 + j}."
                           for j in range(1 + i % 4))
        tasks.append(TaskInput(f"z56-v3-synth-{i:02d}", f"Welche Marke liegt in Behälter {chr(65 + i % 26)} (Fall {i})?",
                               paragraphs))
    return tasks


def plain(value):
    return json.loads(json.dumps(value, default=str))


__all__ = ["V3", "RUN", "EVAL", "ROOT", "OUT", "SMOKE", "netguard", "asdict", "Decimal", "canonical", "sha",
           "file_sha", "write_json", "write_jsonl", "tree_hashes", "configurations", "synthetic_tasks", "plain"]
