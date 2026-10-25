<!-- status: entwurf | quellen: STATE.json Z51 (alter Repo-Pfad, SHA256 960d6402…), rows-R.json Z53 (7f836d8b…), P-ANALYSIS.json, ANALYSIS-R.json, ZAHLENPRUEFUNG.md, P-CLUSTER-SENSITIVITAET.md, intervals.py, configurations.py, Technischer Anhang §14 | codex: GO Runde 2 (Runde 1 NO-GO) | 2026-10-04 -->

# Aufschlüsselung des Qualitätsverlusts von Q gegenüber F*

**Nachträglich und erklärend.** Diese Aufschlüsselung ist nicht Teil des vorab gebundenen Analysevertrags. Sie ändert die Hauptanalyse nicht und wird unabhängig von ihrer Richtung berichtet.

## 0. Vorab-Festlegung

**Festgelegt am 04.10.2026 gegen 10:50 MESZ, bevor eine Untergruppe gerechnet wurde.** Bekannt waren zu diesem Zeitpunkt nur: die aggregierten Werte aus `P-ANALYSIS.json`, `ZAHLENPRUEFUNG.md` und `P-CLUSTER-SENSITIVITAET.md`; aus `ANALYSIS-R.json` die Armmittel und der Vergleich R05 (Q gegen F*); die Häufigkeiten der von Q gewählten Konfigurationen im R-Panel (C01 487 von 2.952, alle 14 kommen vor; F* ist dort immer C01); das Zeilenschema beider Panels einschließlich einer einzelnen P-Zeile (Draw 0, Arm Q). EM, F1 oder Kosten nach Untergruppen waren nicht bekannt. Die SHA256 dieses Abschnitts 0 wird vor dem ersten Rechenlauf in `Q-VERLUST-VORAB.sha256` festgehalten; das Skript prüft sie bei jedem Lauf.

### 0.1 Panels und Daten

- **P (Hauptstudie, Z51):** `STATE.json` im alten Repo, nur lesend, SHA256 `960d6402c87d16c9fc9817e86f1c6a0d0cddafe8d1e66c2b665c1ea1a2f05be6`, Feld `rows` über `STATE-INDEX.json`, 18.080 Zeilen, 9.040 Draws mit genau Q und F. Gleicher Ladeweg wie `p_cluster.py`.
- **R (Referenzpanel, Z53):** `04_ergebnisse/daten/collected/rows-R.json`, SHA256 `7f836d8bf04fae7d1fd0f1e616ba39c314ebc357fc2e5c1bbcfb5d73aa83d3b0` (gleich `rows_sha256` in `ANALYSIS-R.json`). Verwendet werden nur die Arme Q und F derselben Blöcke (2.952 Paare). Die anderen vier Arme bleiben außen vor.
- **Nicht einbezogen:** T- und F-Panel. Dort laufen Q und F* unter Rundenwahl beziehungsweise Ausfall, also unter anderen Bedingungen; das würde die Aufschlüsselung vermischen.
- **Konfigurationsraum:** `communication_pruning/configurations.py` im alten Repo, SHA256 `538bed52e74482ddbd0300fee9965254ec571bddf3adc4868d443c75db8b4796`. Rollen und Kanten je Konfiguration werden aus `bank()` gelesen, nicht von Hand übertragen.
- Kein Ausschluss, keine Imputation: Modellausfälle bleiben mit EM = 0 und bekannten Kosten drin. Kosten wie in der Hauptanalyse (bekannte Kosten, Annahme D-074 zu den vier unbekannten Originalen unverändert).

### 0.2 Schritt 1: bekannte Werte exakt reproduzieren

- P: EM Q 0,3199115044247788 und EM F* 0,3620575221238938; F1-Mittel wie ZAHLENPRUEFUNG §2; Summe der EM-Differenzen −381 (690 × −1, 309 × +1); P-D und P-C mit Kern `intervals.analyze`, Primärseed und B = 19.999 **bitgleich** zu `P-ANALYSIS.json` (gleiches Verfahren und gleiche Laufzeitumgebung wie `p_cluster.py`, provisioniertes Python 3.12).
- R: EM Q 0,29336043360433606, EM F* 0,3434959349593496, R05-Qualitätsschätzer −0,05013550135501355, Kostenquotient R05 als Decimal-Zeichenkette gleich `ANALYSIS-R.json`; Q-Konfigurationshäufigkeiten (C01 = 487).
- In beiden Panels ist jede F-Zeile Konfiguration C01; jede Q- und F-Zeile eines Paars hat dieselbe `task_id`.
- Bei Abweichung: Abbruch, Ursache berichten, keine Aufschlüsselung.

### 0.3 Begriffe

- Paar i: Q- und F-Zeile desselben Blocks. D_i = EM_Q − EM_F, analog F1. Kosten C_Q, C_F (bekannte Kosten in US-Dollar).
- **gleich:** Q wählt C01, also dieselbe Konfiguration wie F*. **abweichend:** Q wählt eine andere der 14 Konfigurationen.
- **Gesamtverlust** L = Σ D_i über alle Paare des Panels. **Beitrag** einer Gruppe = Σ D_i in der Gruppe; **Anteil am Gesamtverlust** = Beitrag / L. Einzelne Anteile können negativ sein oder über 100 % liegen; sie summieren sich zu 100 %.
- **Kostenquotient** einer Gruppe = Σ C_Q / Σ C_F in der Gruppe (Verhältnis der Mittel wie in der Hauptanalyse).
- Kontrolle der Zerlegung: L/n = Anteil_abw · Δ_abw + Anteil_gleich · Δ_gleich, exakt mit Brüchen geprüft.

### 0.4 Aufschlüsselungen (je Panel, rein beschreibend, immer mit n)

Kennzahlen je Gruppe: n, Anteil an allen Paaren, EM Q, EM F*, ΔEM, ΔF1, Beitrag und Anteil am Gesamtverlust, Zahl der Paare „Q richtig, F* falsch“ und „Q falsch, F* richtig“, Modellausfälle Q und F*, mittlere Kosten Q und F*, Kostenquotient, mittlere Aufrufzahl Q und F*.

- **(a) gleich gegen abweichend.**
- **(b) je von Q gewählter Konfiguration** (14 Gruppen), zusätzlich Rollen und Kantenzahl.
- **(c) nach Aufgabenmerkmalen aus der `task_id`:** MuSiQue-Typpräfix vor `__` (erwartet `2hop`, `3hop1`, `3hop2`, `4hop1`, `4hop2`, `4hop3`) und daraus die Hop-Zahl (erste Ziffer). Prüfung: Zahl der durch `_` getrennten Teilfragen-IDs nach `__` gleich Hop-Zahl; Abweichungen werden gezählt, nicht ausgeschlossen. Je Typ und je Hop-Zahl: die Kennzahlen oben, dazu Anteil abweichend sowie ΔEM getrennt für gleich und abweichend. Die Bedeutung der Ziffer nach `hop` wird nicht gedeutet, weil sie aus dem Material nicht belegbar ist.
- **(d) Richtung der Abweichung:** Gruppen nach Bauform: C01; andere Zweiergruppe (C02 bis C06); Dreiergruppe Ring; Dreiergruppe vollvernetzt. Zusätzlich nach Zahl der mit C01 geteilten Rollen (2, 1 oder 0). Zusätzlich in abweichenden Paaren nach der im Block beobachteten Kostenrichtung (C_Q > C_F, gleich, C_Q < C_F) mit ΔEM je Klasse. Die Kostenrichtung hängt vom Ergebnis der Generierung ab (Antwortlänge, Cache) und ist deshalb nur eine Beschreibung, keine Ursache.
- **Konsistenzprüfungen:** Wählt Q für dieselbe `task_id` immer dieselbe Konfiguration, innerhalb P, innerhalb R und zwischen P und R? Zahl der Aufgaben mit mehr als einer Q-Konfiguration wird berichtet.

### 0.5 Intervalle (nur für vier vorab festgelegte Hauptkennzahlen, nur Panel P)

- Kennzahlen: **Δ_abw** und **Δ_gleich** (mittlere EM-Differenz in abweichenden bzw. gleichen Paaren), **ρ_abw** und **ρ_gleich** (Kostenquotient in abweichenden bzw. gleichen Paaren).
- Verfahren: unveränderter Kern `study_preparation/intervals.analyze` (SHA256 `3ddb2db6…`), studentisiert, Quantile 0,025/0,975, B = 19.999, unveränderte Sperren. Atome je Paar: `[(D+1)·a, a, (D+1)·g, g, C_Q·a, C_F·a, C_Q·g, C_F·g]` mit a = 1 bei abweichend, g = 1 − a. Alle vier Kennzahlen als Endpunkte vom Typ `ratio` in einem Aufruf, also mit derselben Ziehungsmatrix. Die Verschiebung um +1 wird wie in `P-CLUSTER-SENSITIVITAET.md` §0.4 an den Grenzen zurückgenommen. Die Gruppengröße ist dabei zufällig; das entspricht der Ziehung ganzer Paare aus allen 9.040.
- **Hauptvariante:** Paar als Ziehungseinheit wie in der Hauptanalyse, Gewichte `np.ones(9040)`. Seed nach der gebundenen Ableitung der Hauptanalyse (kanonisches JSON von `['Z50-analysis-v1', 'Z50-STUDY-v1', 20260920, label]`, SHA256, erste 16 Byte Little-Endian) mit label `'P-qverlust-pair-bootstrap'`.
- **Eine vorab festgelegte Sensitivität:** Aufgabe als Ziehungseinheit (Clustersummen der Atome je `task_id`), label `'P-qverlust-task-bootstrap'`. Grund: Die Clusteranalyse hat gezeigt, dass Paarintervalle unter Aufgabenclustern rund 2,2-mal breiter werden.
- Keine Entscheidungsschwellen, keine Tests über Untergruppen, keine weiteren Seeds oder Varianten nach Sicht der Ergebnisse. R bleibt ohne Intervalle (dort sind laut Vertrag Kosten nur beschreibend; Untergruppen-Hoeffding-Intervalle wären ohne Aussagekraft breit).

### 0.6 Ablesung und Grenzen, vorab benannt

- Alles außer §0.5 ist beschreibend. Gruppen mit n < 30 werden markiert und nicht gedeutet.
- **Keine Oracle-Aussage** (Technischer Anhang §14): Verglichen werden nur die in demselben Block tatsächlich beobachteten Arme Q und F*. Es wird nicht geschätzt, was eine andere Konfiguration in einer Aufgabe geliefert hätte, und nicht, welche Wahl die beste gewesen wäre.
- Weil Q aus dem Fragetext wählt, ist gleich/abweichend eine Eigenschaft der Aufgabe. Unterschiede zwischen den Gruppen vermischen deshalb Aufgabenschwierigkeit und Konfiguration. Die EM von F* je Gruppe (immer C01) wird als Beschreibung der Schwierigkeit mitberichtet, ohne daraus eine Ursache abzuleiten.
- In gleichen Paaren laufen beide Arme mit derselben Konfiguration. Ihre Differenz beschreibt Unterschiede zwischen zwei Generierungen, keine Wirkung der Auswahl.
- Erklärungen kommen nur als begründete Vermutung mit Prüfidee in einen eigenen Abschnitt.

## 1. Ergebnis

Gerechnet am 04.10.2026 ab 10:53 MESZ mit `q_verlust.py` im provisionierten Python 3.12 (numpy 1.26.4); Rohwerte in `Q-VERLUST-AUFSCHLUESSELUNG.json`. Das Skript prüft vor jedem Lauf die SHA256 von Abschnitt 0 gegen `Q-VERLUST-VORAB.sha256` (`613cae34…`).

**Kernbefund.** In der Hauptstudie wählt Q in 1.530 von 9.040 Paaren (16,9 %) dieselbe Konfiguration wie F\* (C01); dort haben beide Arme in jedem einzelnen Paar dasselbe EM-Ergebnis, und der gesamte Verlust von 381 Treffern (−4,21 Prozentpunkte) entsteht in den 7.510 abweichenden Paaren (−5,07 Prozentpunkte, 95-%-Intervall −5,88 bis −4,26, mit Aufgaben als Ziehungseinheit −6,91 bis −3,28). Die Abweichungen sind in zwei Richtungen ungünstig: Andere Zweiergruppen sind im Mittel etwas billiger als F\* (Kostenquotient 0,96), liegen aber 6,9 Prozentpunkte zurück und tragen 58 % des Verlusts; Dreiergruppen sind rund 38 bis 41 % teurer, tragen mehr als die gesamten Mehrkosten (108 %) und liegen ebenfalls zurück (Ring −1,9, vollvernetzt −7,9 Prozentpunkte). Das Referenzpanel R zeigt dasselbe Muster (gleich: 487 Paare, +0,4 Prozentpunkte; abweichend: 2.465 Paare, −6,1 Prozentpunkte, Kostenquotient 1,20).

### 1.1 Schritt 1: Reproduktion

- P: STATE.json SHA256 wie gefordert, 18.080 Zeilen, 9.040 Paare. EM Q 0,3199115044247788, EM F\* 0,3620575221238938, F1 0,4359280383754858 und 0,48077504695132584, EM-Differenzen 690 × −1, 309 × +1, 8.041 × 0. P-D und P-C (Punkt, Standardfehler, Grenzen, Status, undefinierte Resamples) **bitgleich** zu `P-ANALYSIS.json`.
- R: `rows-R.json` SHA256 wie gefordert und gleich `rows_sha256` in `ANALYSIS-R.json`. EM Q 0,29336043360433606, EM F\* 0,3434959349593496, R05-Qualitätsschätzer −0,05013550135501355 und R05-Kostenquotient (Decimal-Zeichenkette) exakt gleich. Q-Konfigurationen: alle 14, C01 487-mal.
- In beiden Panels ist jede F-Zeile C01, Q- und F-Zeile eines Paars haben dieselbe `task_id`. Codehashes von `intervals.py`, `final_analysis.py` und `configurations.py` wie in §0.
- Zerlegungskontrolle exakt bestanden: −381/9.040 = 0,831 · (−5,073 pp) + 0,169 · 0 (P); −148/2.952 = 0,835 · (−6,085 pp) + 0,165 · (+0,411 pp) (R).
- Konsistenz: Q wählt für jede Aufgabe immer dieselbe Konfiguration (P: 2.239 Aufgaben, R: 1.663 Aufgaben, je null Aufgaben mit mehr als einer Q-Konfiguration). Die 1.634 Aufgaben, die in beiden Panels vorkommen, erhalten in beiden dieselbe Konfiguration. Gleich und abweichend ist also eine feste Eigenschaft der Aufgabe (P: 384 der 2.239 Aufgaben gleich).

### 1.2 (a) Gleich gegen abweichend

EM in Prozent, Δ in Prozentpunkten (Q minus F\*). „Anteil Verlust“ = Beitrag der Gruppe zur Summe der EM-Differenzen. „Anteil Mehrkosten“ = Beitrag zu Σ C_Q − Σ C_F.

| Panel | Gruppe | n (Anteil) | EM Q | EM F\* | ΔEM | ΔF1 | Q richtig, F\* falsch | Q falsch, F\* richtig | Anteil Verlust | Kosten-quotient | Anteil Mehrkosten | Ausfälle Q / F\* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P | gleich (C01) | 1.530 (16,9 %) | 33,01 | 33,01 | 0,00 | −0,02 | 0 | 0 | 0 % | 1,010 | 1 % | 56 / 57 |
| P | abweichend | 7.510 (83,1 %) | 31,78 | 36,86 | −5,07 | −5,39 | 309 | 690 | 100 % | 1,200 | 99 % | 172 / 167 |
| R | gleich (C01) | 487 (16,5 %) | 31,01 | 30,60 | +0,41 | +0,18 | 2 | 0 | −1,4 % | 0,987 | −1,3 % | 14 / 15 |
| R | abweichend | 2.465 (83,5 %) | 29,01 | 35,09 | −6,09 | −5,73 | 85 | 235 | 101,4 % | 1,197 | 101,3 % | 45 / 58 |

Bekannte Mehrkosten von Q insgesamt: P 2,08964455 US-Dollar (davon abweichend 2,06888949), R 0,60517029 US-Dollar.

### 1.3 Vorab festgelegte Intervalle (nur P)

| Kennzahl | Punkt | Paar als Einheit (Haupt) | Aufgabe als Einheit (Sensitivität) |
|---|---:|---|---|
| Δ_abw (pp) | −5,07 | −5,88 bis −4,26, ok | −6,91 bis −3,28, ok |
| Δ_gleich (pp) | 0,00 | kein Intervall, Status `variance_zero` | kein Intervall, Status `variance_zero` |
| ρ_abw | 1,1998 | 1,1929 bis 1,2068, ok | 1,1864 bis 1,2130, ok |
| ρ_gleich | 1,0104 | 0,9872 bis 1,0340, ok | 0,9876 bis 1,0340, ok |

B = 19.999, Seeds abgeleitet aus `'P-qverlust-pair-bootstrap'` (`71036992…`) und `'P-qverlust-task-bootstrap'` (`21439480…`), null undefinierte Resamples bei allen Endpunkten mit Status ok. Δ_gleich hat keine Streuung, weil alle 1.530 gleichen Paare die EM-Differenz 0 haben; die vorab festgelegte Sperre greift, ein Ersatzverfahren wird nicht verwendet.

### 1.4 (d) Richtung der Abweichung

| Panel | Bauform der Q-Wahl | n | EM Q | EM F\* | ΔEM | Anteil Verlust | Kosten-quotient | Anteil Mehrkosten | Aufrufe Q / F\* |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P | C01 (wie F\*) | 1.530 | 33,01 | 33,01 | 0,00 | 0 % | 1,010 | 1,0 % | 4,91 / 4,91 |
| P | andere Zweiergruppe | 3.217 | 30,25 | 37,15 | −6,90 | 58,3 % | 0,959 | −9,0 % | 4,97 / 4,97 |
| P | Dreiergruppe Ring | 3.018 | 33,60 | 35,52 | −1,92 | 15,2 % | 1,383 | 74,8 % | 6,90 / 4,94 |
| P | Dreiergruppe vollvernetzt | 1.275 | 31,37 | 39,29 | −7,92 | 26,5 % | 1,407 | 33,2 % | 6,94 / 4,98 |
| R | C01 (wie F\*) | 487 | 31,01 | 30,60 | +0,41 | −1,4 % | 0,987 | −1,3 % | 4,93 / 4,93 |
| R | andere Zweiergruppe | 1.065 | 26,38 | 33,90 | −7,51 | 54,1 % | 0,958 | −9,4 % | 4,98 / 4,95 |
| R | Dreiergruppe Ring | 979 | 30,54 | 34,63 | −4,09 | 27,0 % | 1,373 | 75,8 % | 6,89 / 4,93 |
| R | Dreiergruppe vollvernetzt | 421 | 32,07 | 39,19 | −7,13 | 20,3 % | 1,407 | 35,0 % | 6,98 / 4,99 |

Nach Zahl der mit C01 geteilten Rollen. Die Gruppe „2“ enthält im Skript auch C01 selbst; die Zeile „2 ohne C01“ (C07 bis C10) ist aus Tabelle 1.5 abgeleitet.

| Geteilte Rollen mit C01 | P: n | P: ΔEM | P: Anteil Verlust | P: Kostenquotient | R: n | R: ΔEM | R: Anteil Verlust |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2 (mit C01) | 4.122 | −2,16 | 23,4 % | 1,262 | 1.339 | −3,44 | 31,1 % |
| 2 ohne C01 (C07 bis C10) | 2.592 | −3,43 | 23,4 % | 1,408 | 852 | −5,63 | 32,4 % |
| 1 | 4.214 | −4,96 | 54,9 % | 1,127 | 1.381 | −5,29 | 49,3 % |
| 0 (nur C06) | 704 | −11,79 | 21,8 % | 0,936 | 232 | −12,50 | 19,6 % |

Abweichende Paare nach der im Block beobachteten Kostenrichtung (nur Beschreibung, die Kosten hängen auch von der Generierung ab):

| Panel | Kostenrichtung im Block | n (Anteil an abweichend) | ΔEM | Anteil Verlust |
|---|---|---:|---:|---:|
| P | Q teurer als F\* | 5.098 (67,9 %) | −4,18 | 55,9 % |
| P | Q billiger als F\* | 2.397 (31,9 %) | −7,01 | 44,1 % |
| P | gleich teuer | 15 (0,2 %) | 0,00 | 0 % |
| R | Q teurer als F\* | 1.652 (67,0 %) | −5,87 | 65,5 % |
| R | Q billiger als F\* | 812 (32,9 %) | −6,53 | 35,8 % |
| R | gleich teuer | 1¹ | 0,00 | 0 % |

Die 15 gleich teuren Paare in P sind Paare, in denen beide Arme als Modellausfall enden (n < 30, nicht gedeutet). ¹ n < 30, nicht gedeutet.

### 1.5 (b) Je von Q gewählter Konfiguration

Rollen: B = Belege (evidence), V = Verknüpfung (linking), E = Entwurf (draft), W = Widerspruchsprüfung (checking). C01 = B–V.

| Konf. | Rollen | Kanten | P: n | P: EM Q | P: EM F\* | P: ΔEM | P: Anteil Verlust | P: Kosten-quotient | R: n | R: ΔEM | R: Kosten-quotient |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C01 | B, V | 2 | 1.530 | 33,01 | 33,01 | 0,00 | 0,0 % | 1,010 | 487 | +0,41 | 0,987 |
| C02 | B, E | 2 | 1.040 | 25,58 | 32,69 | −7,12 | 19,4 % | 0,954 | 353 | −7,37 | 0,936 |
| C03 | B, W | 2 | 473 | 36,36 | 45,67 | −9,30 | 11,5 % | 0,941 | 161 | −12,42 | 0,960 |
| C04 | V, E | 2 | 469 | 47,55 | 48,40 | −0,85 | 1,0 % | 0,999 | 148 | 0,00 | 1,006 |
| C05 | V, W | 2 | 531 | 34,27 | 37,48 | −3,20 | 4,5 % | 0,985 | 171 | −2,92 | 0,987 |
| C06 | E, W | 2 | 704 | 18,47 | 30,26 | −11,79 | 21,8 % | 0,936 | 232 | −12,50 | 0,943 |
| C07 | B, V, E (Ring) | 3 | 940 | 33,19 | 36,17 | −2,98 | 7,3 % | 1,409 | 286 | −8,74 | 1,370 |
| C08 | B, V, E (voll) | 6 | 324 | 27,78 | 28,09 | −0,31 | 0,3 % | 1,423 | 114 | −2,63 | 1,443 |
| C09 | B, V, W (Ring) | 3 | 933 | 44,48 | 45,77 | −1,29 | 3,1 % | 1,397 | 326 | −1,84 | 1,405 |
| C10 | B, V, W (voll) | 6 | 395 | 49,11 | 61,27 | −12,15 | 12,6 % | 1,421 | 126 | −11,11 | 1,417 |
| C11 | B, E, W (Ring) | 3 | 719 | 22,67 | 26,43 | −3,76 | 7,1 % | 1,359 | 234 | −2,99 | 1,343 |
| C12 | B, E, W (voll) | 6 | 292 | 20,55 | 34,93 | −14,38 | 11,0 % | 1,362 | 91 | −14,29 | 1,311 |
| C13 | V, E, W (Ring) | 3 | 426 | 29,11 | 27,00 | +2,11 | −2,4 % | 1,341 | 133 | −1,50 | 1,355 |
| C14 | V, E, W (voll) | 6 | 264 | 21,21 | 25,00 | −3,79 | 2,6 % | 1,413 | 90 | 0,00 | 1,443 |

Alle Gruppen in P haben n ≥ 264, in R n ≥ 90. Einzelne Konfigurationen werden nicht gegeneinander getestet.

### 1.6 (c) Nach Aufgabentyp aus der `task_id`

Alle `task_id` folgen dem Muster aus §0.4; die Zahl der Teilfragen-IDs stimmt in allen Paaren mit der Hop-Zahl überein (null Abweichungen).

| Hop-Zahl | P: n | P: Anteil abweichend | P: ΔEM gesamt | P: ΔEM abweichend | P: Anteil Verlust | R: n | R: Anteil abweichend | R: ΔEM gesamt | R: ΔEM abweichend | R: Anteil Verlust |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 4.928 | 87,8 % | −2,74 | −3,12 | 35,4 % | 1.604 | 87,1 % | −4,80 | −5,51 | 52,0 % |
| 3 | 2.583 | 79,5 % | −6,31 | −7,94 | 42,8 % | 861 | 81,1 % | −5,69 | −7,31 | 33,1 % |
| 4 | 1.529 | 74,0 % | −5,43 | −7,33 | 21,8 % | 487 | 76,0 % | −4,52 | −5,95 | 14,9 % |

| Typpräfix | P: n gleich / abweichend | P: ΔEM abweichend | P: EM F\* gleich / abweichend | R: n gleich / abweichend | R: ΔEM abweichend |
|---|---:|---:|---:|---:|---:|
| 2hop | 603 / 4.325 | −3,12 | 33,2 / 35,3 | 207 / 1.397 | −5,51 |
| 3hop1 | 400 / 1.519 | −9,68 | 40,5 / 41,5 | 125 / 510 | −9,02 |
| 3hop2 | 130 / 534 | −3,00 | 40,8 / 24,9 | 38 / 188 | −2,66 |
| 4hop1 | 183 / 730 | −5,89 | 44,3 / 47,1 | 49 / 233 | −5,15 |
| 4hop2 | 15¹ / 231 | −11,69 | 0,0¹ / 31,6 | 5¹ / 73 | −13,70 |
| 4hop3 | 199 / 171 | −7,60 | 4,5 / 35,1 | 63 / 64 | 0,00 |

¹ n < 30, nicht gedeutet.

Kleine Untergruppen (n < 30): P 4hop2 gleich (15) und R 4hop2 gleich (5); ihre Werte stehen in der Tabelle, sind markiert und werden nicht gedeutet. In ΔEM gleich liegen alle Typen in P bei 0,00, in R zwischen 0,00 und +2,63.

## 2. Was das zeigt

- **Kein Verlust bei gleicher Wahl.** Wenn Q dieselbe Konfiguration wie F\* wählt, liefern beide Arme in P in allen 1.530 Paaren dasselbe EM-Ergebnis, in R in 485 von 487 Paaren (zwei Paare zugunsten von Q). Auch F1 ist fast gleich (−0,02 bzw. +0,18 Prozentpunkte). In den beobachteten Studienläufen erzeugten zwei Generierungen mit gleicher Konfiguration also fast nie ein unterschiedliches EM-Ergebnis; F1 unterscheidet sich in P in vier dieser Paare.
- **Der Verlust sitzt vollständig in den abweichenden Paaren.** Q weicht in rund 83 % der Paare von C01 ab und liegt dort im Mittel 5,1 (P) bzw. 6,1 (R) Prozentpunkte zurück. Das Intervall in P liegt auch mit Aufgaben als Ziehungseinheit unter null (−6,91 bis −3,28).
- **Auch die Mehrkosten sitzen dort.** In gleichen Paaren ist der Kostenquotient 1,01 (Intervall 0,987 bis 1,034, schließt 1 ein), in abweichenden 1,20.
- **Zwei Richtungen, beide ungünstig.** Rund 43 % der abweichenden Paare in P gehen an eine andere Zweiergruppe: gleiche Aufrufzahl, etwas billiger, aber −6,9 Prozentpunkte und 58 % des Verlusts. Rund 57 % gehen an eine Dreiergruppe: etwa zwei Aufrufe mehr, rund 40 % teurer, über 100 % der Mehrkosten, und im Mittel ebenfalls schlechter (Ring −1,9, vollvernetzt −7,9 Prozentpunkte). In R ist es dasselbe Bild. Unter den Gruppen mit abweichender Konfiguration (Bauform, Einzelkonfiguration, Typ mal abweichend) ist im Mittel keine zugleich billiger als F\* und mindestens gleich gut; am nächsten kommt C04 (P −0,85 Prozentpunkte bei Kostenquotient 0,999, R 0,00 bei 1,006). Bei gleicher Konfiguration kommt das vor (zum Beispiel R gleich: +0,41 bei 0,987), dort laufen aber beide Arme mit C01.
- **Konfigurationen.** Die größten Abstände in beiden Panels haben C06, C12, C10 und C03 (je rund −9 bis −14 Prozentpunkte). Nahe bei F\* liegen C04, C08, C09 und C13. Die Reihenfolge der Einzelkonfigurationen ist zwischen P und R ähnlich, aber nicht gleich (zum Beispiel C07: P −3,0, R −8,7).
- **Geteilte Rollen.** Am größten ist der Abstand in beiden Panels bei C06, der einzigen Konfiguration ohne eine der beiden C01-Rollen (−11,8 bzw. −12,5 Prozentpunkte). Zwischen einer und zwei geteilten Rollen ist die Reihenfolge nicht einheitlich (P −5,0 gegen −3,4, R −5,3 gegen −5,6 Prozentpunkte).
- **Aufgabentyp.** Q weicht bei 2-Hop-Aufgaben häufiger ab (rund 87 %) als bei 4-Hop-Aufgaben (74 bis 76 %). Der Abstand in abweichenden Paaren ist in beiden Panels bei 2-Hop-Aufgaben am kleinsten und bei den Typen 3hop1 und 4hop2 am größten (rund −9 bis −14 Prozentpunkte). Die Typen 4hop2 und 4hop3 sind klein (n 246 und 370 in P) und in R nicht einheitlich (4hop3 in R 0,00).
- **Schwierigkeit.** F\* trifft in abweichenden Paaren nicht seltener als in gleichen (P 36,9 gegen 33,0 %, R 35,1 gegen 30,6 %). Dass Q gerade bei schweren Aufgaben abweicht, zeigt sich so nicht. Bei 4hop3 wählt Q C01 vor allem bei Aufgaben, die auch F\* kaum löst (EM F\* in gleichen Paaren 4,5 % in P, n = 199, und 1,6 % in R, n = 63).

**Was das nicht zeigt.** Die Tabellen vergleichen nur die in demselben Block beobachteten Arme Q und F\*. Sie sagen nicht, was eine andere Konfiguration in diesen Aufgaben geliefert hätte, und nicht, welche Wahl die beste gewesen wäre (Technischer Anhang §14). Weil die Wahl von Q eine feste Eigenschaft der Aufgabe ist, vermischen die Gruppenunterschiede Aufgabe und Konfiguration.

## 3. Mögliche Erklärung (begründete Vermutung, nicht geprüft)

**Vermutung 1: Die Vorhersagemodelle von Q bewerten Zweiergruppen ohne Verknüpfungsrolle zu gut.** Nicht vorab festgelegt, sondern beim Lesen von Tabelle 1.5 aufgefallen: Die drei Zweiergruppen ohne Verknüpfungsrolle (C02, C03, C06) liegen in P zusammen −9,1 Prozentpunkte zurück (n 2.217, 52,8 % des Verlusts), in R −10,1 Prozentpunkte (n 746, 50,7 %). Die beiden Zweiergruppen mit Verknüpfungsrolle (C04, C05) liegen bei −2,1 bzw. −1,6 Prozentpunkten. Weil Q unter den Kandidaten innerhalb eines Prozentpunkts der besten Vorhersage die billigste wählt, landet eine zu günstige Vorhersage für eine billige Zweiergruppe direkt in der Auswahl. Prüfidee: auf der Entwicklungsmatrix (Z39, familiengetrennt) je Konfiguration vorhergesagte gegen beobachtete Qualität vergleichen und prüfen, ob die Abweichung bei C02, C03 und C06 systematisch positiv ist. Das nutzt nur Entwicklungsdaten und braucht keine Rekonstruktion der Studienläufe.

**Vermutung 2: Die Mehrkosten entstehen, weil Q Dreiergruppen einen Qualitätsvorsprung vorhersagt, der sich nicht zeigt.** Q wählt in 57 % der abweichenden Paare eine Dreiergruppe, die rund zwei Aufrufe mehr braucht; nach der Auswahlregel geschieht das nur, wenn keine billigere Konfiguration innerhalb eines Prozentpunkts der höchsten Vorhersage liegt. Beobachtet ist in diesen Paaren kein Vorsprung gegenüber F\*, sondern ein Rückstand. Prüfidee: auf der Entwicklungsmatrix die Häufigkeit, mit der eine Dreiergruppe die höchste Vorhersage erhält, mit ihrer beobachteten Qualität vergleichen; falls die Vorhersagewerte je Studienblock gespeichert sind, zusätzlich vorhergesagten und beobachteten Abstand der Q-Wahl zu C01 für den Q-Arm vergleichen (ohne Annahmen über nicht ausgeführte Konfigurationen).

Beide Vermutungen passen zu den in der Gliederung genannten Hypothesen (schwaches Signal im Fragetext, kleine Entwicklungsmenge für 14 Modelle), unterscheiden sie aber nicht.

## 4. Abweichungen von der Vorab-Festlegung und Grenzen

- Δ_gleich hat in beiden Varianten den Status `variance_zero`; nach §0.5 gibt es dafür kein Intervall und kein Ersatzverfahren.
- Die Gruppe „2 geteilte Rollen“ enthält im Skript C01 selbst. Das war in §0.4 nicht eindeutig formuliert. Die Zeile ohne C01 ist aus Tabelle 1.5 abgeleitet und als solche gekennzeichnet.
- Nach dem ersten Lauf wurden zwei technische Änderungen am Skript vorgenommen und neu gerechnet: Kostensummen je Gruppe als zusätzliche Felder (aus den vorab festgelegten Kosten abgeleitet, für „Anteil Mehrkosten“) und gültige JSON-Kodierung nicht endlicher Grenzen (`"Infinity"` als Zeichenkette wie in `final_analysis.py`). Alle übrigen Zahlen blieben gleich.
- Die Beobachtung zur Verknüpfungsrolle (§3) ist nachträglich und nicht vorab festgelegt.
- Zusätzlich zu §0.4 enthält das JSON die Kostenrichtung auch für gleiche Paare (`d_gleich_by_block_cost_direction`), rein beschreibend; sie wird im Bericht nicht verwendet.
- Codex-Runde 1 (NO-GO) führte zu: zwei Rundungskorrekturen, engeren Formulierungen in §2 und §5, Gruppengrößen in der Typtabelle und unverkürzter Speicherung der R05-Kostenzeichenkette im JSON (Skript neu gerechnet, sonst gleiche Zahlen).
- Untergruppen sind nicht für Mehrfachvergleiche korrigiert und werden nicht getestet. Die Intervalle in §1.3 gelten je Kennzahl, nicht gemeinsam.
- Für R gibt es keine Intervalle. R ist zeitlich und organisatorisch anders erhoben (ab Block 2.183 parallel, siehe 6.1 der Gliederung); es dient hier nur als zweite Beschreibung desselben Musters.
- Kosten: bekannte Kosten, unter der unveränderten Annahme D-074 zu den vier unbekannten Originalabrechnungen in P.

## 5. Formulierungsvorschläge

**Methodik (1 Satz).** Zur Erklärung des Hauptbefunds wurde der Qualitätsverlust von Q gegenüber F\* nachträglich, aber vor der Rechnung festgelegt, nach der von Q gewählten Konfiguration und nach dem Aufgabentyp aufgeschlüsselt; diese Aufschlüsselung ist beschreibend, ändert die Hauptanalyse nicht und schätzt keine Ergebnisse von Konfigurationen, die nicht ausgeführt wurden.

**Diskussion (5 Sätze).** Der Qualitätsverlust von Q entsteht vollständig dort, wo Q von F\* abweicht: In P haben beide Arme in allen 1.530 Paaren (16,9 %), in denen Q ebenfalls C01 wählt, denselben EM-Wert, in den übrigen liegt Q im Mittel 5,1 Prozentpunkte zurück. Die Abweichungen gehen in zwei Richtungen, die beide ungünstig sind: Wählt Q eine andere Zweiergruppe, ist es etwas billiger, aber deutlich schlechter; wählt es eine Dreiergruppe, ist es rund 40 % teurer, ohne besser zu sein. Die nachträglich zusammengefassten Zweiergruppen ohne Verknüpfungsrolle (C02, C03, C06) tragen 52,8 % beziehungsweise 50,7 % des Nettoverlusts in Hauptstudie und Referenzpanel, das insgesamt dasselbe Muster zeigt. Ob die Vorhersagemodelle von Q diese Konfigurationen systematisch zu gut bewerten, ist eine ungeprüfte Vermutung, die sich auf den Entwicklungsdaten prüfen ließe. Die Aufschlüsselung beschreibt, wo der Verlust liegt, nicht welche Wahl in einer Aufgabe besser gewesen wäre.
