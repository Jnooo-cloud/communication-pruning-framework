"""End-to-end synthetic workflow in a disposable directory; no external services."""
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from .configurations import bank
from .contracts import Response, Usage
from .data import canonical, families, index_file, load_task, make_manifest, save_manifest, read_manifest
from .evaluation import PlannedTask, development_observations, paired_summary, read_result
from .execution import execute
from .selection import CONFIG_IDS, fit_selector


def demo():
    count = 0
    def adapter(request):
        nonlocal count
        count += 1
        return Response("demo answer", Usage(10, 2, Decimal("0.01"), "synthetic"))

    def fixture(a, b):
        return {"id": f"2hop__{a}_{b}", "question": f"Synthetic question {a}?", "answerable": True,
                "answer": "demo answer", "answer_aliases": [],
                "question_decomposition": [{"id": a}, {"id": b}],
                "paragraphs": [{"idx": 0, "title": "Synthetic", "paragraph_text": "Invented context only.",
                                "is_supporting": True}]}

    with tempfile.TemporaryDirectory(prefix="pruning-demo-") as directory:
        root = Path(directory)
        sources, hashes, metadata = {}, {}, []
        for split, records in (("train", [fixture(1, 2), fixture(3, 4)]), ("dev", [fixture(5, 6)])):
            path = root / f"{split}.jsonl"
            with path.open("xb") as output:
                output.write(b"".join(canonical(r) + b"\n" for r in records))
            sources[split] = path
            hashes[split] = sha256(path.read_bytes()).hexdigest()
            metadata.extend(index_file(path, split, hashes[split]))
        family = families(metadata)
        assignments = {family[r.task_id]: "spatial" if r.split == "train" else "holdout" for r in metadata}
        manifest = make_manifest(metadata, exposed_ids=[], assignments=assignments,
                                 seed="synthetic-demo-only", source_hashes=hashes)
        save_manifest(root/"manifest.json", manifest)
        manifest = read_manifest(root/"manifest.json")
        plan, results = [], []
        for meta in metadata[:2]:
            task, reference = load_task(sources["train"], meta.task_id, manifest, phase="spatial")
            plan.append(PlannedTask(task, family[meta.task_id], "spatial", (1,)))
            for config in bank():
                path = root / f"development-{task.task_id}-{config.config_id}.jsonl"
                execute(task, config, adapter, journal_path=path)
                results.append(read_result(path, config, task, reference, family_id=family[meta.task_id],
                                           phase="spatial", repeat=1))
        training = development_observations(results, plan)
        selector = fit_selector(training["observations"], seed="synthetic-demo-only")
        development_calls = count
        meta = metadata[2]
        task, reference = load_task(sources["dev"], meta.task_id, manifest, phase="holdout")
        arms = {}
        for arm, config_id in (("F", CONFIG_IDS[selector.fixed_index]), ("Q", selector.select(task))):
            config = next(c for c in bank() if c.config_id == config_id)
            path = root / f"comparison-{arm}.jsonl"
            execute(task, config, adapter, journal_path=path)
            arms[arm] = [read_result(path, config, task, reference, family_id=family[meta.task_id],
                                     phase="holdout", repeat=1)]
        summary = paired_summary(arms["F"], arms["Q"], expected_slots={(task.task_id, 1)}, phase="holdout")
        return {"mode": "synthetic_only_not_study_evidence", "network_calls": 0, "real_model_cost_usd": "0",
                "development_journals": training["executed_runs"], "development_calls": development_calls,
                "synthetic_development_cost_usd": str(training["executed_cost_usd"]),
                "comparison_journals": 2, "comparison_calls": count-development_calls,
                "selector_fallback": selector.report.get("fallback_reason"), "comparison": summary}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2))
