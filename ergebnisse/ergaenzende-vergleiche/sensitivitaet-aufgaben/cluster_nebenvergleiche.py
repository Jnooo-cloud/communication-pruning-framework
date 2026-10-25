"""Explorative Cluster-Sensitivität der ergänzenden Vergleiche R, T, F (offline, 0 USD).

Vorab-Festlegung: VORAB.md (SHA256 in VORAB.md.sha256, bei jedem Lauf geprüft).
Schritt 1 reproduziert die Hauptauswertung bitgleich (Mittel, Hoeffding, Kostenquotienten),
Schritt 2 prüft die Clusterimplementierung mit Einzelclustern gegen Blockatome,
Schritt 3 rechnet Block-, Aufgaben- und Familienbootstrap sowie Hoeffding über Cluster.
Kern (study_preparation/intervals.py) unverändert aus dem alten Repo importiert, nur lesend,
ohne Bytecode. Ausgabe: CLUSTER-NEBENVERGLEICHE.json.
Ausführen mit dem provisionierten Python 3.12 (runs/Z38-QSEM-001/provision/python).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from decimal import Decimal, localcontext  # noqa: E402
from itertools import combinations  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # Schreibordner
EVAL = ROOT.parent / "Masterarbeit" / "eval-harness/eval"
CODE_SHA = {"study_preparation/intervals.py": "3ddb2db681ac0dc5f38d1263d0b7fe86cc73835b2fb2ac78d7b74b5d2c35193e",
            "study_preparation/final_analysis.py": "b16b4be1370ec1f1aa2d140136e64a5fa008d9ad77fc992b966d400c2c98ff6d",
            "study_preparation/final_plan.py": "e9dc5ef8edc30a138430f0e84f3c2964357e183bb76716672aca679fd6dae4af"}
ROWS_SHA = {"R": "7f836d8bf04fae7d1fd0f1e616ba39c314ebc357fc2e5c1bbcfb5d73aa83d3b0",
            "T": "752c3166618ff0d9f9bbe0e6a2220247e890af3ac109f86f27c34728545386aa",
            "F": "2caadd17c69799b4361cf0dbcd0bb2b0e0e39c7452c8b6408a4fa73aa5e2d2f5"}
PRIMARY_SEED = 142211229048427227715370149966446052232
B = 19999
N = 2952

# Qualitätskontraste: (id, Liste (Vorzeichen, Arm), Wertebereich), Kostenquotienten: (id, Zähler, Nenner)
QUALITY = {
    "R": [("R08", [(1, "F"), (-1, "D")], (-1, 1)), ("R06", [(1, "F"), (-1, "S")], (-1, 1)),
          ("R05", [(1, "Q"), (-1, "F")], (-1, 1))],
    "T": [("T01", [(1, "Q-ST"), (-1, "Q-TF")], (-1, 1))],
    "F": [("d_Q", [(1, "Qf"), (-1, "Qc")], (-1, 1)), ("d_F", [(1, "Ff"), (-1, "Fc")], (-1, 1)),
          ("d_Q_minus_d_F", [(1, "Qf"), (-1, "Qc"), (-1, "Ff"), (1, "Fc")], (-2, 2))],
}
COSTS = {"R": [("R08", "F", "D"), ("R06", "F", "S"), ("R05", "Q", "F")],
         "T": [("T01", "Q-ST", "Q-TF")],
         "F": [("F01", "Qf", "Qc"), ("F02", "Ff", "Fc")]}
# Feste Zahlen aus 08_kanon/GLIEDERUNG.md (gerundet), Prozentpunkte bzw. Quotient
FIXED = {("R", "em", "R08"): (6.71, 1.71, 11.71), ("R", "em", "R06"): (0.27, -4.73, 5.27),
         ("T", "em", "T01"): (-0.17, -5.17, 4.83), ("F", "em", "d_Q_minus_d_F"): (1.12, -8.88, 11.12),
         ("R", "f1", "R08"): (0.063, 0.013, 0.112), ("R", "f1", "R06"): (0.016, -0.034, 0.066),
         ("T", "f1", "T01"): (-0.002, -0.052, 0.048), ("F", "f1", "d_Q_minus_d_F"): (0.017, -0.083, 0.117)}
FIXED_POINT = {("F", "em", "d_Q"): -0.34, ("F", "em", "d_F"): -1.46,
               ("F", "f1", "d_Q"): -0.004, ("F", "f1", "d_F"): -0.021}
FIXED_COST = {("R", "R08"): 0.53, ("R", "R06"): 6.66, ("T", "T01"): 1.40, ("F", "F01"): 0.63, ("F", "F02"): 0.58}


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


def check_prespec() -> str:
    want = (HERE / "VORAB.md.sha256").read_text().split()[0]
    assert sha_file(HERE / "VORAB.md") == want, "Vorab-Festlegung wurde verändert"
    return want


def manifest() -> dict:
    out = {}
    for line in (ROOT / "MANIFEST.tsv").read_text().splitlines()[1:]:
        ziel, _q, digest = line.split("\t")
        out[ziel] = digest
    return out


def load_panel(panel, arms):
    rel = f"04_ergebnisse/daten/collected/rows-{panel}.json"
    path = ROOT / rel
    assert sha_file(path) == ROWS_SHA[panel] == manifest()[rel], panel
    rows = json.loads(path.read_text())
    by = defaultdict(dict)
    for r in rows:
        assert r["panel"] == panel
        assert r["arm"] not in by[r["draw_index"]]
        by[r["draw_index"]][r["arm"]] = r
    assert len(rows) == N * len(arms) and sorted(by) == list(range(N))
    blocks = []
    for i in range(N):
        assert set(by[i]) == set(arms), (panel, i)
        blk = [by[i][a] for a in arms]
        assert len({r["task_id"] for r in blk}) == 1 and len({r["family_id"] for r in blk}) == 1, (panel, i)
        blocks.append(blk)
    return blocks


def main():
    prespec_sha = check_prespec()
    for rel, digest in CODE_SHA.items():
        assert sha_file(EVAL / rel) == digest, rel
    sys.path.insert(0, str(EVAL))
    from study_preparation import intervals  # noqa: E402
    from study_preparation.final_plan import ARMS  # noqa: E402
    assert derive_seed("P-bootstrap") == PRIMARY_SEED

    out = {"exploratory": True, "prespec_sha256": prespec_sha, "code_sha256": CODE_SHA, "rows_sha256": ROWS_SHA,
           "numpy": np.__version__, "python": sys.version.split()[0], "bootstrap_reps": B, "panels": {}}
    for panel in ("R", "T", "F"):
        arms = ARMS[panel]
        idx = {a: k for k, a in enumerate(arms)}
        blocks = load_panel(panel, arms)
        ref = json.loads((ROOT / f"04_ergebnisse/belege/RTF/ANALYSIS-{panel}.json").read_text())
        assert ref["rows_sha256"] == ROWS_SHA[panel]
        rep = ref["report"]
        res = {"arms": list(arms)}

        # ---------- Schritt 1: Reproduktion ----------
        step1 = {"estimates": {}, "hoeffding": {}, "cost_ratio": {}, "fixed_numbers_checked": []}
        for a in arms:
            for metric in ("em", "f1"):
                v = math.fsum(b[idx[a]][metric] for b in blocks) / N
                assert v == rep["estimates"][a][metric], (panel, a, metric, v)
                step1["estimates"].setdefault(a, {})[metric] = v
        template = "T1" if panel == "T" else panel
        for metric in ("em", "f1"):
            vals = np.asarray([[r[metric] for r in b] for b in blocks], dtype=float)
            orig = intervals.secondary_quality(vals, template)
            if panel == "R":
                mine = {f"R{i:02d}": orig[f"R/{i:02d}"] for i in range(1, 10)}
            elif panel == "T":
                mine = {"T01": orig["T1/01"]}
            else:
                mine = orig
            want = rep["secondary_quality"][metric]
            assert set(mine) == set(want)
            for ep, d in mine.items():
                for k in ("estimate", "lower", "upper", "radius", "n", "simultaneous"):
                    assert d[k] == want[ep][k], (panel, metric, ep, k, d[k], want[ep][k])
            step1["hoeffding"][metric] = {ep: mine[ep] for ep, _, _ in QUALITY[panel]}
        for ep, num, den in COSTS[panel]:
            with localcontext() as ctx:
                ctx.prec = 50
                n_ = sum(Decimal(b[idx[num]]["cost_usd"]) for b in blocks) / N
                d_ = sum(Decimal(b[idx[den]]["cost_usd"]) for b in blocks) / N
                q = n_ / d_
            assert str(q) == rep["descriptive_costs"]["endpoints"][ep]["estimate"], (panel, ep, str(q))
            step1["cost_ratio"][ep] = str(q)
        for (p, metric, ep), (pt, lo, hi) in FIXED.items():
            if p != panel:
                continue
            h = step1["hoeffding"][metric][ep]
            scale, nd = (100, 2) if metric == "em" else (1, 3)
            got = (round(h["estimate"] * scale, nd), round(h["lower"] * scale, nd), round(h["upper"] * scale, nd))
            assert got == (pt, lo, hi), (panel, metric, ep, got)
            step1["fixed_numbers_checked"].append([metric, ep, list(got)])
        for (p, metric, ep), pt in FIXED_POINT.items():
            if p != panel:
                continue
            h = step1["hoeffding"][metric][ep]
            scale, nd = (100, 2) if metric == "em" else (1, 3)
            assert round(h["estimate"] * scale, nd) == pt, (panel, metric, ep)
            step1["fixed_numbers_checked"].append([metric, ep, pt])
        for (p, ep), val in FIXED_COST.items():
            if p == panel:
                got = round(float(Decimal(step1["cost_ratio"][ep])), 2)
                assert got == val, (panel, ep, got)
                step1["fixed_numbers_checked"].append(["cost", ep, got])
        res["step1_reproduced_bitwise"] = step1

        # ---------- Blockwerte ----------
        contrast = {}
        for metric in ("em", "f1"):
            for ep, terms, _bounds in QUALITY[panel]:
                contrast[(metric, ep)] = [math.fsum(s * b[idx[a]][metric] for s, a in terms) for b in blocks]
        cost = {a: [float(Decimal(b[idx[a]]["cost_usd"])) for b in blocks] for a in arms}
        qual_eps = [(metric, ep, bounds) for metric in ("em", "f1") for ep, _t, bounds in QUALITY[panel]]
        for metric, ep, bounds in qual_eps:  # Konsistenz mit dem Hoeffding-Schätzer
            assert abs(np.mean(contrast[(metric, ep)]) - step1["hoeffding"][metric][ep]["estimate"]) < 1e-12
            assert min(contrast[(metric, ep)]) >= bounds[0] and max(contrast[(metric, ep)]) <= bounds[1]

        # ---------- Clusterlauf ----------
        def cluster_run(keyfn, seed):
            groups = defaultdict(list)
            for i, b in enumerate(blocks):
                groups[keyfn(i, b)].append(i)
            keys = sorted(groups)
            cols, endpoints, col = [], [], 0
            for metric, ep, bounds in qual_eps:
                h = -bounds[0]
                cols.append([math.fsum(contrast[(metric, ep)][i] + h for i in groups[k]) for k in keys])
                cols.append([float(len(groups[k])) for k in keys])
                endpoints.append({"id": f"{metric}:{ep}", "kind": "ratio", "_shift": h, "_col": col})
                col += 2
            for ep, num, den in COSTS[panel]:
                cols.append([math.fsum(cost[num][i] for i in groups[k]) for k in keys])
                cols.append([math.fsum(cost[den][i] for i in groups[k]) for k in keys])
                endpoints.append({"id": f"cost:{ep}", "kind": "ratio", "_shift": 0, "_col": col})
                col += 2
            atoms = np.asarray(cols, dtype=float).T
            kern = []
            for e in endpoints:
                vec_n = [0.0] * col
                vec_d = [0.0] * col
                vec_n[e["_col"]] = 1.0
                vec_d[e["_col"] + 1] = 1.0
                kern.append({"id": e["id"], "kind": "ratio", "numerator": vec_n, "denominator": vec_d})
            r = intervals.analyze(atoms, np.ones(len(keys), dtype=np.int64), kern,
                                  rng=np.random.Generator(np.random.PCG64(seed)), bootstrap_reps=B)
            outp = {"seed": str(seed), "clusters": len(keys), "bootstrap_reps": r["bootstrap_reps"], "endpoints": {}}
            for e in endpoints:
                d = r["endpoints"][e["id"]]
                h = e["_shift"]
                outp["endpoints"][e["id"]] = {"estimate": d["estimate"] - h, "se": d["se"], "lower": d["lower"] - h,
                                              "upper": d["upper"] - h, "status": d["status"],
                                              "undefined_resamples": d["undefined_resamples"]}
            sizes = sorted(len(v) for v in groups.values())
            outp["cluster_sizes"] = {"min": sizes[0], "median": sizes[len(sizes) // 2], "max": sizes[-1],
                                     "mean": round(sum(sizes) / len(sizes), 4),
                                     "sum_m2_over_n": sum(s * s for s in sizes) / N,
                                     "share_blocks_in_largest_1pct_clusters": round(
                                         sum(sizes[-max(1, len(sizes) // 100):]) / N, 4),
                                     "histogram": {str(k): v for k, v in sorted(Counter(sizes).items())}}
            return outp, groups

        # ---------- Schritt 2: Einzelcluster gegen Blockatome ----------
        seeds = {v: derive_seed(f"{panel}-cluster-{v}-bootstrap") for v in ("block", "task", "family")}
        v0, _ = cluster_run(lambda i, b: i, seeds["block"])
        direct_cols, direct_eps = [], []
        for metric, ep, bounds in qual_eps:
            direct_eps.append({"id": f"{metric}:{ep}", "kind": "mean", "numerator": None, "bounds": list(bounds)})
            direct_cols.append(contrast[(metric, ep)])
        for ep, num, den in COSTS[panel]:
            direct_eps.append({"id": f"cost:{ep}", "kind": "ratio", "numerator": None, "denominator": None})
            direct_cols.append(cost[num])
            direct_cols.append(cost[den])
        width = len(direct_cols)
        c = 0
        for e in direct_eps:
            vec = [0.0] * width
            vec[c] = 1.0
            e["numerator"] = vec
            c += 1
            if e["kind"] == "ratio":
                dv = [0.0] * width
                dv[c] = 1.0
                e["denominator"] = dv
                c += 1
        direct = intervals.analyze(np.asarray(direct_cols, dtype=float).T, np.ones(N, dtype=np.int64), direct_eps,
                                   rng=np.random.Generator(np.random.PCG64(seeds["block"])), bootstrap_reps=B)
        maxdev = 0.0
        for e in direct_eps:
            for k in ("estimate", "se", "lower", "upper"):
                dev = abs(v0["endpoints"][e["id"]][k] - direct["endpoints"][e["id"]][k])
                maxdev = max(maxdev, dev)
                assert dev <= 1e-12, (panel, e["id"], k, dev)
            assert v0["endpoints"][e["id"]]["status"] == direct["endpoints"][e["id"]]["status"]
        res["step2_singleton_max_abs_dev"] = maxdev

        # ---------- Schritt 3 ----------
        variants = {"0_block": v0}
        variants["A_task"], g_task = cluster_run(lambda i, b: b[0]["task_id"], seeds["task"])
        variants["B_family"], g_fam = cluster_run(lambda i, b: b[0]["family_id"], seeds["family"])
        variants["A_task_mc"], _ = cluster_run(lambda i, b: b[0]["task_id"], PRIMARY_SEED)
        variants["B_family_mc"], _ = cluster_run(lambda i, b: b[0]["family_id"], PRIMARY_SEED)
        res["seeds"] = {k: str(v) for k, v in seeds.items()}

        # Hoeffding über Cluster (analytisch, bedingt auf Clustergrößen)
        hc = {}
        for name, groups in (("task", g_task), ("family", g_fam)):
            s2 = sum(len(v) ** 2 for v in groups.values())
            for metric, ep, (a, b_) in qual_eps:
                mean = step1["hoeffding"][metric][ep]["estimate"]
                radius = (b_ - a) * math.sqrt(math.log(40) * s2 / 2) / N
                hc.setdefault(name, {})[f"{metric}:{ep}"] = {"estimate": mean, "radius": radius,
                                                            "lower": max(a, mean - radius),
                                                            "upper": min(b_, mean + radius), "sum_m2": s2}
        res["hoeffding_cluster"] = hc

        # Breiten und Ablesung
        for vname, v in variants.items():
            for eid, d in v["endpoints"].items():
                w = d["upper"] - d["lower"]
                d["width"] = w
                d["width_ratio_to_block_bootstrap"] = w / (v0["endpoints"][eid]["upper"] - v0["endpoints"][eid]["lower"])
                if not eid.startswith("cost:"):
                    metric, ep = eid.split(":")
                    hw = 2 * step1["hoeffding"][metric][ep]["radius"]
                    d["width_ratio_to_hoeffding"] = w / hw
                    d["width_ratio_to_hoeffding_squared"] = (w / hw) ** 2
                    d["contains_0"] = d["lower"] <= 0 <= d["upper"]
                    d["contains_minus_3pp"] = d["lower"] <= -0.03 <= d["upper"]
                    d["contains_plus_3pp"] = d["lower"] <= 0.03 <= d["upper"]
                else:
                    d["contains_1"] = d["lower"] <= 1 <= d["upper"]
        reading = {}
        for metric, ep, _b in qual_eps:
            eid = f"{metric}:{ep}"
            h = step1["hoeffding"][metric][ep]
            base = h["lower"] <= 0 <= h["upper"]
            row = {"hoeffding_contains_0": base}
            for vname in ("0_block", "A_task", "B_family", "A_task_mc", "B_family_mc"):
                row[vname] = variants[vname]["endpoints"][eid]["contains_0"]
            for name in ("task", "family"):
                row[f"hoeffding_{name}"] = hc[name][eid]["lower"] <= 0 <= hc[name][eid]["upper"]
            row["flips_vs_hoeffding"] = sorted(k for k, v in row.items() if k != "hoeffding_contains_0" and v != base)
            reading[eid] = row
        res["variants"] = variants
        res["reading_contains_0"] = reading

        # ---------- Wiederholungsstruktur ----------
        multi = {k: v for k, v in g_task.items() if len(v) > 1}
        rep_struct = {"tasks": len(g_task), "families": len(g_fam), "tasks_multi": len(multi),
                      "blocks_in_multi_tasks": sum(len(v) for v in multi.values()),
                      "sum_m2_over_n_task": sum(len(v) ** 2 for v in g_task.values()) / N,
                      "sum_m2_over_n_family": sum(len(v) ** 2 for v in g_fam.values()) / N,
                      "identical_contrast_all_reps": {}, "identical_contrast_pairwise": {},
                      "identical_arm_em_all_reps": {}}
        for _m, ep, _b in [q for q in qual_eps if q[0] == "em"]:
            vals = contrast[("em", ep)]
            same = sum(len({vals[i] for i in v}) == 1 for v in multi.values())
            pairs = [(vals[i] == vals[j]) for v in multi.values() for i, j in combinations(v, 2)]
            rep_struct["identical_contrast_all_reps"][ep] = same / len(multi)
            rep_struct["identical_contrast_pairwise"][ep] = sum(pairs) / len(pairs)
        for a in arms:
            same = sum(len({blocks[i][idx[a]]["em"] for i in v}) == 1 for v in multi.values())
            rep_struct["identical_arm_em_all_reps"][a] = same / len(multi)
        res["repetition"] = rep_struct
        out["panels"][panel] = res

        print(panel, "Schritt 1 bitgleich; Schritt 2 max Abw.", maxdev)
        for metric, ep, _b in qual_eps:
            eid = f"{metric}:{ep}"
            h = step1["hoeffding"][metric][ep]
            s = f"  {eid:22s} Punkt {h['estimate']:+.5f} H [{h['lower']:+.4f},{h['upper']:+.4f}]"
            for vname in ("0_block", "A_task", "B_family"):
                d = variants[vname]["endpoints"][eid]
                s += f" {vname}[{d['lower']:+.4f},{d['upper']:+.4f}]{'' if d['status'] == 'ok' else d['status']}"
            for name in ("task", "family"):
                s += f" H{name[0]}[{hc[name][eid]['lower']:+.4f},{hc[name][eid]['upper']:+.4f}]"
            print(s)
        for ep, _n, _d in COSTS[panel]:
            eid = f"cost:{ep}"
            s = f"  {eid:22s} Punkt {variants['0_block']['endpoints'][eid]['estimate']:.4f}"
            for vname in ("0_block", "A_task", "B_family"):
                d = variants[vname]["endpoints"][eid]
                s += f" {vname}[{d['lower']:.4f},{d['upper']:.4f}]{'' if d['status'] == 'ok' else d['status']}"
            print(s)
        print("  Wiederholung", json.dumps(rep_struct))
    (HERE / "CLUSTER-NEBENVERGLEICHE.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
