<!-- status: Ergebnis nach ANALYSEPLAN.md | Codex-Nachrechnung: 8/8 bestätigt | 2026-10-19 -->

# Ergebnis der Offline-Prüfung zu Feedbackpunkt 2 und 5

Durchgeführt am 19.10.2026 nach dem vorab festgelegten `ANALYSEPLAN.md`, ohne Modellaufrufe und ohne Zugriff auf den Dev-Bestand. Daten: Entwicklungsmatrix von Z39 (300 Aufgaben, 100 Familien, 14 Konfigurationen). Rohwerte: `ergebnis-offline.json`, Skripte: `build_features.py`, `analyse_offline.py`. Alle Werte sind nachträglich und explorativ. Der vorab festgelegte Hauptvergleich bleibt unberührt.

## Kurzfassung

1. **Überanpassung belegt.** Auf den eigenen 300 Trainingsaufgaben trifft ⟦Q⟧ 50,67 %. Das ist der Höchstwert: In jeder Aufgabe, in der überhaupt eine Konfiguration richtig antwortet, wählt ⟦Q⟧ eine richtige. Auf zurückgehaltenen Teilen sind es 35,33 %, die feste Referenz kommt dort auf 39,00 %.
2. **Behebbar nur, indem ⟦Q⟧ zu ⟦F*⟧ wird.** Mit stärkerer Regularisierung oder weniger Merkmalen verschwindet die Überanpassung, die Wahl nähert sich aber der festen Referenz. Die verschachtelte, ehrliche Schätzung der besten Lernprozedur liegt bei 39,33 % gegen 39,00 %, also +0,33 Pp. (95-%-Intervall −1,37 bis +2,08). Das Kostenverhältnis ist 1,0001.
3. **Kein Zusatzlauf.** Das vorab gesetzte Kriterium (mindestens +1,0 Pp. in A4) ist verfehlt. Ein bezahlter Neulauf würde nach diesen Daten den Befund nicht ändern.
4. **Zerlegung der Eingriffe (Punkt 5)**, beschreibend auf Entwicklungsdaten:
   - Mehr Kommunikationskanten bei gleichen Rollen und Aufrufen kosten rund 13 % mehr und bringen keine bessere Qualität: −1,75 Pp., Intervall −3,54 bis 0,00.
   - Welche Rollen eine Zweiergruppe hat, wirkt stärker als jeder andere Eingriff. Die Verknüpfungsrolle bringt +11,89 Pp. (8,61 bis 15,35).
   - Eine dritte Rolle bringt wenig (Ring +1,97 Pp., voll vernetzt +0,22 Pp.) bei 32 % bis 49 % höheren Kosten.

## A: Überanpassung

**A0 Reproduktion: bestanden.**
- Die neu berechnete Merkmalsmatrix reproduziert die gespeicherten Vorhersagen aller 300 zurückgehaltenen Aufgaben für α = 1, 10 und 100 exakt (größte Abweichung 0).
- Auch die Qualitätswerte (33,67 / 35,33 / 35,33 %) und die feste Referenz (39,00 %) stimmen.
- Die Wahl des abschließenden Modells stimmt mit den gespeicherten 300 Trainingswahlen überein.

**A1 bis A3: Trainings- gegen zurückgehaltene Qualität** (ohne Verschachtelung, daher für die beste Zeile zu günstig):

| Merkmale | α | Training | zurückgehalten | feste Referenz | Kostenverhältnis |
|---|---|---|---|---|---|
| alle 388 | 1 | 50,67 % | 33,67 % | 39,00 % | 1,172 |
| alle 388 | 100 (gewählt) | 50,67 % | 35,33 % | 39,00 % | 1,114 |
| alle 388 | 1.000 | 50,67 % | 38,33 % | 39,00 % | 1,062 |
| alle 388 | 10.000 | 46,33 % | 39,67 % | 39,00 % | 1,001 |
| alle 388 | 1.000.000 | 40,17 % | 39,00 % | 39,00 % | 1,000 |
| 4 Textmerkmale | 1 | 42,42 % | 39,67 % | 39,00 % | 1,031 |
| 5 Hauptkomponenten + 4 | 1.000 | 42,33 % | 39,33 % | 39,00 % | 0,993 |
| 20 Hauptkomponenten + 4 | 1.000 | 43,83 % | 40,33 % | 39,00 % | 0,998 |

- Bis α = 1.000 trifft ⟦Q⟧ mit allen 388 Merkmalen auf den Trainingsaufgaben den Höchstwert, die Daten werden also auswendig gelernt.
- Mit wachsender Regularisierung sinkt die Trainingsqualität, die zurückgehaltene steigt, und Wahl und Kosten nähern sich der festen Referenz. Bei α = 1.000.000 wählt ⟦Q⟧ wie ⟦F*⟧.
- Die beste Einzelzeile (20 Hauptkomponenten, α = 1.000, +1,33 Pp.) ist eine Auswahl unter 28 Kombinationen auf denselben Teilen und deshalb zu günstig. Darüber entscheidet A4.

**A4 Verschachtelte Schätzung (entscheidend):**
- Innen gewählt wurden je äußerem Teil: 20 Hauptkomponenten bei α = 1.000, 5 Hauptkomponenten bei α = 1.000, 4 Textmerkmale bei α = 100, 5 Hauptkomponenten bei α = 1.000, 4 Textmerkmale bei α = 100. Die Wahl ist also nicht stabil.
- Qualität der Lernprozedur auf zurückgehaltenen Aufgaben: 39,33 %, feste Referenz 39,00 %. Differenz +0,33 Pp., 95-%-Familien-Cluster-Bootstrap −1,37 bis +2,08, Kostenverhältnis 1,0001.
- Kriterium für einen Zusatzlauf (≥ +1,0 Pp.): **nicht erfüllt.**

**Deutung:** Die Überanpassung erklärt, warum ⟦Q⟧ schlechter wählt als ⟦F*⟧. Wird sie verhindert, bleibt von der aufgabenabhängigen Auswahl kaum etwas übrig: Sie wählt dann fast immer wie die feste Referenz, mit einem Vorteil, der nicht von null zu unterscheiden ist. Auf diesen Merkmalen und bei dieser Datenmenge ist kein Vorteil einer Auswahl je Aufgabe gegenüber ⟦F*⟧ belegt, auch nicht für eine gegen Überanpassung abgesicherte Auswahl. Ausgeschlossen ist ein kleiner Vorteil damit nicht (oberes Intervallende +2,08 Pp.). Über andere Merkmale oder mehr Daten sagt die Prüfung nichts.

## B: Zerlegung der Pruning-Eingriffe

Grundlage ist der Exact Match der Entwicklungsmatrix, je Aufgabe gemittelt. Für 250 Aufgaben gibt es nur einen Lauf. Die 95-%-Intervalle stammen aus einem Familien-Cluster-Bootstrap ohne Korrektur für Mehrfachvergleiche und sind beschreibend. ⟦F*⟧ (C01) wurde auf denselben Daten gewählt.

**B1 Kanten bei gleichen Rollen und gleich vielen Aufrufen** (voll vernetzt, 6 Kanten, gegen Ring, 3 Kanten; je 7 Aufrufe):

| Dreiergruppe | voll minus Ring | 95-%-Intervall | Kosten voll / Ring |
|---|---|---|---|
| Beleg, Verknüpfung, Entwurf (C08 − C07) | +0,67 Pp. | −2,48 bis +4,10 | 1,151 |
| Beleg, Verknüpfung, Widerspruch (C10 − C09) | −3,33 Pp. | −6,61 bis −0,29 | 1,121 |
| Beleg, Entwurf, Widerspruch (C12 − C11) | −3,67 Pp. | −7,12 bis −0,34 | 1,105 |
| Verknüpfung, Entwurf, Widerspruch (C14 − C13) | −0,67 Pp. | −3,14 bis +1,74 | 1,135 |
| gepoolt | −1,75 Pp. | −3,54 bis 0,00 | 1,128 (1,111 bis 1,145) |

**B2 Rollenwahl in Zweiergruppen** (alle mit 2 Kanten und 5 Aufrufen). Zweiergruppen: C01 40,33 %, C02 29,33 %, C03 22,00 %, C04 38,33 %, C05 37,00 %, C06 28,67 %. Der Effekt einer Rolle ist das Mittel der drei Zweiergruppen mit ihr minus das Mittel der drei ohne sie:

| Rolle | Effekt | 95-%-Intervall |
|---|---|---|
| Verknüpfung | +11,89 Pp. | +8,61 bis +15,35 |
| Entwurf | −1,00 Pp. | −3,70 bis +1,67 |
| Beleg | −4,11 Pp. | −6,95 bis −1,28 |
| Widerspruch | −6,78 Pp. | −9,07 bis −4,52 |

**B3 Dritte Rolle, mit ihren Kanten und Aufrufen** (Dreiergruppe minus jede ihrer drei Zweiergruppen, gepoolt über 12 Paare):

| Bauform | Differenz | 95-%-Intervall | Kostenverhältnis |
|---|---|---|---|
| Ring | +1,97 Pp. | +0,47 bis +3,51 | 1,320 |
| voll vernetzt | +0,22 Pp. | −1,68 bis +2,07 | 1,489 |

**B4 Runden:** nicht neu gerechnet. Es gilt die vorhandene Zählung der Rundenentwicklung (92 von 100 Aufgaben unverändert, 3 besser, 5 schlechter; Arbeit N1305).

**Deutung:** Auf diesen Entwicklungsdaten lassen sich die Eingriffe weitgehend auseinanderhalten.
- **Kanten:** Mehr Kommunikationskanten bei gleichen Rollen sind teurer und nicht besser. Das ist räumliche Redundanz auf Kantenebene.
- **Rollen:** Welche Rollen zusammenarbeiten, bestimmt die Qualität am stärksten. Die Verknüpfungsrolle trägt, die Widerspruchsrolle schadet.
- **Gruppengröße und Runden:** Eine dritte Rolle oder eine zweite Runde bringen wenig bis nichts.
- **Grenzen:** Das sind beschreibende Befunde aus Einzelläufen, keine ursächlichen Wirkungen einzelner Kanten. Für die zweite Forschungsfrage ändern sie nichts.

## Prüfvermerk

**Unabhängige Nachrechnung** durch Codex (gpt-6-luna, read-only, eigener Code) nach Plan Teil C: 8 von 8 Punkten stimmen (`C-codex.json`). Geprüft wurden:
- Trainingsqualität 50,67 % und die Übereinstimmung mit den gespeicherten Trainingswahlen
- A0 (größte Abweichung 5,2 × 10⁻¹³)
- das Raster
- A4 einschließlich der inneren Wahlen
- B1 bis B3
- die Zuordnung der Konfigurationen gegen `configurations.py`

Die Bootstrap-Intervalle wurden nicht nachgerechnet.

**Offene Festlegung im Plan:** Der Plan legte nicht fest, ob die Einbettung vor der Hauptkomponentenzerlegung standardisiert wird. Gerechnet wurde ohne diese Standardisierung; erst die Eingabe der Ridge-Regression ist standardisiert. Codex kam mit der anderen Reihenfolge zunächst auf andere Werte. Als Sensitivität ist A4 mit standardisierter Einbettung nachgerechnet (`sens_pca_std.py`, `ergebnis-offline-sens-pca-std.json`):
- 39,33 % gegen 39,00 %, also +0,33 Pp.
- 95-%-Intervall −1,64 bis +2,35, Kostenverhältnis 1,006
- Kriterium nicht erfüllt

Das Ergebnis hängt also nicht an dieser Festlegung.
