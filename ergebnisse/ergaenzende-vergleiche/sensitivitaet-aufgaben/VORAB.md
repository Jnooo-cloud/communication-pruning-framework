<!-- status: vorab-festlegung, vor jeder Rechnung gehasht | 2026-10-06 -->

# Vorab-Festlegung: Cluster-Sensitivität der ergänzenden Vergleiche

**Explorativ und nachträglich.** Festgelegt am 6. Oktober 2026, rund 11:00 MESZ, bevor eine Einzelzeile der Panels R, T oder F für diese Analyse geladen oder eine Variante gerechnet wurde. Freigabe: Auftrag von Jannik vom 6. Oktober 2026 (Review `06_thesis/review/kap4-R.md`, R-02, Entscheidung 2), 0 USD, keine Modellaufrufe. Die Analyse ändert die vorab gebundene Auswertung der ergänzenden Vergleiche nicht und wird unabhängig von ihrer Richtung berichtet. Vorlage: `04_ergebnisse/nacharbeit-2026-10-04/P-CLUSTER-SENSITIVITAET.md` §0.

Bekannt waren zu diesem Zeitpunkt: die aggregierten Werte aus `04_ergebnisse/belege/RTF/ANALYSIS-{R,T,F}.json` (Reproduktionsziel), die Ergebnisse der P-Cluster-Sensitivität und der K-Fenster-Auswertung, sowie zur Schemaprüfung die ersten zwei Zeilen von `rows-T.json` (Block 0). Keine Clustergrößen, keine Wiederholungsstruktur und keine Varianzzerlegung der Panels R, T, F.

## 1. Daten

- `04_ergebnisse/daten/collected/rows-R.json`, `rows-T.json`, `rows-F.json`; SHA256 Pflicht gegen `MANIFEST.tsv` und gegen `rows_sha256` in `ANALYSIS-{R,T,F}.json`: R `7f836d8b…`, T `752c3166…`, F `2caadd17…`. Je Panel 2.952 Blöcke (`draw_index` 0 bis 2.951), Arme je Block genau wie `final_plan.ARMS` (R: S, S-k, D, Z, Q, F; T: Q-ST, Q-TF; F: Qc, Qf, Fc, Ff). `task_id` und `family_id` müssen innerhalb eines Blocks über alle Arme gleich sein, sonst Abbruch.
- Kein Ausschluss, keine Imputation: Modellausfälle bleiben mit EM = 0 und ihren Kosten drin, wie in der Hauptauswertung.

## 2. Kennzahlen

Je Block ein Kontrastwert. Qualität (Hauptkennzahl EM; F1 nachrangig mit derselben Logik):

| Vergleich | Qualitätskontrast je Block | Wertebereich | Kostenquotient (Verhältnis der Mittel) |
|---|---|---|---|
| R08 | EM(F) − EM(D) | [−1, 1] | C(F) / C(D) |
| R06 | EM(F) − EM(S) | [−1, 1] | C(F) / C(S) |
| R05 (ergänzend, weil 6.4 „Q liegt unter F*“ daran hängt) | EM(Q) − EM(F) | [−1, 1] | C(Q) / C(F) |
| T01 | EM(Q-ST) − EM(Q-TF) | [−1, 1] | C(Q-ST) / C(Q-TF) |
| F d_Q | EM(Qf) − EM(Qc) | [−1, 1] | F01: C(Qf) / C(Qc) |
| F d_F | EM(Ff) − EM(Fc) | [−1, 1] | F02: C(Ff) / C(Fc) |
| F Differenz | d_Q − d_F | [−2, 2] | (keiner) |

Weitere Endpunkte (R01 bis R04, R07, R09) werden nicht gerechnet.

## 3. Schritt 1: Hauptauswertung exakt reproduzieren

- Kern unverändert aus dem alten Repo importiert, nur lesend, ohne Bytecode: `study_preparation/intervals.py` (SHA256 `3ddb2db6…`), `final_analysis.py` (`b16b4be1…`), `final_plan.py` (`e9dc5ef8…`, nur `ARMS`).
- Python 3.12 aus `runs/Z38-QSEM-001/provision/python` (numpy 1.26.4), wie bei P-Cluster.
- Abnahme, **bitgleich** (Gleichheit der float-Werte bzw. der Dezimalzeichenketten): EM- und F1-Mittel je Arm wie `analyze_panel` (`math.fsum / n`) gegen `report.estimates`; alle Hoeffding-Einträge (`estimate`, `lower`, `upper`, `radius`, `n`) für EM und F1 aller Endpunkte über `intervals.secondary_quality` mit Blöcken in kanonischer Armfolge gegen `report.secondary_quality`; Kostenquotienten mit `Decimal`, Präzision 50, als Zeichenkette gegen `report.descriptive_costs.endpoints.*.estimate`. Zusätzlich gerundet gegen die festen Zahlen in `08_kanon/GLIEDERUNG.md` (Referenz-, Runden-, Ausfallvergleich). Jede Abweichung: Abbruch, Ursache berichten, keine Variante.

## 4. Schritt 2: Implementierungsprüfung

Cluster-Varianten laufen über Clustersummen im unveränderten Kern (§5). Prüffall je Panel: jeder Block als eigener Cluster (Variante 0, Block-Bootstrap) gegen einen direkten Kernaufruf mit Blockatomen (Qualität als `mean` mit dem jeweiligen Wertebereich als `bounds`, Kosten als `ratio`), gleicher Seed. Abweichung je Grenze, Punktwert und Standardfehler höchstens 1e-12, sonst Abbruch.

## 5. Schritt 3: Varianten

Für Cluster c mit m_c Blöcken: S_c = Σ (x_i + h) mit h = 1 bei Wertebereich [−1, 1] und h = 2 bei [−2, 2], m_c, sowie je Kostenquotient A_c = Σ Zählerkosten, B_c = Σ Nennerkosten (Summen mit `math.fsum`, Kosten `float(Decimal(...))`). Endpunkte im Kern als `ratio`: Qualität S/m (Grenzen um −h zurückverschoben), Kosten A/B. Alle Endpunkte eines Panels in einem Kernaufruf, also mit gemeinsamen Ziehungen. B = 19.999, studentisiert, Quantile 0,025/0,975, unveränderte Sperren, keine Ersatzverfahren. Clusterreihenfolge: sortierte Schlüssel.

- **Variante 0, Block-Bootstrap** (Referenz, trennt Methode von Clusterung): Cluster = Block. Seed-Label `<Panel>-cluster-block-bootstrap`.
- **Variante A, Aufgaben:** Cluster = `task_id`. Seed-Label `<Panel>-cluster-task-bootstrap`.
- **Variante B, Familien:** Cluster = `family_id`. Seed-Label `<Panel>-cluster-family-bootstrap`.
- Seed-Ableitung wie P-Cluster: kanonisches JSON von `['Z50-analysis-v1', 'Z50-STUDY-v1', 20260920, Label]` (`sort_keys=True`, Trenner `(',', ':')`, `ensure_ascii=False`), SHA256, erste 16 Byte Little-Endian; Panel ∈ {R, T, F}. Prüfung: dieselbe Funktion liefert für `P-bootstrap` den Primärseed `142211229048427227715370149966446052232`.
- Monte-Carlo-Kontrolle, nachrangig: A und B zusätzlich mit dem Primärseed. Maßgeblich bleiben die abgeleiteten Seeds; kein Nachschieben weiterer Seeds.
- **Analytische Ergänzung, Hoeffding über Cluster:** dieselbe Ungleichung wie die Hauptauswertung, aber mit Clustern statt Blöcken als unabhängigen Einheiten, bedingt auf die beobachteten Clustergrößen: Clustersumme liegt in [m_c·a, m_c·b], Radius = (b − a) · sqrt(ln 40 · Σ m_c² / 2) / n. Für Einzelcluster ergibt das genau den Radius der Hauptauswertung. Nur Qualität (EM, F1), für Aufgaben und Familien.

## 6. Wiederholungsstruktur (beschreibend)

Je Panel: Zahl verschiedener Aufgaben und Familien, Clustergrößen (Minimum, Median, Maximum, Mittel, Anteil Blöcke in den 1 % größten Clustern), Zahl mehrfach gezogener Aufgaben und ihr Blockanteil, Σ m²/n für Aufgaben und Familien. **Anteil identischer Ergebnisse bei Wiederholung:** unter den mehrfach gezogenen Aufgaben der Anteil, bei dem (a) der EM-Kontrast jedes Vergleichs über alle Wiederholungen gleich ist, (b) die EM eines Arms über alle Wiederholungen gleich ist (je Arm). Dazu der Anteil gleicher EM-Kontraste über alle Paare von Wiederholungen derselben Aufgabe.

## 7. Ablesung

- Berichtet werden je Kennzahl Punktwert, Hoeffding-Intervall der Hauptauswertung (nur Qualität), Hoeffding über Aufgaben und Familien, Intervalle der Varianten 0, A, B mit Standardfehler und Status, Intervallbreite, Breitenverhältnis zu Hoeffding und zu Variante 0 und dessen Quadrat.
- Qualität, je Variante: Liegt 0 im Intervall? Liegt −3 bzw. +3 Prozentpunkte im Intervall? Eine Aussage gilt als **gekippt**, wenn sich gegenüber dem Hoeffding-Intervall der Hauptauswertung ändert, ob 0 enthalten ist. Das betrifft nach den bekannten Hoeffding-Werten vor allem R08 (untere Grenze +1,71) und R05 (obere Grenze −0,01); die übrigen Intervalle enthalten 0.
- Kosten: Hoeffding-Intervalle gibt es nicht, die Hauptauswertung beschreibt Kosten nur. Bootstrap-Intervalle für Kosten wurden vor der abschließenden Bewertung verworfen, weil die Simulation für die ergänzenden Vergleiche zu geringe Genauigkeit zeigte. Die Kostenintervalle hier sind deshalb nur eine Einordnung der Spannweite unter Clusterung, keine abgesicherte Kostenrichtung; gelesen wird nur, ob 1 enthalten ist.
- Keine weitere Variante, kein anderes Verfahren und kein anderer Endpunkt nach Sicht der Ergebnisse.

## 8. Grenzen, vorab benannt

- Clusterbootstrap behandelt Aufgaben bzw. Familien als Ziehungseinheit; das ist eine andere Abhängigkeitsannahme, keine Aussage über Aufgaben außerhalb des Dev-Bestands.
- Zeitlich gemeinsame Anbieterzustände (Last, Cache, Modellstand, Wechsel von sequenzieller zu paralleler Erhebung im Referenzvergleich ab Block 2.183) erfasst keine der Varianten.
- Die analytische Hoeffding-Variante setzt unabhängige Cluster voraus und ist bedingt auf die Clustergrößen; dass die Aufgabenwahl unabhängig von der Zahl der Ziehungen ist, wird angenommen.
- Wenige große Familiencluster schwächen die Studentisierung; die Größenverteilung wird berichtet.

## 9. Ausgaben

Skript `cluster_nebenvergleiche.py` (prüft die SHA256 dieser Datei gegen `VORAB.md.sha256` bei jedem Lauf), Rohwerte `CLUSTER-NEBENVERGLEICHE.json`, Ergebnis `CLUSTER-NEBENVERGLEICHE.md`, Codex-Prüfung `CODEX-1.md` (ggf. `CODEX-2.md`, `CODEX-3.md`).
