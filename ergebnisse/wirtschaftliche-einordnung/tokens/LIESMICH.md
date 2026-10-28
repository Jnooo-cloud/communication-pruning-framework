# Tokens pro Arm im Referenzvergleich (Tabelle 7.3)

Die Anmerkung zu Tabelle 7.3 der Arbeit nennt pro Arm die mittleren Tokens pro Aufgabe: Eingabetokens ohne Cache, Eingabetokens aus dem Cache und Ausgabetokens. Mit ihnen lassen sich die Kosten zu anderen Preisen nachrechnen.

## Nachrechnen

Aus der Wurzel des Repositorys, nur Python-Standardbibliothek:

```sh
python3 ergebnisse/wirtschaftliche-einordnung/tokens/pruefe_tokens.py
```

Das Skript prüft jede Zeile von `tokens-je-lauf.tsv` gegen die Ergebniszeilen (`ergebnisse/ergaenzende-vergleiche/zeilen/rows-R.json`, für den neuen Abstimmungsarm `ergebnisse/ergaenzende-vergleiche/abstimmungsarm-nachstudie/rows-R-SK.json`). Die bekannten Kosten jeder Zeile müssen dort gleich sein. Außerdem muss (Eingabetokens minus Cache) × 0,10 + Cache × 0,01 + Ausgabetokens × 0,40 US-Dollar pro Million Tokens genau diese Kosten ergeben. Danach gibt es die Mittel pro Arm aus. Erwartet:

| Arm | Eingabe ohne Cache | Eingabe aus dem Cache | Ausgabe | Kosten pro 1.000 Aufgaben |
|---|---:|---:|---:|---:|
| Einzelaufruf | 1.797,18 | 708,67 | 5,91 | 0,19 US-Dollar |
| Abstimmungsarm, neu (Temperatur 1,0) | 7.248,07 | 5.280,34 | 30,57 | 0,79 US-Dollar |
| F* | 10.779,20 | 2.256,94 | 397,51 | 1,26 US-Dollar |
| Q | 12.832,02 | 2.577,44 | 388,81 | 1,46 US-Dollar |
| Zufallsauswahl | 13.486,71 | 2.403,55 | 404,43 | 1,53 US-Dollar |
| dichte Vierergruppe | 20.938,61 | 2.816,82 | 605,84 | 2,36 US-Dollar |

Mittel über die 2.952 Blöcke des Referenzvergleichs, über dieselben Versuche wie die Kosten, bezahlte Fehlversuche eingeschlossen. Der alte Abstimmungsarm steht in den Dateien gesondert und gehört nicht zu Tabelle 7.3.

## Dateien

- `tokens-je-lauf.tsv`: pro Lauf Eingabetokens, davon aus dem Cache, Ausgabetokens, Zahl der Versuche und bekannte Kosten. Die Spalte `auswertung` trennt Referenzvergleich, alten und neuen Abstimmungsarm.
- `pruefe_tokens.py`: Nachrechnung oben.
- `TOKENS-REFERENZVERGLEICH.json` und `tokens_referenzvergleich.py`: Herleitung aus den Laufprotokollen und den gespeicherten Rohantworten des Anbieters. Diese Daten liegen nicht in diesem Repository (siehe README). Das Skript läuft deshalb nur im Entwicklungsrepository. Es ordnet jede Ergebniszeile ihren Laufdaten zu. Danach prüft es Kosten, Tokens und Preisformel pro Versuch.

## Herkunft der Cache-Angabe

Ein- und Ausgabetokens stehen in den Laufprotokollen, die Cache-Tokens in den Rohantworten des Anbieters. Für 108.296 von 108.297 Versuchen liegt eine Rohantwort vor, und bei allen ergibt die Preisformel genau den gemeldeten Betrag. Beim fehlenden Versuch (Block R:00038, Arm D, 3.470 Eingabe- und 326 Ausgabetokens) ist der gemeldete Betrag von 0,0004774 US-Dollar genau der Preis ohne Cache-Rabatt. Jedes Cache-Token hätte den Betrag um 0,00000009 US-Dollar gesenkt, und die gemeldeten Beträge sind auf 0,00000001 US-Dollar genau. Seine Cache-Tokens sind daher 0. In `tokens-je-lauf.tsv` ist diese Zeile mit `rohantworten_und_betrag` gekennzeichnet. `TOKENS-REFERENZVERGLEICH.json` beruht nur auf Rohantworten und führt den Versuch deshalb unter `open_points`.
