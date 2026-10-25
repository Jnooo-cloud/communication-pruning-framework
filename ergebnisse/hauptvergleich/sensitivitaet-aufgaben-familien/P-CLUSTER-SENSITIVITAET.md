<!-- status: entwurf | quellen: STATE.json Z51 (alter Repo-Pfad siehe §0), P-ANALYSIS.json, ZAHLENPRUEFUNG.md, intervals.py, final_analysis.py, Technischer Anhang §§ 151, 165, 181–185, runde3/CODEX.md | codex: GO Runde 2 (Runde 1 NO-GO) | 2026-10-04 -->

# Explorative Cluster-Sensitivität für den Hauptvergleich P

**Explorativ und nachträglich.** Diese Analyse ist nicht Teil des vorab gebundenen Analysevertrags. Sie ändert die Hauptanalyse nicht, ersetzt sie nicht und wird unabhängig von ihrer Richtung berichtet.

## 0. Vorab-Festlegung

**Festgelegt am 04.10.2026, 09:32 MESZ, bevor eine P-Einzelzeile geladen oder eine Cluster-Variante gerechnet wurde.** Bis zu diesem Zeitpunkt waren nur die aggregierten Werte aus `P-ANALYSIS.json` und `ZAHLENPRUEFUNG.md` bekannt (2.239 Aufgaben, 528 Familien, 9.040 Paare). Die SHA256 dieses Abschnitts 0 wird vor dem ersten Rechenlauf in `P-CLUSTER-VORAB.sha256` festgehalten; das Skript prüft sie bei jedem Lauf.

### 0.1 Daten

- Einzelzeilen: `eval-harness/eval/runs/Z51-RETRY-EINZELERSATZ-001/operation/isolated-backup-D074/8fa92e0363674966964a48fc89d9abc1/STATE.json` im alten Repo, nur lesend. Pflicht: SHA256 `960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6`, Feld `rows` über `STATE-INDEX.json`, 18.080 Zeilen, 9.040 Draws mit genau Q und F.
- Cluster-Schlüssel: `task_id` (Variante A) und `family_id` (Variante B). Aufgabenfamilien sind im Material definiert: verbundene Komponenten über gemeinsame `question_decomposition`-IDs (Technischer Anhang, Abschnitt Daten). Beide Schlüssel sind innerhalb eines Paars gleich (ZAHLENPRUEFUNG §1).
- Kein Ausschluss, keine Imputation: Modellausfälle mit EM = 0 und bekannten Kosten bleiben drin; die vier unbekannten Originalkosten bleiben wie in der Hauptanalyse außen vor (Kostenannahme D-074 unverändert).

### 0.2 Schritt 1: Hauptanalyse exakt reproduzieren

- Atome je Draw wie `final_analysis._primary`: `[EM_Q − EM_F, float(C_Q), float(C_F)]`, Reihenfolge nach `draw_index`.
- Kern unverändert importiert: `study_preparation/intervals.analyze` (SHA256 `3ddb2db6…` laut ZAHLENPRUEFUNG §3), Endpunkte `PRIMARY_ENDPOINTS` aus `final_analysis.py`, Gewichte `np.ones(9040)`, B = 19.999, `np.random.PCG64(142211229048427227715370149966446052232)`. Seed vorher unabhängig aus `['Z50-analysis-v1', 'Z50-STUDY-v1', 20260920, 'P-bootstrap']` abgeleitet (kanonisches JSON, `sort_keys=True`, Trenner `(',', ':')`, `ensure_ascii=False`; SHA256, erste 16 Byte Little-Endian).
- Abnahme: EM Q = 0,3199115044…, EM F* = 0,3620575221…, Punktwerte, Standardfehler, untere und obere Grenzen beider Endpunkte **bitgleich** zu `P-ANALYSIS.json` (`report.primary.kernel`), Kostenquotient 1,1692640311394327. Bei Abweichung: Abbruch, Ursache berichten, keine Cluster-Variante.

### 0.3 Schritt 2: Implementierungsprüfung

Die Cluster-Varianten nutzen denselben Kern über Clustersummen (§0.4). Prüffall: jeder Draw als eigener Cluster, Primärseed. Das muss die Grenzen aus Schritt 1 bis auf Gleitkomma-Rundung reproduzieren (|Abweichung| ≤ 1e-12 je Grenze). Sonst Abbruch.

### 0.4 Schritt 3: Cluster-Varianten

Für jeden Cluster c mit m_c Paaren: `S_c = Σ (D_i + 1)`, `m_c`, `A_c = Σ C_Q,i`, `B_c = Σ C_F,i`. Endpunkte:

- **Qualität:** `Δ = Σ_c S_c / Σ_c m_c − 1`, also genau der Mittelwert der 9.040 Paardifferenzen (paargewichtet, keine Familien- oder Aufgabengleichgewichtung). Der Kern kennt nur nichtnegative Verhältnisse; die Verschiebung um +1 ändert weder Pivot noch Standardfehler (Residuum `S_c − (Δ + 1) m_c = Σ D_i − Δ m_c`). Grenzen werden um −1 zurückverschoben.
- **Kosten:** `ρ = Σ_c A_c / Σ_c B_c`, also genau das Verhältnis der Kostenmittel.
- Verfahren: `intervals.analyze` mit Atomen `[S_c, m_c, A_c, B_c]`, Endpunkten vom Typ `ratio`, Gewichten `np.ones(G)`; das heißt ganze Cluster mit allen ihren Q/F*-Paaren werden mit Zurücklegen gezogen (G aus G), studentisiert mit dem linearisierten Cluster-Standardfehler des Kerns, Quantile 0,025/0,975, B = 19.999, unveränderte Sperren (`denominator_weak`, `variance_zero`, `resample_undefined`) ohne Ersatzverfahren.
- **Variante A, Aufgaben:** Cluster = `task_id`. Seed nach derselben Logik aus `['Z50-analysis-v1', 'Z50-STUDY-v1', 20260920, 'P-cluster-task-bootstrap']`.
- **Variante B, Familien:** Cluster = `family_id`. Seed aus `['Z50-analysis-v1', 'Z50-STUDY-v1', 20260920, 'P-cluster-family-bootstrap']`.
- Monte-Carlo-Kontrolle, nachrangig: beide Varianten zusätzlich mit dem Primärseed. Maßgeblich bleiben die abgeleiteten Seeds; kein Nachschieben weiterer Seeds.

### 0.5 Ablesung

- Gleiche sechs Aussagen und Schwellen wie die Hauptanalyse: Qualität erhalten (L_Δ > −0,03), Qualitätsverlust (U_Δ < 0), Verlust über 3 pp (U_Δ < −0,03), Kostenersparnis mindestens 10 % (U_ρ < 0,90), Ersparnis unter 10 % (L_ρ > 0,90), Kostenanstieg (L_ρ > 1); gemeinsamer positiver Befund nur bei L_Δ > −0,03 und U_ρ < 0,90.
- Berichtet werden je Variante Punktwert, Standardfehler, Grenzen, Status, Intervallbreite, Breitenverhältnis zur Hauptanalyse und dessen Quadrat (als grobe Kennzahl eines Designeffekts), dazu Clusterzahl und Verteilung der Clustergrößen.
- Interpretation vorab: Bleiben alle sechs Aussagen gleich, gilt die Hauptaussage als robust gegenüber dieser Abhängigkeitsannahme. Kippt eine Aussage, wird das als Befund berichtet, die Hauptanalyse bleibt maßgeblich, und die Arbeit nennt beide Ergebnisse. Keine weitere Variante, kein anderes Verfahren nach Sicht der Ergebnisse.

### 0.6 Grenzen, vorab benannt

- Andere Zielgröße der Unsicherheit: Clusterbootstrap behandelt Aufgaben bzw. Familien als Ziehungseinheit; das entspricht einem Verallgemeinerungsanspruch auf neue Aufgaben bzw. Familien, nicht dem gebundenen Schluss auf den festen Dev-Bestand.
- Zeitlich gemeinsame Anbieterzustände (Last, Cache, Modellstand) werden weder durch Aufgaben- noch durch Familiencluster erfasst.
- Wenige sehr große Cluster würden die Studentisierung schwächen; die Clustergrößenverteilung wird deshalb berichtet.
- Der Kern klemmt sehr kleine Standardfehler bei Verhältnissen auf 0 (`ZERO_TOL`); für die Qualitätsgröße in Verhältnisform greift das statt der Qualitätsregel. Bei den erwarteten Größenordnungen ist das ohne Wirkung; wenn doch, wird es als Status berichtet.

## 1. Ergebnis

Gerechnet am 04.10.2026 ab 09:35 MESZ mit `p_cluster.py`; Rohwerte in `P-CLUSTER-SENSITIVITAET.json`. Das Skript prüft vor jedem Lauf die SHA256 von Abschnitt 0 gegen `P-CLUSTER-VORAB.sha256` (`eb53559e…`).

**Kurzbefund.** Unter beiden Cluster-Annahmen bleiben Qualitätsverlust und (unter der Kostenannahme D-074) Kostenanstieg von Q gegenüber F\* festgestellt; Qualitätserhalt innerhalb 3 pp ist nach der festgelegten Regel weiterhin nicht nachgewiesen, ein gemeinsamer positiver Befund also nicht festgestellt. Die Intervalle werden aber deutlich breiter (Qualität rund 2,2- bis 2,4-fach, Kosten 1,7- bis 2,6-fach). Dadurch kippt eine der sechs Aussagen: Ein Qualitätsverlust **über 3 Prozentpunkte** ist unter Aufgaben- und unter Familienclustern nicht mehr festgestellt (obere Grenze −2,72 bzw. −2,60 pp statt −3,54 pp). Ein Qualitätsverlust überhaupt bleibt festgestellt.

### 1.1 Schritt 1 und 2: Reproduktion

- STATE.json SHA256 wie gefordert, 18.080 Zeilen, 9.040 Draws mit Q und F; Code-SHA256 von `intervals.py` und `final_analysis.py` wie in ZAHLENPRUEFUNG §3; Seed unabhängig abgeleitet und gleich.
- **Hauptanalyse bitgleich reproduziert:** EM Q 0,3199115044247788, EM F\* 0,3620575221238938; P-D −0,042146017699115045, Grenzen −0,049015432668103605 bis −0,03539775454970843; P-C 1,1692640311394327, Grenzen 1,1620586486852333 bis 1,1763602101327406; Standardfehler, Status und null undefinierte Resamples identisch zu `P-ANALYSIS.json`.
- Laufzeitumgebung: Bitgleichheit gilt mit dem provisionierten Python 3.12 im alten Repo (`runs/Z38-QSEM-001/provision/python`, numpy 1.26.4 mit OpenBLAS). Das System-Python mit numpy 1.26.4 auf Apple Accelerate weicht schon beim Punktwert P-C in der 16. Stelle ab (1,1692640311394336) und bricht die Abnahme ab; Ursache ist die andere Summationsreihenfolge der BLAS-Bibliothek. Alle Ergebnisse unten stammen aus dem provisionierten Python.
- Einzelcluster-Prüfung bestanden: größte Abweichung 1,0 · 10⁻¹⁶.

### 1.2 Schritt 3: Cluster-Varianten

| | Hauptanalyse (Paare) | A: Aufgaben | B: Familien |
|---|---:|---:|---:|
| Resampling-Einheiten | 9.040 | 2.239 | 528 |
| Clustergröße Median (Spanne) | 1 | 4 (1 bis 12) | 9 (1 bis 224) |
| P-D Punkt (pp) | −4,21 | −4,21 | −4,21 |
| P-D Standardfehler (pp) | 0,347 | 0,772 | 0,823 |
| P-D Grenzen (pp) | −4,90 bis −3,54 | −5,75 bis −2,72 | −5,92 bis −2,60 |
| P-C Punkt | 1,1693 | 1,1693 | 1,1693 |
| P-C Standardfehler | 0,00367 | 0,00623 | 0,00926 |
| P-C Grenzen | 1,1621 bis 1,1764 | 1,1572 bis 1,1816 | 1,1505 bis 1,1874 |
| Breitenverhältnis P-D / P-C | 1 / 1 | 2,22 / 1,71 | 2,43 / 2,58 |
| Status, undefinierte Resamples | ok, 0 | ok, 0 | ok, 0 |

Monte-Carlo-Kontrolle mit dem Primärseed: A −5,77 bis −2,69 pp und 1,1569 bis 1,1816; B −5,90 bis −2,65 pp und 1,1505 bis 1,1875. Gleiche Aussagen wie mit den abgeleiteten Seeds.

Familien: Die 1 % größten Familien (5 von 528) enthalten 10,9 % der Paare, die größte 224 Paare.

### 1.3 Aussagen

| Aussage (Schwelle) | Hauptanalyse | A: Aufgaben | B: Familien |
|---|---|---|---|
| Qualität erhalten (L_Δ > −3 pp) | nicht festgestellt | nicht festgestellt | nicht festgestellt |
| Qualitätsverlust (U_Δ < 0) | festgestellt | festgestellt | festgestellt |
| Verlust über 3 pp (U_Δ < −3 pp) | **festgestellt** | **nicht festgestellt** | **nicht festgestellt** |
| Ersparnis mindestens 10 % (U_ρ < 0,90) | nicht festgestellt | nicht festgestellt | nicht festgestellt |
| Ersparnis unter 10 % (L_ρ > 0,90) | festgestellt | festgestellt | festgestellt |
| Kostenanstieg (L_ρ > 1) | festgestellt | festgestellt | festgestellt |
| gemeinsamer positiver Befund | nein | nein | nein |

Nach der Vorab-Regel (§0.5) ist das ein gekippter Befund und wird so berichtet. Die Hauptanalyse bleibt maßgeblich.

### 1.4 Nachträgliche Beschreibung (nicht vorab festgelegt, keine Inferenz)

Um die Verbreiterung einzuordnen, beschreibt `p_cluster_beschreibung.py` (Ausgabe `P-CLUSTER-BESCHREIBUNG.json`) den Ziehungsrahmen und die Wiederholungsstruktur. Das ist eine nachträgliche Erklärung, keine weitere Variante.

- Ziehungsrahmen laut `PLAN.json` (SHA256 `42a55ddd…`): 2.277 Aufgaben in 535 Familien, Ziehung mit Zurücklegen. Bei gleichwahrscheinlicher Ziehung wären 2.234 verschiedene Aufgaben zu erwarten; beobachtet sind 2.239.
- 2.081 Aufgaben wurden mehrfach gezogen (8.882 der 9.040 Paare). In 99,2 % davon ist die EM-Differenz Q − F\* bei allen Wiederholungen gleich; die Intraklassenkorrelation der EM-Differenz innerhalb einer Aufgabe beträgt 0,98, die des Kostenresiduums 0,47.
- Die Größe Σm²/n (m = Ziehungen je Aufgabe) beträgt 4,91, erwartet unter gleichwahrscheinlicher Ziehung 4,97. Das Quadrat des Breitenverhältnisses bei P-D in Variante A beträgt 4,94.

Lesart: Weil wiederholte Ziehungen derselben Aufgabe fast immer dasselbe Qualitätsergebnis liefern, behandelt der Aufgabenbootstrap eine Aufgabe mit m Ziehungen ähnlich wie ein einzelnes, m-fach gewichtetes Ergebnis. Seine Varianz wächst dann näherungsweise um einen Faktor in der Größenordnung von Σm²/n, und diese Größenordnung zeigt sich (analytischer Varianzquotient laut Codex-Nachrechnung 4,96, Quadrat des Breitenverhältnisses 4,94, Σm²/n 4,91). Das ist keine allgemeine Identität; der Faktor hängt auch davon ab, wie Clustergröße und Abweichung vom Gesamtmittel zusammenhängen.

Zur Einordnung: Die Aufgabenziehungen der Hauptstudie sind nach Design unabhängig (gleichwahrscheinlich mit Zurücklegen aus dem festen Rahmen). Für unabhängige **Paarergebnisse** braucht der Paarbootstrap zusätzlich die im Analysevertrag benannte Annahme eines stationären Generierungsprozesses ohne gemeinsame zufällige Zustände zwischen Ziehungen (Technischer Anhang, Abschnitt zur Ziehung). Weder die identischen EM-Differenzen noch die passenden Wiederholungszahlen prüfen diese Annahme. Die Zielgröße der Hauptanalyse ist vorab festgelegt (aufgabengewichtetes Mittel über den festen Rahmen); die Clusterintervalle zeigen die Sensitivität gegenüber einer anderen angenommenen Abhängigkeitsstruktur, nicht eine alternative Zielgröße, zwischen der nachträglich zu wählen wäre.

## 2. Unterschied zur Hauptanalyse

- Gleich: Daten, Paarbildung, Punktschätzer (paargewichteter Mittelwert der EM-Differenzen, Verhältnis der Kostenmittel), Kern `intervals.analyze`, B = 19.999, Quantile, Sperren, Schwellen.
- Anders: Resampling-Einheit (Aufgabe bzw. Familie statt Paar), damit der Standardfehler (Cluster-linearisiert) und der Verallgemeinerungsanspruch; die Qualitätsgröße läuft im Kern als Verhältnis statt als Mittel (§0.4).
- Die Hauptanalyse ist vorab gebunden und bleibt maßgeblich; diese Analyse ist nachträglich und explorativ.

## 3. Grenzen

- Die in §0.6 genannten Grenzen gelten: andere Zielgröße der Unsicherheit, keine Erfassung zeitlich gemeinsamer Anbieterzustände (Last, Cache, Modellstand), wenige große Familiencluster (größte 224 Paare, 10,9 % der Paare in den 5 größten).
- Familien sind über gemeinsame Teilfragen definiert; gemeinsame Kontextpassagen außerhalb dieser Regel sind nicht berücksichtigt.
- Die Beschreibung in §1.4 ist nachträglich; die ICC ist ein grobes Maß für eine diskrete EM-Differenz mit den Werten −1, 0 und +1.
- Ein Bootstrap über Zeitabschnitte oder Laufsegmente wurde nicht gerechnet.

## 4. Folgerung für die Arbeit

- Robust gegenüber beiden Cluster-Annahmen: Q verliert gegenüber F\* an Qualität, und unter der unveränderten Kostenannahme D-074 sind die bekannten Kosten höher. Qualitätserhalt innerhalb 3 pp ist nach der festgelegten Entscheidungsregel nicht nachgewiesen; der gemeinsame positive Befund des Effizienzvertrags ist damit nicht festgestellt.
- Nicht robust: der Nachweis eines Qualitätsverlusts **über** 3 Prozentpunkte. Formulierungen wie „obere Qualitätsgrenze −3,54 pp liegt unter −3 pp“ sollten mit dem Zusatz stehen, dass dies unter der Paar-Analyseeinheit gilt und unter Aufgaben- oder Familienclustern nicht mehr festgestellt ist.
- Die Darstellungspflicht aus Runde 3 (Analyseeinheit, Zielgröße, Ziehung mit Zurücklegen, Annahme stationärer Generierungen) wird durch §1.4 konkreter: Wiederholte Ziehungen derselben Aufgabe liefern fast immer dasselbe Ergebnis. Die Clusterintervalle zeigen die Sensitivität gegenüber einer anderen angenommenen Abhängigkeitsstruktur. Eine Übertragung auf eine größere Aufgabenpopulation erfordert zusätzliche Annahmen (Zielpopulation, Auswahl und Unabhängigkeit ihrer Aufgaben bzw. Familien), die diese Analyse nicht begründet.
