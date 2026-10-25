<!-- status: vorab festgelegt, vor jeder Rechnung | Freigabe Jannik 19.10.2026 („Go für die Prüfung“) | 2026-10-19 -->

# Analyseplan: nachträgliche Offline-Prüfung zu Feedbackpunkt 2 und 5

Festgelegt am 19.10.2026, bevor eine der folgenden Rechnungen lief. Bekannt waren zu diesem Zeitpunkt nur die gespeicherten Ergebnisse von Z39 (Regularisierung 1/10/100: 33,67/35,33/35,33 % auf zurückgehaltenen Teilen, feste Referenz 39,00 %) und die Trainingsqualität des abschließenden Modells (50,67 %), siehe `../FEEDBACK-UND-ANALYSE.md`.

Alle Rechnungen sind nachträglich und explorativ. Sie nutzen nur die vorhandene Entwicklungsmatrix (300 Aufgaben, 100 Familien, 14 Konfigurationen, 4.900 Läufe), ohne Modellaufrufe und ohne Zugriff auf den Dev-Bestand. Sie ändern weder den vorab festgelegten Hauptvergleich noch dessen Befund.

## Daten und Werkzeuge

- Matrix: `eval-harness/eval/runs/Z39-RAEUM-ENTWICKLUNG-001/recovery-fit/run-001/development-means.json` (je Aufgabe gemittelter Exact Match und mittlere bekannte Kosten je Konfiguration, Familie).
- Teile: die fünf gespeicherten familiengetrennten Teile aus `raw-Q-sem.json` (`folds`).
- Merkmale: neu berechnet mit dem gebundenen Encoder `eval-harness/eval/runs/Z38-QSEM-001/provision/encoder/all-MiniLM-L6-v2` und der Merkmalsfunktion `communication_pruning.selection.features`, Fragen und Absätze aus den versiegelten Laufjournalen von Z39.
- Auswahlregel unverändert: höchste Vorhersage, Spielraum 1 Pp. (`EPSILON = 0.01`), dann geringste mittlere Trainingskosten, dann Konfigurationsnummer.

## A: Überanpassung der aufgabenabhängigen Auswahl

- **A0 Reproduktion (Abbruchkriterium).**
  - Merkmalsmatrix neu bauen. Für α ∈ {1, 10, 100} auf den fünf Teilen anpassen.
  - Die vorhergesagten Werte je zurückgehaltener Aufgabe müssen mit den gespeicherten `scores` übereinstimmen (größte absolute Abweichung < 1e-6).
  - Qualität und feste Referenz müssen 33,67/35,33/35,33 % und 39,00 % ergeben.
  - Weicht etwas ab: Abbruch und Bericht, keine weiteren Rechnungen.
- **A1 Überanpassungslücke.**
  - Für jedes α: Qualität der Wahl auf den eigenen Trainingsteilen (Mittel über die fünf Teile) gegen Qualität auf dem zurückgehaltenen Teil.
  - Dazu das abschließende Modell auf allen 300 Aufgaben.
- **A2 Erweitertes Raster.**
  - α ∈ {1, 10, 100, 1.000, 10.000, 100.000, 1.000.000}, gleiche Teile und Regel.
  - Berichtet werden Qualität und mittlere bekannte Kosten auf zurückgehaltenen Teilen sowie die Differenz zur festen Referenz.
- **A3 Weniger Merkmale**, Standardisierung und Hauptkomponenten nur auf den jeweiligen Trainingsteilen:
  - (a) nur die vier Textmerkmale
  - (b) Einbettung auf 5 Hauptkomponenten plus vier Textmerkmale
  - (c) Einbettung auf 20 Hauptkomponenten plus vier Textmerkmale
  - Für jede Variante das α-Raster aus A2.
- **A4 Verschachtelte Schätzung (entscheidend).**
  - Äußere Schleife: die fünf gespeicherten Teile.
  - Innen: Die Familien der vier Trainingsteile werden nach Familienkennung sortiert und reihum auf vier innere Teile verteilt.
  - Innen gewählt wird die Kombination aus Variante (volle Merkmale, A3a, A3b, A3c) und α (Raster A2) nach demselben Muster: beste innere Qualität, 1 Pp. Spielraum, dann geringere innere Kosten. Bei Gleichstand gilt das größere α, dann die Variante mit weniger Merkmalen.
  - Mit der gewählten Kombination wird auf allen vier Trainingsteilen neu angepasst und auf dem äußeren Teil bewertet.
  - Feste Referenz je äußerem Teil: aus den vier Trainingsteilen nach der Regel der festen Referenz.
  - Ergebnis: Qualität der ganzen Lernprozedur auf zurückgehaltenen Aufgaben, Differenz zur festen Referenz und ein 95-%-Perzentilintervall per Familien-Cluster-Bootstrap über die Paardifferenzen (10.000 Ziehungen, Seed 20261019). Das Intervall ist beschreibend und bedingt auf die angepassten Modelle.

**Kriterium für einen Zusatzlauf (Option B):** Eine Vorlage für einen bezahlten Zusatzlauf entsteht nur, wenn die verschachtelte Differenz aus A4 (Lernprozedur minus feste Referenz) als Punktwert mindestens +1,0 Pp. beträgt. Ergebnisse aus A2 und A3 ohne Verschachtelung entscheiden darüber nicht, weil die Wahl unter vielen Varianten dort zu günstig ausfällt (vgl. Cawley & Talbot, 2010).

## B: Zerlegung der Pruning-Eingriffe (Feedbackpunkt 5)

Grundlage ist die Entwicklungsmatrix, je Aufgabe gemittelter Exact Match und mittlere bekannte Kosten. Alle Werte sind beschreibend. Die Matrix beruht für 250 Aufgaben auf einem Lauf. ⟦F*⟧ (C01) wurde auf denselben Daten gewählt, das betrifft B2 und B3.

- **B1 Kanten bei gleichen Rollen und Aufrufen:** voll vernetzt minus Ring je Dreiergruppe (C08−C07, C10−C09, C12−C11, C14−C13) und gepoolt (Mittel der vier Differenzen je Aufgabe). Dazu das Kostenverhältnis voll/Ring.
- **B2 Rollenwahl bei gleicher Größe, gleichen Kanten und Aufrufen:** sechs Zweiergruppen. Je Rolle das Mittel der drei Zweiergruppen mit dieser Rolle minus das Mittel der drei ohne sie.
- **B3 Zusätzliche Rolle, mit ihren Kanten und Aufrufen:** für jede Dreiergruppe und jede ihrer drei Zweiergruppen die Dreiergruppe minus Zweiergruppe, getrennt für Ring und voll vernetzt. Gepoolt über alle zwölf Paare je Bauform.
- **B4 Runden:** nur wenn die Rundenentwicklung (100 Aufgaben, 50 Familien) lokal mit Familienkennung vorliegt: zwei minus eine Runde. Sonst nur Verweis auf die vorhandene Zählung (92 gleich, 3 besser, 5 schlechter).
- **Intervalle:** 95-%-Perzentilintervall per Familien-Cluster-Bootstrap (10.000 Ziehungen, Seed 20261019). Ohne Korrektur für Mehrfachvergleiche, daher nur beschreibend.

## C: Unabhängige Nachrechnung

Codex (gpt-6-luna, read-only) rechnet mit eigener Implementierung nach: Trainingsqualität 50,67 %, A0 aus den gespeicherten Werten, B1, B3 und die Hauptzahl aus A4, Letztere aus der gespeicherten Merkmalsmatrix. Abweichungen werden berichtet, nicht geglättet.

## Ausgaben

`analyse/ERGEBNIS-OFFLINE.md`, `analyse/ergebnis-offline.json`, Skripte in `analyse/`, Merkmalsmatrix `analyse/features-300.npz` (ohne Antworten oder Goldantworten).
