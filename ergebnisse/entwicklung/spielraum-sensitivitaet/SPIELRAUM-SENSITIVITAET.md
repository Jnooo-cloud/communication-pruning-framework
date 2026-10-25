<!-- status: entwurf | quellen: Z39 recovery-fit/run-001 (OOF-and-filter-diagnosis.json 5c0fbe65…, raw-Q-sem.json c48fa831…, F-star.json 9050e4ac…, development-means.json 9719dd03…, RESULT.json b911b890…), semantic_selection.py, selection.py, Z39-R1-ERGEBNIS.md, Technischer Anhang §9, Z32-Plan §2, VORAB.md (1750acb9…) | codex: GO Runde 2 (Runde 1 NO-GO wegen Überdeutung über die fünf Stufen hinaus, behoben) | 2026-10-05 -->

# Sensitivität des Auswahlspielraums (Entwicklungsmatrix Z39)

**Kernbefund.** Bei allen fünf Spielräumen (0, 0,5, 1, 2, 3 Prozentpunkte) liegt Q auf den zurückgehaltenen Teilen derselben Kreuzvalidierung unter der faltenweise bestimmten festen Referenz (−5,33 bis −2,33 Prozentpunkte EM) und ist zugleich teurer (Kostenverhältnis 1,095 bis 1,138); Q wählt auf 253 bis 265 der 300 Aufgaben anders. F* auf der vollen Entwicklungsmatrix bleibt bis 1 Prozentpunkt C01 (40,33 %) und wechselt ab 2 Prozentpunkten zu C04 (38,33 %, rund 1,2 % geringere mittlere Kosten), wobei C04 bei 2 Prozentpunkten genau auf der Grenze liegt (6 von 300 Aufgaben weniger richtig). Der kleinere Rückstand bei 2 und 3 Prozentpunkten entsteht, weil die feste Referenz in einzelnen Falten auf günstigere Konfigurationen (C04, C05) ausweicht, die auf den zurückgehaltenen Teilen zusammen schwächer abschneiden als C01, und Q sich gleichzeitig um höchstens 0,67 Prozentpunkte gegenüber 1 Prozentpunkt verbessert.

Vorab festgelegt in `VORAB.md` (SHA256 `1750acb9588afa72cc3807584fbb7c86ab10aa67f499570698e5ab3a987bbf59`, Datei `VORAB.md.sha256`), gerechnet mit `spielraum.py` (nur Standardbibliothek, prüft Eingabe- und Vorab-Hash vor der Rechnung), Rohwerte in `SPIELRAUM-ERGEBNIS.json`. 0 USD, keine Modellaufrufe, kein Neutraining.

## Reproduktion bei 1 Prozentpunkt

Bestanden, alle Bedingungen aus VORAB §5:

- alle 300 Q-Wahlen und alle 300 Referenzwahlen identisch mit den in Z39 gespeicherten (`selected_index`, `fixed_index`), ebenso Qualität und Kosten je Aufgabe;
- Q 35,33 % (106 von 300), feste Referenz je Falte 39,00 % (117 von 300), Differenz −3,6667 Prozentpunkte, Kostenverhältnis 1,114032 (rund 11,4 % höher);
- Alpha 100 gewählt; die gespeicherten Mittel für Alpha 1 und 10 ebenfalls exakt reproduziert;
- F* auf 300 Aufgaben = C01 mit 0,4033333;
- abschließend trainiertes Q: 251 von 300 Wahlen ungleich C01.

Zur Zahl 251: Sie betrifft das abschließend auf allen 300 Aufgaben trainierte Q gegen das endgültige F* (C01), also die Trainingsaufgaben selbst. Auf den zurückgehaltenen Teilen der Kreuzvalidierung wählt Q bei 1 Prozentpunkt auf 253 Aufgaben anders als die jeweilige Faltenreferenz (so auch Z39-R1-ERGEBNIS.md Z. 142). Für andere Spielräume wird nur die zweite Größe berichtet, weil die Vorhersagen des abschließenden Modells auf den Trainingsaufgaben nicht gespeichert sind.

## Ergebnisse je Spielraum

Hauptvariante: Alpha 100 fest, beide Regeln mit demselben Spielraum. „F* je Falte“ ist die feste Referenz, die in jeder Falte nur aus den vier Trainingsteilen bestimmt wird.

| Spielraum | F* (300 Aufgaben): Konfiguration, EM, mittlere Kosten USD, zugelassen | Q EM (zurückgehalten) | F* je Falte EM | Differenz Q − F* (Prozentpunkte) | Kostenverhältnis Q / F* | Abweichende Wahl | F* je Falte (Falten 0 bis 4) | Filter zugelassen (gleicher Spielraum / 1 Prozentpunkt) |
|---|---|---:|---:|---:|---:|---:|---|---|
| 0 | C01, 40,33 %, 0,00111262, 1 | 35,33 % | 40,33 % | −5,00 | 1,1380 | 264 (88,0 %) | C01, C01, C01, C01, C01 | nein / nein |
| 0,5 | C01, 40,33 %, 0,00111262, 1 | 35,00 % | 40,33 % | −5,33 | 1,1268 | 260 (86,7 %) | C01, C01, C01, C01, C01 | nein / nein |
| **1 (Z39)** | **C01, 40,33 %, 0,00111262, 1** | **35,33 %** | **39,00 %** | **−3,67** | **1,1140** | **253 (84,3 %)** | C01, C01, C01, C01, C04 | nein / nein |
| 2 | C04, 38,33 %, 0,00109934, 2 | 35,67 % | 38,00 % | −2,33 | 1,0947 | 254 (84,7 %) | C01, C01, C04, C01, C04 | nein / nein |
| 3 | C04, 38,33 %, 0,00109934, 3 | 36,00 % | 38,33 % | −2,33 | 1,0978 | 265 (88,3 %) | C04, C04, C05, C01, C05 | ja / nein |

Mittlere bekannte Kosten je Aufgabe auf den zurückgehaltenen Teilen (USD): Q 0,00126615 / 0,00125369 / 0,00124297 / 0,00121825 / 0,00120988, feste Referenz je Falte 0,00111262 / 0,00111262 / 0,00111574 / 0,00111281 / 0,00110206 (Spielraum 0 bis 3).

Ergänzend (VORAB §4 c1): Wird Alpha mit demselben Spielraum neu gewählt, bleibt es bei jedem Spielraum 100. Alpha 1 und 10 liegen bei jedem Spielraum ebenfalls unter der Referenz (−6,67 bis −2,67 Prozentpunkte, Kostenverhältnis 1,151 bis 1,183); Einzelwerte in der JSON.

**Verteilung der Wahlen von Q** auf den zurückgehaltenen Teilen (Aufgaben je Konfiguration; bei jedem Spielraum werden alle 14 Konfigurationen genutzt):

| Konfiguration | 0 | 0,5 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|---:|
| C01 | 36 | 40 | 39 | 38 | 37 |
| C02 | 16 | 17 | 17 | 21 | 25 |
| C03 | 8 | 9 | 9 | 10 | 10 |
| C04 | 31 | 31 | 33 | 34 | 36 |
| C05 | 27 | 29 | 33 | 34 | 35 |
| C06 | 23 | 23 | 26 | 29 | 32 |
| C07 | 25 | 25 | 26 | 26 | 24 |
| C08 | 22 | 20 | 19 | 15 | 14 |
| C09 | 19 | 16 | 14 | 14 | 13 |
| C10 | 31 | 29 | 29 | 26 | 24 |
| C11 | 15 | 15 | 14 | 14 | 13 |
| C12 | 7 | 7 | 6 | 6 | 6 |
| C13 | 24 | 25 | 22 | 22 | 21 |
| C14 | 16 | 14 | 13 | 11 | 10 |

Die Wahlen der festen Referenz je Falte (Aufgaben je Konfiguration): 0 und 0,5 Prozentpunkte C01 300; 1 Prozentpunkt C01 240, C04 60; 2 Prozentpunkte C01 180, C04 120; 3 Prozentpunkte C01 60, C04 120, C05 120.

## Was das zeigt

- **Richtung stabil.** Q liegt bei keinem der fünf Spielräume auf Höhe der festen Referenz und ist bei keinem günstiger. Bei den fünf geprüften Werten hängt der Befund aus Z39 in seiner Richtung nicht am Wert 1 Prozentpunkt; über Werte zwischen den geprüften Stufen sagt das nichts.
- **Größe nicht stabil.** Bei den fünf geprüften Werten reicht der Rückstand von −5,33 bis −2,33 Prozentpunkten, die Mehrkosten von 9,5 bis 13,8 %. Bei 0 und 0,5 Prozentpunkten ist der Rückstand größer als in Z39, bei 2 und 3 kleiner.
- **Woher die Änderung kommt.** Q selbst bewegt sich wenig (35,00 bis 36,00 %). Die Referenz ändert sich stärker (40,33 bis 38,00 %): Mit wachsendem Spielraum lässt sie in einzelnen Falten günstigere Konfigurationen (C04, C05) zu. Auf den zurückgehaltenen Teilen ist das nicht in jeder Falte ein Nachteil (in den Falten 0 und 1 antwortet C04 dort besser als C01), über alle 300 Aufgaben aber schon: Mit C01 in allen Falten läge die Referenz bei 40,33 %. Q verschiebt seine Wahlen mit wachsendem Spielraum zu den günstigeren Konfigurationen (C02, C04, C05, C06 häufiger, C08 bis C14 seltener), wodurch seine Kosten sinken.
- **F* hängt am Spielraum.** Bis 1 Prozentpunkt ist C01 die einzige zugelassene Konfiguration, also unabhängig vom Kostenkriterium. Ab genau 2 Prozentpunkten wird C04 zugelassen und wegen geringerer Kosten gewählt. Bei 2 Prozentpunkten liegt C04 exakt auf der Grenze (115 gegen 121 richtige Aufgaben); ein Spielraum knapp unter 2 Prozentpunkten ergäbe wieder C01. Der Wechsel von C01 zu C04 würde rund 1,2 % mittlere Kosten sparen und 2 Prozentpunkte Entwicklungsqualität kosten.
- **Filter.** Mit fester Schwelle von 1 Prozentpunkt empfiehlt der Entwicklungsfilter bei jedem Spielraum F*. Folgt die Filterschwelle demselben Spielraum, ließe er Q nur bei 3 Prozentpunkten zu, weil der Rückstand (−2,33) dann kleiner als die Schwelle ist; das ist eine Folge der weiteren Schwelle, kein besseres Q.
- **Abweichende Wahl.** Der Auswahlkontrast zwischen Q und der Referenz liegt bei den fünf geprüften Werten bei 84 bis 88 % der Aufgaben; keiner dieser Werte hätte Q zu einer weitgehend konstanten Wahl gemacht.

## Grenzen

- **Kein Rückschluss auf die Hauptstudie.** In der Hauptstudie wurden nur die bei 1 Prozentpunkt tatsächlich gewählten Konfigurationen ausgeführt. Welche Qualität und welche Kosten Q und F* bei einem anderen Spielraum dort erreicht hätten, ist nicht beobachtet und lässt sich aus dieser Analyse nicht ableiten.
- **Keine unabhängige Prüfung.** Dieselbe Entwicklungsmatrix diente dem Fit, der Alpha-Wahl und dieser Nachrechnung; die Werte sind Entwicklungsdiagnosen, keine Wirksamkeitsbelege.
- **Kein besserer Spielraum ausgewählt.** Die Analyse ist beschreibend; keiner der Werte wird nachträglich als geeigneter bezeichnet.
- **Keine Intervalle oder Tests.** Unterschiede von 0,33 Prozentpunkten entsprechen einer Aufgabe von 300.
- **Nur gespeicherte Modelle.** Gerechnet wurde mit den gespeicherten Vorhersagen der fünf Faltenmodelle von Z39. Das abschließend auf 300 Aufgaben trainierte Q wurde nur bei 1 Prozentpunkt (251 abweichende Wahlen) geprüft.
- **Nur fünf Stufen.** Die Spannen gelten nur für 0, 0,5, 1, 2 und 3 Prozentpunkte, nicht für den ganzen Bereich dazwischen. Die Kennzahlen ändern sich sprunghaft und nicht monoton: Eine Gegenprobe von Codex (Runde 1, außerhalb der Vorab-Festlegung) ergab bei 2,1 Prozentpunkten einen Rückstand von nur −1,33 Prozentpunkten (Q 108, Referenz 112 von 300). Dieser Wert ist nicht Teil der vorab festgelegten Analyse und wird nur als Hinweis auf die Stufenabhängigkeit genannt.
- **Nicht abgedeckt.** Derselbe Spielraum steckt auch in der Rundenregel (Q-TF) und in der Redundanzdefinition; beide sind hier nicht nachgerechnet.

## Formulierungsvorschläge

**Für 5.4** (ersetzt den letzten Satz des Absatzes zur festen Referenz, „Den Spielraum von einem Prozentpunkt … überflüssig.“, oder schließt an den Absatz zum ungünstigen Signal an):

> Den Spielraum von einem Prozentpunkt hat die Arbeit selbst gesetzt. Eine nachträgliche Rechnung auf denselben Entwicklungsdaten, mit denselben fünf Teilen und denselben gelernten Modellen, wiederholte beide Auswahlen mit 0, 0,5, 2 und 3 Prozentpunkten. Bei 0, 0,5 und einem Prozentpunkt bleibt $F^*$ die Zweiergruppe aus Beleg- und Verknüpfungsrolle, bei zwei und drei Prozentpunkten fiele die Wahl auf die etwas günstigere Zweiergruppe aus Verknüpfungs- und Entwurfsrolle mit 38,33~\%. Auf den zurückgehaltenen Teilen lag $Q$ bei jedem der fünf geprüften Werte unter der festen Referenz, um 2,33 bis 5,33 Prozentpunkte, und war um 9,5 bis 13,8~\% teurer.

**Für 7.4** (Gruppe Reichweite, ersetzt „ohne Sensitivitätsprüfung“ aus W-7.4-01):

> Der Spielraum von einem Prozentpunkt ist eine eigene Setzung. Auf den Entwicklungsdaten blieb die Richtung des Entwicklungsbefunds bei den fünf geprüften Spielräumen 0, 0,5, 1, 2 und 3 Prozentpunkte erhalten, die Größe nicht: Der Rückstand von $Q$ lag dort zwischen 2,33 und 5,33 Prozentpunkten, und bei zwei und drei Prozentpunkten wäre eine andere feste Referenz gewählt worden. Werte zwischen diesen Stufen wurden nicht systematisch geprüft. Für die Hauptstudie folgt daraus nichts, denn dort liefen nur die bei einem Prozentpunkt gewählten Konfigurationen; ob $Q$ und $F^*$ bei einem anderen Spielraum dort anders abgeschnitten hätten, ist ungeprüft.
