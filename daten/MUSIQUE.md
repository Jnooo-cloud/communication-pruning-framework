# MuSiQue: Herkunft, Lizenz und verwendete Aufgaben

Alle Aufgaben der Studien stammen aus MuSiQue-Answerable, Version 1.0:

Trivedi, H., Balasubramanian, N., Khot, T., & Sabharwal, A. (2022). MuSiQue: Multihop questions via single-hop question composition. *Transactions of the Association for Computational Linguistics, 10*, 539-554. https://doi.org/10.1162/tacl_a_00475

Quelle: https://github.com/StonyBrookNLP/musique. Lizenz: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Die Daten selbst sind hier nicht enthalten, mit zwei Ausnahmen (unten).

## Verwendete Dateien

| Datei | Verwendung | SHA-256 der verwendeten Fassung |
|---|---|---|
| `musique_ans_v1.0_train.jsonl` | Entwicklung der Auswahlregeln (300 und 100 Aufgaben) | `83a75b1e11e4e9bb8f8308e72ac40ca617ae4431b3a0d955b61cab259248490a` |
| `musique_ans_v1.0_dev.jsonl` | Haupt-, Referenz-, Runden- und Ausfallvergleich | `15fa63794d18a94ce12411aca6e2327e65b6e83b0b1490efab3f1962e48abf3b` |

Laden: Das MuSiQue-Repository enthält ein Skript zum Herunterladen der Daten (siehe dessen README). Nach dem Herunterladen lässt sich die Fassung mit `shasum -a 256 <datei>` gegen die Tabelle prüfen.

## Liste der Aufgaben

`AUFGABEN-IDS.tsv` nennt je Verwendung die MuSiQue-Kennungen (`id` im Datensatz), bei den Vergleichen mit Fragenfamilie und Zahl der Ziehungen.

| Verwendung | Aufgaben |
|---|---|
| Dev-Bestand nach Ausschlüssen (535 Familien) | 2.277 |
| Hauptvergleich (9.040 Ziehungen) | 2.239 |
| Referenzvergleich (2.952 Ziehungen) | 1.663 |
| Rundenvergleich (2.952 Ziehungen) | 1.654 |
| Ausfallvergleich (2.952 Ziehungen) | 1.654 |
| Entwicklung der Konfigurationsauswahl (Train) | 300 |
| Entwicklung der Rundenregel (Train) | 100 |

Die Zuordnung zu Fragenfamilien und die Ziehungen stehen im eingefrorenen Plan `auswertungsplan/PLAN.json`.

## Dateien mit MuSiQue-Text

`ergebnisse/entwicklung/runden/INPUT.json` enthält einen Auszug aus MuSiQue: Fragen und mitgelieferte Absätze der 100 Entwicklungsaufgaben der Rundenregel, weil die Datei die gebundene Eingabe dieser Regel ist. Der Auszug ist unverändert übernommen.

`ergebnisse/textueberlappung/inspect_input_structure.mjs` enthält in den Zeilen 8 bis 15 sechs Beispielfragen aus MuSiQue, wie sie in Tabelle 1 bei Trivedi et al. (2022) stehen. Das Skript prüft damit, ob diese veröffentlichten Beispiele in den verwendeten Daten vorkommen. Diese Zeilen stehen nicht unter der MIT-Lizenz des übrigen Codes.

Urheber beider Texte: Trivedi et al. (2022), Quelle und Lizenz wie oben (CC BY 4.0). Alle anderen Dateien enthalten nur Kennungen, Bewertungen, Kosten und abgeleitete Merkmale.
