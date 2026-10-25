"""Invented MuSiQue-shaped data and network replacement for Z20 only."""
import json
from pathlib import Path

from communication_pruning.data import canonical, families, index_file, make_manifest
from communication_pruning.openrouter import MODEL, PROVIDER, encoded, save_new
from communication_pruning.spatial_plan import make_plan
from communication_pruning.study import file_hash, FileGuard


def fixture(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(302):
        a = 1000 + (i // 3 if i < 300 else (0 if i == 300 else 101))
        b = 100000 + i
        rows.append({"id": f"2hop__{a}_{b}", "question": f"Invented question {i}?", "answerable": True,
                     "answer": "PRIVATE_REFERENCE_NEVER_SEND", "answer_aliases": ["PRIVATE_ALIAS_NEVER_SEND"],
                     "question_decomposition": [{"id": a}, {"id": b}],
                     "paragraphs": [{"title": "Invented", "paragraph_text": f"Synthetic context {i}.", "is_supporting": True}]})
    source = folder / "fake-train.jsonl"
    save_new(source, b"".join(canonical(row) + b"\n" for row in rows))
    metadata = index_file(source, "train", file_hash(source))
    fmap = families(metadata)
    manifest = make_manifest(metadata, exposed_ids=[], assignments={f: "spatial" if t != rows[-1]["id"] else "pilot" for t, f in fmap.items()}, seed="Z20-fake-only", source_hashes={"train": file_hash(source)})
    ids = [row["id"] for row in rows[:300]]
    repeats = ids[:50]
    bindings = {"source": "a" * 64, "allocation": "b" * 64, "repetition": "c" * 64}
    plan = make_plan(manifest, ids, repeats, bindings=bindings)
    for name, value in [("manifest.json", manifest), ("plan.json", plan), ("exposure.json", [])]:
        save_new(folder / name, encoded(value))
    guard = FileGuard({p: file_hash(p) for p in folder.iterdir() if p.is_file()})
    return dict(plan=plan, manifest=manifest, task_ids=ids, repeats=repeats,
                bindings=bindings, source_path=source, guard=guard)


class FakeTransport:
    def __init__(self, *, fail_at=None, mode=None):
        self.calls = 0
        self.fail_at, self.mode = fail_at, mode
        self.bodies = []

    def __call__(self, endpoint, body=None):
        if endpoint == "models/google/gemini-2.5-flash-lite/endpoints":
            return 200, encoded({"data": {"id": MODEL, "endpoints": [{"tag": PROVIDER, "model_id": MODEL,
                "status": 0, "context_length": 1048576, "max_completion_tokens": 65535,
                "pricing": {"prompt": "0.0000001", "completion": "0.0000004"},
                "supported_parameters": ["reasoning", "temperature", "max_tokens"]}]}})
        if endpoint != "chat/completions":
            raise AssertionError("unexpected endpoint")
        self.calls += 1
        self.bodies.append(json.loads(body))
        mode = self.mode if self.calls == self.fail_at else None
        if mode == "transport":
            raise OSError("invented network error")
        if mode == "interrupt":
            raise KeyboardInterrupt("invented interruption")
        reply = {"id": f"fake-gen-{self.calls}", "model": MODEL, "provider": "Google",
                 "choices": [{"finish_reason": "length" if mode == "length" else "stop",
                              "message": {"role": "assistant", "content": f"Invented output {self.calls}"}}],
                 "usage": {"prompt_tokens": 100, "completion_tokens": 2, "total_tokens": 102,
                           "cost": "0.0000108", "is_byok": False,
                           "completion_tokens_details": {"reasoning_tokens": 0}}}
        if mode == "unknown":
            reply["usage"].pop("cost")
        if mode == "duplicate":
            reply["id"] = "fake-gen-1"
        if mode == "over":
            reply["usage"]["cost"] = "0.30"
        return (503 if mode == "http" else 200), encoded(reply)
