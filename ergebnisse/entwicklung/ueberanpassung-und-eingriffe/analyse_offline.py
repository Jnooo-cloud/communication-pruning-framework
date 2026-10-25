"""Offline-Prüfung nach ANALYSEPLAN.md (A0 bis A4, B1 bis B3).

Liest: analyse/features-300.npz, Z39 raw-Q-sem.json und development-means.json.
Schreibt: analyse/ergebnis-offline.json. Keine Modellaufrufe.
"""
import json
import math
from decimal import Decimal
from pathlib import Path

import numpy as np
from sklearn.decomposition import PCA
from sklearn.linear_model import Ridge

ROOT = Path("/Users/jannikhiller/Desktop/ai operations/Studium OS/Masterarbeit")
FIT = ROOT / "eval-harness/eval/runs/Z39-RAEUM-ENTWICKLUNG-001/recovery-fit/run-001"
OUT = Path(__file__).resolve().parent
EPS, TOL = 0.01, 1e-12
ALPHAS_ORIG = [1, 10, 100]
ALPHAS = [1, 10, 100, 1_000, 10_000, 100_000, 1_000_000]
VARIANTS = ["text4", "pca5", "pca20", "voll"]  # nach Merkmalszahl aufsteigend (Gleichstandsregel A4)
SEED, REPS = 20261019, 10_000

raw = json.loads((FIT / "raw-Q-sem.json").read_text(encoding="utf-8"))
dm = json.loads((FIT / "development-means.json").read_text(encoding="utf-8"))
data = np.load(OUT / "features-300.npz")
X = data["X"]
ORDER = list(raw["task_families"])
assert list(data["task_ids"]) == ORDER
assert [r["task_id"] for r in dm] == ORDER, "Reihenfolge der Entwicklungsmittel weicht ab"
CONFIG = raw["config_ids"]
Y = np.asarray([r["quality_em"] for r in dm], dtype=float)          # 300 x 14
COST = [[Decimal(c) for c in r["cost_usd"]] for r in dm]            # 300 x 14, Decimal
FAM = [raw["task_families"][t] for t in ORDER]
assert all(r["family_id"] == f for r, f in zip(dm, FAM))
POS = {t: i for i, t in enumerate(ORDER)}
FOLDS = [[POS[t] for t in fold] for fold in raw["folds"]]


def mean_costs(idx):
    n = len(idx)
    return [sum((COST[i][k] for i in idx), Decimal(0)) / n for k in range(14)]


def choose(values, costs):
    best = max(values)
    eligible = [k for k, v in enumerate(values) if v >= best - EPS - TOL]
    return min(eligible, key=lambda k: (costs[k], CONFIG[k]))


def design(variant, train, test):
    emb, txt = X[:, :384], X[:, 384:388]
    if variant == "voll":
        a, b = X[train], X[test]
    elif variant == "text4":
        a, b = txt[train], txt[test]
    else:
        k = int(variant[3:])
        pca = PCA(n_components=k, svd_solver="full").fit(emb[train])
        a = np.hstack([pca.transform(emb[train]), txt[train]])
        b = np.hstack([pca.transform(emb[test]), txt[test]])
    mean = a.mean(axis=0)
    scale = a.std(axis=0, ddof=0)
    const = np.ptp(a, axis=0) == 0
    scale[const] = 1.0
    za, zb = (a - mean) / scale, (b - mean) / scale
    za[:, const] = 0.0
    zb[:, const] = 0.0
    return za, zb, const


def fit_predict(variant, alpha, train, test):
    za, zb, const = design(variant, train, test)
    est = Ridge(alpha=alpha, fit_intercept=True, solver="svd").fit(za, Y[train])
    est.coef_[:, const] = 0.0
    return est.predict(zb), est.predict(za)


def evaluate(variant, alpha, train, test):
    """Wahl auf test (und auf train) mit Kosten aus train; Rückgabe je Aufgabe."""
    pred_test, pred_train = fit_predict(variant, alpha, train, test)
    costs = mean_costs(train)
    fixed = choose(list(Y[train].mean(axis=0)), costs)
    sel_test = [choose(list(p), costs) for p in pred_test]
    sel_train = [choose(list(p), costs) for p in pred_train]
    return {"test": [(i, s) for i, s in zip(test, sel_test)], "train": [(i, s) for i, s in zip(train, sel_train)],
            "fixed": fixed, "pred_test": pred_test}


def cv(variant, alpha, folds, rows=None):
    out, train_q, fixed_rows = [], [], []
    for f, held in enumerate(folds):
        train = [i for g, fold in enumerate(folds) if g != f for i in fold]
        r = evaluate(variant, alpha, train, held)
        out += r["test"]
        fixed_rows += [(i, r["fixed"]) for i in held]
        train_q.append(np.mean([Y[i, s] for i, s in r["train"]]))
    n = len(out)
    q = math.fsum(Y[i, s] for i, s in out) / n
    c = sum((COST[i][s] for i, s in out), Decimal(0)) / n
    fq = math.fsum(Y[i, s] for i, s in fixed_rows) / n
    fc = sum((COST[i][s] for i, s in fixed_rows), Decimal(0)) / n
    return {"quality": q, "cost": c, "fixed_quality": fq, "fixed_cost": fc,
            "train_quality": float(np.mean(train_q)), "sel": dict(out), "fixed_sel": dict(fixed_rows)}


def cluster_boot(diff_by_task, idx, stat="mean", num=None, den=None):
    """Familien-Cluster-Bootstrap; diff_by_task: Werte je Aufgabe (oder num/den für Verhältnis)."""
    rng = np.random.default_rng(SEED)
    fams = sorted({FAM[i] for i in idx})
    members = {f: [i for i in idx if FAM[i] == f] for f in fams}
    vals = []
    for _ in range(REPS):
        draw = rng.integers(0, len(fams), len(fams))
        rows = [i for d in draw for i in members[fams[d]]]
        if stat == "mean":
            vals.append(np.mean([diff_by_task[i] for i in rows]))
        else:
            vals.append(np.sum([num[i] for i in rows]) / np.sum([den[i] for i in rows]))
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


res = {"plan": "ANALYSEPLAN.md", "seed": SEED, "reps": REPS}

# A0 Reproduktion
a0 = {}
stored = {c["alpha"]: c for c in raw["cross_validation"]}
for alpha in ALPHAS_ORIG:
    maxdev = 0.0
    for f, held in enumerate(FOLDS):
        train = [i for g, fold in enumerate(FOLDS) if g != f for i in fold]
        pred, _ = fit_predict("voll", alpha, train, held)
        st = {o["task_id"]: o["scores"] for o in stored[alpha]["outcomes"] if o["fold"] == f}
        for i, p in zip(held, pred):
            maxdev = max(maxdev, float(np.max(np.abs(np.asarray(st[ORDER[i]]) - p))))
    r = cv("voll", alpha, FOLDS)
    a0[alpha] = {"max_abs_score_dev": maxdev, "quality": r["quality"], "stored_quality": stored[alpha]["quality"],
                 "fixed_quality": r["fixed_quality"], "stored_fixed_quality": stored[alpha]["fixed_quality"]}
ok = all(v["max_abs_score_dev"] < 1e-6 and abs(v["quality"] - v["stored_quality"]) < 1e-12
         and abs(v["fixed_quality"] - v["stored_fixed_quality"]) < 1e-12 for v in a0.values())
res["A0"] = {"pass": ok, "by_alpha": a0}
if not ok:
    (OUT / "ergebnis-offline.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    raise SystemExit("A0 nicht bestanden, Abbruch nach Plan")

# A1 Überanpassungslücke und abschließendes Modell
everything = list(range(300))
final = evaluate("voll", 100, everything, everything)
res["A1_final_in_sample_quality"] = float(np.mean([Y[i, s] for i, s in final["test"]]))
res["A1_oracle_quality"] = float(np.mean(Y.max(axis=1)))
res["A1_training_selections_match"] = [CONFIG[s] for _, s in final["test"]] == raw["training_selections"]

# A2 und A3: Raster je Variante (ohne Verschachtelung)
grid = {}
for v in VARIANTS:
    for alpha in ALPHAS:
        r = cv(v, alpha, FOLDS)
        grid["%s|%d" % (v, alpha)] = {k: (str(x) if isinstance(x, Decimal) else x) for k, x in r.items()
                                       if k not in ("sel", "fixed_sel")}
res["A2_A3_grid"] = grid

# A4 verschachtelt
outcomes = []
chosen = []
for f, held in enumerate(FOLDS):
    train = [i for g, fold in enumerate(FOLDS) if g != f for i in fold]
    fams = sorted({FAM[i] for i in train})
    inner_of = {fam: k % 4 for k, fam in enumerate(fams)}
    inner = [[i for i in train if inner_of[FAM[i]] == k] for k in range(4)]
    reports = []
    for v in VARIANTS:
        for alpha in ALPHAS:
            r = cv(v, alpha, inner)
            reports.append((v, alpha, r["quality"], r["cost"]))
    best = max(q for _, _, q, _ in reports)
    eligible = [x for x in reports if x[2] >= best - EPS - TOL]
    v, alpha, _, _ = min(eligible, key=lambda x: (x[3], -x[1], VARIANTS.index(x[0])))
    chosen.append({"outer_fold": f, "variant": v, "alpha": alpha, "inner_best_quality": best})
    r = evaluate(v, alpha, train, held)
    for i, s in r["test"]:
        outcomes.append((i, s, r["fixed"]))
q = np.array([Y[i, s] for i, s, _ in outcomes])
fq = np.array([Y[i, fx] for i, _, fx in outcomes])
idx = [i for i, _, _ in outcomes]
diff = {i: Y[i, s] - Y[i, fx] for i, s, fx in outcomes}
lo, hi = cluster_boot(diff, idx)
cq = sum((COST[i][s] for i, s, _ in outcomes), Decimal(0)) / 300
cf = sum((COST[i][fx] for i, _, fx in outcomes), Decimal(0)) / 300
res["A4"] = {"chosen": chosen, "quality": float(q.mean()), "fixed_quality": float(fq.mean()),
             "difference_pp": float((q.mean() - fq.mean()) * 100), "ci95_pp": [lo * 100, hi * 100],
             "cost_ratio": float(cq / cf),
             "criterion_met_for_extra_run": bool((q.mean() - fq.mean()) * 100 >= 1.0)}

# B Zerlegung auf der Entwicklungsmatrix
ix = {c: k for k, c in enumerate(CONFIG)}
C = np.asarray([[float(x) for x in row] for row in COST])
ALL = list(range(300))


def contrast(pairs):
    """pairs: Liste (a, b); Differenz a minus b je Aufgabe, gemittelt über die Paare."""
    d = {i: np.mean([Y[i, ix[a]] - Y[i, ix[b]] for a, b in pairs]) for i in ALL}
    lo, hi = cluster_boot(d, ALL)
    num = {i: sum(C[i, ix[a]] for a, _ in pairs) for i in ALL}
    den = {i: sum(C[i, ix[b]] for _, b in pairs) for i in ALL}
    clo, chi = cluster_boot(None, ALL, stat="ratio", num=num, den=den)
    return {"diff_pp": float(np.mean(list(d.values())) * 100), "ci95_pp": [lo * 100, hi * 100],
            "cost_ratio": float(sum(num.values()) / sum(den.values())), "cost_ratio_ci95": [clo, chi]}


TRIADS = {"BVE": ("C07", "C08", ["C01", "C02", "C04"]), "BVW": ("C09", "C10", ["C01", "C03", "C05"]),
          "BEW": ("C11", "C12", ["C02", "C03", "C06"]), "VEW": ("C13", "C14", ["C04", "C05", "C06"])}
b1 = {name: contrast([(voll, ring)]) for name, (ring, voll, _) in TRIADS.items()}
b1["gepoolt"] = contrast([(voll, ring) for ring, voll, _ in TRIADS.values()])
res["B1_voll_minus_ring"] = b1
PAIRS = {"B": ["C01", "C02", "C03"], "V": ["C01", "C04", "C05"], "E": ["C02", "C04", "C06"], "W": ["C03", "C05", "C06"]}
b2 = {}
for role, with_ in PAIRS.items():
    without = [c for c in ["C01", "C02", "C03", "C04", "C05", "C06"] if c not in with_]
    d = {i: np.mean([Y[i, ix[c]] for c in with_]) - np.mean([Y[i, ix[c]] for c in without]) for i in ALL}
    lo, hi = cluster_boot(d, ALL)
    b2[role] = {"diff_pp": float(np.mean(list(d.values())) * 100), "ci95_pp": [lo * 100, hi * 100]}
b2["zweiergruppen_em"] = {c: float(Y[:, ix[c]].mean() * 100) for c in ["C01", "C02", "C03", "C04", "C05", "C06"]}
res["B2_rolle_in_zweiergruppen"] = b2
res["B3_dreier_minus_zweier"] = {
    "ring": contrast([(ring, p) for ring, _, ps in TRIADS.values() for p in ps]),
    "voll": contrast([(voll, p) for _, voll, ps in TRIADS.values() for p in ps])}

(OUT / "ergebnis-offline.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps({"A0": res["A0"]["pass"], "A1": res["A1_final_in_sample_quality"],
                  "A1_match": res["A1_training_selections_match"], "A4": res["A4"]}, indent=1, default=str))
