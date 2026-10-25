"""oekonomie_rechnung.py: Zahlen für den Abschnitt "Wirtschaftliche Einordnung" (rev10, 19.10.2026).

Rechnet aus vorhandenen Primärdaten, nur lesend, ohne Modellaufrufe (0 USD):
  1. bekannte Modellkosten je 1.000 Aufgaben je Arm (Referenzvergleich, Hauptstudie, neuer Abstimmungsarm)
  2. Kosten der Entwicklungsmatrix (einmalig, Wahl von F* und Q)
  3. Amortisation dieser Entwicklung gegenüber der dichten Vierergruppe
  4. Mehrkosten F* gegenüber Einzelaufruf und Q gegenüber F* je eine Million Aufgaben
  5. nacheinander laufende Modellaufrufe je Arm und, wo Zeitstempel je Aufruf vorliegen, gemessene Wartezeiten
  6. Abgleich mit den Zahlen der Arbeit (paras.txt) und Empfindlichkeit gegenüber dem Anbieter-Cache

Aufruf aus beliebigem Verzeichnis:  python3 oekonomie_rechnung.py
Ausgabe: oekonomie_rechnung.out.txt neben diesem Skript (und auf stdout).
"""
import glob
import hashlib
import json
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .../Masterarbeit
RUNS = ROOT / "eval-harness/eval/runs"

F_ROWS_R = RUNS / "Z53-SCHNELLFORTSETZUNG-001/live/collected/rows-R.json"
F_ANA_R = RUNS / "Z53-SCHNELLFORTSETZUNG-001/ANALYSIS-R.json"
F_ROWS_SK = RUNS / "Z54-SK-KORREKTUR-001/live/collected/rows-R-SK.json"
F_ANA_SK = RUNS / "Z54-SK-KORREKTUR-001/ANALYSIS-R-SK.json"
F_ANA_P = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/P-ANALYSIS.json"
D_STATE_P = RUNS / "Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1"
F_PLAN = RUNS / "Z50-NACHARBEIT-001/coordination/final-candidate-001/PLAN.json"
F_MATRIX_ACC = RUNS / "Z39-RAEUM-ENTWICKLUNG-001/FINAL-R1-MATRIX-ACCEPTANCE.json"
F_LEDGER_1 = RUNS / "Z39-RAEUM-ENTWICKLUNG-001/live/budget.jsonl"
F_LEDGER_2 = RUNS / "Z39-RAEUM-ENTWICKLUNG-001/recovery/budget.jsonl"
D_DISPATCH = RUNS / ("Z52-NEBENPANEL-ANSCHLUSS-001/recovery-R00038/continuation-R00087/"
                     "recovery-R00125/technical-R00203/live/dispatch")
D_Z53_BLOCKS = RUNS / "Z53-SCHNELLFORTSETZUNG-001/live/blocks"
F_PARAS = HERE.parent / "paras.txt"

EXPECTED_SHA = {
    F_ROWS_R: "7f836d8bf04fae7d1fd0f1e616ba39c314ebc357fc2e5c1bbcfb5d73aa83d3b0",
    F_PLAN: "42a55ddd7dc71738d39fbdb546b0bb60ca19a0d6485f47688de32c893f47f61f",
    D_STATE_P / "STATE.json": "960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6",
}

ARMS = ["S", "S-k", "F", "Q", "Z", "D"]
NAME = {"S": "Einzelaufruf", "S-k": "Abstimmungsarm alt (Temperatur 0)", "S-k-neu": "Abstimmungsarm neu (Temperatur 1,0)",
        "F": "F*", "Q": "Q", "Z": "Zufallsauswahl", "D": "dichte Vierergruppe"}
K = Decimal(1000)
M = Decimal(1000000)

OUT = []


def p(*a):
    s = " ".join(str(x) for x in a)
    OUT.append(s)
    print(s)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def de(x, nd=2, thousands=True):
    """Deutsche Zahl: Komma als Dezimal-, Punkt als Tausendertrennzeichen."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), rounding=ROUND_HALF_UP)
    s = f"{q:,.{nd}f}" if thousands else f"{q:.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def need(cond, msg):
    if not cond:
        raise SystemExit("ABBRUCH: " + msg)


def check(label, ours, thesis, tol):
    ok = abs(float(ours) - float(thesis)) <= tol
    p(f"  Abgleich {label}: gerechnet {ours} | Arbeit {thesis} | {'stimmt' if ok else 'ABWEICHUNG'}")
    return ok


# ------------------------------------------------------------------ 0 Eingaben
p("WIRTSCHAFTLICHE EINORDNUNG: RECHNUNG AUS PRIMÄRDATEN (nur lesend, keine Modellaufrufe, 0 USD)")
p("Projektwurzel:", ROOT)
p("")
p("0. Eingaben (SHA-256)")
for f in [F_ROWS_R, F_ANA_R, F_ROWS_SK, F_ANA_SK, F_ANA_P, D_STATE_P / "STATE.json", F_PLAN, F_MATRIX_ACC,
          F_LEDGER_1, F_LEDGER_2]:
    h = sha(f)
    if f in EXPECTED_SHA:
        need(h == EXPECTED_SHA[f], f"Hash weicht ab: {f}")
    p(f"  {f.relative_to(ROOT)}  {h}")
p(f"  {D_DISPATCH.relative_to(ROOT)}/*-settled.json und *-response.json (Zeitstempel und Tokens je Sendeversuch)")
paras = F_PARAS.read_text(encoding="utf-8")
p("")

# ------------------------------------------------------------------ 1 Referenzvergleich
p("1. Referenzvergleich: bekannte Modellkosten, Qualität und Aufrufe je Arm (2.952 Blöcke)")
rows_r = json.loads(F_ROWS_R.read_text())
ana_r = json.loads(F_ANA_R.read_text())["report"]
plan = json.loads(F_PLAN.read_text())
order_r = {b["draw_index"]: b["arm_order"] for b in plan["panels"]["R"]}
order_p = {b["draw_index"]: b["arm_order"] for b in plan["panels"]["P"]}

R = {}
for a in ARMS:
    rr = [r for r in rows_r if r["arm"] == a]
    need(len(rr) == 2952, f"Arm {a}: {len(rr)} Zeilen")
    tot = sum(Decimal(r["cost_usd"]) for r in rr)
    R[a] = dict(n=len(rr), total=tot, mean=tot / len(rr), em=sum(r["em"] for r in rr) / len(rr),
                calls=sum(r["call_count"] for r in rr) / len(rr), calldist=Counter(r["call_count"] for r in rr),
                rows=rr)
    need(tot == Decimal(ana_r["descriptive_costs"]["arms"][a]["total"]), f"Summe {a} ungleich Analysedatei")
    need(abs(R[a]["em"] - ana_r["estimates"][a]["em"]) < 1e-12, f"EM {a} ungleich Analysedatei")

rows_sk = [r for r in json.loads(F_ROWS_SK.read_text()) if r["arm"] == "S-k"]
ana_sk = json.loads(F_ANA_SK.read_text())["report"]
need(len(rows_sk) == 2952, "neuer Abstimmungsarm: Zeilenzahl")
tot = sum(Decimal(r["cost_usd"]) for r in rows_sk)
need(tot == Decimal(ana_sk["descriptive_costs"]["arms"]["S-k"]["total"]), "Summe neuer Abstimmungsarm")
R["S-k-neu"] = dict(n=2952, total=tot, mean=tot / 2952, em=sum(r["em"] for r in rows_sk) / 2952,
                    calls=sum(r["call_count"] for r in rows_sk) / 2952, calldist=Counter(r["call_count"] for r in rows_sk),
                    rows=rows_sk)
p("  Quelle: rows-R.json (Zeilen je Block und Arm) und rows-R-SK.json; Summen und EM identisch mit ANALYSIS-R.json bzw. ANALYSIS-R-SK.json")
p("")
for a in ["S", "S-k-neu", "S-k", "F", "Q", "Z", "D"]:
    x = R[a]
    p(f"  {NAME[a]}: exakt richtig {de(x['em'] * 100)} %, bekannte Kosten gesamt {de(x['total'])} USD "
      f"(genau {x['total']}), je Aufgabe {x['mean']:.10f} USD, "
      f"je 1.000 Aufgaben {de(x['mean'] * K)} USD (genau {de(x['mean'] * K, 6)}), "
      f"je eine Million Aufgaben {de(x['mean'] * M, 0)} USD, mittlere Modellaufrufe je Lauf {de(x['calls'])}")
    p(f"     Verteilung der Aufrufzahl je Lauf: {dict(sorted(x['calldist'].items()))}")
p("")
p("  Abgleich mit Tabelle 6.5 (Summe der bekannten Kosten, exakt richtig):")
t65 = {"F": (3.72, 34.35), "Q": (4.32, 29.34), "S": (0.56, 34.08), "S-k": (2.18, 34.08), "S-k-neu": (2.33, 34.21),
       "D": (6.98, 27.64), "Z": (4.53, 29.00)}
for a, (c, em) in t65.items():
    check(f"{NAME[a]} Kosten", de(R[a]["total"]).replace(",", "."), c, 0.005)
    check(f"{NAME[a]} exakt richtig", de(R[a]["em"] * 100).replace(",", "."), em, 0.005)
p("")

# ------------------------------------------------------------------ 2 Verhältnisse
p("2. Kostenverhältnisse der Mittel (Tabelle 6.6) und Anteile")
t66 = [("F", "D", 0.53), ("F", "S", 6.66), ("F", "S-k", 1.70), ("F", "S-k-neu", 1.59), ("F", "Z", 0.82),
       ("Q", "F", 1.16), ("Q", "S", 7.74), ("Q", "S-k", 1.98), ("Q", "S-k-neu", 1.85), ("Q", "D", 0.62),
       ("Q", "Z", 0.95)]
for a, b, th in t66:
    v = R[a]["mean"] / R[b]["mean"]
    check(f"{NAME[a]} / {NAME[b]}", f"{v:.4f}", th, 0.005)
s_share = R["S"]["mean"] / R["F"]["mean"]
p(f"  Einzelaufruf in Prozent der Kosten von F*: {de(s_share * 100, 1)} % (Kurzfassung: rund 15 %)")
p(f"  Abstimmungsarm neu / Einzelaufruf: {de(R['S-k-neu']['mean'] / R['S']['mean'], 2)} (Arbeit: rund 4,2-fach)")
p(f"  F* / dichte Vierergruppe: {de(R['F']['mean'] / R['D']['mean'], 3)} (rund halbe Kosten)")
p("")

# Hoeffding-Radius wie in der Arbeit: Differenz zweier Anteile, Wertebereich 2, n = 2.952, alpha 0,05
n = 2952
rad = 2 * math.sqrt(math.log(2 / 0.05) / (2 * n))
diff_fs = R["F"]["em"] - R["S"]["em"]
diff_fd = R["F"]["em"] - R["D"]["em"]
p(f"  Hoeffding-Radius bei n = 2.952: {de(rad * 100, 2)} Prozentpunkte")
p(f"  F* minus Einzelaufruf: {de(diff_fs * 100, 2)} Pp., Intervall {de((diff_fs - rad) * 100, 2)} bis {de((diff_fs + rad) * 100, 2)} (Tabelle 6.6: 0,27; -4,73 bis 5,27)")
p(f"  F* minus dichte Vierergruppe: {de(diff_fd * 100, 2)} Pp., Intervall {de((diff_fd - rad) * 100, 2)} bis {de((diff_fd + rad) * 100, 2)} (Tabelle 6.6: 6,71; 1,71 bis 11,71)")
p("")

# ------------------------------------------------------------------ 3 Hauptstudie
p("3. Hauptstudie: bekannte Modellkosten von Q und F* (9.040 Paare, nacheinander erhoben)")
ana_p = json.loads(F_ANA_P.read_text())["report"]
idx = json.loads((D_STATE_P / "STATE-INDEX.json").read_text())
need(idx["state_sha256"] == EXPECTED_SHA[D_STATE_P / "STATE.json"], "STATE-Index passt nicht")
fld = next(x for x in idx["fields"] if x["name"] == "rows")
with open(D_STATE_P / "STATE.json", "rb") as fh:
    fh.seek(fld["start"])
    rows_p = json.loads(fh.read(fld["end"] - fld["start"]))
P = {}
for a in ["Q", "F"]:
    rr = [r for r in rows_p if r["arm"] == a]
    need(len(rr) == 9040, f"Hauptstudie {a}: {len(rr)} Zeilen")
    tot = sum(Decimal(r["cost_usd"]) for r in rr)
    need(tot == Decimal(ana_p["descriptive_costs"]["arms"][a]["total"]), f"Hauptstudie Summe {a}")
    P[a] = dict(total=tot, mean=tot / 9040, em=sum(r["em"] for r in rr) / 9040,
                calls=sum(r["call_count"] for r in rr) / 9040, rows=rr)
    p(f"  {NAME[a]}: exakt richtig {de(P[a]['em'] * 100)} %, bekannte Kosten gesamt {de(P[a]['total'])} USD "
      f"(genau {tot}), je 1.000 Aufgaben {de(P[a]['mean'] * K)} USD (genau {de(P[a]['mean'] * K, 6)}), "
      f"mittlere Modellaufrufe je Lauf {de(P[a]['calls'])}")
ratio_p = P["Q"]["mean"] / P["F"]["mean"]
check("Q Kosten gesamt", de(P["Q"]["total"]).replace(",", "."), 14.44, 0.005)
check("F* Kosten gesamt", de(P["F"]["total"]).replace(",", "."), 12.35, 0.005)
check("Kostenverhältnis Q/F*", f"{ratio_p:.4f}", 1.169, 0.0005)
check("Q exakt richtig", f"{P['Q']['em'] * 100:.2f}", 31.99, 0.005)
check("F* exakt richtig", f"{P['F']['em'] * 100:.2f}", 36.21, 0.005)
check("Aufrufe Q (Tabelle 6.4)", f"{P['Q']['calls']:.2f}", 5.88, 0.005)
check("Aufrufe F* (Tabelle 6.4)", f"{P['F']['calls']:.2f}", 4.95, 0.005)
p("")

# ------------------------------------------------------------------ 4 Entwicklungsmatrix
p("4. Entwicklungsmatrix (einmalig; aus ihr wurden F* und Q gewählt)")
acc = json.loads(F_MATRIX_ACC.read_text())
dev_known = Decimal(0)
settled = 0
unknown = 0
reserves = Decimal(0)
for f in [F_LEDGER_1, F_LEDGER_2]:
    for line in open(f, encoding="utf-8"):
        d = json.loads(line)
        if d["kind"] == "settled":
            settled += 1
            c = (d.get("usage") or {}).get("cost_usd")
            if c is None:
                unknown += 1
            else:
                dev_known += Decimal(c)
need(dev_known == Decimal(acc["known_cost_usd"]), "Entwicklungskosten ungleich Abnahmedatei")
need(acc["completed_slots"] == 4900 and acc["tasks"] == 300 and acc["repeat_tasks"] == 50, "Matrixumfang")
dev_reserve = Decimal(acc["old_unknown_reserve_usd"])
p(f"  abgerechnete Sendeversuche in beiden Kontenbüchern: {de(settled, 0)}")
p(f"  bekannte Modellkosten der Entwicklungsmatrix: {de(dev_known)} USD (genau {dev_known}); "
  f"Abnahmedatei: {acc['known_cost_usd']}")
p(f"  unbekannte Abrechnungen: {unknown} (zurückgehaltene Reserve {de(dev_reserve)} USD, keine Ausgabe)")
p(f"  Umfang: {de(acc['completed_slots'], 0)} Läufe = 300 Aufgaben x 14 Konfigurationen + 50 Wiederholungsaufgaben x 14; "
  f"Ergebnisstatus abgeschlossen {acc['result_status_counts']['completed']}, Modellausfall {acc['result_status_counts']['model_failed']}")
check("Läufe der Matrix (Abschnitt 5.4: 4.900)", acc["completed_slots"], 4900, 0)
p(f"  zum Vergleich: so viel kosten {de(dev_known / R['S']['mean'], 0)} Einzelaufrufe "
  f"oder {de(dev_known / R['F']['mean'], 0)} Läufe von F* im Referenzvergleich")
p("")

# ------------------------------------------------------------------ 5 Amortisation
p("5. Amortisation der Entwicklung (nur wo F* belastbar besser und billiger ist: gegenüber der dichten Vierergruppe)")
save_fd = R["D"]["mean"] - R["F"]["mean"]
be = dev_known / save_fd
be_res = (dev_known + dev_reserve) / save_fd
p(f"  Ersparnis F* gegenüber dichter Vierergruppe je Aufgabe: {save_fd:.10f} USD = {de(save_fd * K)} USD je 1.000 Aufgaben")
p(f"  Amortisation nach {de(be, 0)} Aufgaben (genau {de(be, 1)}; gerundet rund 5.750); "
  f"mit der Reserve als Obergrenze der unbekannten Abrechnung nach {de(be_res, 0)} Aufgaben")
p(f"  Gegenüber Einzelaufruf: F* kostet je Aufgabe {de((R['F']['mean'] - R['S']['mean']) * K)} USD je 1.000 Aufgaben mehr "
  f"und ist nicht nachweisbar besser; keine Amortisation, die Entwicklung kommt zu höheren Betriebskosten hinzu")
p(f"  Gegenüber Abstimmungsarm neu: F* kostet {de((R['F']['mean'] - R['S-k-neu']['mean']) * K)} USD je 1.000 Aufgaben mehr "
  f"und ist nicht nachweisbar besser; keine Amortisation")
p("")

# ------------------------------------------------------------------ 6 Mehrkosten je Million
p("6. Mehrkosten je eine Million Aufgaben")
fs = (R["F"]["mean"] - R["S"]["mean"]) * M
qf_p = (P["Q"]["mean"] - P["F"]["mean"]) * M
qf_r = (R["Q"]["mean"] - R["F"]["mean"]) * M
p(f"  F* gegenüber Einzelaufruf (Referenzvergleich): {de(fs, 0)} USD (genau {de(fs, 2)}), "
  f"also rund einen US-Dollar ({de(fs / 1000, 2)}) je 1.000 Aufgaben")
p(f"  Q gegenüber F* (Hauptstudie, maßgeblicher Vergleich): {de(qf_p, 0)} USD (genau {de(qf_p, 2)})")
lo, hi = Decimal("1.162"), Decimal("1.176")
p(f"     mit den Grenzen des Kostenverhältnisses 1,162 und 1,176 bei festem Mittel von F*: "
  f"{de((lo - 1) * P['F']['mean'] * M, 0)} bis {de((hi - 1) * P['F']['mean'] * M, 0)} USD")
p(f"  Q gegenüber F* (Referenzvergleich, nur beschreibend): {de(qf_r, 0)} USD")
p(f"  dichte Vierergruppe gegenüber F* (Referenzvergleich): {de(save_fd * M, 0)} USD")
p("")

# ------------------------------------------------------------------ 7 Cache und Armreihenfolge
p("7. Empfindlichkeit gegenüber dem Anbieter-Cache: Kosten nach Position des Arms im Block (beschreibend)")
p("  Begründung: Innerhalb eines Blocks liefen die Arme nacheinander; spätere Arme senden dieselben Absätze erneut und")
p("  erhalten teils Cache-Rabatt. Ein Arm, der im Block zuerst lief, kommt dem Einzelbetrieb eines Systems am nächsten.")
first = {}
for a in ["S", "F", "Q", "Z", "D", "S-k"]:
    f1 = [r for r in R[a]["rows"] if order_r[r["draw_index"]][0] == a]
    f2 = [r for r in R[a]["rows"] if order_r[r["draw_index"]][0] != a]
    m1 = sum(Decimal(r["cost_usd"]) for r in f1) / len(f1)
    m2 = sum(Decimal(r["cost_usd"]) for r in f2) / len(f2)
    first[a] = m1
    p(f"  Referenzvergleich {NAME[a]}: zuerst im Block {len(f1)} Läufe, je 1.000 Aufgaben {de(m1 * K)} USD; "
      f"später {len(f2)} Läufe, {de(m2 * K)} USD; Verhältnis {de(m1 / m2, 2)}")
for a in ["F", "Q"]:
    f1 = [r for r in P[a]["rows"] if order_p[r["draw_index"]][0] == a]
    f2 = [r for r in P[a]["rows"] if order_p[r["draw_index"]][0] != a]
    m1 = sum(Decimal(r["cost_usd"]) for r in f1) / len(f1)
    m2 = sum(Decimal(r["cost_usd"]) for r in f2) / len(f2)
    p(f"  Hauptstudie {NAME[a]}: zuerst im Paar {len(f1)} Läufe, je 1.000 Aufgaben {de(m1 * K)} USD; "
      f"als zweiter Arm {len(f2)} Läufe, {de(m2 * K)} USD")
p(f"  Mit den Kosten der Blöcke, in denen der Arm zuerst lief: F*/Einzelaufruf {de(first['F'] / first['S'], 2)} "
  f"(rund {de(first['F'] / first['S'], 1)}-fach) statt {de(R['F']['mean'] / R['S']['mean'], 2)} "
  f"(rund {de(R['F']['mean'] / R['S']['mean'], 1)}-fach); F*/dichte Vierergruppe {de(first['F'] / first['D'], 2)} "
  f"statt {de(R['F']['mean'] / R['D']['mean'], 2)}")
p(f"     Mehrkosten F* gegenüber Einzelaufruf je eine Million Aufgaben {de((first['F'] - first['S']) * M, 0)} USD; "
  f"Amortisation gegenüber dichter Vierergruppe nach {de(dev_known / (first['D'] - first['F']), 0)} Aufgaben")
rank_first = [a for a in sorted(["S", "S-k", "F", "Q", "Z", "D"], key=lambda a: first[a])]
rank_all = [a for a in sorted(["S", "S-k", "F", "Q", "Z", "D"], key=lambda a: R[a]["mean"])]
p(f"     Einzelaufruf zuerst im Block: {de(first['S'] * K)} USD je 1.000 Aufgaben statt {de(R['S']['mean'] * K)}; "
  f"Rangfolge der Arme nach Kosten {'unverändert' if rank_first == rank_all else 'VERÄNDERT'}: "
  f"{' < '.join(NAME[a] for a in rank_first)}")
p(f"  Grund für das höhere Kostenniveau von F* in der Hauptstudie ({de(P['F']['mean'] * K)} statt {de(R['F']['mean'] * K)} USD "
  f"je 1.000 Aufgaben): F* lief dort in der Hälfte der Paare zuerst, im Referenzvergleich nur in rund einem Sechstel der Blöcke;")
p("     wo F* zuerst lief, liegen beide Studien nahe beieinander (siehe Zeilen oben). Andere Ziehungen kommen hinzu.")
p("")

# ------------------------------------------------------------------ 8 Aufrufketten
p("8. Nacheinander laufende Modellaufrufe je Arm (Ablauf nach Abschnitt 5.2 und 5.3)")
p("  In dieser Umsetzung ruft das Framework alle Aufrufe eines Laufs nacheinander auf; auch die fünf Antworten des")
p("  Abstimmungsarms wurden nacheinander abgefragt. Nominal je Lauf ohne Modellausfall:")
p("    Einzelaufruf 1 | Abstimmungsarm 5 | F* 5 (2 Rollen x 2 Runden + Zusammenführung) | Q 5 oder 7 | "
  "Zufallsauswahl 5 oder 7 | dichte Vierergruppe 9 (4 x 2 + 1)")
p(f"  beobachtetes Mittel im Referenzvergleich: " + "; ".join(f"{NAME[a]} {de(R[a]['calls'])}" for a in ["S", "S-k-neu", "F", "Q", "Z", "D"]))
p("  Weil keine Rolle Antworten derselben Runde liest, könnten die Aufrufe einer Runde gleichzeitig laufen; die Kette hätte")
p("  dann 3 Stufen (Runde 1, Runde 2, Zusammenführung) bei allen Mehragentenarmen, 1 beim Einzelaufruf und beim Abstimmungsarm.")
p("")

# ------------------------------------------------------------------ 9 Zeitstempel und Wartezeiten
p("9. Zeitstempel und gemessene Wartezeiten")
# 9a: Laufprotokoll ohne Zeitstempel? Schlüssel aller Ereignisse in den F*-Laufprotokollen des Parallelabschnitts
keys = Counter()
nj = 0
for jf in glob.glob(str(D_Z53_BLOCKS / "R-*" / "F" / "journal.jsonl")):
    nj += 1
    for line in open(jf, encoding="utf-8"):
        d = json.loads(line)
        keys.update(d.keys())
        pl = d.get("payload", {})
        keys.update("payload." + k for k in pl.keys())
        ev = pl.get("event")
        if isinstance(ev, dict):
            keys.update("event." + k for k in ev.keys())
timeish = sorted(k for k in keys if any(t in k.lower() for t in ("time", "_at", "created", "stamp", "date")))
p(f"  Laufprotokolle (journal.jsonl) von {nj} F*-Läufen geprüft; Schlüssel: {sorted(keys)}")
p(f"  Zeitstempel-Schlüssel im Laufprotokoll: {timeish if timeish else 'keine'}")
p("  Zeitstempel je Sendeversuch stehen dagegen in den Sendebelegen (dispatched_at, received_at), in den Kontenbüchern")
p("  (time je Reservierung und Abrechnung) und in den Anbieterantworten (created, sekundengenau).")
# 9b: Wartezeiten aus den Sendebelegen des nacheinander erhobenen Abschnitts
runs = defaultdict(list)
prices_ok = 0
prices_n = 0
for fn in sorted(glob.glob(str(D_DISPATCH / "*-settled.json"))):
    d = json.loads(open(fn, encoding="utf-8").read())
    di = d["dispatch"]
    parts = di["logical_id"].split(":")
    blk, arm = int(parts[3]), parts[4]
    stage = "1" if arm in ("S", "S-k") else parts[5]
    rc = d.get("receipt") or {}
    runs[(blk, arm)].append((di["dispatched_at"], rc.get("received_at"), di["retry_kind"], stage))
    resp = Path(fn.replace("-settled.json", "-response.json"))
    if d.get("outcome") in ("completed", "model_failed") and resp.exists():
        u = json.loads(resp.read_text()).get("usage") or {}
        if "prompt_tokens" in u and u.get("cost") is not None:
            prices_n += 1
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
            calc = (Decimal("1e-7") * (u["prompt_tokens"] - cached) + Decimal("1e-8") * cached
                    + Decimal("4e-7") * u["completion_tokens"])
            if abs(calc - Decimal(str(u["cost"]))) < Decimal("1e-10"):
                prices_ok += 1
blocks = sorted({b for b, _ in runs})
lo_b, hi_b = blocks[0] + 1, blocks[-1] - 1  # erster und letzter Block des Abschnitts unvollständig
p(f"  Sendebelege: {de(len(glob.glob(str(D_DISPATCH / '*-settled.json'))), 0)} Sendeversuche, Blöcke {blocks[0]} bis {blocks[-1]}, "
  f"ausgewertet vollständige Blöcke {lo_b} bis {hi_b} ({de(hi_b - lo_b + 1, 0)} Blöcke)")
p(f"  Tarifprüfung je Anbieterantwort: {de(prices_ok, 0)} von {de(prices_n, 0)} Beträgen erfüllen exakt "
  f"0,10 USD je Million Eingabetokens ohne Cache, 0,01 USD je Million aus dem Cache, 0,40 USD je Million Ausgabetokens")
res_sum, res_crit, res_wall, excl = defaultdict(list), defaultdict(list), defaultdict(list), Counter()
for (b, a), L in runs.items():
    if not (lo_b <= b <= hi_b):
        continue
    if any(x[2] != "initial" or x[1] is None for x in L):
        excl[a] += 1
        continue
    res_sum[a].append(sum(x[1] - x[0] for x in L))
    res_wall[a].append(max(x[1] for x in L) - min(x[0] for x in L))
    by_stage = defaultdict(list)
    for x in L:
        by_stage[x[3]].append(x[1] - x[0])
    res_crit[a].append(sum(max(v) for v in by_stage.values()))
p("  Modellwartezeit je Aufgabe = Summe der Dauern vom Senden bis zum Empfang über alle Aufrufe eines Laufs (Sekunden):")
med = {}
for a in ["S", "S-k", "F", "Q", "Z", "D"]:
    v = sorted(res_sum[a])
    med[a] = st.median(v)
    p(f"    {NAME[a]}: {len(v)} Läufe (ausgeschlossen mit wiederholtem Sendeversuch: {excl[a]}), "
      f"Median {de(st.median(v), 1)} s, Mittel {de(st.mean(v), 1)} s, 90-%-Quantil {de(v[int(0.9 * len(v))], 1)} s; "
      f"Gesamtdauer erster Versand bis letzter Empfang, Median {de(st.median(res_wall[a]), 2)} s "
      f"(Summe der Einzeldauern, Median {de(st.median(v), 2)} s: Aufrufe liefen nacheinander)")
p(f"    Verhältnis der Mediane F*/Einzelaufruf {de(med['F'] / med['S'], 1)}, dichte Vierergruppe/Einzelaufruf {de(med['D'] / med['S'], 1)}")
p("  Rechnerisch, falls die Aufrufe einer Runde gleichzeitig liefen (Summe der längsten Dauer je Stufe, gleiche Einzeldauern):")
for a in ["S", "S-k", "F", "Q", "Z", "D"]:
    v = res_crit[a]
    p(f"    {NAME[a]} bei gleichzeitigen Aufrufen je Runde: Median {de(st.median(v), 1)} s")
p(f"    bei gleichzeitigen Aufrufen je Runde: Verhältnis der Mediane F*/Einzelaufruf {de(st.median(res_crit['F']) / st.median(res_crit['S']), 1)}")
p("")

# ------------------------------------------------------------------ 10 Grenzkosten
p("10. Rechnerische Grenzkosten je zusätzlicher exakt richtiger Antwort von F* gegenüber dem Einzelaufruf")
extra_cost = (R["F"]["mean"] - R["S"]["mean"]) * K
for lab, d_pp in [("Punktschätzer", diff_fs), ("obere Intervallgrenze", diff_fs + rad)]:
    extra_correct = Decimal(str(d_pp)) * K
    p(f"  {lab}: {de(extra_correct, 1)} zusätzliche richtige Antworten je 1.000 Aufgaben für {de(extra_cost)} USD, "
      f"also {de(extra_cost / extra_correct, 3)} USD (rund {de(extra_cost / extra_correct, 2)} USD) je zusätzlicher richtiger Antwort")
p("  untere Intervallgrenze negativ: dort wäre der Einzelaufruf besser und billiger; der Wert einer richtigen Antwort ist nicht gemessen")
p("")

# ------------------------------------------------------------------ 11 Zusammenfassung für die Tabelle
p("11. Tabelle für den Entwurf (Referenzvergleich, 2.952 Blöcke; Kosten je 1.000 Aufgaben gerundet)")
for a, calls in [("S", "1"), ("S-k-neu", "5"), ("F", "5"), ("Q", "5 oder 7"), ("Z", "5 oder 7"), ("D", "9")]:
    p(f"  Tabellenzeile {NAME[a]} | exakt richtig {de(R[a]['em'] * 100)} % | je 1.000 Aufgaben {de(R[a]['mean'] * K)} USD | "
      f"Modellaufrufe nacheinander {calls}")
p("")
p("Ende der Rechnung.")

(HERE / "oekonomie_rechnung.out.txt").write_text("\n".join(OUT) + "\n", encoding="utf-8")
