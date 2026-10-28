"""Tokens pro Arm im Referenzvergleich (Tabelle 7.3 der Arbeit), nachgerechnet aus den Dateien dieses Repositorys.

Aufruf aus der Wurzel des Repositorys: python3 ergebnisse/wirtschaftliche-einordnung/tokens/pruefe_tokens.py
Prüft für jede Zeile von tokens-je-lauf.tsv:
  1. die bekannten Kosten sind gleich cost_usd der Ergebniszeile (rows-R.json bzw. rows-R-SK.json),
  2. (Eingabetokens - Cache) * 0,10 + Cache * 0,01 + Ausgabetokens * 0,40 US-Dollar pro Million ergibt genau diese Kosten.
Danach gibt es pro Arm die mittleren Tokens pro Aufgabe (Summe / 2.952) und die Kosten pro 1.000 Aufgaben aus.
"""
import csv, json, sys
from decimal import Decimal as D
from pathlib import Path

WURZEL = Path.cwd()
TSV = Path(__file__).resolve().parent / "tokens-je-lauf.tsv"
ZEILEN = {"referenzvergleich": "ergebnisse/ergaenzende-vergleiche/zeilen/rows-R.json",
          "abstimmungsarm-alt": "ergebnisse/ergaenzende-vergleiche/zeilen/rows-R.json",
          "abstimmungsarm-neu": "ergebnisse/ergaenzende-vergleiche/abstimmungsarm-nachstudie/rows-R-SK.json"}
PREIS = {"ohne": D("0.10"), "cache": D("0.01"), "aus": D("0.40")}  # US-Dollar pro Million Tokens
NAMEN = [("referenzvergleich", "S", "Einzelaufruf"), ("abstimmungsarm-neu", "S-k", "Abstimmungsarm, neu"),
         ("referenzvergleich", "F", "F*"), ("referenzvergleich", "Q", "Q"), ("referenzvergleich", "Z", "Zufallsauswahl"),
         ("referenzvergleich", "D", "dichte Vierergruppe"), ("abstimmungsarm-alt", "S-k", "Abstimmungsarm, alt (nicht in Tabelle 7.3)")]

kosten = {}
for auswertung, pfad in ZEILEN.items():
    for r in json.load(open(WURZEL / pfad, encoding="utf-8")):
        kosten[(auswertung, r["slot_id"])] = D(r["cost_usd"])

summen, fehler = {}, 0
with open(TSV, encoding="utf-8") as f:
    for z in csv.DictReader(f, delimiter="\t"):
        ein, cache, aus = int(z["eingabetokens"]), int(z["davon_aus_cache"]), int(z["ausgabetokens"])
        k = D(z["bekannte_kosten_usd"])
        preis = ((ein - cache) * PREIS["ohne"] + cache * PREIS["cache"] + aus * PREIS["aus"]) / D(10**6)
        soll = kosten.get((z["auswertung"], z["slot_id"]))
        if soll is None or k != soll or preis != k:
            fehler += 1
            print("Abweichung:", z["auswertung"], z["slot_id"], k, soll, preis)
        s = summen.setdefault((z["auswertung"], z["arm"]), [0, 0, 0, D(0), 0])
        s[0] += ein - cache; s[1] += cache; s[2] += aus; s[3] += k; s[4] += 1

print("Mittlere Tokens pro Aufgabe (Eingabe ohne Cache, aus dem Cache, Ausgabe) und Kosten pro 1.000 Aufgaben")
for auswertung, arm, name in NAMEN:
    s = summen[(auswertung, arm)]
    n = s[4]
    print("  %-44s %9.2f %9.2f %8.2f   %.2f US-Dollar   (%d Aufgaben)" % (name, s[0] / n, s[1] / n, s[2] / n, s[3] / n * 1000, n))
print("Zeilen mit Abweichung:", fehler)
sys.exit(1 if fehler else 0)
