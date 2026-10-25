"""Merkmalsmatrix der 300 Entwicklungsaufgaben neu bauen (Analyseplan A0).

Liest nur: Abnahmedatei und Laufjournale von Z39, gebundenen Encoder aus Z38.
Schreibt nur: analyse/features-300.npz und analyse/features-300.meta.json.
Keine Modellaufrufe, keine Goldantworten.
Aufruf mit der gebundenen Python-Umgebung aus Z38 (siehe ANALYSEPLAN.md).
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit")
EVAL = ROOT / "eval-harness/eval"
Z39 = EVAL / "runs/Z39-RAEUM-ENTWICKLUNG-001"
FIT = Z39 / "recovery-fit/run-001"
PROVISION = EVAL / "runs/Z38-QSEM-001/provision"
OUT = Path(__file__).resolve().parent

sys.path.insert(0, str(EVAL))
from communication_pruning.contracts import TaskInput  # noqa: E402
from communication_pruning.selection import features  # noqa: E402
from communication_pruning.semantic_selection import FrozenMiniLM, _matrix  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    raw = json.loads((FIT / "raw-Q-sem.json").read_text(encoding="utf-8"))
    order = list(raw["task_families"])  # sortiert nach Aufgabenkennung, wie im Original-Fit
    acceptance = json.loads((Z39 / "FINAL-R1-MATRIX-ACCEPTANCE.json").read_text(encoding="utf-8"))
    tasks = {}
    checked = 0
    for slot, result_path in sorted(acceptance["matrix_results"].items()):
        result_path = Path(result_path)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        tid = result["task_id"]
        if tid in tasks:
            continue
        journal = result_path.parent / (slot + ".jsonl")
        if sha(journal) != result["journal_sha256"]:
            raise SystemExit("Journal-Prüfsumme weicht ab: " + str(journal))
        header = json.loads(journal.read_bytes().split(b"\n", 1)[0])
        task = header["payload"]["trace"]["task"]
        if task["task_id"] != tid:
            raise SystemExit("Aufgabenkennung im Journal weicht ab: " + slot)
        tasks[tid] = TaskInput(task["task_id"], task["question"], tuple(task["paragraphs"]))
        checked += 1
    missing = [t for t in order if t not in tasks]
    if missing:
        raise SystemExit("Aufgaben fehlen: %d" % len(missing))
    runtime = raw["encoder"]
    encoder = FrozenMiniLM(PROVISION / "encoder/all-MiniLM-L6-v2", files=runtime["files"], runtime=runtime["runtime"])
    matrix, meta = _matrix([tasks[t] for t in order], encoder)
    np.savez(OUT / "features-300.npz", X=np.asarray(matrix, dtype=float), task_ids=np.asarray(order))
    (OUT / "features-300.meta.json").write_text(json.dumps({
        "tasks": len(order), "dimension": int(np.asarray(matrix).shape[1]), "journals_checked": checked,
        "truncated_questions": meta["truncated_questions"],
        "encoder_files": runtime["files"], "features_sha256": sha(OUT / "features-300.npz")}, indent=1), encoding="utf-8")
    print("ok", np.asarray(matrix).shape, "journals", checked)


if __name__ == "__main__":
    main()
