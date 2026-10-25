"""Nachträgliche Aufschlüsselung des Qualitätsverlusts Q gegenüber F* (offline, 0 USD).

Vorab-Festlegung: Q-VERLUST-AUFSCHLUESSELUNG.md §0, Hash in Q-VERLUST-VORAB.sha256.
Schritt 1 reproduziert bekannte Werte aus P und R exakt, danach folgen die beschreibenden
Aufschlüsselungen (a) bis (d) und die vier vorab festgelegten Intervalle (nur P).
Kern und Konfigurationsraum werden unverändert aus dem alten Repo importiert, ohne Bytecode
zu schreiben. Alle Eingaben werden nur gelesen. Ausgabe: Q-VERLUST-AUFSCHLUESSELUNG.json.
Laufzeit: provisioniertes Python 3.12 (runs/Z38-QSEM-001/provision/python) für Bitgleichheit.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from copy import deepcopy  # noqa: E402
from decimal import Decimal, localcontext  # noqa: E402
from fractions import Fraction  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # Masterarbeit-Schreiben
EVAL = ROOT.parent / "Masterarbeit" / "eval-harness/eval"
STATE_DIR = EVAL / "runs/Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1"
STATE_SHA = "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6"
R_ROWS = ROOT / "04_ergebnisse/daten/collected/rows-R.json"
R_SHA = "7f836d8bf04fae7d1fd0f1e616ba39c314ebc357fc2e5c1bbcfb5d73aa83d3b0"
CODE_SHA = {"study_preparation/intervals.py": "3ddb2db681ac0dc5f38d1263d0b7fe86cc73835b2fb2ac78d7b74b5d2c35193e",
            "study_preparation/final_analysis.py": "b16b4be1370ec1f1aa2d140136e64a5fa008d9ad77fc992b966d400c2c98ff6d",
            "communication_pruning/configurations.py": "538bed52e74482ddbd0300fee9965254ec571bddf3adc4868d443c75db8b4796"}
PRIMARY_SEED = 142211229048427227715370149966446052232
B = 19999
TYPE_RE = re.compile(r"^(\d)hop(\d?)__(.+)$")


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
    text = (HERE / "Q-VERLUST-AUFSCHLUESSELUNG.md").read_text(encoding="utf-8")
    sec = text[text.index("## 0. Vorab-Festlegung"):text.index("## 1. Ergebnis")]
    want = (HERE / "Q-VERLUST-VORAB.sha256").read_text().split()[0]
    assert hashlib.sha256(sec.encode("utf-8")).hexdigest() == want, "Vorab-Festlegung wurde verändert"
    return want


def load_p_rows():
    state, index = STATE_DIR / "STATE.json", STATE_DIR / "STATE-INDEX.json"
    idx = json.loads(index.read_text())
    assert idx["state_sha256"] == STATE_SHA and sha_file(state) == STATE_SHA
    assert state.stat().st_size == idx["bytes"]
    field = next(x for x in idx["fields"] if x["name"] == "rows")
    with state.open("rb") as f:
        f.seek(field["start"])
        return json.loads(f.read(field["end"] - field["start"]))


def make_pairs(rows, n_expected):
    draws = defaultdict(dict)
    for r in rows:
        if r["arm"] in ("Q", "F"):
            assert r["arm"] not in draws[r["draw_index"]]
            draws[r["draw_index"]][r["arm"]] = r
    assert sorted(draws) == list(range(n_expected))
    pairs = []
    for i in range(n_expected):
        q, f = draws[i]["Q"], draws[i]["F"]
        assert q["task_id"] == f["task_id"] and q["family_id"] == f["family_id"] and q["block_id"] == f["block_id"]
        assert f["configuration"] == "C01"
        pairs.append((q, f))
    return pairs


def task_type(task_id):
    m = TYPE_RE.match(task_id)
    assert m, task_id
    hops = int(m.group(1))
    return f"{m.group(1)}hop{m.group(2)}", hops, len(m.group(3).split("_")) == hops


def describe(members, total_loss):
    """Beschreibende Kennzahlen einer Paargruppe; exakte Summen für EM und Kosten."""
    n = len(members)
    if n == 0:
        return {"n": 0}
    dsum = sum(int(q["em"] - f["em"]) for q, f in members)
    with localcontext() as ctx:
        ctx.prec = 50
        cq = sum(Decimal(q["cost_usd"]) for q, _ in members)
        cf = sum(Decimal(f["cost_usd"]) for _, f in members)
        ratio = cq / cf
    return {
        "n": n,
        "em_q": math.fsum(q["em"] for q, _ in members) / n,
        "em_f": math.fsum(f["em"] for _, f in members) / n,
        "delta_em": dsum / n,
        "delta_f1": math.fsum(q["f1"] - f["f1"] for q, f in members) / n,
        "sum_delta_em": dsum,
        "share_of_total_loss": float(Fraction(dsum, total_loss)) if total_loss else None,
        "q_right_f_wrong": sum(1 for q, f in members if q["em"] > f["em"]),
        "q_wrong_f_right": sum(1 for q, f in members if q["em"] < f["em"]),
        "failures_q": sum(1 for q, _ in members if q["status"] != "ok"),
        "failures_f": sum(1 for _, f in members if f["status"] != "ok"),
        "mean_cost_q": float(cq / n), "mean_cost_f": float(cf / n), "cost_ratio": float(ratio),
        "sum_cost_q": str(cq), "sum_cost_f": str(cf), "sum_cost_diff": str(cq - cf),
        "mean_calls_q": math.fsum(q["call_count"] for q, _ in members) / n,
        "mean_calls_f": math.fsum(f["call_count"] for _, f in members) / n,
        "small_n_flag": n < 30,
    }


def breakdown(pairs, cfg_info):
    total_loss = sum(int(q["em"] - f["em"]) for q, f in pairs)
    n = len(pairs)

    def group(key_fn):
        g = defaultdict(list)
        for p in pairs:
            g[key_fn(p)].append(p)
        return {k: describe(v, total_loss) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}

    dev = lambda p: "gleich" if p[0]["configuration"] == "C01" else "abweichend"  # noqa: E731
    out = {"n": n, "total_loss_sum_delta_em": total_loss, "all": describe(pairs, total_loss)}
    out["a_gleich_abweichend"] = group(dev)
    a = out["a_gleich_abweichend"]
    # Zerlegungskontrolle exakt mit Brüchen
    lhs = Fraction(total_loss, n)
    rhs = sum(Fraction(a[k]["sum_delta_em"], n) for k in a)
    assert lhs == rhs
    out["a_decomposition_exact"] = True
    by_cfg = group(lambda p: p[0]["configuration"])
    for k, v in by_cfg.items():
        v.update(cfg_info[k])
    out["b_by_q_configuration"] = by_cfg
    out["c_by_type"] = group(lambda p: task_type(p[0]["task_id"])[0])
    out["c_by_hops"] = group(lambda p: task_type(p[0]["task_id"])[1])
    out["c_by_type_x_gleich"] = group(lambda p: f"{task_type(p[0]['task_id'])[0]} | {dev(p)}")
    out["c_by_hops_x_gleich"] = group(lambda p: f"{task_type(p[0]['task_id'])[1]} | {dev(p)}")
    out["c_id_count_mismatch"] = sum(1 for p in pairs if not task_type(p[0]["task_id"])[2])
    out["d_by_form"] = group(lambda p: cfg_info[p[0]["configuration"]]["form"])
    out["d_by_shared_roles_with_c01"] = group(lambda p: cfg_info[p[0]["configuration"]]["shared_roles_with_c01"])

    def cost_dir(p):
        cq, cf = Decimal(p[0]["cost_usd"]), Decimal(p[1]["cost_usd"])
        return "C_Q > C_F" if cq > cf else ("C_Q < C_F" if cq < cf else "C_Q = C_F")
    out["d_abweichend_by_block_cost_direction"] = {
        k: describe(v, total_loss) for k, v in sorted(
            {d: [p for p in pairs if dev(p) == "abweichend" and cost_dir(p) == d]
             for d in ("C_Q > C_F", "C_Q = C_F", "C_Q < C_F")}.items())}
    out["d_gleich_by_block_cost_direction"] = {
        k: describe(v, total_loss) for k, v in sorted(
            {d: [p for p in pairs if dev(p) == "gleich" and cost_dir(p) == d]
             for d in ("C_Q > C_F", "C_Q = C_F", "C_Q < C_F")}.items())}
    task_cfgs = defaultdict(set)
    for q, _ in pairs:
        task_cfgs[q["task_id"]].add(q["configuration"])
    out["consistency_tasks"] = len(task_cfgs)
    out["consistency_tasks_with_more_than_one_q_config"] = sum(1 for v in task_cfgs.values() if len(v) > 1)
    out["consistency_tasks_gleich"] = sum(1 for v in task_cfgs.values() if v == {"C01"})
    return out, task_cfgs


def strict(value):
    """Nicht endliche Zahlen wie in final_analysis als Zeichenkette kodieren (gültiges JSON)."""
    if isinstance(value, float) and not math.isfinite(value):
        return None if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {k: strict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [strict(v) for v in value]
    return value


def main():
    prespec_sha = check_prespec()
    for rel, digest in CODE_SHA.items():
        assert sha_file(EVAL / rel) == digest, rel
    assert sha_file(R_ROWS) == R_SHA
    sys.path.insert(0, str(EVAL))
    from study_preparation import intervals  # noqa: E402
    from study_preparation.final_analysis import PRIMARY_ENDPOINTS  # noqa: E402
    from communication_pruning.configurations import bank  # noqa: E402

    c01_roles = set(next(c for c in bank() if c.config_id == "C01").roles)
    cfg_info = {}
    for c in bank():
        k = len(c.roles)
        e = len(c.edges)
        form = ("C01 (wie F*)" if c.config_id == "C01" else "andere Zweiergruppe" if k == 2
                else "Dreiergruppe Ring" if e == 3 else "Dreiergruppe vollvernetzt")
        assert (k, e) in ((2, 2), (3, 3), (3, 6))
        cfg_info[c.config_id] = {"roles": list(c.roles), "n_roles": k, "n_edges": e, "form": form,
                                 "shared_roles_with_c01": len(c01_roles & set(c.roles))}
    assert len(cfg_info) == 14

    # Schritt 1: P exakt reproduzieren
    assert derive_seed("P-bootstrap") == PRIMARY_SEED
    p_rows = load_p_rows()
    assert len(p_rows) == 18080
    p_pairs = make_pairs(p_rows, 9040)
    atoms = np.asarray([[q["em"] - f["em"], float(Decimal(q["cost_usd"])), float(Decimal(f["cost_usd"]))]
                        for q, f in p_pairs], dtype=float)
    main_res = intervals.analyze(atoms, np.ones(9040, dtype=np.int64), deepcopy(PRIMARY_ENDPOINTS),
                                 rng=np.random.Generator(np.random.PCG64(PRIMARY_SEED)), bootstrap_reps=B)
    ref = json.loads((ROOT / "04_ergebnisse/belege/P/P-ANALYSIS.json").read_text())["report"]
    for ep in ("P-D", "P-C"):
        for k in ("estimate", "se", "lower", "upper", "status", "undefined_resamples"):
            assert main_res["endpoints"][ep][k] == ref["primary"]["kernel"]["endpoints"][ep][k], (ep, k)
    em_q = math.fsum(q["em"] for q, _ in p_pairs) / 9040
    em_f = math.fsum(f["em"] for _, f in p_pairs) / 9040
    assert em_q == ref["estimates"]["Q"]["em"] == 0.3199115044247788
    assert em_f == ref["estimates"]["F"]["em"] == 0.3620575221238938
    f1_q = math.fsum(q["f1"] for q, _ in p_pairs) / 9040
    f1_f = math.fsum(f["f1"] for _, f in p_pairs) / 9040
    assert f1_q == 0.4359280383754858 and f1_f == 0.48077504695132584
    dcount = Counter(int(q["em"] - f["em"]) for q, f in p_pairs)
    assert dcount == Counter({0: 8041, -1: 690, 1: 309})
    step1_p = {ep: {k: main_res["endpoints"][ep][k] for k in ("estimate", "se", "lower", "upper")}
               for ep in ("P-D", "P-C")}

    # Schritt 1: R exakt reproduzieren
    r_rows = json.loads(R_ROWS.read_text())
    r_pairs = make_pairs(r_rows, 2952)
    ref_r = json.loads((ROOT / "04_ergebnisse/belege/RTF/ANALYSIS-R.json").read_text())
    assert ref_r["rows_sha256"] == R_SHA
    rr = ref_r["report"]
    r_em_q = math.fsum(q["em"] for q, _ in r_pairs) / 2952
    r_em_f = math.fsum(f["em"] for _, f in r_pairs) / 2952
    assert r_em_q == rr["estimates"]["Q"]["em"] == 0.29336043360433606
    assert r_em_f == rr["estimates"]["F"]["em"] == 0.3434959349593496
    r05 = float(np.mean(np.asarray([q["em"] - f["em"] for q, f in r_pairs], dtype=float)))
    assert r05 == rr["secondary_quality"]["em"]["R05"]["estimate"] == -0.05013550135501355, r05
    with localcontext() as ctx:
        ctx.prec = 50
        cq = sum(Decimal(q["cost_usd"]) for q, _ in r_pairs) / 2952
        cf = sum(Decimal(f["cost_usd"]) for _, f in r_pairs) / 2952
        r05_cost = str(cq / cf)
        assert r05_cost == rr["descriptive_costs"]["endpoints"]["R05"]["estimate"], r05_cost
    r_cfg = Counter(q["configuration"] for q, _ in r_pairs)
    assert r_cfg["C01"] == 487 and len(r_cfg) == 14
    step1_r = {"em_q": r_em_q, "em_f": r_em_f, "r05_em": r05, "r05_cost_ratio": r05_cost}

    # Aufschlüsselungen
    p_out, p_task_cfgs = breakdown(p_pairs, cfg_info)
    r_out, r_task_cfgs = breakdown(r_pairs, cfg_info)
    shared = set(p_task_cfgs) & set(r_task_cfgs)
    cross = {"shared_tasks": len(shared),
             "shared_tasks_same_q_config": sum(1 for t in shared if p_task_cfgs[t] == r_task_cfgs[t])}

    # Vorab festgelegte Intervalle, nur P
    def atoms_of(members):
        a = np.zeros(8)
        for q, f in members:
            d1 = q["em"] - f["em"] + 1
            cq_, cf_ = float(Decimal(q["cost_usd"])), float(Decimal(f["cost_usd"]))
            if q["configuration"] != "C01":
                a += [d1, 1, 0, 0, cq_, cf_, 0, 0]
            else:
                a += [0, 0, d1, 1, 0, 0, cq_, cf_]
        return a

    eps = [{"id": "delta_abw+1", "kind": "ratio", "numerator": [1, 0, 0, 0, 0, 0, 0, 0], "denominator": [0, 1, 0, 0, 0, 0, 0, 0]},
           {"id": "delta_gleich+1", "kind": "ratio", "numerator": [0, 0, 1, 0, 0, 0, 0, 0], "denominator": [0, 0, 0, 1, 0, 0, 0, 0]},
           {"id": "rho_abw", "kind": "ratio", "numerator": [0, 0, 0, 0, 1, 0, 0, 0], "denominator": [0, 0, 0, 0, 0, 1, 0, 0]},
           {"id": "rho_gleich", "kind": "ratio", "numerator": [0, 0, 0, 0, 0, 0, 1, 0], "denominator": [0, 0, 0, 0, 0, 0, 0, 1]}]

    def run(units, seed, label):
        cat = np.asarray([atoms_of(u) for u in units], dtype=float)
        res = intervals.analyze(cat, np.ones(len(units), dtype=np.int64), deepcopy(eps),
                                rng=np.random.Generator(np.random.PCG64(seed)), bootstrap_reps=B)
        out = {"label": label, "seed": str(seed), "units": len(units)}
        for e in eps:
            r = res["endpoints"][e["id"]]
            shift = 1 if e["id"].endswith("+1") else 0
            out[e["id"].replace("+1", "")] = {"estimate": r["estimate"] - shift, "se": r["se"],
                                              "lower": r["lower"] - shift, "upper": r["upper"] - shift,
                                              "status": r["status"], "undefined_resamples": r["undefined_resamples"]}
        return out

    seeds = {"pair": derive_seed("P-qverlust-pair-bootstrap"), "task": derive_seed("P-qverlust-task-bootstrap")}
    by_task = defaultdict(list)
    for p in p_pairs:
        by_task[p[0]["task_id"]].append(p)
    ci = {"pair": run([[p] for p in p_pairs], seeds["pair"], "Paar als Ziehungseinheit (Haupt)"),
          "task": run([by_task[k] for k in sorted(by_task)], seeds["task"], "Aufgabe als Ziehungseinheit (Sensitivität)")}
    # Punktwerte müssen mit der Beschreibung übereinstimmen
    pa = p_out["a_gleich_abweichend"]
    for v in ci.values():
        assert abs(v["delta_abw"]["estimate"] - pa["abweichend"]["delta_em"]) < 1e-12
        assert abs(v["delta_gleich"]["estimate"] - pa["gleich"]["delta_em"]) < 1e-12
        assert abs(v["rho_abw"]["estimate"] - pa["abweichend"]["cost_ratio"]) < 1e-12
        assert abs(v["rho_gleich"]["estimate"] - pa["gleich"]["cost_ratio"]) < 1e-12

    out = {"post_hoc_explanatory": True, "prespec_sha256": prespec_sha,
           "inputs": {"P_state_sha256": STATE_SHA, "R_rows_sha256": R_SHA, "code_sha256": CODE_SHA},
           "numpy": np.__version__, "python": sys.version.split()[0], "bootstrap_reps": B,
           "seeds": {"primary": str(PRIMARY_SEED), **{k: str(v) for k, v in seeds.items()}},
           "configurations": cfg_info,
           "step1": {"P": step1_p | {"em_q": em_q, "em_f": em_f, "f1_q": f1_q, "f1_f": f1_f,
                                     "delta_counts": {str(k): v for k, v in sorted(dcount.items())}},
                     "R": step1_r | {"q_config_counts": dict(r_cfg.most_common())}},
           "P": p_out, "R": r_out, "cross_panel_q_config": cross, "intervals_P": ci}
    (HERE / "Q-VERLUST-AUFSCHLUESSELUNG.json").write_text(json.dumps(strict(out), indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    for name, o in (("P", p_out), ("R", r_out)):
        print(name, "Verlust", o["total_loss_sum_delta_em"])
        for k, v in o["a_gleich_abweichend"].items():
            print(" ", k, v["n"], round(v["delta_em"], 4), round(v["share_of_total_loss"], 3), round(v["cost_ratio"], 4))
        print("  Konsistenz", o["consistency_tasks"], o["consistency_tasks_with_more_than_one_q_config"])
    print("cross", cross)
    for k, v in ci.items():
        print(k, {e: (round(v[e]["lower"], 4), round(v[e]["upper"], 4), v[e]["status"])
                  for e in ("delta_abw", "delta_gleich", "rho_abw", "rho_gleich")})


if __name__ == "__main__":
    main()
