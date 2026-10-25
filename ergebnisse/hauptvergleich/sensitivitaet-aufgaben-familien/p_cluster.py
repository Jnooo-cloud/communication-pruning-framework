"""Explorative Cluster-Sensitivität für P (offline, 0 USD). Vorab-Festlegung: P-CLUSTER-SENSITIVITAET.md §0.

Schritt 1 reproduziert die Hauptanalyse bitgleich, Schritt 2 prüft die Cluster-Implementierung
mit Einzelclustern, Schritt 3 rechnet Aufgaben- und Familiencluster. Der Bootstrap-Kern
(study_preparation/intervals.py) wird unverändert aus dem alten Repo importiert, ohne Bytecode
zu schreiben. STATE.json wird nur gelesen. Ausgabe: P-CLUSTER-SENSITIVITAET.json.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from copy import deepcopy  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EVAL = ROOT.parent / "Masterarbeit" / "eval-harness/eval"
STATE_DIR = EVAL / "runs/Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1"
STATE_SHA = "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6"
CODE_SHA = {"study_preparation/intervals.py": "3ddb2db681ac0dc5f38d1263d0b7fe86cc73835b2fb2ac78d7b74b5d2c35193e",
            "study_preparation/final_analysis.py": "b16b4be1370ec1f1aa2d140136e64a5fa008d9ad77fc992b966d400c2c98ff6d"}
PRIMARY_SEED = 142211229048427227715370149966446052232
B = 19999


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def derive_seed(label: str) -> int:
    payload = json.dumps(["Z50-analysis-v1", "Z50-STUDY-v1", 20260920, label], sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "little")


def check_prespec():
    text = (HERE / "P-CLUSTER-SENSITIVITAET.md").read_text(encoding="utf-8")
    sec = text[text.index("## 0. Vorab-Festlegung"):text.index("## 1. Ergebnis")]
    want = (HERE / "P-CLUSTER-VORAB.sha256").read_text().split()[0]
    assert hashlib.sha256(sec.encode("utf-8")).hexdigest() == want, "Vorab-Festlegung wurde verändert"
    return want


def load_rows():
    state, index = STATE_DIR / "STATE.json", STATE_DIR / "STATE-INDEX.json"
    idx = json.loads(index.read_text())
    assert idx["state_sha256"] == STATE_SHA and sha_file(state) == STATE_SHA
    assert state.stat().st_size == idx["bytes"]
    field = next(x for x in idx["fields"] if x["name"] == "rows")
    with state.open("rb") as f:
        f.seek(field["start"])
        rows = json.loads(f.read(field["end"] - field["start"]))
    return rows


def main():
    prespec_sha = check_prespec()
    for rel, digest in CODE_SHA.items():
        assert sha_file(EVAL / rel) == digest, rel
    sys.path.insert(0, str(EVAL))
    from study_preparation import intervals  # noqa: E402
    from study_preparation.final_analysis import PRIMARY_ENDPOINTS  # noqa: E402

    assert derive_seed("P-bootstrap") == PRIMARY_SEED
    rows = load_rows()
    draws = defaultdict(dict)
    for r in rows:
        draws[r["draw_index"]][r["arm"]] = r
    assert len(rows) == 18080 and sorted(draws) == list(range(9040))
    assert all(set(v) == {"Q", "F"} for v in draws.values())
    pairs = []
    for i in range(9040):
        q, f = draws[i]["Q"], draws[i]["F"]
        assert q["task_id"] == f["task_id"] and q["family_id"] == f["family_id"]
        pairs.append((q, f))

    # Schritt 1: exakte Reproduktion wie final_analysis._primary
    atoms = np.asarray([[q["em"] - f["em"], float(Decimal(q["cost_usd"])), float(Decimal(f["cost_usd"]))]
                        for q, f in pairs], dtype=float)
    main_res = intervals.analyze(atoms, np.ones(9040, dtype=np.int64), deepcopy(PRIMARY_ENDPOINTS),
                                 rng=np.random.Generator(np.random.PCG64(PRIMARY_SEED)), bootstrap_reps=B)
    ref = json.loads((ROOT / "04_ergebnisse/belege/P/P-ANALYSIS.json").read_text())["report"]
    ref_kernel = ref["primary"]["kernel"]["endpoints"]
    step1 = {}
    for ep in ("P-D", "P-C"):
        mine = main_res["endpoints"][ep]
        step1[ep] = {k: mine[k] for k in ("estimate", "se", "lower", "upper", "status", "undefined_resamples")}
        for k in ("estimate", "se", "lower", "upper", "status", "undefined_resamples"):
            assert mine[k] == ref_kernel[ep][k], (ep, k, mine[k], ref_kernel[ep][k])
    em_q = math.fsum(q["em"] for q, _ in pairs) / 9040
    em_f = math.fsum(f["em"] for _, f in pairs) / 9040
    assert em_q == ref["estimates"]["Q"]["em"] and em_f == ref["estimates"]["F"]["em"]

    def cluster_run(key_fn, seed, label):
        groups = defaultdict(list)
        for q, f in pairs:
            groups[key_fn(q)].append((q, f))
        keys = sorted(groups)  # feste, inhaltsunabhängige Reihenfolge der Cluster
        cat = []
        for k in keys:
            members = groups[k]
            cat.append([math.fsum(q["em"] - f["em"] + 1 for q, f in members), float(len(members)),
                        math.fsum(float(Decimal(q["cost_usd"])) for q, _ in members),
                        math.fsum(float(Decimal(f["cost_usd"])) for _, f in members)])
        cat = np.asarray(cat, dtype=float)
        endpoints = [{"id": "Delta+1", "kind": "ratio", "numerator": [1, 0, 0, 0], "denominator": [0, 1, 0, 0]},
                     {"id": "rho", "kind": "ratio", "numerator": [0, 0, 1, 0], "denominator": [0, 0, 0, 1]}]
        res = intervals.analyze(cat, np.ones(len(keys), dtype=np.int64), endpoints,
                                rng=np.random.Generator(np.random.PCG64(seed)), bootstrap_reps=B)
        d, r = res["endpoints"]["Delta+1"], res["endpoints"]["rho"]
        out = {"label": label, "seed": str(seed), "clusters": len(keys), "bootstrap_reps": res["bootstrap_reps"],
               "P-D": {"estimate": d["estimate"] - 1, "se": d["se"], "lower": d["lower"] - 1, "upper": d["upper"] - 1,
                       "status": d["status"], "undefined_resamples": d["undefined_resamples"]},
               "P-C": {k: r[k] for k in ("estimate", "se", "lower", "upper", "status", "undefined_resamples")}}
        sizes = Counter(len(v) for v in groups.values())
        allsz = sorted(len(v) for v in groups.values())
        out["cluster_sizes"] = {"min": allsz[0], "median": allsz[len(allsz) // 2], "max": allsz[-1],
                                "mean": round(sum(allsz) / len(allsz), 4),
                                "share_pairs_in_largest_1pct_clusters": round(
                                    sum(allsz[-max(1, len(allsz) // 100):]) / 9040, 4),
                                "histogram": {str(k): v for k, v in sorted(sizes.items())}}
        return out

    # Schritt 2: Einzelcluster mit Primärseed müssen Schritt 1 reproduzieren
    step2 = cluster_run(lambda q: q["draw_index"], PRIMARY_SEED, "singleton-check")
    for ep in ("P-D", "P-C"):
        for k in ("estimate", "lower", "upper", "se"):
            dev = abs(step2[ep][k] - step1[ep][k])
            step2[ep][f"abs_dev_{k}"] = dev
            assert dev <= 1e-12, (ep, k, dev)

    # Schritt 3
    seeds = {"task": derive_seed("P-cluster-task-bootstrap"), "family": derive_seed("P-cluster-family-bootstrap")}
    variants = {
        "A_task": cluster_run(lambda q: q["task_id"], seeds["task"], "task_id, abgeleiteter Seed"),
        "B_family": cluster_run(lambda q: q["family_id"], seeds["family"], "family_id, abgeleiteter Seed"),
        "A_task_mc": cluster_run(lambda q: q["task_id"], PRIMARY_SEED, "task_id, Primärseed (Monte-Carlo-Kontrolle)"),
        "B_family_mc": cluster_run(lambda q: q["family_id"], PRIMARY_SEED, "family_id, Primärseed (Monte-Carlo-Kontrolle)"),
    }

    def statements(d, c):
        """Wie final_analysis._primary: bei Endpunktstatus ungleich ok lautet die Aussage "blocked"."""
        def st(ep, cond):
            return "blocked" if ep["status"] != "ok" else cond
        return {"quality_preserved_3pp": st(d, d["lower"] > -0.03), "quality_loss": st(d, d["upper"] < 0),
                "quality_loss_beyond_3pp": st(d, d["upper"] < -0.03),
                "cost_saving_at_least_10pct": st(c, c["upper"] < 0.90),
                "cost_saving_below_10pct": st(c, c["lower"] > 0.90), "cost_increase": st(c, c["lower"] > 1),
                "joint_positive": (d["status"] == "ok" and c["status"] == "ok"
                                   and d["lower"] > -0.03 and c["upper"] < 0.90)}

    main_st = statements(step1["P-D"], step1["P-C"])
    ref_st = ref["primary"]["statements"]
    assert all((ref_st[k] == "established") == v for k, v in main_st.items() if k != "joint_positive")
    width = {ep: step1[ep]["upper"] - step1[ep]["lower"] for ep in ("P-D", "P-C")}
    for v in variants.values():
        v["statements"] = statements(v["P-D"], v["P-C"])
        v["statements_equal_main"] = v["statements"] == main_st
        for ep in ("P-D", "P-C"):
            w = v[ep]["upper"] - v[ep]["lower"]
            v[ep]["width"] = w
            v[ep]["width_ratio_to_main"] = w / width[ep]
            v[ep]["width_ratio_squared"] = (w / width[ep]) ** 2
            v[ep]["se_ratio_to_main"] = v[ep]["se"] / step1[ep]["se"]
    out = {"exploratory": True, "prespec_sha256": prespec_sha, "state_sha256": STATE_SHA,
           "code_sha256": CODE_SHA, "numpy": np.__version__, "bootstrap_reps": B,
           "seeds": {"primary": str(PRIMARY_SEED), **{k: str(v) for k, v in seeds.items()}},
           "step1_main_reproduced_bitwise": step1, "em_means": {"Q": em_q, "F": em_f},
           "main_statements": main_st, "main_width": width,
           "step2_singleton_check": step2, "variants": variants}
    (HERE / "P-CLUSTER-SENSITIVITAET.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("Schritt 1 bitgleich:", step1)
    print("Schritt 2 max Abweichung:", max(step2[ep][f"abs_dev_{k}"] for ep in ("P-D", "P-C")
                                          for k in ("estimate", "lower", "upper", "se")))
    for name, v in variants.items():
        print(name, v["clusters"], v["cluster_sizes"]["max"], "D", round(v["P-D"]["lower"], 6), round(v["P-D"]["upper"], 6),
              v["P-D"]["status"], "C", round(v["P-C"]["lower"], 6), round(v["P-C"]["upper"], 6), v["P-C"]["status"],
              "Breite x", round(v["P-D"]["width_ratio_to_main"], 4), round(v["P-C"]["width_ratio_to_main"], 4),
              "gleich", v["statements_equal_main"])


if __name__ == "__main__":
    main()
