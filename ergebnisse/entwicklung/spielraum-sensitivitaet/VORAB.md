<!-- status: vorab-festlegung, vor jeder Rechnung gehasht | 2026-10-05 -->

# Vorab-Festlegung: Sensitivität des Auswahlspielraums

Festgelegt am 5. Oktober 2026, bevor irgendeine Kennzahl für einen anderen Spielraum als 1 Prozentpunkt gerechnet wurde. Bekannt waren zu diesem Zeitpunkt nur die in Z39 gespeicherten Werte bei 1 Prozentpunkt (sie sind das Reproduktionsziel). Freigabe: Auftrag von Jannik vom 5. Oktober 2026, 0 USD, keine Modellaufrufe.

## 1. Frage

Wie hängen die Wahl von F* auf der Entwicklungsmatrix und der Kreuzvalidierungsbefund von Q gegen F* (Z39) vom Auswahlspielraum ab? Beschreibende Entwicklungsanalyse, keine Aussage zur Hauptstudie.

## 2. Spielräume

ε ∈ {0; 0,005; 0,01; 0,02; 0,03} (0, 0,5, 1, 2, 3 Prozentpunkte). Zulassung wie im Code (`selection.choose`, `semantic_selection.choose_scores`): Wert ≥ Maximum − ε − 1e-12; unter den Zugelassenen die geringsten mittleren Trainingskosten, dann kleinste Konfigurations-ID. Die Toleranz 1e-12 bleibt unverändert, bei ε = 0 werden also nur das Maximum und exakte Gleichstände zugelassen.

## 3. Eingaben (altes Repo, nur lesend)

Verzeichnis `eval-harness/eval/runs/Z39-RAEUM-ENTWICKLUNG-001/recovery-fit/run-001/`:

| Datei | SHA256 |
|---|---|
| `OOF-and-filter-diagnosis.json` | 5c0fbe65f02193dfedf27a10e402aa50aca861599eceb40f09e685bb89409013 |
| `raw-Q-sem.json` | c48fa831b8db4e9319072dd508a527944f8797c1fc647e1eea56fd050518a097 |
| `F-star.json` | 9050e4acd90d38cce94558c95b11c38ba667fd435e13a4f0095075711597c61b |
| `development-means.json` | 9719dd0357bf15775c5b105d63361d28b6d9d58e5f79a681158873f5385d5ad7 |
| `RESULT.json` | b911b890cd749f1937ea71a7eb9f4326f1889adb0dd01e5f08a4e5bf3a882581 |

Kein Neutraining. Verwendet werden die gespeicherten Vorhersagewerte (`scores`) jeder zurückgehaltenen Aufgabe aus den Faltenmodellen von Z39 sowie die gespeicherten Trainings-Kostenmittel und Trainings-Qualitätsmittel je Faltenmodell. Damit sind Falten, Seeds, Standardisierung und Regressionsgewichte identisch mit Z39; nur die Auswahlregel ändert sich. Qualität und Kosten einer gewählten Konfiguration auf einer zurückgehaltenen Aufgabe kommen aus `development-means.json` (Aufgabenmittel über die Wiederholungen).

## 4. Kennzahlen je Spielraum

**(a) F* auf der Entwicklungsmatrix:** Regel mit ε auf die 300-Aufgaben-Mittel (`F-star.json`: `training_quality_em`, `training_cost_usd`). Berichtet: gewählte Konfiguration, ihre Entwicklungsqualität (EM) und mittleren Kosten, Zahl der zugelassenen Konfigurationen.

**(b) Kreuzvalidierung, Hauptvariante (Alpha = 100 fest, das in Z39 gewählte Modell):** Je Falte wird F*_Falte mit ε aus den Trainingsmitteln des Faltenmodells bestimmt, Q je zurückgehaltener Aufgabe mit ε aus den gespeicherten Vorhersagen und Trainings-Kostenmitteln. Beide Regeln verwenden denselben Spielraum, wie im Design (beide Regeln folgen derselben Logik). Berichtet:
1. Anteil und Zahl der Aufgaben, auf denen Q anders wählt als F*_Falte;
2. EM von Q und von F*_Falte auf den zurückgehaltenen Teilen (Mittel über 300), Differenz in Prozentpunkten;
3. Kostenverhältnis mittlere bekannte Kosten Q / F*_Falte;
4. Verteilung der von Q gewählten Konfigurationen und der F*_Falte-Wahlen (Aufgaben je Konfiguration).

**(c) Ergänzend, nicht Hauptvariante:**
1. Alpha mit demselben ε neu gewählt (Regel `_select_alpha`: Validierungs-EM ≥ beste − ε − 1e-12, dann geringere Validierungskosten, dann größeres Alpha), mit den Kennzahlen aus (b) für das gewählte Alpha; alle drei Alphas werden mitberichtet.
2. Entscheidung des Entwicklungsfilters, wenn seine Schwelle demselben ε folgt (zugelassen, wenn EM(Q) ≥ EM(F*_Falte) − ε − 1e-12), und bei fester Schwelle 1 Prozentpunkt.

**Nicht gerechnet:** Wahl des abschließend auf allen 300 Aufgaben trainierten Q bei anderen Spielräumen. Dessen Vorhersagen auf den 300 Trainingsaufgaben sind nicht gespeichert; sie neu zu erzeugen hieße, den Encoder erneut auszuführen. Diese Größe (251 von 300 abweichend bei 1 Prozentpunkt) wird nur bei 1 Prozentpunkt aus den gespeicherten `training_selections` reproduziert.

## 5. Reproduktionsbedingung (Abbruch bei Abweichung)

Bei ε = 0,01 und Alpha 100 muss gelten:
- jede neu bestimmte Q-Wahl und jede F*_Falte-Wahl gleich `selected_index` bzw. `fixed_index` der gespeicherten 300 Outcomes; Qualität und Kosten je Aufgabe gleich den gespeicherten Werten;
- EM Q = 0,3533333 (gerundet 35,33 %), EM F*_Falte = 0,39 (39,00 %), Differenz −3,6667 Prozentpunkte, Kostenverhältnis 1,114032 (6 Nachkommastellen);
- gewähltes Alpha nach (c1) = 100; für Alpha 1 und 10 dieselben EM- und Kostenmittel wie gespeichert;
- F* auf 300 Aufgaben (a) = C01 mit EM 0,4033333;
- abschließendes Q: 251 von 300 `training_selections` ungleich C01.

Hinweis vorab: Die 251 abweichenden Wahlen in Z39 und 5.4 betreffen das abschließend auf allen 300 Aufgaben trainierte Q gegen das endgültige F* (C01), nicht die zurückgehaltenen Teile. Laut unabhängiger Nachrechnung (Z39-R1-ERGEBNIS.md Z. 142) beträgt die Zahl der Abweichungen auf den zurückgehaltenen Teilen 253. Diese 253 sind Teil der Reproduktionsbedingung; die 251 werden getrennt reproduziert.

Weicht eine der Bedingungen ab, wird nichts für andere Spielräume berichtet, sondern gemeldet.

## 6. Grenzen, die im Ergebnis stehen müssen

- Kein Rückschluss auf die Hauptstudie: Dort wurden nur die bei 1 Prozentpunkt tatsächlich gewählten Konfigurationen ausgeführt; welche Qualität und Kosten andere Spielräume in der Hauptstudie ergeben hätten, ist nicht beobachtet.
- Dieselbe Entwicklungsmatrix dient Fit, Alpha-Wahl und dieser Analyse; die Werte sind keine unabhängige Prüfung.
- Kein Spielraum wird nachträglich als besser ausgewählt; die Analyse ist beschreibend.
- Keine Intervalle oder Tests.
