"""Hash the study data and foreign evidence V3d/V3e read (before/after), or compare two manifests.

  hash_inputs.py snapshot OUT.json
  hash_inputs.py compare BEFORE.json AFTER.json
"""
import sys

sys.dont_write_bytecode = True

from hashlib import sha256  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import time  # noqa: E402

RUNS = Path(__file__).resolve().parents[2]
SETS = {
    "z53_r_blocks_R-02183_R-02282": [RUNS / "Z53-SCHNELLFORTSETZUNG-001/live/blocks" / f"R-{i:05d}" for i in range(2183, 2283)],
    "z55_gptswarm_demo": [RUNS / "Z55-GPTSWARM-DEMO-001"],
    "z31_gptswarm_original": [RUNS / "Z31-PRUNING-001/original", RUNS / "Z31-PRUNING-001/original-manifest.json"],
    "z37_messabnahme": [RUNS / "Z37-MESSABNAHME-001"],
    "z53_fake_transport": [RUNS / "Z53-SCHNELLFORTSETZUNG-001/fake_transport.py"],
}


def files(path):
    return [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())


def snapshot(target):
    out = {"epoch": time.time(), "root": str(RUNS), "sets": {}}
    for name, paths in SETS.items():
        entries = {}
        for root in paths:
            if not root.exists():
                raise SystemExit(f"missing input {root}")
            for p in files(root):
                entries[str(p.relative_to(RUNS))] = sha256(p.read_bytes()).hexdigest()
        out["sets"][name] = {"files": len(entries), "digest": sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
                             "entries": entries}
    with open(target, "x") as handle:
        json.dump(out, handle, indent=1)
        handle.write("\n")
    print(json.dumps({k: {"files": v["files"], "digest": v["digest"]} for k, v in out["sets"].items()}, indent=1))


def compare(before, after):
    a, b = json.load(open(before)), json.load(open(after))
    result = {}
    for name in SETS:
        ea, eb = a["sets"][name]["entries"], b["sets"][name]["entries"]
        result[name] = {"files": len(ea), "identical": ea == eb, "changed": sorted(k for k in ea if k in eb and ea[k] != eb[k]),
                        "missing": sorted(set(ea) - set(eb)), "new": sorted(set(eb) - set(ea))}
    print(json.dumps(result, indent=1))
    return all(r["identical"] for r in result.values())


if __name__ == "__main__":
    if sys.argv[1] == "snapshot":
        snapshot(sys.argv[2])
    else:
        raise SystemExit(0 if compare(sys.argv[2], sys.argv[3]) else 1)
