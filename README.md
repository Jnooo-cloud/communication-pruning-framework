# Belege zur Masterthesis „Entwicklung und Evaluation eines Communication-Pruning-Frameworks für LLM-basierte Multi-Agenten-Systeme“

Repository: https://github.com/Jnooo-cloud/communication-pruning-framework

`studiencode-ad152f2/` ist bytegleich zum Entwicklungsstand ad152f2 vom 4. Oktober 2026, auf den Abschnitt 5.5 der Arbeit verweist. Herkunft und SHA-256 jeder Datei stehen in `HERKUNFT.tsv`.

**English summary.** This repository accompanies the master's thesis „Entwicklung und Evaluation eines Communication-Pruning-Frameworks für LLM-basierte Multi-Agenten-Systeme“ (Jannik Hiller, Herman Hollerith Zentrum, Faculty of Informatics, Digital Business Engineering, 2026). It holds the framework code and tests in the exact version used for the studies, the analysis plan frozen before the final evaluation, the result rows and analysis outputs of all comparisons, the blinded measurement acceptance cases with both evaluations, and the checks run after the studies. Every file the thesis refers to is listed in the table below. The core results can be recomputed offline, without model calls, in about ten seconds with `python3 nachrechnen/nachrechnen.py`. Task data come from MuSiQue (CC BY 4.0). The task IDs are listed in `daten/`, and one input file contains MuSiQue text. Documentation is in German.

## Zweck

Das Repository stellt die Belege bereit, auf die die Arbeit verweist. Wer die Arbeit prüft, kann damit jede genannte Datei öffnen und die Kernergebnisse aus den gespeicherten Ergebniszeilen nachrechnen. Es enthält den Code in der Fassung der Studien, den vorab eingefrorenen Auswertungsplan, die Ergebniszeilen und Analyseausgaben aller Vergleiche, die Fälle der Messabnahme mit beiden Auswertungen sowie die Nachprüfungen nach Studienabschluss. Neue Modellaufrufe sind für keine der Rechnungen nötig.

## Aufbau

```
studiencode-ad152f2/                    Code und Tests in der Fassung der Studien (Commit ad152f2, Abschnitt 5.5)
  eval-harness/eval/communication_pruning/   Framework: Auswahl, Ausführung, Laufprotokoll, Prüfroutine, Kosten
  eval-harness/eval/study_preparation/       Studienablauf und Auswertung (u. a. final_analysis.py, intervals.py)
  eval-harness/eval/tests/                   Tests
  project/research_control/                  Hilfsmodul, das einige Module von study_preparation importieren
auswertungsplan/                        Eingefrorener Plan: Bindung der Auswertung, Ziehungen, Auswahlregeln, Freigabe
ergebnisse/
  hauptvergleich/                       Q gegen F*: Analyseausgabe, gepaarte Ergebniszeilen, Aufschlüsselungen
  ergaenzende-vergleiche/               Referenz-, Runden-, Ausfallvergleich, neuer Abstimmungsarm, Sensitivitäten
  entwicklung/                          Entwicklungsmatrix, Lernkurven, Rundenentwicklung, Überanpassung, Zusatzrechnungen
  messabnahme/                          Verdeckte Messabnahme, festes Prüfskript, rückblickende Abnahme
  gptswarm/                             Künstlicher Anschluss, Demonstration mit echten Aufrufen, Kostenzerlegung
  textueberlappung/                     Absatzüberlappung zwischen Train- und Dev-Teil von MuSiQue
  wirtschaftliche-einordnung/           Rechnung zu Abschnitt 7.5
nachpruefungen-nach-studienabschluss/   Prüfroutine über alle Laufprotokolle, Anschluss an LangGraph (Code nach ad152f2)
nachrechnen/nachrechnen.py              Rechnet die Kernzahlen aus den Ergebniszeilen nach
daten/                                  Liste der verwendeten MuSiQue-Aufgaben, Herkunft und Lizenz der Daten
HERKUNFT.tsv                            Pfad, Größe, SHA-256 und Herkunft jeder Datei
LICENSE, LICENSE-DATA                   MIT für Code, CC BY 4.0 für Ergebnisdateien und Dokumentation
```

### Zwei Codestände

`studiencode-ad152f2/` enthält den Code, mit dem die Studien liefen, bytegleich zur Fassung in Commit `ad152f2ab2bfbe0f6982ce8b117a588982b1cfae` des Entwicklungsrepositorys vom 4. Oktober 2026 (Abschnitt 5.5). Der Code unter `communication_pruning/`, `study_preparation/` und `tests/` hat sich danach nicht mehr geändert. Hinzugekommen sind nur die Nachprüfungen nach Studienabschluss. Sie liegen getrennt unter `nachpruefungen-nach-studienabschluss/` und rufen den unveränderten Studiencode auf. Die Hash-Stände des Frameworks vor und nach diesen Prüfungen stehen in `nachpruefungen-nach-studienabschluss/manifest/` und in den Dateien `framework-check-*.json`.

### Statusfelder und Zeitpunkt der Freigabe

Einige Dateien in `auswertungsplan/` tragen Statusfelder aus der Vorbereitung, etwa `"not_authorized_or_frozen"` in `ANALYSIS-BINDING.json` und `"study_frozen": false` in `PREPARATION-RESULT.json`. Sie dokumentieren den Stand vor der Freigabe. `ANALYSIS-BINDING.json` bleibt unverändert, weil die Startfreigabe die Datei per SHA-256 bindet. `PREPARATION-RESULT.json` ist als unverändertes Vorbereitungsprotokoll erhalten und von dieser Bindung ausgenommen. Den eingefrorenen Studienstand bestätigt die Autorenfreigabe `freigabe/AUTHOR-RELEASE.json` (`"study_frozen": true`), die autorisierte Startfreigabe ist `freigabe/CANDIDATE-AUTHORIZED.json`. Die Startfreigabe bindet per SHA-256 alle Dateien in `auswertungsplan/` außer `PREPARATION-RESULT.json`, `freigabe/CALENDAR.json` und sich selbst. Die Kalenderwerte stehen in ihr selbst. Von den 39 Quelldateien, die sie bindet, liegen 25 mit gleicher Prüfsumme in diesem Repository, darunter alle 22 Codedateien der Pakete `communication_pruning` und `study_preparation`.

Den Zeitpunkt hält ein nicht öffentliches Repository fest (Abschnitt 4.3 der Arbeit). Die Startfreigabe (SHA-256 `7868b57bb9df1c6406bbfd674cf9f8d80a4f40ee3b60ed9f846d7bc16bbbb47d`) lag im Startpaket mit SHA-256 `da721cc7f394a1e5af322ee700a7cb265ef82ac46d93b91b48c962ef6c03a401` (31.985.254 Byte). GitHub verzeichnet dessen Upload als Asset 577552659 im Entwurfs-Release 392572604 mit `created_at` 2026-09-20T21:00:20Z, rund zehn Minuten vor dem Start der Erhebung.

## Zuordnung: Abschnitt der Arbeit zu Pfad

| Abschnitt der Arbeit | Aussage oder Verweis | Pfad |
|---|---|---|
| 5.5 | Quellcode und Tests | `studiencode-ad152f2/` |
| 5.5 | Codefassung der Studien (Commit ad152f2) | `studiencode-ad152f2/`, `HERKUNFT.tsv` |
| 5.5 | Auswertungsskripte und Ergebnisdateien | `ergebnisse/`, `nachrechnen/` |
| 4.2, Tabelle der DSR-Phasen | Repositoryhinweis | diese Datei |
| 4.2, 4.3, 7.4 | Auswahlregeln, Rundenregel, Ziehungen und Auswertungsplan vor der abschließenden Bewertung eingefroren | `auswertungsplan/freigabe/`, `auswertungsplan/ANALYSIS-BINDING.json`, `auswertungsplan/PLAN.json`, `auswertungsplan/auswahlregeln/` |
| 4.3 | Textüberlappung zwischen Train- und Dev-Teil (2.250 von 2.417 Aufgaben, 2.061 Belegabsatzvorkommen) | `ergebnisse/textueberlappung/` |
| 4.4 | Vorab festgelegtes Verfahren: studentisierter Bootstrap über ganze Paare, 19.999 Wiederholungen | `auswertungsplan/ANALYSIS-BINDING.json`, `studiencode-ad152f2/eval-harness/eval/study_preparation/intervals.py`, `final_analysis.py` |
| 4.4, 6.1, 6.3 | Kostenannahme zu den vier unbekannten Originalabrechnungen | `ergebnisse/hauptvergleich/P-ANALYSIS.json` (Feld `recovery_cost_caveat`) |
| 4.4, 6.3 | Werte je Konfiguration und je Aufgabentyp | `ergebnisse/hauptvergleich/aufschluesselung-je-konfiguration/` |
| 5.4 | Berechnung der vier Textmerkmale | `studiencode-ad152f2/eval-harness/eval/communication_pruning/selection.py` (`features`) |
| 5.4, B.2 | Entwicklungsmatrix, Regularisierungswert, Entwicklungswerte je Konfiguration | `ergebnisse/entwicklung/konfigurationen/`, `ergebnisse/entwicklung/zusatzrechnungen/` |
| 2.3, 4.3, 5.1 | Antwortbewertung nach dem Bewertungsskript von MuSiQue | `studiencode-ad152f2/eval-harness/eval/communication_pruning/evaluation.py` |
| 5.5, 6.3 | Modellausfälle als falsche Antworten mit Kosten | `studiencode-ad152f2/eval-harness/eval/communication_pruning/failure_policy.py`, `ergebnisse/hauptvergleich/P-ROWS.json` |
| 5.7, 6.2 | Verdeckte Messabnahme mit zwölf Fällen, drei Belegstufen und Sollschlüssel | `ergebnisse/messabnahme/verdeckt/` |
| 6.2 | Beide Auswertungen der verdeckten Messabnahme | `ergebnisse/messabnahme/verdeckt/reviewer/view3-reconstruction-v1-*`, `view3-reconstruction-v2-*`, `view3-reconstruction-deviation.md`, `view3-reconstruction-v1-v2-check.json` |
| Kurzfassung, 1.3, 6.2, 7.1 | Prüfroutine des Frameworks weist fünf von acht eingebauten Verletzungen zurück | `ergebnisse/messabnahme/verdeckt/instrument/RESULTS.json`, `ergebnisse/messabnahme/verdeckt/private/answer-key.json` |
| 5.7, 6.2, Tabelle 6.3 | Festes Prüfskript ohne Sprachmodell | `ergebnisse/messabnahme/festes-pruefskript/` |
| 5.7 | Sollfälle der Messung | `studiencode-ad152f2/eval-harness/eval/tests/test_measurement.py`, `measurement_reference.py` |
| 6.2 | Rückblickende Messabnahme, gleiche Anfragen nach der Korrektur | `ergebnisse/messabnahme/rueckblickend/` |
| 6.2 | Künstlicher GPTSwarm-Anschluss mit drei Fällen | `ergebnisse/gptswarm/kuenstlicher-anschluss/` |
| 6.2 | GPTSwarm-Demonstration mit echten Aufrufen, Nachspielen 100 von 100 | `ergebnisse/gptswarm/demonstration/` |
| 6.2 | Behandlung eines Sendeversuchs mit unklarem Ausgang in Tests | `studiencode-ad152f2/eval-harness/eval/tests/test_gptswarm_musique_demo.py` |
| 5.7, Tabelle 6.2 | Abgleich der gemeldeten Beträge mit dem Kontoguthaben in der Demonstration | nicht enthalten (Kontoangaben, siehe unten); Summe der gemeldeten Beträge 0,40005314 US-Dollar in `ergebnisse/gptswarm/demonstration/ANALYSIS-001.json` |
| 6.2, Tabelle 7.1 | Nachträgliche Kostenzerlegung der Demonstration | `ergebnisse/gptswarm/kostenzerlegung/` |
| 6.2, 7.4 | Zweite Nachrechnung aller 6.673 parallel erhobenen Blöcke | `ergebnisse/ergaenzende-vergleiche/skripte-und-nachpruefung/POST-CHECKS.json` |
| 6.2, 7.1, 8.1 | Prüfroutine über die Studienläufe nach Abschluss der Studie (47.600 Laufprotokolle) | `nachpruefungen-nach-studienabschluss/pruefroutine-studienlaeufe/` |
| 6.3 | Hauptvergleich | `ergebnisse/hauptvergleich/P-ANALYSIS.json`, `ergebnisse/hauptvergleich/P-ROWS.json` |
| 6.3 | Aufgaben und Familien als Ziehungseinheit | `ergebnisse/hauptvergleich/sensitivitaet-aufgaben-familien/` |
| 6.1, Tabelle 6.1 | Kostenverhältnisse ohne nahe Wiederholungen | `ergebnisse/ergaenzende-vergleiche/nahe-wiederholungen/` |
| 6.4 bis 6.6 | Referenz-, Runden- und Ausfallvergleich | `ergebnisse/ergaenzende-vergleiche/ANALYSIS-R.json`, `ANALYSIS-T.json`, `ANALYSIS-F.json`, `ergebnisse/ergaenzende-vergleiche/zeilen/` |
| 6.1, 6.4 | Neu erhobener Abstimmungsarm | `ergebnisse/ergaenzende-vergleiche/abstimmungsarm-nachstudie/` |
| 4.4, 6.4 bis 6.6 | Sensitivität der ergänzenden Vergleiche mit Aufgaben als Einheit | `ergebnisse/ergaenzende-vergleiche/sensitivitaet-aufgaben/` |
| 7.2, 8.2 | Gespeicherte Lernkurven mit 103, 201 und 300 Entwicklungsaufgaben | `ergebnisse/entwicklung/konfigurationen/learning-curves.json` |
| 7.2 | Zählung der Rundenentwicklung | `ergebnisse/entwicklung/runden/INPUT.json`, `ergebnisse/entwicklung/zusatzrechnungen/REDTEAMFIX-ZAHLEN.md` |
| 7.2 | Zählung im Rundenvergleich aus den Ergebniszeilen | `ergebnisse/ergaenzende-vergleiche/zeilen/rows-T.json` |
| Kurzfassung, 7.1, 7.2 | Überanpassung von Q, abgesicherte Auswahl, Mehrkosten zusätzlicher Kanten | `ergebnisse/entwicklung/ueberanpassung-und-eingriffe/` |
| 7.2 | Auswahlspielraum | `ergebnisse/entwicklung/spielraum-sensitivitaet/` |
| 7.3, Tabelle 7.1 | Ergänzende Auswertung zu Tarifen und Modellausfällen | `ergebnisse/entwicklung/zusatzrechnungen/REDTEAMFIX-ZAHLEN.md`, `ergebnisse/gptswarm/kostenzerlegung/` |
| 1.3, 4.2, 4.3, 7.3, 8.1, 8.2 | Anschluss an LangGraph 1.0.6 ohne Modellaufrufe: 1.080 Läufe, Wiedergabe der 100 Blöcke, Muster der Messabnahme | `nachpruefungen-nach-studienabschluss/langgraph-anschluss/` |
| 7.5, Tabelle 7.4 | Wirtschaftliche Einordnung | `ergebnisse/wirtschaftliche-einordnung/`, `ergebnisse/ergaenzende-vergleiche/` |

## Kernzahlen nachrechnen

Voraussetzungen: Python ab 3.10 und NumPy. Die Studien liefen mit Python 3.12.14 und NumPy 1.26.4 (`auswertungsplan/RUNTIME.json`). Aus der Wurzel des Repositorys:

```sh
python3 nachrechnen/nachrechnen.py
```

Das Skript berechnet Haupt-, Referenz-, Runden- und Ausfallvergleich sowie den Referenzvergleich mit neuem Abstimmungsarm mit der unveränderten Funktion `analyze_panel` aus `study_preparation/final_analysis.py`, dem eingefrorenen Plan und dem vorab gebundenen Seed neu und vergleicht das Ergebnis mit den gespeicherten Analyseausgaben. Gleitkommawerte dürfen sich je nach Umgebung in den letzten Stellen unterscheiden (relative Toleranz 10⁻¹²). Danach zählt es einige im Text genannte Werte direkt aus den Zeilen nach.

Erwartete Ausgabe, mit den Werten der Arbeit:

| Wert | Arbeit | Abschnitt |
|---|---|---|
| exakt richtig, Q gegen F* | 31,99 % gegen 36,21 % | 6.3 |
| Qualitätsdifferenz mit 95-%-Intervall | −4,21 Prozentpunkte (−4,90 bis −3,54) | 6.3 |
| Kostenverhältnis mit Intervall | 1,169 (1,162 bis 1,176) | 6.3 |
| Paare gleich, nur F* richtig, nur Q richtig | 8.041, 690, 309 | 6.3 |
| Modellausfälle Q und F*, mittlerer F1 | 228 und 224, 0,436 und 0,481 | 6.3 |
| bekannte Modellkosten Q und F* | 14,44 und 12,35 US-Dollar | 6.3 |
| Aufgaben und Familien im Hauptvergleich | 2.239 und 528 | 6.3 |
| Rundenvergleich, Blöcke mit zwei Runden nach der Regel | 1.303; 422 mit zwei Runden, 425 mit einer Runde exakt richtig | 7.2 |
| Rundenentwicklung, Wirkung der zweiten Runde | 92 unverändert, 3 besser, 5 schlechter | 7.2 |
| Rückstand von Q in den Lernkurven bei 103, 201, 300 Aufgaben | 3,88, 4,98, 3,67 Prozentpunkte | 7.2 |
| Prüfroutine über die Laufprotokolle (gespeichertes Ergebnis) | 47.600 Laufprotokolle, 47.598 abgeschlossene angenommen, 2 offene, 0 zurückgewiesen, 5.904 Läufe ohne solches Protokoll | 6.2 |

Am Ende steht `Ergebnis: alle gespeicherten Analysen reproduziert`. Die Zahl zur Prüfroutine wird nur aus der gespeicherten Ergebnisdatei gelesen, weil die 47.600 Laufprotokolle nicht enthalten sind (siehe unten).

Die übrigen Skripte unter `ergebnisse/` und `nachpruefungen-nach-studienabschluss/` sind unveränderte Belege des damaligen Rechenwegs. Sie verwenden teils absolute Pfade des Entwicklungsrechners und Eingaben, die hier nicht enthalten sind. Sie sind deshalb nicht ohne Anpassung ausführbar. Ihre Ergebnisse liegen jeweils daneben als JSON- oder Markdown-Datei.

## Tests ausführen

Die Tests nutzen `unittest` und brauchen kein Netzwerk. Aus `studiencode-ad152f2/eval-harness/eval`:

```sh
PYTHONPATH="$PWD/../.." python3 -m unittest discover -s tests -v
```

Hinweise zur Umgebung: Am besten in einer frischen virtuellen Umgebung mit NumPy laufen lassen. Ein fremdes Python-Paket namens `tests` (etwa aus `textstat`) verdeckt sonst den Testordner, der kein `__init__.py` hat. Unter macOS verweist das Temp-Verzeichnis über `/var` auf `/private/var`. Ein kanonischer Pfad (`TMPDIR=$(cd "$TMPDIR" && pwd -P)`) vermeidet Fehler bei Pfadbindungen.

Stand dieses Repositorys (25.10.2026, Python 3.13.9, NumPy 1.26.4, Netzwerk gesperrt): 83 Testmodule mit 788 Tests, davon 694 bestanden, 0 fehlgeschlagen und 94 mit Fehler abgebrochen. 91 dieser Fehler entstehen, weil Tests Dateien aus Laufordnern der Studie erwarten (`runs/Z42-PILOT-001`, `Z45-ANSCHLUSS-001`, `Z50-STUDIENSTART-001`, `Z52-NEBENPANEL-ANSCHLUSS-001`, `Z53-SCHNELLFORTSETZUNG-001`), die hier nicht enthalten sind. 2 betreffen Tests, die das Paket AutoGen brauchen. 1 Mehrprozesstest (`test_complete_once_and_four_process_identity_parity`) bricht in dieser Umgebung ab; die Ursache ist nicht geklärt. Kein Test versuchte einen Netzwerkzugriff.

## Was nicht enthalten ist

- **Laufprotokolle und Anbieterantworten der Studien** (rund 20 GB). Die Rohantworten des Anbieters enthalten Kontokennungen. Enthalten sind die daraus abgeleiteten Ergebniszeilen, die Analyseausgaben und für die Prüfroutine nach Studienabschluss die SHA-256-Werte aller gelesenen Dateien (`MANIFEST-FILES.jsonl.gz`, `MANIFEST-RUNS.jsonl.gz`).
- **Gesicherter Endzustand der Hauptstudie** (78,6 MB). `ergebnisse/hauptvergleich/P-ROWS.json` ist das unveränderte Feld `rows` daraus. Lage und SHA-256 stehen in `ergebnisse/hauptvergleich/herkunft/`.
- **MuSiQue-Daten**, bis auf eine Datei (siehe `daten/MUSIQUE.md`).
- **Fremder Code** von GPTSwarm und LangGraph. Verwendet wurden GPTSwarm Commit `c23a827f561c934ce21dd950408f7606aa4a8821` und LangGraph 1.0.6.
- Texte und Entwürfe der Arbeit, Fachliteratur und Arbeitsprotokolle.

- **Drei Laufdateien der GPTSwarm-Demonstration mit Kontoangaben** (`run-full.log`, `live/SMOKE-STARTED.json`, `live/FULL-STARTED.json`). Sie enthalten Guthaben und Schlüsselnutzung des Anbieterkontos und sind deshalb nicht veröffentlicht. Hash-Verweise auf diese Dateien, etwa in Manifesten der Nachprüfungen, lassen sich hier nicht auflösen. Der Abgleich mit dem Kontoguthaben (Abschnitt 5.7) ist im Text der Arbeit berichtet.

Einige Berichte enthalten Statuszeilen und absolute Pfade aus dem Arbeitsablauf. Sie sind unverändert übernommen, weil mehrere Dateien über SHA-256 aneinander gebunden sind und eine Änderung diese Bindungen brechen würde.

## Daten

Alle Aufgaben stammen aus MuSiQue-Answerable, Version 1.0:

Trivedi, H., Balasubramanian, N., Khot, T., & Sabharwal, A. (2022). MuSiQue: Multihop questions via single-hop question composition. *Transactions of the Association for Computational Linguistics, 10*, 539-554. https://doi.org/10.1162/tacl_a_00475

Quelle: https://github.com/StonyBrookNLP/musique, Lizenz CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/). Die Datei `ergebnisse/entwicklung/runden/INPUT.json` enthält einen unveränderten Auszug daraus: Fragen und mitgelieferte Absätze der 100 Entwicklungsaufgaben der Rundenregel. Außerdem enthält `ergebnisse/textueberlappung/inspect_input_structure.mjs` in den Zeilen 8 bis 15 sechs Beispielfragen aus MuSiQue, wie sie in Tabelle 1 bei Trivedi et al. (2022) stehen. Das Skript prüft damit, ob diese veröffentlichten Beispiele in den verwendeten Daten vorkommen. Alle anderen Dateien enthalten nur Aufgabenkennungen. Verwendete Dateien mit SHA-256, Ladehinweis und die Liste aller verwendeten Aufgaben-IDs stehen in `daten/`.

## Lizenz

Copyright (c) 2026 Jannik Hiller.

| Inhalt | Lizenz | Datei |
|---|---|---|
| Code: alle Quelltextdateien (`.py`, `.mjs`, `.sh`), also `studiencode-ad152f2/`, `nachrechnen/` und die Skripte in `ergebnisse/` und `nachpruefungen-nach-studienabschluss/`, ohne die MuSiQue-Fragen in der nächsten Zeile | MIT | `LICENSE` |
| Ergebnisdateien und Dokumentation: alle übrigen Dateien in `auswertungsplan/`, `ergebnisse/`, `nachpruefungen-nach-studienabschluss/` und `daten/` sowie `README.md` und `HERKUNFT.tsv` | CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ | `LICENSE-DATA` |
| MuSiQue-Auszug in `ergebnisse/entwicklung/runden/INPUT.json` und die sechs MuSiQue-Beispielfragen in `ergebnisse/textueberlappung/inspect_input_structure.mjs`, Zeilen 8 bis 15 | CC BY 4.0 der MuSiQue-Autoren (Namensnennung oben) | `LICENSE-DATA` |
