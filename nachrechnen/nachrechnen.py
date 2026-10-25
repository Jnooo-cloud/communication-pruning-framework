"""Rechnet die Kernzahlen der Arbeit aus den Ergebniszeilen nach.

Aufruf aus der Wurzel des Repositorys:
    python3 nachrechnen/nachrechnen.py

Voraussetzungen: Python ab 3.10 und NumPy (Studienumgebung: Python 3.12.14, NumPy 1.26.4).
Keine Netzwerkzugriffe, keine Modellaufrufe. Dauer rund 10 Sekunden.

1. Haupt-, Referenz-, Runden- und Ausfallvergleich sowie der Referenzvergleich mit neuem
   Abstimmungsarm werden mit der unveraenderten Auswertungsfunktion
   `study_preparation.final_analysis.analyze_panel` (Commit ad152f2), dem eingefrorenen Plan
   und dem vorab gebundenen Seed neu berechnet und mit den gespeicherten Analyseausgaben
   verglichen. Gleitkommawerte duerfen sich je nach Umgebung in den letzten Stellen
   unterscheiden (relative Toleranz 1e-12); alles andere muss exakt gleich sein.
2. Einige im Text genannte Zaehlungen werden direkt aus den Zeilen nachgezaehlt.
"""
import json
import math
import sys
import warnings
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "studiencode-ad152f2/eval-harness/eval"))

from study_preparation.final_analysis import analyze_panel  # noqa: E402

E = "ergebnisse/ergaenzende-vergleiche"
PANELS = [
    ("Hauptvergleich (P)", "P", "ergebnisse/hauptvergleich/P-ROWS.json", "ergebnisse/hauptvergleich/P-ANALYSIS.json"),
    ("Referenzvergleich (R)", "R", f"{E}/zeilen/rows-R.json", f"{E}/ANALYSIS-R.json"),
    ("Referenzvergleich mit neuem Abstimmungsarm (R)", "R", f"{E}/abstimmungsarm-nachstudie/rows-R-SK.json",
     f"{E}/abstimmungsarm-nachstudie/ANALYSIS-R-SK.json"),
    ("Rundenvergleich (T)", "T", f"{E}/zeilen/rows-T.json", f"{E}/ANALYSIS-T.json"),
    ("Ausfallvergleich (F)", "F", f"{E}/zeilen/rows-F.json", f"{E}/ANALYSIS-F.json"),
]


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def compare(new, old, path=""):
    """Liefert Abweichungen; Gleitkommazahlen mit relativer Toleranz 1e-12."""
    out = []
    if isinstance(new, dict) and isinstance(old, dict):
        for key in sorted(set(new) | set(old)):
            if key not in new or key not in old:
                out.append(f"{path}/{key}: fehlt")
            else:
                out += compare(new[key], old[key], f"{path}/{key}")
    elif isinstance(new, list) and isinstance(old, list) and len(new) == len(old):
        for i, (a, b) in enumerate(zip(new, old)):
            out += compare(a, b, f"{path}[{i}]")
    elif isinstance(new, float) and isinstance(old, float):
        if not math.isclose(new, old, rel_tol=1e-12, abs_tol=1e-15):
            out.append(f"{path}: {new} statt {old}")
    elif new != old:
        out.append(f"{path}: {new!r} statt {old!r}")
    return out


def pp(x):
    return f"{100 * x:.2f}".replace(".", ",")


def main():
    plan = load("auswertungsplan/PLAN.json")
    seed = load("auswertungsplan/ANALYSIS-BINDING.json")["primary_bootstrap_seed"]
    failures = 0
    reports = {}
    for label, panel, rows_rel, analysis_rel in PANELS:
        rows = load(rows_rel)
        with warnings.catch_warnings():
            # NumPy mit Apple Accelerate meldet hier falsche Ueberlauf-Warnungen; Ergebnisse sind endlich.
            warnings.simplefilter("ignore", RuntimeWarning)
            report = analyze_panel(plan, panel, rows, bootstrap_seed=seed)
        diffs = compare(report, load(analysis_rel)["report"])
        failures += bool(diffs)
        print(f"{label}: n={report['n']}, gespeicherte Analyse {'reproduziert' if not diffs else 'ABWEICHEND'}")
        for d in diffs[:10]:
            print("   ", d)
        reports[rows_rel] = (report, rows)

    rep, rows = reports[PANELS[0][2]]
    k = rep["primary"]["kernel"]["endpoints"]
    q, f = rep["estimates"]["Q"], rep["estimates"]["F"]
    pairs = {}
    for r in rows:
        pairs.setdefault(r["draw_index"], {})[r["arm"]] = r
    both = Counter((p["Q"]["em"], p["F"]["em"]) for p in pairs.values())
    print("\nHauptvergleich (Abschnitt 6.3):")
    print(f"  exakt richtig: Q {pp(q['em'])} %, F* {pp(f['em'])} %")
    print(f"  Qualitaetsdifferenz {pp(k['P-D']['estimate'])} Pp., Intervall {pp(k['P-D']['lower'])} bis {pp(k['P-D']['upper'])}")
    print(f"  Kostenverhaeltnis {k['P-C']['estimate']:.3f}, Intervall {k['P-C']['lower']:.3f} bis {k['P-C']['upper']:.3f}".replace(".", ","))
    print(f"  gleiche Antwortwertung {both[(1.0, 1.0)] + both[(0.0, 0.0)]}, nur F* richtig {both[(0.0, 1.0)]}, nur Q richtig {both[(1.0, 0.0)]}")
    print(f"  Modellausfaelle: Q {q['model_failures']}, F* {f['model_failures']}; mittlerer F1: Q {q['f1']:.3f}, F* {f['f1']:.3f}".replace(".", ","))
    tot = rep["descriptive_costs"]["arms"]
    print(f"  bekannte Modellkosten: Q {float(tot['Q']['total']):.2f} US-Dollar, F* {float(tot['F']['total']):.2f} US-Dollar".replace(".", ","))
    print(f"  Aufgaben {len({r['task_id'] for r in rows})}, Familien {len({r['family_id'] for r in rows})}")

    t_rows = reports[f"{E}/zeilen/rows-T.json"][1]
    blocks = {}
    for r in t_rows:
        blocks.setdefault(r["draw_index"], {})[r["arm"]] = r
    two = [b for b in blocks.values() if b["Q-ST"]["rounds"] == 2]
    print("\nRundenvergleich, Bloecke mit Rundenregel zwei Runden (Abschnitt 7.2):")
    print(f"  {len(two)} Bloecke; exakt richtig mit zwei Runden {int(sum(b['Q-ST']['em'] for b in two))}, "
          f"mit einer Runde {int(sum(b['Q-TF']['em'] for b in two))}")

    dev = load("ergebnisse/entwicklung/runden/INPUT.json")["rows"]
    change = Counter((r["quality_em"][1] > r["quality_em"][0]) - (r["quality_em"][1] < r["quality_em"][0]) for r in dev)
    print("\nRundenentwicklung, 100 Aufgaben (Abschnitt 7.2):")
    print(f"  zweite Runde unveraendert {change[0]}, verbessert {change[1]}, verschlechtert {change[-1]}")

    curves = load("ergebnisse/entwicklung/konfigurationen/learning-curves.json")["curves"]
    print("\nLernkurven, Rueckstand von Q gegen F* auf zurueckgehaltenen Teilen (Abschnitt 7.2):")
    for c in curves:
        sel = c["selector"]
        cv = next(x for x in sel["cross_validation"] if x["alpha"] == sel["chosen_alpha"])
        print(f"  {c['n']} Aufgaben: {pp(cv['fixed_quality'] - cv['quality'])} Pp.")

    t = load("nachpruefungen-nach-studienabschluss/pruefroutine-studienlaeufe/run-001/SUMMARY.json")["table"]
    with_log = [v for v in t.values() if "accepted" in v]
    acc = sum(v["accepted"] for v in with_log)
    pre = sum(v.get("accepted_prefix", 0) for v in with_log)
    na = sum(v.get("not_applicable", 0) for v in t.values())
    bad = sum(v["disallowed_messages"] + v["inactive_role_calls"] + v["wrong_round_messages"] for v in with_log)
    print("\nPruefroutine ueber die Studienlaeufe (Abschnitt 6.2; gespeichertes Ergebnis, ohne Laufprotokolle nicht neu berechenbar):")
    print(f"  Laufprotokolle {acc + pre}: abgeschlossen angenommen {acc}, offen als Praefix angenommen {pre}, "
          f"zurueckgewiesen 0; Laeufe ohne solches Protokoll {na}; unerlaubte Nachrichten, Aufrufe nicht aktiver "
          f"Rollen und Nachrichten falscher Runde zusammen {bad}")

    print("\nErgebnis:", "alle gespeicherten Analysen reproduziert" if not failures else f"{failures} Analyse(n) abweichend")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
