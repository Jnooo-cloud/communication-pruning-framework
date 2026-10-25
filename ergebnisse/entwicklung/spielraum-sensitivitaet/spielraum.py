"""Sensitivität des Auswahlspielraums (VORAB.md). Nur Standardbibliothek, liest das alte Repo nur.

Kein Neutraining: gespeicherte Z39-Vorhersagen der Faltenmodelle, nur die Auswahlregel variiert.
"""
from collections import Counter
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import math
import sys

HIER = Path(__file__).resolve().parent
RUN = (HIER.parents[3] / "Masterarbeit" / "eval-harness" / "eval" / "runs"
       / "Z39-RAEUM-ENTWICKLUNG-001" / "recovery-fit" / "run-001").resolve()
TOL = 1e-12
SPIELRAEUME = [("0", 0.0), ("0,5", 0.005), ("1", 0.01), ("2", 0.02), ("3", 0.03)]
EINGABEN = {
    "OOF-and-filter-diagnosis.json": "5c0fbe65f02193dfedf27a10e402aa50aca861599eceb40f09e685bb89409013",
    "raw-Q-sem.json": "c48fa831b8db4e9319072dd508a527944f8797c1fc647e1eea56fd050518a097",
    "F-star.json": "9050e4acd90d38cce94558c95b11c38ba667fd435e13a4f0095075711597c61b",
    "development-means.json": "9719dd0357bf15775c5b105d63361d28b6d9d58e5f79a681158873f5385d5ad7",
    "RESULT.json": "b911b890cd749f1937ea71a7eb9f4326f1889adb0dd01e5f08a4e5bf3a882581",
}
VORAB_SHA = "1750acb9588afa72cc3807584fbb7c86ab10aa67f499570698e5ab3a987bbf59"


def fail(msg):
    print("ABBRUCH:", msg, file=sys.stderr)
    sys.exit(2)


def load(name):
    data = (RUN / name).read_bytes()
    if sha256(data).hexdigest() != EINGABEN[name]:
        fail("Hash weicht ab: " + name)
    return json.loads(data)


def waehle(werte, kosten, ids, eps):
    """Wie selection.choose / semantic_selection.choose_scores, mit variablem eps."""
    best = max(werte)
    zul = [i for i, w in enumerate(werte) if w >= best - eps - TOL]
    return min(zul, key=lambda i: (kosten[i], ids[i])), len(zul)


def alpha_wahl(berichte, eps):
    best = max(b["em_q"] for b in berichte)
    zul = [b for b in berichte if b["em_q"] >= best - eps - TOL]
    return min(zul, key=lambda b: (Decimal(b["kosten_q"]), -b["alpha"]))["alpha"]


def kv(report, eps, ids, dev):
    """Kreuzvalidierung für ein Alpha mit Spielraum eps."""
    modelle = {f["fold"]: f["model"] for f in report["folds"]}
    fstar = {}
    for fold, m in modelle.items():
        kosten = tuple(Decimal(c) for c in m["costs"])
        fstar[fold], _ = waehle(m["training_quality"], kosten, ids, eps)
    zeilen = []
    for o in report["outcomes"]:
        m = modelle[o["fold"]]
        kosten = tuple(Decimal(c) for c in m["costs"])
        q, _ = waehle(o["scores"], kosten, ids, eps)
        f = fstar[o["fold"]]
        d = dev[o["task_id"]]
        zeilen.append({"task_id": o["task_id"], "fold": o["fold"], "q": q, "f": f,
                       "q_em": d["quality_em"][q], "f_em": d["quality_em"][f],
                       "q_kosten": Decimal(d["cost_usd"][q]), "f_kosten": Decimal(d["cost_usd"][f])})
    n = len(zeilen)
    em_q = math.fsum(z["q_em"] for z in zeilen) / n
    em_f = math.fsum(z["f_em"] for z in zeilen) / n
    k_q = sum((z["q_kosten"] for z in zeilen), Decimal(0)) / n
    k_f = sum((z["f_kosten"] for z in zeilen), Decimal(0)) / n
    abw = sum(z["q"] != z["f"] for z in zeilen)
    return {"alpha": report["alpha"], "n": n, "em_q": em_q, "em_f": em_f,
            "diff_pp": (em_q - em_f) * 100, "kosten_q": str(k_q), "kosten_f": str(k_f),
            "kostenverhaeltnis": float(k_q / k_f), "abweichend": abw, "anteil_abweichend": abw / n,
            "fstar_je_falte": {str(k): ids[v] for k, v in sorted(fstar.items())},
            "verteilung_q": dict(sorted(Counter(ids[z["q"]] for z in zeilen).items())),
            "verteilung_f": dict(sorted(Counter(ids[z["f"]] for z in zeilen).items())),
            "_zeilen": zeilen}


def main():
    if sha256((HIER / "VORAB.md").read_bytes()).hexdigest() != VORAB_SHA:
        fail("VORAB.md weicht vom gehashten Stand ab")
    oof = load("OOF-and-filter-diagnosis.json")
    raw = load("raw-Q-sem.json")
    fs = load("F-star.json")
    devl = load("development-means.json")
    res = load("RESULT.json")
    ids = raw["config_ids"]
    dev = {d["task_id"]: d for d in devl}
    if len(dev) != 300 or len(ids) != 14:
        fail("Umfang")
    berichte = {r["alpha"]: r for r in oof["cross_validation"]}

    # ---------- Reproduktion bei 1 Prozentpunkt ----------
    rep = {}
    r100 = kv(berichte[100], 0.01, ids, dev)
    gespeichert = {o["task_id"]: o for o in berichte[100]["outcomes"]}
    for z in r100["_zeilen"]:
        o = gespeichert[z["task_id"]]
        if (z["q"] != o["selected_index"] or z["f"] != o["fixed_index"] or z["q_em"] != o["quality"]
                or z["f_em"] != o["fixed_quality"] or z["q_kosten"] != Decimal(o["cost_usd"])
                or z["f_kosten"] != Decimal(o["fixed_cost_usd"])):
            fail("Einzelwahl weicht ab: " + z["task_id"])
    rep["einzelwahlen_300_identisch"] = True
    alle = {a: kv(berichte[a], 0.01, ids, dev) for a in (1, 10, 100)}
    for a, b in alle.items():
        if b["em_q"] != berichte[a]["quality"] or Decimal(b["kosten_q"]) != Decimal(berichte[a]["cost_usd"]) \
                or b["em_f"] != berichte[a]["fixed_quality"] \
                or Decimal(b["kosten_f"]) != Decimal(berichte[a]["fixed_cost_usd"]):
            fail("Mittel weichen ab, Alpha %d" % a)
    checks = {
        "em_q_35_33": f"{r100['em_q']*100:.2f}" == "35.33",
        "em_f_39_00": f"{r100['em_f']*100:.2f}" == "39.00",
        "diff_-3_6667": f"{r100['diff_pp']:.4f}" == "-3.6667",
        "kostenverhaeltnis_1_114032": f"{r100['kostenverhaeltnis']:.6f}" == "1.114032",
        "oof_abweichend_253": r100["abweichend"] == 253,
        "alpha_100": alpha_wahl(list(alle.values()), 0.01) == 100 == oof["chosen_alpha"] == res["chosen_alpha"],
        "final_q_251_ungleich_C01": sum(s != "C01" for s in raw["training_selections"]) == 251,
        "fstar_300_C01": waehle(fs["training_quality_em"], tuple(Decimal(c) for c in fs["training_cost_usd"]), ids, 0.01)[0] == 0
                          and fs["config_id"] == "C01",
        "fstar_300_em_0_4033333": f"{fs['training_quality_em'][0]:.7f}" == "0.4033333",
    }
    if not all(checks.values()):
        fail("Reproduktion: " + json.dumps(checks))
    rep.update(checks)

    # ---------- Spielräume ----------
    tq = fs["training_quality_em"]
    tk = tuple(Decimal(c) for c in fs["training_cost_usd"])
    ergebnisse = []
    for label, eps in SPIELRAEUME:
        fi, nzul = waehle(tq, tk, ids, eps)
        a = {"konfiguration": ids[fi], "em": tq[fi], "mittlere_kosten_usd": str(tk[fi]), "zugelassen": nzul}
        drei = {al: kv(berichte[al], eps, ids, dev) for al in (1, 10, 100)}
        haupt = drei[100]
        alpha_eps = alpha_wahl(list(drei.values()), eps)
        def sauber(b):
            return {k: v for k, v in b.items() if not k.startswith("_")}
        ergebnisse.append({
            "spielraum_pp": label, "epsilon": eps,
            "a_fstar_300": a,
            "b_kv_alpha100": sauber(haupt),
            "c1_alpha_neu_gewaehlt": alpha_eps,
            "c1_kv_gewaehltes_alpha": sauber(drei[alpha_eps]),
            "c1_alle_alphas": {str(al): {k: sauber(b)[k] for k in ("em_q", "em_f", "diff_pp", "kosten_q", "kosten_f",
                                                                  "kostenverhaeltnis", "abweichend")}
                               for al, b in drei.items()},
            "c2_filter_gleicher_spielraum_zugelassen": haupt["em_q"] >= haupt["em_f"] - eps - TOL,
            "c2_filter_1pp_zugelassen": haupt["em_q"] >= haupt["em_f"] - 0.01 - TOL,
        })
    out = {"schema": "spielraum-sensitivitaet/v1", "vorab_sha256": VORAB_SHA,
           "eingaben": {k: {"pfad": str(RUN / k), "sha256": v} for k, v in EINGABEN.items()},
           "reproduktion_1pp": rep, "ergebnisse": ergebnisse,
           "hinweis": "Kein Neutraining; abschließendes Q (251) nur bei 1 pp reproduziert, nicht für andere Spielräume."}
    (HIER / "SPIELRAUM-ERGEBNIS.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(rep, indent=1))
    for e in ergebnisse:
        b = e["b_kv_alpha100"]
        print(e["spielraum_pp"], e["a_fstar_300"]["konfiguration"], round(e["a_fstar_300"]["em"], 4),
              e["a_fstar_300"]["zugelassen"], "|", round(b["em_q"]*100, 2), round(b["em_f"]*100, 2),
              round(b["diff_pp"], 2), round(b["kostenverhaeltnis"], 4), b["abweichend"], b["fstar_je_falte"],
              "| alpha", e["c1_alpha_neu_gewaehlt"], "| filter", e["c2_filter_gleicher_spielraum_zugelassen"],
              e["c2_filter_1pp_zugelassen"])
        print("   Q:", b["verteilung_q"])
        print("   F:", b["verteilung_f"])


if __name__ == "__main__":
    main()
